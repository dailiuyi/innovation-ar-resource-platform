package com.ruoyi.ar;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.common.utils.SecurityUtils;
import java.io.IOException;
import java.io.InputStream;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

/**
 * One application instance and one private local volume. No background upload worker.
 * A version's file list is fixed at creation. Uploads and file transfers share the version
 * read lock; publish and whole-version deletion take its write lock. The 256 file locks serialize attempts
 * on the same file.
 */
@Service
@DependsOnDatabaseInitialization
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class SceneVersionService implements InitializingBean {
    private static final String SUMMARY = "select v.id::text as id, v.scene_id::text as \"sceneId\", v.version_no as \"versionNo\", v.description, v.lock_version as \"lockVersion\","
        + " coalesce(s.published_version_id=v.id,false) as published,"
        + " case when exists(select 1 from ar_version_deletion d where d.version_id=v.id and d.completed_at is null)"
        + "   then case when (select d.failure_reason from ar_version_deletion d where d.version_id=v.id) is null then 'DELETING' else 'DELETE_FAILED' end"
        + " when c.uploading>0 then 'UPLOADING' when c.failed>0 then 'FAILED' when c.available=c.total then 'READY' else 'PENDING' end as \"uploadStatus\","
        + " c.total as \"fileCount\", c.available as \"availableCount\", c.failed as \"failedCount\", c.bytes as \"totalBytes\","
        + " v.creator_id as \"creatorId\", v.creator_name as \"creatorName\", v.created_at as \"createdAt\", v.updated_at as \"updatedAt\""
        + " from ar_scene_version v join ar_scene s on s.id=v.scene_id and s.deleted_at is null"
        + " cross join lateral (select count(*) as total, count(*) filter (where f.status='AVAILABLE') as available,"
        + " count(*) filter (where f.status='FAILED') as failed, count(*) filter (where f.status='UPLOADING') as uploading,"
        + " coalesce(sum(f.expected_bytes),0)::bigint as bytes from ar_version_file f where f.version_id=v.id) c";
    private static final String FILE_COLUMNS = "id::text as \"fileId\", relative_path as \"relativePath\", expected_bytes as bytes, expected_sha256 as sha256,"
        + " status, failure_reason as \"failureReason\", attempts";
    private static final String PENDING_DELETION = "exists(select 1 from ar_version_deletion d where d.version_id=%s and d.completed_at is null)";

    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final ObjectMapper json;
    private final long maxBytes;
    private final int versionMaxFiles;
    private final long versionMaxBytes;
    private final ReentrantLock[] locks = new ReentrantLock[256];
    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> versionLocks = new ConcurrentHashMap<>();

    public SceneVersionService(JdbcTemplate db,PlatformTransactionManager transactions,ArtifactStorage storage,ObjectMapper json,
            @Value("${ar.storage.max-bytes}") long maxBytes,
            @Value("${ar.storage.version-max-files}") int versionMaxFiles,
            @Value("${ar.storage.version-max-bytes}") long versionMaxBytes) {
        this.db=db; this.tx=new TransactionTemplate(transactions); this.storage=storage; this.json=json;
        this.maxBytes=maxBytes; this.versionMaxFiles=versionMaxFiles; this.versionMaxBytes=versionMaxBytes;
        Arrays.setAll(locks,i -> new ReentrantLock());
    }

    public Map<String,Object> config() {
        return Map.of("maxBytes",maxBytes,"versionMaxFiles",versionMaxFiles,"versionMaxBytes",versionMaxBytes);
    }

    private static ResponseStatusException error(HttpStatus status,String reason) { return new ResponseStatusException(status,reason); }
    private Map<String,Object> one(String sql,Object... args) {
        var rows=db.queryForList(sql,args);
        if(rows.isEmpty()) throw error(HttpStatus.NOT_FOUND,"场景、版本或文件不存在");
        return rows.get(0);
    }
    private void scene(UUID id,boolean lock) {
        one("select id from ar_scene where id=? and deleted_at is null"+(lock?" for update":""),id);
    }
    private UUID sceneOf(UUID versionId) {
        return (UUID)one("select v.scene_id from ar_scene_version v join ar_scene s on s.id=v.scene_id and s.deleted_at is null where v.id=?",versionId).get("scene_id");
    }
    private boolean deleting(UUID versionId) {
        return Boolean.TRUE.equals(db.queryForObject("select "+PENDING_DELETION.formatted("?"),Boolean.class,versionId));
    }
    private void requireNotDeleting(UUID versionId) {
        if(deleting(versionId)) throw error(HttpStatus.CONFLICT,"版本正在删除，暂不能操作");
    }
    private boolean published(UUID versionId) {
        return Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_scene where published_version_id=?)",Boolean.class,versionId));
    }
    private ReentrantReadWriteLock versionLock(UUID id) { return versionLocks.computeIfAbsent(id,k -> new ReentrantReadWriteLock()); }
    private void lockWrite(UUID versionId) {
        if(!versionLock(versionId).writeLock().tryLock()) throw error(HttpStatus.CONFLICT,"版本文件正在上传或下载，请稍后重试");
    }
    private void lockRead(UUID versionId) {
        if(!versionLock(versionId).readLock().tryLock()) throw error(HttpStatus.CONFLICT,"版本正在发布或删除，请稍后重试");
    }
    private ReentrantLock lock(UUID id) { return locks[(id.hashCode() & Integer.MAX_VALUE)%locks.length]; }

    private void audit(UUID sceneId,UUID versionId,UUID fileId,String action,long actor,String actorName,Map<String,Object> values) {
        var detail=new LinkedHashMap<String,Object>(values);
        detail.put("versionId",versionId.toString());
        if(fileId!=null) detail.put("fileId",fileId.toString());
        try {
            db.update("insert into ar_audit(scene_id,actor_id,actor_name,action,detail) values(?,?,?,?,?::jsonb)",
                sceneId,actor,actorName,action,json.writeValueAsString(detail));
        } catch(JsonProcessingException e) { throw new IllegalStateException(e); }
    }
    private void audit(UUID sceneId,UUID versionId,UUID fileId,String action,Map<String,Object> values) {
        audit(sceneId,versionId,fileId,action,SecurityUtils.getUserId(),SecurityUtils.getUsername(),values);
    }

    // ---- reads -------------------------------------------------------------------------------------------

    private Map<String,Object> summary(UUID versionId) { return one(SUMMARY+" where v.id=?",versionId); }
    private List<Map<String,Object>> fileViews(UUID versionId) {
        return db.queryForList("select "+FILE_COLUMNS+" from ar_version_file where version_id=? order by relative_path,id",versionId);
    }
    public Map<String,Object> detail(UUID versionId) {
        var row=new LinkedHashMap<>(summary(versionId));
        row.put("files",fileViews(versionId));
        return row;
    }
    public Map<String,Object> list(UUID sceneId,int limit,int offset) {
        var sceneRow=one("select lock_version as \"lockVersion\", published_version_id as \"publishedVersionId\" from ar_scene where id=? and deleted_at is null",sceneId);
        var result=new LinkedHashMap<String,Object>();
        result.put("items",db.queryForList(SUMMARY+" where v.scene_id=? order by v.version_no desc limit ? offset ?",sceneId,limit,offset));
        result.put("total",db.queryForObject("select count(*) from ar_scene_version where scene_id=?",Long.class,sceneId));
        result.put("sceneLockVersion",sceneRow.get("lockVersion"));
        if(sceneRow.get("publishedVersionId")!=null)
            result.put("published",one("select v.id::text as id, v.version_no as \"versionNo\", v.description, s.published_at as \"publishedAt\", s.published_by_name as \"publishedByName\" from ar_scene s join ar_scene_version v on v.id=s.published_version_id where s.id=?",sceneId));
        return result;
    }
    private Map<String,Object> file(UUID versionId,UUID id) {
        return one("select "+FILE_COLUMNS+" from ar_version_file where version_id=? and id=?",versionId,id);
    }
    public Map<String,Object> fileStatus(UUID versionId,UUID id) {
        sceneOf(versionId);
        return file(versionId,id);
    }
    private ArtifactStorage.Descriptor descriptor(Map<String,Object> row) {
        return new ArtifactStorage.Descriptor(UUID.fromString((String)row.get("fileId")),((Number)row.get("bytes")).longValue(),(String)row.get("sha256"));
    }

    // ---- create / edit -----------------------------------------------------------------------------------

    public record Created(Map<String,Object> version,boolean created) {}
    private record FileSpec(String path,long bytes,String sha256) {
        String key() { return path+'\0'+bytes+'\0'+sha256; }
    }

    public Created create(UUID sceneId,SceneVersionController.CreateInput input) {
        var files=input.files();
        if(files.size()>versionMaxFiles) throw error(HttpStatus.PAYLOAD_TOO_LARGE,"超过每个版本的文件数量上限");
        long total=0;
        for(var file:files) {
            if(file.bytes()>maxBytes) throw error(HttpStatus.PAYLOAD_TOO_LARGE,"文件超过配置的大小上限："+file.relativePath());
            total+=file.bytes();
        }
        if(total>versionMaxBytes) throw error(HttpStatus.PAYLOAD_TOO_LARGE,"超过每个版本的总大小上限");
        List<String> paths;
        try { paths=RelativePath.normalizeAll(files.stream().map(SceneVersionController.FileInput::relativePath).toList()); }
        catch(IllegalArgumentException e) { throw error(HttpStatus.BAD_REQUEST,"files "+e.getMessage()); }
        for(String path:paths) {
            String name=RelativePath.fileName(path);
            if(name.indexOf('%')>=0 || name.indexOf(';')>=0)
                throw error(HttpStatus.BAD_REQUEST,"files 文件名不能包含 % 或 ;，客户端下载地址无法承载："+path);
        }
        var specs=new ArrayList<FileSpec>(files.size());
        for(int i=0;i<files.size();i++) specs.add(new FileSpec(paths.get(i),files.get(i).bytes(),files.get(i).sha256()));
        final long totalBytes=total;
        return tx.execute(s -> {
            scene(sceneId,true);
            if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_version_deletion where scene_id=? and request_key=?)",Boolean.class,sceneId,input.requestKey())))
                throw error(HttpStatus.GONE,"该版本已删除或正在删除，重新导入请使用新的请求标识");
            var existing=db.queryForList("select id from ar_scene_version where scene_id=? and request_key=?",sceneId,input.requestKey());
            if(!existing.isEmpty()) {
                UUID id=(UUID)existing.get(0).get("id");
                if(!sameRequest(id,input.description(),specs))
                    throw error(HttpStatus.CONFLICT,"同一请求标识已用于不同内容，请刷新核对");
                return new Created(detail(id),false);
            }
            UUID id=UUID.randomUUID();
            long actor=SecurityUtils.getUserId(); String name=SecurityUtils.getUsername();
            int versionNo=db.queryForObject("select coalesce(max(version_no),0)+1 from ar_scene_version where scene_id=?",Integer.class,sceneId);
            db.update("insert into ar_scene_version(id,scene_id,version_no,request_key,description,creator_id,creator_name) values(?,?,?,?,?,?,?)",
                id,sceneId,versionNo,input.requestKey(),input.description(),actor,name);
            var rows=new ArrayList<Object[]>(specs.size());
            for(var spec:specs) {
                UUID fileId=UUID.randomUUID();
                rows.add(new Object[]{fileId,id,spec.path(),spec.bytes(),spec.sha256(),fileId+".bin",actor,name,actor,name});
            }
            db.batchUpdate("insert into ar_version_file(id,version_id,relative_path,expected_bytes,expected_sha256,storage_key,creator_id,creator_name,last_actor_id,last_actor_name) values(?,?,?,?,?,?,?,?,?,?)",rows);
            audit(sceneId,id,null,"VERSION_CREATE",Map.of("versionNo",versionNo,"description",input.description(),"fileCount",specs.size(),"totalBytes",totalBytes));
            return new Created(detail(id),true);
        });
    }
    /** Same description and same path/size/digest set. */
    private boolean sameRequest(UUID id,String description,List<FileSpec> specs) {
        if(!Boolean.TRUE.equals(db.queryForObject("select description=? from ar_scene_version where id=?",Boolean.class,description,id)))
            return false;
        Set<String> stored=new HashSet<>();
        for(var row:db.queryForList("select relative_path,expected_bytes,expected_sha256 from ar_version_file where version_id=?",id))
            stored.add(new FileSpec((String)row.get("relative_path"),((Number)row.get("expected_bytes")).longValue(),(String)row.get("expected_sha256")).key());
        Set<String> requested=new HashSet<>();
        for(var spec:specs) requested.add(spec.key());
        return stored.equals(requested);
    }

    public Map<String,Object> edit(UUID versionId,SceneVersionController.EditInput input) {
        return tx.execute(s -> {
            UUID sceneId=sceneOf(versionId);
            scene(sceneId,true);
            requireNotDeleting(versionId);
            var before=summary(versionId);
            if(db.update("update ar_scene_version set description=?,lock_version=lock_version+1,updated_at=now() where id=? and lock_version=?",
                    input.description(),versionId,input.expectedVersion())!=1) throw error(HttpStatus.CONFLICT,"版本已修改，请刷新后重试");
            audit(sceneId,versionId,null,"VERSION_EDIT",Map.of("before",before.get("description"),"after",input.description()));
            return detail(versionId);
        });
    }

    // ---- upload ------------------------------------------------------------------------------------------

    public Map<String,Object> upload(UUID versionId,UUID id,InputStream input) {
        sceneOf(versionId);
        lockRead(versionId);
        try {
            ReentrantLock guard=lock(id);
            if(!guard.tryLock()) throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新或重试");
            try { return uploadLocked(versionId,id,input); }
            finally { guard.unlock(); }
        } finally { versionLock(versionId).readLock().unlock(); }
    }
    private Map<String,Object> uploadLocked(UUID versionId,UUID id,InputStream input) {
        var row=tx.execute(s -> {
            UUID sceneId=sceneOf(versionId);
            requireNotDeleting(versionId);
            var current=file(versionId,id);
            if(!"AVAILABLE".equals(current.get("status"))) {
                db.update("update ar_version_file set status='UPLOADING',failure_reason=null,verified_bytes=null,verified_sha256=null,attempts=attempts+1,last_actor_id=?,last_actor_name=?,updated_at=now() where id=?",
                    SecurityUtils.getUserId(),SecurityUtils.getUsername(),id);
                audit(sceneId,versionId,id,"FILE_UPLOAD_START",Map.of());
            }
            return current;
        });
        boolean wasAvailable="AVAILABLE".equals(row.get("status"));
        try {
            var expected=descriptor(row);
            // An AVAILABLE file is not overwritten or re-read; only its presence and length are checked.
            if(wasAvailable) {
                if(storage.size(expected.id())!=expected.bytes()) throw new IOException("Artifact missing or size mismatch");
            } else storeReplacingUnverified(expected,input);
        } catch(IOException e) {
            String message=String.valueOf(e.getMessage());
            boolean mismatch=message.contains("size mismatch") || message.contains("SHA256 mismatch") || message.contains("exceeds configured storage limit");
            String reason=message.contains("size mismatch") ? "实际文件大小与登记值不一致，请核对原文件"
                : message.contains("SHA256 mismatch") ? "实际 SHA256 与登记摘要不一致，请核对原文件"
                : message.contains("exceeds configured storage limit") ? "文件超过当前存储大小上限"
                : "上传中断或存储不可用，请重新选择原文件重试；持续失败请联系管理员检查存储";
            finish(versionId,id,false,reason,false);
            throw mismatch ? error(HttpStatus.UNPROCESSABLE_ENTITY,reason) : error(HttpStatus.SERVICE_UNAVAILABLE,reason);
        }
        if(!wasAvailable) finish(versionId,id,true,null,false);
        return file(versionId,id);
    }
    /** store never replaces retained bytes. A not-yet-available upload may discard that unverified leftover and receive the new body. */
    private void storeReplacingUnverified(ArtifactStorage.Descriptor expected, InputStream input) throws IOException {
        try {
            storage.store(expected, input);
        } catch (ArtifactStorage.UnverifiedLeftoverException leftover) {
            storage.delete(expected.id());
            storage.store(expected, input);
        }
    }
    private void finish(UUID versionId,UUID id,boolean available,String reason,boolean recovery) {
        tx.executeWithoutResult(s -> {
            var before=one("select f.last_actor_id,f.last_actor_name,v.scene_id from ar_version_file f join ar_scene_version v on v.id=f.version_id where f.id=?",id);
            db.update("update ar_version_file set status=?,verified_bytes=case when ? then expected_bytes else null end,verified_sha256=case when ? then expected_sha256 else null end,failure_reason=?,updated_at=now() where id=?",
                available?"AVAILABLE":"FAILED",available,available,reason,id);
            var values=new LinkedHashMap<String,Object>();
            values.put("status",available?"AVAILABLE":"FAILED"); values.put("recovery",recovery);
            if(reason!=null) values.put("reason",reason);
            if(recovery) values.put("performedBy","SYSTEM_RECONCILIATION");
            audit((UUID)before.get("scene_id"),versionId,id,recovery?"FILE_RECONCILE":available?"FILE_AVAILABLE":"FILE_FAILED",
                ((Number)before.get("last_actor_id")).longValue(),(String)before.get("last_actor_name"),values);
        });
    }

    // ---- publish -----------------------------------------------------------------------------------------

    public Map<String,Object> publish(UUID versionId,long expectedSceneVersion) {
        if(Boolean.TRUE.equals(summary(versionId).get("published"))) return detail(versionId);
        UUID sceneId=sceneOf(versionId);
        lockWrite(versionId);
        try {
            return tx.execute(s -> {
                scene(sceneId,true);
                if(Boolean.TRUE.equals(summary(versionId).get("published"))) return detail(versionId);
                var sceneRow=one("select lock_version as \"lockVersion\", published_version_id as \"publishedVersionId\" from ar_scene where id=? and deleted_at is null",sceneId);
                if(((Number)sceneRow.get("lockVersion")).longValue()!=expectedSceneVersion)
                    throw error(HttpStatus.CONFLICT,"场景已修改，请刷新后重试");
                requireComplete(versionId);
                UUID from=(UUID)sceneRow.get("publishedVersionId");
                if(db.update("update ar_scene set published_version_id=?,published_at=now(),published_by_id=?,published_by_name=?,lock_version=lock_version+1,updated_at=now() where id=? and deleted_at is null and lock_version=?",
                        versionId,SecurityUtils.getUserId(),SecurityUtils.getUsername(),sceneId,expectedSceneVersion)!=1)
                    throw error(HttpStatus.CONFLICT,"场景已修改，请刷新后重试");
                var values=new LinkedHashMap<String,Object>();
                values.put("fromVersionId",from==null?null:from.toString());
                values.put("toVersionId",versionId.toString());
                audit(sceneId,versionId,null,"VERSION_PUBLISH",values);
                return detail(versionId);
            });
        } finally { versionLock(versionId).writeLock().unlock(); }
    }
    /** Database state only: no storage reads and no digests. */
    private void requireComplete(UUID versionId) {
        var row=summary(versionId);
        switch((String)row.get("uploadStatus")) {
            case "READY" -> { }
            case "DELETING", "DELETE_FAILED" -> throw error(HttpStatus.CONFLICT,"版本正在删除，不能发布");
            case "UPLOADING" -> throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新再发布");
            default -> throw error(HttpStatus.BAD_REQUEST,"存在未完成或失败的文件，不能发布");
        }
    }

    // ---- whole-version deletion --------------------------------------------------------------------------

    public void removeVersion(UUID versionId) {
        if(db.queryForList("select id from ar_scene_version where id=?",versionId).isEmpty()) {
            if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_version_deletion where version_id=? and completed_at is not null)",Boolean.class,versionId))) return;
            throw error(HttpStatus.NOT_FOUND,"场景、版本或文件不存在");
        }
        lockWrite(versionId);
        try {
            boolean needed=Boolean.TRUE.equals(tx.execute(s -> {
                var version=db.queryForList("select scene_id,request_key,version_no,description from ar_scene_version where id=?",versionId);
                if(version.isEmpty()) return false;
                UUID sceneId=(UUID)version.get(0).get("scene_id");
                scene(sceneId,true);
                if(published(versionId)) throw error(HttpStatus.CONFLICT,"当前发布版本不能删除，请先发布其他版本");
                var detail=new LinkedHashMap<String,Object>();
                detail.put("versionNo",version.get(0).get("version_no"));
                detail.put("description",version.get(0).get("description"));
                detail.put("fileCount",db.queryForObject("select count(*) from ar_version_file where version_id=?",Long.class,versionId));
                if(db.queryForList("select 1 from ar_version_deletion where version_id=?",versionId).isEmpty()) {
                    db.update("insert into ar_version_deletion(version_id,scene_id,request_key,actor_id,actor_name) values(?,?,?,?,?)",
                        versionId,sceneId,version.get(0).get("request_key"),SecurityUtils.getUserId(),SecurityUtils.getUsername());
                } else {
                    db.update("update ar_version_deletion set failure_reason=null,actor_id=?,actor_name=? where version_id=?",
                        SecurityUtils.getUserId(),SecurityUtils.getUsername(),versionId);
                    detail.put("retry",true);
                }
                audit(sceneId,versionId,null,"VERSION_DELETE_REQUEST",detail);
                return true;
            }));
            if(needed && !completeDeletion(versionId,false))
                throw error(HttpStatus.SERVICE_UNAVAILABLE,"物理删除未完成，请查看失败原因并重试删除版本");
        } finally { versionLock(versionId).writeLock().unlock(); }
    }
    /** Removes every payload by UUID, then rows and receipt in one transaction. Caller holds the version write lock. */
    private boolean completeDeletion(UUID versionId,boolean recovery) {
        var receipts=db.queryForList("select scene_id,actor_id,actor_name from ar_version_deletion where version_id=? and completed_at is null",versionId);
        if(receipts.isEmpty()) return true;
        UUID sceneId=(UUID)receipts.get(0).get("scene_id");
        long actor=((Number)receipts.get(0).get("actor_id")).longValue();
        String actorName=(String)receipts.get(0).get("actor_name");
        var performed=recovery?Map.<String,Object>of("recovery",true,"performedBy","SYSTEM_RECONCILIATION"):Map.<String,Object>of("recovery",false);
        var fileIds=db.queryForList("select id from ar_version_file where version_id=? order by id",versionId);
        try {
            for(var row:fileIds) storage.delete((UUID)row.get("id"));
        } catch(IOException e) {
            tx.executeWithoutResult(s -> {
                db.update("update ar_version_deletion set failure_reason=? where version_id=? and completed_at is null",
                    "存储文件删除失败，请检查存储权限或文件占用后重试删除",versionId);
                audit(sceneId,versionId,null,"VERSION_DELETE_FAILED",actor,actorName,performed);
            });
            return false;
        }
        tx.executeWithoutResult(s -> {
            db.update("delete from ar_version_file where version_id=?",versionId);
            db.update("delete from ar_scene_version where id=?",versionId);
            db.update("update ar_version_deletion set completed_at=now(),failure_reason=null where version_id=?",versionId);
            var values=new LinkedHashMap<String,Object>(performed);
            values.put("physicalFilesDeleted",true);
            values.put("fileCount",fileIds.size());
            audit(sceneId,versionId,null,"VERSION_DELETE",actor,actorName,values);
        });
        return true;
    }

    // ---- file transfer -----------------------------------------------------------------------------------

    public void adminDownload(UUID versionId,UUID fileId,HttpServletRequest request,HttpServletResponse response) throws IOException {
        sceneOf(versionId);
        lockRead(versionId);
        try {
            requireNotDeleting(versionId);
            var file=file(versionId,fileId);
            if(!"AVAILABLE".equals(file.get("status"))) throw error(HttpStatus.CONFLICT,"文件尚未上传完成");
            stream(file,"application/octet-stream",(String)file.get("relativePath"),request,response);
        } finally { versionLock(versionId).readLock().unlock(); }
    }

    /**
     * Anonymous read of one file of the CURRENT published version. The URL names the version it was issued for:
     * once the scene points elsewhere the answer is 409, so an in-flight download never mixes versions. The
     * existence check runs before the lock so arbitrary ids never allocate one; it is repeated under the read
     * lock, which stays held until the stream closes. The file name is only compared, never used as a path.
     */
    public void clientDownload(UUID sceneId,UUID versionId,UUID fileId,String fileName,HttpServletRequest request,HttpServletResponse response) throws IOException {
        clientVersion(sceneId,versionId);
        lockRead(versionId);
        try {
            clientVersion(sceneId,versionId);
            var file=file(versionId,fileId);
            String path=(String)file.get("relativePath");
            if(!RelativePath.fileName(path).equals(fileName)) throw error(HttpStatus.NOT_FOUND,"场景、版本或文件不存在");
            requireNotDeleting(versionId);
            if(!"AVAILABLE".equals(file.get("status"))) throw error(HttpStatus.CONFLICT,"文件尚未就绪");
            String contentType=ClientSceneService.contentType(path);
            stream(file,contentType,null,request,response);
        } finally { versionLock(versionId).readLock().unlock(); }
    }
    /** 404 if the scene is not visible or does not know the version, 409 if the version is no longer published. */
    private void clientVersion(UUID sceneId,UUID versionId) {
        var rows=db.queryForList("select s.published_version_id from ar_scene s join ar_scene_version v on v.scene_id=s.id"
            +" where s.id=? and v.id=? and s.enabled and s.deleted_at is null and s.published_version_id is not null",sceneId,versionId);
        if(rows.isEmpty()) throw error(HttpStatus.NOT_FOUND,"场景、版本或文件不存在");
        if(!versionId.equals(rows.get(0).get("published_version_id"))) throw error(HttpStatus.CONFLICT,"该版本已不是当前发布版本，请重新获取场景详情");
    }
    /** Length check only, then the stored digest as strong ETag; caller holds the version read lock. */
    private void stream(Map<String,Object> file,String contentType,String attachmentName,HttpServletRequest request,HttpServletResponse response) throws IOException {
        UUID fileId=UUID.fromString((String)file.get("fileId"));
        long size=((Number)file.get("bytes")).longValue();
        try {
            if(storage.size(fileId)!=size) throw new IOException("Artifact size mismatch");
        } catch(IOException e) {
            throw error(HttpStatus.CONFLICT,"文件已记录但存储缺失或长度不符，请联系管理员检查存储");
        }
        String etag="\""+file.get("sha256")+"\"";
        HttpRange.Slice slice=HttpRange.parse(request,size,etag);
        HttpRange.write(response,slice,etag,contentType,attachmentName==null?null:RelativePath.fileName(attachmentName),
            !"HEAD".equalsIgnoreCase(request.getMethod()),
            (offset,length) -> storage.open(fileId,offset,length));
    }

    // ---- startup recovery --------------------------------------------------------------------------------

    /** Runs after Flyway and before startup completes: pending deletions first, then unfinished uploads only. */
    @Override public void afterPropertiesSet() {
        for(var row:db.queryForList("select version_id from ar_version_deletion where completed_at is null order by version_id")) {
            UUID versionId=(UUID)row.get("version_id");
            lockWrite(versionId);
            try { completeDeletion(versionId,true); }
            finally { versionLock(versionId).writeLock().unlock(); }
        }
        Set<UUID> leftovers=new HashSet<>();
        try { for(var entry:storage.inventory()) leftovers.add(entry.id()); }
        catch(IOException e) { throw new IllegalStateException("存储目录无法盘点，拒绝启动对账",e); }
        UUID cursor=new UUID(0,0);
        while(true) {
            var rows=db.queryForList("select "+FILE_COLUMNS+", version_id::text as \"versionId\" from ar_version_file where id>? and status in ('PENDING','UPLOADING','FAILED') and not "
                +PENDING_DELETION.formatted("ar_version_file.version_id")+" order by id limit 100",cursor);
            if(rows.isEmpty()) break;
            for(var row:rows) {
                UUID id=UUID.fromString((String)row.get("fileId")); cursor=id;
                UUID versionId=UUID.fromString((String)row.get("versionId"));
                String status=(String)row.get("status");
                ReentrantLock guard=lock(id); guard.lock();
                try {
                    try {
                        if(leftovers.contains(id) && storage.recover(descriptor(row))) finish(versionId,id,true,null,true);
                        else if("UPLOADING".equals(status)) finish(versionId,id,false,"重启对账未找到完整且校验通过的正式文件，请重新上传",true);
                    } catch(IOException e) {
                        if(!"FAILED".equals(status)) finish(versionId,id,false,"重启对账未找到完整且校验通过的正式文件，请重新上传",true);
                    }
                } finally { guard.unlock(); }
            }
        }
    }
}
