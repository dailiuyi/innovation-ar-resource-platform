package com.ruoyi.ar;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.ar.storage.LocalZipExportStore;
import com.ruoyi.common.utils.SecurityUtils;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

/** One application instance and one private local volume. No background upload worker. */
@Service
@DependsOnDatabaseInitialization
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class DraftService implements InitializingBean {
    private static final String DRAFT_COLUMNS = "d.id::text as id, d.scene_id::text as \"sceneId\", d.description, d.lock_version as \"lockVersion\", d.creator_id as \"creatorId\", d.creator_name as \"creatorName\", d.created_at as \"createdAt\", d.updated_at as \"updatedAt\", (s.published_draft_id is not null and s.published_draft_id=d.id) as published";
    private static final String FILE_COLUMNS = "id::text as id, draft_id::text as \"draftId\", collection_id::text as \"collectionId\", file_name as \"fileName\", relative_path as \"relativePath\", kind, expected_bytes as bytes, expected_sha256 as sha256, storage_key as \"storageKey\", case when exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id and d.completed_at is null) then case when (select d.failure_reason from ar_file_deletion d where d.file_id=ar_draft_file.id) is null then 'DELETING' else 'DELETE_FAILED' end else status end as status, verified_bytes as \"verifiedBytes\", verified_sha256 as \"verifiedSha256\", coalesce((select d.failure_reason from ar_file_deletion d where d.file_id=ar_draft_file.id),failure_reason) as \"failureReason\", attempts, creator_id as \"creatorId\", creator_name as \"creatorName\", last_actor_id as \"lastActorId\", last_actor_name as \"lastActorName\", created_at as \"createdAt\", updated_at as \"updatedAt\"";
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final LocalZipExportStore zips;
    private final ObjectMapper json;
    private final long maxBytes;
    private final int collectionMaxFiles;
    private final long collectionMaxBytes;
    private final int zipTtlHours;
    private final long zipCacheMaxBytes;
    private final ReentrantLock[] locks = new ReentrantLock[256];
    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> draftLocks = new ConcurrentHashMap<>();

    public DraftService(JdbcTemplate db,PlatformTransactionManager transactions,ArtifactStorage storage,
            LocalZipExportStore zips,ObjectMapper json,@Value("${ar.storage.max-bytes}") long maxBytes,
            @Value("${ar.storage.collection-max-files}") int collectionMaxFiles,
            @Value("${ar.storage.collection-max-bytes}") long collectionMaxBytes,
            @Value("${ar.storage.zip-ttl-hours}") int zipTtlHours,
            @Value("${ar.storage.zip-cache-max-bytes}") long zipCacheMaxBytes) {
        this.db=db; this.tx=new TransactionTemplate(transactions); this.storage=storage; this.zips=zips;
        this.json=json; this.maxBytes=maxBytes; this.collectionMaxFiles=collectionMaxFiles;
        this.collectionMaxBytes=collectionMaxBytes; this.zipTtlHours=zipTtlHours; this.zipCacheMaxBytes=zipCacheMaxBytes;
        Arrays.setAll(locks,i -> new ReentrantLock());
    }
    public Map<String,Object> config() {
        return Map.of("maxBytes",maxBytes,"collectionMaxFiles",collectionMaxFiles,"collectionMaxBytes",collectionMaxBytes);
    }
    private static ResponseStatusException error(HttpStatus status,String reason) { return new ResponseStatusException(status,reason); }
    private Map<String,Object> one(String sql,Object... args) {
        var rows=db.queryForList(sql,args);
        if(rows.isEmpty()) throw error(HttpStatus.NOT_FOUND,"场景、草稿或文件不存在");
        return rows.get(0);
    }
    private void scene(UUID id,boolean lock) {
        one("select id from ar_scene where id=? and deleted_at is null"+(lock?" for update":""),id);
    }
    public Map<String,Object> detail(UUID id) {
        var row=new LinkedHashMap<>(one("select "+DRAFT_COLUMNS+" from ar_draft d join ar_scene s on s.id=d.scene_id where d.id=?",id));
        var active=db.queryForList("select id::text as id, generation, file_count as \"fileCount\", total_bytes as \"totalBytes\" from ar_draft_collection where draft_id=? and status='ACTIVE'",id);
        if(!active.isEmpty()) {
            row.put("currentCollectionId",active.get(0).get("id"));
            row.put("collectionGeneration",active.get(0).get("generation"));
            row.put("fileCount",active.get(0).get("fileCount"));
            row.put("totalBytes",active.get(0).get("totalBytes"));
            UUID cid=UUID.fromString((String)active.get(0).get("id"));
            row.put("availableCount",db.queryForObject("select count(*) from ar_draft_file where collection_id=? and removed_at is null and status='AVAILABLE' and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id)",Long.class,cid));
        } else {
            row.put("fileCount",0L);
            row.put("availableCount",0L);
            row.put("totalBytes",0L);
        }
        var pending=replacementRow(id,null);
        if(pending!=null) {
            pending.remove("items");
            row.put("pendingReplacement",pending);
        }
        String reason=blockedReason(id);
        if(reason!=null) row.put("downloadBlockedReason",reason);
        return row;
    }
    private UUID sceneOf(UUID id) { return UUID.fromString((String)detail(id).get("sceneId")); }
    private void writable(UUID id) { scene(sceneOf(id),true); }
    private boolean currentlyPublished(UUID draftId) {
        return Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_scene where published_draft_id=?)",Boolean.class,draftId));
    }
    private void requireUnpublished(UUID draftId) {
        if(currentlyPublished(draftId)) throw error(HttpStatus.CONFLICT,"已发布版本文件已冻结，仅可修改说明");
    }
    private void requireNoPending(UUID draftId) {
        if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_draft_collection where draft_id=? and status='PENDING')",Boolean.class,draftId)))
            throw error(HttpStatus.CONFLICT,"正在替换全部文件，完成后才能继续");
    }
    private ReentrantReadWriteLock draftLock(UUID id) { return draftLocks.computeIfAbsent(id,k -> new ReentrantReadWriteLock()); }
    private void lockWrite(UUID draftId) {
        if(!draftLock(draftId).writeLock().tryLock()) throw error(HttpStatus.CONFLICT,"文件集合正在变更或下载，请稍后重试");
    }
    private void lockRead(UUID draftId) {
        if(!draftLock(draftId).readLock().tryLock()) throw error(HttpStatus.CONFLICT,"文件集合正在变更，请稍后重试");
    }
    private void audit(UUID sceneId,UUID draftId,UUID fileId,String action,long actor,String actorName,Map<String,Object> values) {
        var detail=new LinkedHashMap<String,Object>(values);
        detail.put("draftId",draftId.toString());
        if(fileId!=null) detail.put("fileId",fileId.toString());
        try {
            db.update("insert into ar_audit(scene_id,actor_id,actor_name,action,detail) values(?,?,?,?,?::jsonb)",
                sceneId,actor,actorName,action,json.writeValueAsString(detail));
        } catch(JsonProcessingException e) { throw new IllegalStateException(e); }
    }
    private void audit(UUID draftId,UUID fileId,String action,Map<String,Object> values) {
        audit(sceneOf(draftId),draftId,fileId,action,SecurityUtils.getUserId(),SecurityUtils.getUsername(),values);
    }
    public Map<String,Object> list(UUID sceneId,int limit,int offset) {
        var sceneRow=one("select lock_version as \"lockVersion\", published_draft_id as \"publishedDraftId\" from ar_scene where id=? and deleted_at is null",sceneId);
        var result=new LinkedHashMap<String,Object>();
        result.put("items",db.queryForList("select "+DRAFT_COLUMNS+" from ar_draft d join ar_scene s on s.id=d.scene_id where d.scene_id=? order by d.created_at desc,d.id limit ? offset ?",sceneId,limit,offset));
        result.put("total",db.queryForObject("select count(*) from ar_draft where scene_id=?",Long.class,sceneId));
        result.put("sceneLockVersion",sceneRow.get("lockVersion"));
        if(sceneRow.get("publishedDraftId")!=null)
            result.put("published",one("select d.id::text as id, d.description, s.published_at as \"publishedAt\", s.published_by_name as \"publishedByName\" from ar_scene s join ar_draft d on d.id=s.published_draft_id where s.id=?",sceneId));
        return result;
    }
    public Map<String,Object> publish(UUID draftId,long expectedSceneVersion) {
        var draft=detail(draftId);
        if(Boolean.TRUE.equals(draft.get("published"))) return draft;
        UUID sceneId=UUID.fromString((String)draft.get("sceneId"));
        lockWrite(draftId);
        try {
            var files=activeFileIds(draftId);
            List<ReentrantLock> held=new ArrayList<>();
            try {
                for(UUID fileId:files) {
                    ReentrantLock guard=lock(fileId);
                    if(!guard.tryLock()) throw error(HttpStatus.CONFLICT,"文件正在上传或校验，暂不能发布");
                    held.add(guard);
                }
                completeFiles(draftId);
                return tx.execute(s -> {
                    scene(sceneId,true);
                    var latest=detail(draftId);
                    if(Boolean.TRUE.equals(latest.get("published"))) return latest;
                    var sceneRow=one("select lock_version as \"lockVersion\", published_draft_id as \"publishedDraftId\" from ar_scene where id=? and deleted_at is null",sceneId);
                    if(((Number)sceneRow.get("lockVersion")).longValue()!=expectedSceneVersion)
                        throw error(HttpStatus.CONFLICT,"场景已修改，请刷新后重试");
                    requireComplete(draftId);
                    UUID from=(UUID)sceneRow.get("publishedDraftId");
                    if(db.update("update ar_scene set published_draft_id=?,published_at=now(),published_by_id=?,published_by_name=?,lock_version=lock_version+1,updated_at=now() where id=? and deleted_at is null and lock_version=?",
                            draftId,SecurityUtils.getUserId(),SecurityUtils.getUsername(),sceneId,expectedSceneVersion)!=1)
                        throw error(HttpStatus.CONFLICT,"场景已修改，请刷新后重试");
                    var values=new LinkedHashMap<String,Object>();
                    values.put("fromDraftId",from==null?null:from.toString());
                    values.put("toDraftId",draftId.toString());
                    values.put("description",latest.get("description"));
                    audit(sceneId,draftId,null,"DRAFT_PUBLISH",SecurityUtils.getUserId(),SecurityUtils.getUsername(),values);
                    return detail(draftId);
                });
            } finally {
                for(int i=held.size()-1;i>=0;i--) held.get(i).unlock();
            }
        } finally { draftLock(draftId).writeLock().unlock(); }
    }
    public Map<String,Object> create(UUID sceneId,DraftController.DraftInput input) {
        return tx.execute(s -> {
            scene(sceneId,true);
            var existing=db.queryForList("select id from ar_draft where scene_id=? and request_key=?",sceneId,input.requestKey());
            if(!existing.isEmpty()) return detail((UUID)existing.get(0).get("id"));
            UUID id=UUID.randomUUID();
            db.update("insert into ar_draft(id,scene_id,request_key,description,creator_id,creator_name) values(?,?,?,?,?,?)",
                id,sceneId,input.requestKey(),input.description(),SecurityUtils.getUserId(),SecurityUtils.getUsername());
            audit(id,null,"DRAFT_CREATE",Map.of("description",input.description()));
            return detail(id);
        });
    }
    public Map<String,Object> edit(UUID id,DraftController.EditInput input) {
        return tx.execute(s -> {
            writable(id);
            var before=detail(id);
            if(db.update("update ar_draft set description=?,lock_version=lock_version+1,updated_at=now() where id=? and lock_version=?",
                    input.description(),id,input.expectedVersion())!=1) throw error(HttpStatus.CONFLICT,"草稿已修改，请刷新后重试");
            audit(id,null,"DRAFT_EDIT",Map.of("before",before.get("description"),"after",input.description()));
            return detail(id);
        });
    }
    public void removeDraft(UUID draftId) {
        if(db.queryForList("select id from ar_draft where id=?",draftId).isEmpty()) return;
        lockWrite(draftId);
        try {
            writable(draftId);
            if(currentlyPublished(draftId)) throw error(HttpStatus.CONFLICT,"当前发布版本不能删除，请先发布其他草稿");
            requireNoPending(draftId);
            UUID sceneId=sceneOf(draftId);
            var draft=detail(draftId);
            var files=db.queryForList("select id from ar_draft_file where draft_id=? order by id",draftId);
            List<ReentrantLock> held=new ArrayList<>();
            try {
                for(var row:files) {
                    ReentrantLock guard=lock((UUID)row.get("id"));
                    if(!guard.tryLock()) throw error(HttpStatus.CONFLICT,"文件正在上传或校验，暂不能删除草稿");
                    held.add(guard);
                }
                var current=db.queryForList("select id,status from ar_draft_file where draft_id=?",draftId);
                if(current.size()!=files.size() || current.stream().anyMatch(row -> "UPLOADING".equals(row.get("status"))))
                    throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新再删除草稿");
                audit(sceneId,draftId,null,"DRAFT_DELETE_REQUEST",SecurityUtils.getUserId(),SecurityUtils.getUsername(),
                    Map.of("fileCount",files.size(),"description",draft.get("description")));
                for(var row:files) remove(draftId,(UUID)row.get("id"),true);
                tx.executeWithoutResult(s -> {
                    writable(draftId);
                    if(db.queryForList("select id from ar_draft where id=? for update",draftId).isEmpty()) return;
                    if(db.queryForObject("select count(*) from ar_draft_file where draft_id=?",Long.class,draftId)!=0)
                        throw error(HttpStatus.SERVICE_UNAVAILABLE,"草稿中部分文件未能物理删除，请查看失败原因后重试删除草稿");
                    deleteZipsForDraft(draftId);
                    db.update("delete from ar_zip_export where collection_id in (select id from ar_draft_collection where draft_id=?)",draftId);
                    db.update("delete from ar_draft_collection where draft_id=?",draftId);
                    audit(sceneId,draftId,null,"DRAFT_DELETE",SecurityUtils.getUserId(),SecurityUtils.getUsername(),
                        Map.of("physicalFilesDeleted",true,"fileCount",files.size(),"description",draft.get("description")));
                    db.update("delete from ar_draft where id=?",draftId);
                });
            } finally {
                for(int i=held.size()-1;i>=0;i--) held.get(i).unlock();
            }
        } finally { draftLock(draftId).writeLock().unlock(); }
    }
    public Map<String,Object> files(UUID id,int limit,int offset) {
        detail(id);
        var active=db.queryForList("select id from ar_draft_collection where draft_id=? and status='ACTIVE'",id);
        if(active.isEmpty()) return Map.of("items",List.of(),"total",0L);
        UUID cid=(UUID)active.get(0).get("id");
        return Map.of("items",db.queryForList("select "+FILE_COLUMNS+" from ar_draft_file where draft_id=? and collection_id=? and removed_at is null order by relative_path,id limit ? offset ?",id,cid,limit,offset),
            "total",db.queryForObject("select count(*) from ar_draft_file where draft_id=? and collection_id=? and removed_at is null",Long.class,id,cid));
    }
    private Map<String,Object> file(UUID draftId,UUID id) { return one("select "+FILE_COLUMNS+" from ar_draft_file where draft_id=? and id=? and removed_at is null and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id)",draftId,id); }
    public Map<String,Object> register(UUID draftId,DraftController.FileInput input) {
        if(input.bytes()>maxBytes) throw error(HttpStatus.PAYLOAD_TOO_LARGE,"文件超过配置的大小上限");
        String relative;
        try { relative=RelativePath.normalizeOne(input.relativePath()==null||input.relativePath().isBlank()?input.fileName():input.relativePath()); }
        catch(IllegalArgumentException e) { throw error(HttpStatus.BAD_REQUEST,e.getMessage()); }
        if(!RelativePath.fileName(relative).equals(input.fileName()))
            throw error(HttpStatus.BAD_REQUEST,"文件名必须与相对路径的最后一段一致");
        if(input.fileName().chars().anyMatch(c -> c<32 || c==127) || input.fileName().contains("/") || input.fileName().contains("\\"))
            throw error(HttpStatus.BAD_REQUEST,"文件名不能包含路径或控制字符");
        if(input.fileName().toLowerCase(Locale.ROOT).endsWith(".aar") && !"CLIENT_LIBRARY".equals(input.kind()))
            throw error(HttpStatus.BAD_REQUEST,"AAR 必须登记为客户端集成库");
        lockWrite(draftId);
        try {
            return tx.execute(s -> {
                writable(draftId);
                requireUnpublished(draftId);
                requireNoPending(draftId);
                if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_file_deletion d where d.draft_id=? and d.request_key=? and not exists(select 1 from ar_draft_file f join ar_draft_collection c on c.id=f.collection_id where f.draft_id=d.draft_id and f.request_key=d.request_key and c.status in ('ACTIVE','PENDING') and f.removed_at is null and not exists(select 1 from ar_file_deletion x where x.file_id=f.id)))",Boolean.class,draftId,input.requestKey())))
                    throw error(HttpStatus.GONE,"该文件已删除或正在删除，重新添加请使用新的请求标识");
                var rows=db.queryForList("select f.id,f.removed_at from ar_draft_file f join ar_draft_collection c on c.id=f.collection_id where f.draft_id=? and f.request_key=? and c.status='ACTIVE'",draftId,input.requestKey());
                if(!rows.isEmpty()) {
                    if(rows.get(0).get("removed_at")!=null) throw error(HttpStatus.GONE,"该文件登记已移除，重新添加请使用新的请求标识");
                    var existing=file(draftId,(UUID)rows.get(0).get("id"));
                    if(!input.fileName().equals(existing.get("fileName")) || !relative.equals(existing.get("relativePath")) || !input.kind().equals(existing.get("kind"))
                        || input.bytes().longValue()!=((Number)existing.get("bytes")).longValue() || !input.sha256().equals(existing.get("sha256")))
                        throw error(HttpStatus.CONFLICT,"同一请求标识已用于不同文件，请刷新核对");
                    return existing;
                }
                UUID collectionId=ensureActiveCollection(draftId);
                var existingPaths=new ArrayList<String>();
                for(var pathRow:db.queryForList("select relative_path as path from ar_draft_file where collection_id=? and removed_at is null",collectionId))
                    existingPaths.add((String)pathRow.get("path"));
                existingPaths.add(relative);
                try { RelativePath.normalizeAll(existingPaths); }
                catch(IllegalArgumentException e) { throw error(HttpStatus.CONFLICT,e.getMessage()); }
                long count=db.queryForObject("select count(*) from ar_draft_file where collection_id=? and removed_at is null",Long.class,collectionId);
                long total=db.queryForObject("select coalesce(sum(expected_bytes),0) from ar_draft_file where collection_id=? and removed_at is null",Long.class,collectionId);
                if(count+1>collectionMaxFiles) throw error(HttpStatus.BAD_REQUEST,"超过每个文件集合的文件数量上限");
                if(total+input.bytes()>collectionMaxBytes) throw error(HttpStatus.BAD_REQUEST,"超过每个文件集合的总大小上限");
                UUID id=UUID.randomUUID();
                long actor=SecurityUtils.getUserId(); String name=SecurityUtils.getUsername();
                db.update("insert into ar_draft_file(id,draft_id,collection_id,request_key,file_name,relative_path,kind,expected_bytes,expected_sha256,storage_key,creator_id,creator_name,last_actor_id,last_actor_name) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    id,draftId,collectionId,input.requestKey(),input.fileName(),relative,input.kind(),input.bytes(),input.sha256(),id+".bin",actor,name,actor,name);
                refreshCollection(collectionId,true);
                audit(draftId,id,"FILE_REGISTER",Map.of("fileName",input.fileName(),"relativePath",relative,"bytes",input.bytes(),"sha256",input.sha256(),"kind",input.kind()));
                return file(draftId,id);
            });
        } finally { draftLock(draftId).writeLock().unlock(); }
    }
    public void remove(UUID draftId,UUID id) {
        lockWrite(draftId);
        try { remove(draftId,id,false,false); }
        finally { draftLock(draftId).writeLock().unlock(); }
    }
    private void remove(UUID draftId,UUID id,boolean internal) { remove(draftId,id,internal,false); }
    private void remove(UUID draftId,UUID id,boolean internal,boolean recovery) {
        ReentrantLock guard=lock(id);
        if(!guard.tryLock()) throw error(HttpStatus.CONFLICT,"文件正在上传或校验，暂不能删除");
        try {
            boolean completed=Boolean.TRUE.equals(tx.execute(s -> {
                writable(draftId);
                if(!internal) { requireUnpublished(draftId); requireNoPending(draftId); }
                var receipts=db.queryForList("select completed_at,actor_id,actor_name from ar_file_deletion where file_id=? and draft_id=?",id,draftId);
                if(!receipts.isEmpty()) {
                    if(receipts.get(0).get("completed_at")!=null) return true;
                    if(!recovery) {
                        db.update("update ar_file_deletion set failure_reason=null,actor_id=?,actor_name=? where file_id=?",SecurityUtils.getUserId(),SecurityUtils.getUsername(),id);
                        audit(draftId,id,"FILE_DELETE_RETRY",Map.of());
                    } else {
                        audit(sceneOf(draftId),draftId,id,"FILE_DELETE_RETRY",
                            ((Number)receipts.get(0).get("actor_id")).longValue(),(String)receipts.get(0).get("actor_name"),
                            Map.of("recovery",true,"performedBy","SYSTEM_RECONCILIATION"));
                    }
                    return false;
                }
                var row=one("select file_name,status,request_key,expected_bytes,expected_sha256,collection_id,last_actor_id,last_actor_name,creator_id,creator_name from ar_draft_file where draft_id=? and id=? for update",draftId,id);
                if("UPLOADING".equals(row.get("status"))) throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新再删除");
                long actor=recovery?((Number)row.get("last_actor_id")).longValue():SecurityUtils.getUserId();
                String actorName=recovery?(String)row.get("last_actor_name"):SecurityUtils.getUsername();
                db.update("insert into ar_file_deletion(file_id,draft_id,request_key,actor_id,actor_name) values(?,?,?,?,?)",
                    id,draftId,row.get("request_key"),actor,actorName);
                var detail=new LinkedHashMap<String,Object>();
                detail.put("fileName",row.get("file_name"));
                detail.put("previousStatus",row.get("status"));
                detail.put("bytes",row.get("expected_bytes"));
                detail.put("sha256",row.get("expected_sha256"));
                if(recovery) { detail.put("recovery",true); detail.put("performedBy","SYSTEM_RECONCILIATION"); }
                audit(sceneOf(draftId),draftId,id,"FILE_DELETE_REQUEST",actor,actorName,detail);
                return false;
            }));
            if(!completed && !completeDeletion(draftId,id,recovery))
                throw error(HttpStatus.SERVICE_UNAVAILABLE,"物理删除未完成，请查看失败原因并重试删除");
        } finally { guard.unlock(); }
    }
    private boolean completeDeletion(UUID draftId,UUID id,boolean recovery) {
        UUID collectionId=null;
        var live=db.queryForList("select collection_id from ar_draft_file where id=?",id);
        if(!live.isEmpty()) collectionId=(UUID)live.get(0).get("collection_id");
        try {
            storage.delete(id);
        } catch(IOException e) {
            tx.executeWithoutResult(s -> {
                var receipt=one("select actor_id,actor_name from ar_file_deletion where file_id=?",id);
                db.update("update ar_file_deletion set failure_reason=? where file_id=? AND completed_at is null",
                    "存储文件删除失败，请检查存储权限或文件占用后重试删除",id);
                audit(sceneOf(draftId),draftId,id,"FILE_DELETE_FAILED",((Number)receipt.get("actor_id")).longValue(),(String)receipt.get("actor_name"),Map.of("recovery",recovery));
            });
            return false;
        }
        UUID cid=collectionId;
        tx.executeWithoutResult(s -> {
            var receipt=one("select actor_id,actor_name,completed_at from ar_file_deletion where file_id=? for update",id);
            if(receipt.get("completed_at")!=null) return;
            db.update("delete from ar_draft_file where id=? and draft_id=?",id,draftId);
            db.update("update ar_file_deletion set completed_at=now(),failure_reason=null where file_id=?",id);
            if(cid!=null && db.queryForObject("select count(*) from ar_draft_collection where id=? and status='ACTIVE'",Long.class,cid)>0)
                refreshCollection(cid,true);
            audit(sceneOf(draftId),draftId,id,"FILE_DELETE",((Number)receipt.get("actor_id")).longValue(),(String)receipt.get("actor_name"),
                Map.of("physicalFileDeleted",true,"recovery",recovery,"performedBy",recovery?"SYSTEM_RECONCILIATION":"ADMIN"));
        });
        return true;
    }
    private void reconcileDeletions() {
        UUID cursor=new UUID(0,0);
        while(true) {
            var rows=db.queryForList("select file_id,draft_id from ar_file_deletion where completed_at is null and file_id>? order by file_id limit 100",cursor);
            if(rows.isEmpty()) return;
            for(var row:rows) {
                UUID id=(UUID)row.get("file_id"); cursor=id;
                ReentrantLock guard=lock(id);guard.lock();
                try { completeDeletion((UUID)row.get("draft_id"),id,true); }
                finally { guard.unlock(); }
            }
        }
    }
    private ArtifactStorage.Descriptor descriptor(Map<String,Object> row) {
        return new ArtifactStorage.Descriptor(UUID.fromString((String)row.get("id")),((Number)row.get("bytes")).longValue(),(String)row.get("sha256"));
    }
    /** Metadata-only check for files already confirmed AVAILABLE; content digests are checked once at ingestion or recovery. */
    private void requireStored(ArtifactStorage.Descriptor expected) throws IOException {
        if(storage.size(expected.id())!=expected.bytes()) throw new IOException("Artifact missing or size mismatch");
    }
    private ReentrantLock lock(UUID id) { return locks[(id.hashCode() & Integer.MAX_VALUE)%locks.length]; }
    public Map<String,Object> upload(UUID draftId,UUID id,InputStream input) {
        ReentrantLock lock=lock(id);
        if(!lock.tryLock()) throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新或重试");
        try {
            var row=tx.execute(s -> {
                writable(draftId);
                requireUnpublished(draftId);
                var current=file(draftId,id);
                UUID collection=UUID.fromString((String)current.get("collectionId"));
                String collectionStatus=db.queryForObject("select status from ar_draft_collection where id=?",String.class,collection);
                if(!"PENDING".equals(collectionStatus)) requireNoPending(draftId);
                if(!"AVAILABLE".equals(current.get("status"))) {
                    db.update("update ar_draft_file set status='UPLOADING',failure_reason=null,verified_bytes=null,verified_sha256=null,attempts=attempts+1,last_actor_id=?,last_actor_name=?,updated_at=now() where id=?",
                        SecurityUtils.getUserId(),SecurityUtils.getUsername(),id);
                    audit(draftId,id,"FILE_UPLOAD_START",Map.of());
                }
                return current;
            });
            try {
                var expected=descriptor(row);
                if("AVAILABLE".equals(row.get("status"))) requireStored(expected);
                else storage.store(expected,input);
            } catch(IOException e) {
                String reason=switch(String.valueOf(e.getMessage())) {
                    case "Artifact size mismatch" -> "实际文件大小与登记值不一致，请核对原文件";
                    case "Artifact SHA256 mismatch" -> "实际 SHA256 与登记摘要不一致，请核对原文件";
                    case "Artifact exceeds configured storage limit" -> "文件超过当前存储大小上限";
                    default -> "上传中断或存储不可用，请重新选择原文件重试；持续失败请联系管理员检查存储";
                };
                finish(draftId,id,false,reason,false);
                throw error(HttpStatus.UNPROCESSABLE_ENTITY,"文件校验或存储失败，请查看文件记录并重试");
            }
            if(!"AVAILABLE".equals(row.get("status"))) finish(draftId,id,true,null,false);
            var uploaded=file(draftId,id);
            lock.unlock();
            lock=null;
            trySwitch(draftId,false);
            return uploaded;
        } finally { if(lock!=null) lock.unlock(); }
    }
    private void finish(UUID draftId,UUID id,boolean available,String reason,boolean recovery) {
        tx.executeWithoutResult(s -> {
            var before=file(draftId,id);
            db.update("update ar_draft_file set status=?,verified_bytes=case when ? then expected_bytes else null end,verified_sha256=case when ? then expected_sha256 else null end,failure_reason=?,updated_at=now() where id=?",
                available?"AVAILABLE":"FAILED",available,available,reason,id);
            var values=new LinkedHashMap<String,Object>();
            values.put("status",available?"AVAILABLE":"FAILED"); values.put("recovery",recovery);
            if(reason!=null) values.put("reason",reason);
            if(recovery) {
                values.put("performedBy","SYSTEM_RECONCILIATION");
                audit(sceneOf(draftId),draftId,id,"FILE_RECONCILE",((Number)before.get("lastActorId")).longValue(),(String)before.get("lastActorName"),values);
            } else audit(draftId,id,available?"FILE_AVAILABLE":"FILE_FAILED",values);
        });
    }
    public Map<String,Object> startReplacement(UUID draftId,DraftController.ReplacementInput input) {
        List<String> raw=input.files().stream().map(DraftController.ReplacementFile::relativePath).toList();
        List<String> paths;
        try { paths=RelativePath.normalizeAll(raw); }
        catch(IllegalArgumentException e) { throw error(HttpStatus.BAD_REQUEST,e.getMessage()); }
        if(input.files().size()>collectionMaxFiles) throw error(HttpStatus.BAD_REQUEST,"超过每个文件集合的文件数量上限");
        long total=0;
        for(int i=0;i<input.files().size();i++) {
            var item=input.files().get(i);
            if(item.bytes()>maxBytes) throw error(HttpStatus.PAYLOAD_TOO_LARGE,"文件超过配置的大小上限");
            total+=item.bytes();
            if(RelativePath.fileName(paths.get(i)).toLowerCase(Locale.ROOT).endsWith(".aar") && !"CLIENT_LIBRARY".equals(item.kind()))
                throw error(HttpStatus.BAD_REQUEST,"AAR 必须登记为客户端集成库");
        }
        if(total>collectionMaxBytes) throw error(HttpStatus.BAD_REQUEST,"超过每个文件集合的总大小上限");
        final long totalBytes=total;
        String fingerprint=fingerprintFromReplacement(input.files(),paths);
        lockWrite(draftId);
        try {
            Map<String,Object> created=tx.execute(s -> {
                writable(draftId);
                requireUnpublished(draftId);
                var existing=db.queryForList("select id,fingerprint,status from ar_draft_collection where draft_id=? and request_key=?",draftId,input.requestKey());
                if(!existing.isEmpty()) {
                    if(!"PENDING".equals(existing.get(0).get("status"))) throw error(HttpStatus.CONFLICT,"该替换批次已结束，请使用新的请求标识");
                    if(!fingerprint.equals(existing.get(0).get("fingerprint"))) throw error(HttpStatus.CONFLICT,"同一替换批次的文件清单不能改变");
                    return replacement((UUID)existing.get(0).get("id"));
                }
                if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_draft_collection where draft_id=? and status='PENDING')",Boolean.class,draftId)))
                    throw error(HttpStatus.CONFLICT,"已有未完成的文件夹替换，请先完成、重试或取消");
                if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_draft_file f join ar_draft_collection c on c.id=f.collection_id where f.draft_id=? and c.status='ACTIVE' and f.removed_at is null and (f.status='UPLOADING' or exists(select 1 from ar_file_deletion d where d.file_id=f.id and d.completed_at is null)))",Boolean.class,draftId)))
                    throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新再替换");
                UUID collectionId=UUID.randomUUID();
                long actor=SecurityUtils.getUserId(); String name=SecurityUtils.getUsername();
                db.update("insert into ar_draft_collection(id,draft_id,request_key,status,generation,file_count,total_bytes,fingerprint,creator_id,creator_name) values(?,?,?,'PENDING',1,?,?,?,?,?)",
                    collectionId,draftId,input.requestKey(),input.files().size(),totalBytes,fingerprint,actor,name);
                for(int i=0;i<input.files().size();i++) {
                    var item=input.files().get(i);
                    UUID fileId=UUID.randomUUID();
                    String path=paths.get(i);
                    db.update("insert into ar_draft_file(id,draft_id,collection_id,request_key,file_name,relative_path,kind,expected_bytes,expected_sha256,storage_key,creator_id,creator_name,last_actor_id,last_actor_name) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        fileId,draftId,collectionId,item.requestKey(),RelativePath.fileName(path),path,item.kind(),item.bytes(),item.sha256(),fileId+".bin",actor,name,actor,name);
                }
                audit(draftId,null,"COLLECTION_REPLACE_START",Map.of("collectionId",collectionId.toString(),"fileCount",input.files().size(),"totalBytes",totalBytes));
                return replacement(collectionId);
            });
            return created;
        } finally { draftLock(draftId).writeLock().unlock(); }
    }
    public Map<String,Object> replacement(UUID draftId,UUID replacementId) {
        detail(draftId);
        var row=replacementRow(draftId,replacementId);
        if(row==null) throw error(HttpStatus.NOT_FOUND,"场景、草稿或文件不存在");
        return row;
    }
    private Map<String,Object> replacement(UUID collectionId) {
        var row=one("select id::text as id, draft_id::text as \"draftId\", request_key::text as \"requestKey\", status, generation, file_count as \"fileCount\", total_bytes as \"totalBytes\", fingerprint from ar_draft_collection where id=?",collectionId);
        UUID draftId=UUID.fromString((String)row.get("draftId"));
        row.put("availableCount",db.queryForObject("select count(*) from ar_draft_file where collection_id=? and status='AVAILABLE' and removed_at is null",Long.class,collectionId));
        row.put("failedCount",db.queryForObject("select count(*) from ar_draft_file where collection_id=? and status='FAILED' and removed_at is null",Long.class,collectionId));
        row.put("items",db.queryForList("select "+FILE_COLUMNS+" from ar_draft_file where collection_id=? and removed_at is null order by relative_path,id",collectionId));
        row.put("draftId",draftId.toString());
        return row;
    }
    private Map<String,Object> replacementRow(UUID draftId,UUID replacementId) {
        var rows=replacementId==null
            ? db.queryForList("select id from ar_draft_collection where draft_id=? and status='PENDING'",draftId)
            : db.queryForList("select id from ar_draft_collection where draft_id=? and id=?",draftId,replacementId);
        if(rows.isEmpty()) return null;
        return replacement((UUID)rows.get(0).get("id"));
    }
    public Map<String,Object> cancelReplacement(UUID draftId,UUID replacementId) {
        lockWrite(draftId);
        try {
            writable(draftId);
            requireUnpublished(draftId);
            var row=one("select status from ar_draft_collection where draft_id=? and id=? for update",draftId,replacementId);
            if(!"PENDING".equals(row.get("status"))) throw error(HttpStatus.CONFLICT,"当前没有可取消的替换批次");
            var files=db.queryForList("select id,status from ar_draft_file where collection_id=? order by id",replacementId);
            if(files.stream().anyMatch(f -> "UPLOADING".equals(f.get("status"))))
                throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后取消替换");
            db.update("update ar_draft_collection set status='CANCELLED', updated_at=now() where id=?",replacementId);
            audit(draftId,null,"COLLECTION_REPLACE_CANCEL",Map.of("collectionId",replacementId.toString()));
        } finally { draftLock(draftId).writeLock().unlock(); }
        cleanupRetired(draftId,false);
        return detail(draftId);
    }
    public Map<String,Object> manifest(UUID draftId,UUID collectionId,Long generation) {
        lockRead(draftId);
        try {
            var files=completeFiles(draftId);
            var active=currentCollection(draftId);
            if(collectionId!=null && !collectionId.equals(active.id()) || generation!=null && generation!=active.generation())
                throw error(HttpStatus.CONFLICT,"文件集合已变化，请重新获取清单");
            return manifestBody(draftId,active,files);
        } finally { draftLock(draftId).readLock().unlock(); }
    }
    public void downloadFile(UUID draftId,UUID fileId,UUID collectionId,long generation,
            HttpServletRequest request,HttpServletResponse response) throws IOException {
        lockRead(draftId);
        try {
            var files=completeFiles(draftId);
            var active=currentCollection(draftId);
            if(!collectionId.equals(active.id()) || generation!=active.generation())
                throw error(HttpStatus.CONFLICT,"文件集合已变化，请重新获取清单");
            var match=files.stream().filter(f -> fileId.toString().equals(f.get("id"))).findFirst()
                .orElseThrow(() -> error(HttpStatus.NOT_FOUND,"场景、草稿或文件不存在"));
            String etag="\""+match.get("sha256")+"\"";
            long size=((Number)match.get("bytes")).longValue();
            HttpRange.Slice slice=HttpRange.parse(request,size,etag);
            HttpRange.write(response,slice,etag,"application/octet-stream",(String)match.get("fileName"),
                !"HEAD".equalsIgnoreCase(request.getMethod()),
                (offset,length) -> storage.open(fileId,offset,length));
        } finally { draftLock(draftId).readLock().unlock(); }
    }
    public Map<String,Object> zipExport(UUID draftId,UUID collectionId,long generation) throws IOException {
        lockRead(draftId);
        try {
            var files=completeFiles(draftId);
            var active=currentCollection(draftId);
            if(!collectionId.equals(active.id()) || generation!=active.generation())
                throw error(HttpStatus.CONFLICT,"文件集合已变化，请重新获取清单");
            var existing=db.queryForList("select id::text as id, bytes, sha256, status from ar_zip_export where collection_id=? and generation=? and status='AVAILABLE' and (expires_at is null or expires_at>now())",collectionId,generation);
            if(!existing.isEmpty()) {
                UUID exportId=UUID.fromString((String)existing.get(0).get("id"));
                if(zips.exists(exportId)) {
                    db.update("update ar_zip_export set last_accessed_at=now() where id=?",exportId);
                    return zipView(draftId,collectionId,generation,existing.get(0));
                }
            }
            var preparing=db.queryForList("select id from ar_zip_export where collection_id=? and generation=? and status='PREPARING'",collectionId,generation);
            if(!preparing.isEmpty()) throw error(HttpStatus.CONFLICT,"ZIP 正在准备，请稍后重试");
            evictZipCache();
            UUID exportId=UUID.randomUUID();
            try {
                db.update("insert into ar_zip_export(id,collection_id,generation,status,expires_at) values(?,?,?,'PREPARING',?)",
                    exportId,collectionId,generation,OffsetDateTime.now(ZoneOffset.UTC).plusHours(zipTtlHours));
            } catch(DuplicateKeyException e) {
                throw error(HttpStatus.CONFLICT,"ZIP 正在准备，请稍后重试");
            }
            try {
                var written=zips.write(exportId, out -> {
                    OutputStream keepOpen=LocalZipExportStore.keepOpen(out);
                    try (ZipOutputStream zip=new ZipOutputStream(keepOpen, StandardCharsets.UTF_8)) {
                        for(var file:files) {
                            ZipEntry entry=new ZipEntry((String)file.get("relativePath"));
                            zip.putNextEntry(entry);
                            try (InputStream in=storage.open(UUID.fromString((String)file.get("id")))) { in.transferTo(zip); }
                            zip.closeEntry();
                        }
                    }
                });
                db.update("update ar_zip_export set status='AVAILABLE', bytes=?, sha256=?, completed_at=now(), last_accessed_at=now(), failure_reason=null where id=?",
                    written.bytes(),written.sha256(),exportId);
                return zipView(draftId,collectionId,generation,Map.of("id",exportId.toString(),"bytes",written.bytes(),"sha256",written.sha256(),"status","AVAILABLE"));
            } catch(IOException | RuntimeException e) {
                try { zips.delete(exportId); } catch(IOException ignored) {}
                db.update("update ar_zip_export set status='FAILED', failure_reason=?, completed_at=now() where id=?",
                    "ZIP 准备失败，请稍后重试",exportId);
                throw error(HttpStatus.SERVICE_UNAVAILABLE,"ZIP 准备失败，请稍后重试");
            }
        } finally { draftLock(draftId).readLock().unlock(); }
    }
    public void downloadZip(UUID draftId,UUID exportId,HttpServletRequest request,HttpServletResponse response) throws IOException {
        lockRead(draftId);
        try {
            var files=completeFiles(draftId);
            var row=one("select e.id::text as id, e.collection_id as \"collectionId\", e.generation, e.bytes, e.sha256, e.status, (e.expires_at is not null and e.expires_at<now()) as expired from ar_zip_export e join ar_draft_collection c on c.id=e.collection_id where e.id=? and c.draft_id=?",exportId,draftId);
            if(!"AVAILABLE".equals(row.get("status")) || Boolean.TRUE.equals(row.get("expired")))
                throw error(HttpStatus.CONFLICT,"ZIP 已失效，请重新准备下载");
            var active=currentCollection(draftId);
            if(!active.id().equals(row.get("collectionId")) || active.generation()!=((Number)row.get("generation")).longValue())
                throw error(HttpStatus.CONFLICT,"文件集合已变化，请重新获取清单");
            if(!zips.exists(exportId)) throw error(HttpStatus.CONFLICT,"ZIP 已失效，请重新准备下载");
            db.update("update ar_zip_export set last_accessed_at=now() where id=?",exportId);
            String etag="\""+row.get("sha256")+"\"";
            long size=((Number)row.get("bytes")).longValue();
            HttpRange.Slice slice=HttpRange.parse(request,size,etag);
            HttpRange.write(response,slice,etag,"application/zip",zipFileName(files),
                !"HEAD".equalsIgnoreCase(request.getMethod()),
                (offset,length) -> zips.open(exportId,offset,length));
        } finally { draftLock(draftId).readLock().unlock(); }
    }
    private Map<String,Object> zipView(UUID draftId,UUID collectionId,long generation,Map<String,Object> export) {
        var result=new LinkedHashMap<String,Object>();
        result.put("id",export.get("id"));
        result.put("collectionId",collectionId.toString());
        result.put("generation",generation);
        result.put("status",export.get("status"));
        result.put("bytes",export.get("bytes"));
        result.put("sha256",export.get("sha256"));
        result.put("downloadPath","/api/v1/drafts/"+draftId+"/zip-exports/"+export.get("id")+"/content");
        return result;
    }
    private Map<String,Object> manifestBody(UUID draftId,CollectionRef active,List<Map<String,Object>> files) {
        var items=new ArrayList<Map<String,Object>>();
        long total=0;
        for(var file:files) {
            var item=new LinkedHashMap<String,Object>();
            item.put("fileId",file.get("id"));
            item.put("relativePath",file.get("relativePath"));
            item.put("fileName",file.get("fileName"));
            item.put("kind",file.get("kind"));
            item.put("bytes",file.get("bytes"));
            item.put("sha256",file.get("sha256"));
            item.put("downloadPath","/api/v1/drafts/"+draftId+"/files/"+file.get("id")+"/content?collectionId="+active.id()+"&generation="+active.generation());
            items.add(item);
            total+=((Number)file.get("bytes")).longValue();
        }
        var result=new LinkedHashMap<String,Object>();
        result.put("draftId",draftId.toString());
        result.put("collectionId",active.id().toString());
        result.put("generation",active.generation());
        result.put("fileCount",items.size());
        result.put("totalBytes",total);
        result.put("files",items);
        return result;
    }
    private record CollectionRef(UUID id, long generation) {}
    private CollectionRef currentCollection(UUID draftId) {
        var rows=db.queryForList("select id, generation from ar_draft_collection where draft_id=? and status='ACTIVE'",draftId);
        if(rows.isEmpty()) throw error(HttpStatus.BAD_REQUEST,"至少需要一个已校验入库且完整的文件才能发布或下载");
        return new CollectionRef((UUID)rows.get(0).get("id"),((Number)rows.get(0).get("generation")).longValue());
    }
    private List<UUID> activeFileIds(UUID draftId) {
        var active=db.queryForList("select id from ar_draft_collection where draft_id=? and status='ACTIVE'",draftId);
        if(active.isEmpty()) return List.of();
        return db.queryForList("select id from ar_draft_file where collection_id=? and removed_at is null and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id) order by id",active.get(0).get("id"))
            .stream().map(row -> (UUID)row.get("id")).toList();
    }
    private String blockedReason(UUID draftId) {
        if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_draft_collection where draft_id=? and status='PENDING')",Boolean.class,draftId)))
            return "正在替换全部文件，完成后才能发布或下载";
        var active=db.queryForList("select id from ar_draft_collection where draft_id=? and status='ACTIVE'",draftId);
        if(active.isEmpty()) return "至少需要一个已校验入库且完整的文件才能发布或下载";
        UUID cid=(UUID)active.get(0).get("id");
        if(Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_draft_file where collection_id=? and removed_at is null and (status='UPLOADING' or exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id and d.completed_at is null)))",Boolean.class,cid)))
            return "文件正在处理，请稍后刷新再发布或下载";
        long total=db.queryForObject("select count(*) from ar_draft_file where collection_id=? and removed_at is null and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id)",Long.class,cid);
        long available=db.queryForObject("select count(*) from ar_draft_file where collection_id=? and removed_at is null and status='AVAILABLE' and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id)",Long.class,cid);
        if(total<1) return "至少需要一个已校验入库且完整的文件才能发布或下载";
        if(available!=total) return "存在未完成或失败的文件，不能发布或下载";
        return null;
    }
    private void requireComplete(UUID draftId) {
        String reason=blockedReason(draftId);
        if(reason==null) return;
        throw error(reason.contains("正在") || reason.contains("处理")?HttpStatus.CONFLICT:HttpStatus.BAD_REQUEST,reason);
    }
    private List<Map<String,Object>> completeFiles(UUID draftId) {
        requireComplete(draftId);
        UUID cid=currentCollection(draftId).id();
        var files=db.queryForList("select "+FILE_COLUMNS+" from ar_draft_file where collection_id=? and removed_at is null and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id) order by relative_path,id",cid);
        for(var row:files) {
            try { requireStored(descriptor(row)); }
            catch(IOException e) { throw error(HttpStatus.CONFLICT,"文件集合不完整或存储校验失败，请刷新后重试"); }
        }
        return files;
    }
    private UUID ensureActiveCollection(UUID draftId) {
        var active=db.queryForList("select id from ar_draft_collection where draft_id=? and status='ACTIVE'",draftId);
        if(!active.isEmpty()) return (UUID)active.get(0).get("id");
        UUID id=UUID.randomUUID();
        db.update("insert into ar_draft_collection(id,draft_id,request_key,status,generation,file_count,total_bytes,fingerprint,creator_id,creator_name) values(?,?,?,'ACTIVE',1,0,0,?,?,?)",
            id,draftId,UUID.randomUUID(),fingerprint(List.of()),SecurityUtils.getUserId(),SecurityUtils.getUsername());
        return id;
    }
    private void refreshCollection(UUID collectionId,boolean bumpGeneration) {
        var files=db.queryForList("select relative_path as \"relativePath\", kind, expected_bytes as bytes, expected_sha256 as sha256 from ar_draft_file where collection_id=? and removed_at is null",collectionId);
        long total=files.stream().mapToLong(f -> ((Number)f.get("bytes")).longValue()).sum();
        db.update("update ar_draft_collection set file_count=?, total_bytes=?, fingerprint=?, generation=generation+?, updated_at=now() where id=?",
            files.size(),total,fingerprint(files),bumpGeneration?1:0,collectionId);
        invalidateZips(collectionId);
    }
    private String fingerprint(List<Map<String,Object>> files) {
        var sorted=new ArrayList<>(files);
        sorted.sort(Comparator.comparing(m -> String.valueOf(m.get("relativePath"))));
        MessageDigest digest=sha256();
        for(var file:sorted) {
            digest.update(String.valueOf(file.get("relativePath")).getBytes(StandardCharsets.UTF_8));
            digest.update((byte)0);
            digest.update(String.valueOf(file.get("kind")).getBytes(StandardCharsets.UTF_8));
            digest.update((byte)0);
            digest.update(Long.toString(((Number)file.get("bytes")).longValue()).getBytes(StandardCharsets.UTF_8));
            digest.update((byte)0);
            digest.update(String.valueOf(file.get("sha256")).getBytes(StandardCharsets.UTF_8));
            digest.update((byte)'\n');
        }
        return HexFormat.of().formatHex(digest.digest());
    }
    private String fingerprintFromReplacement(List<DraftController.ReplacementFile> files,List<String> paths) {
        var rows=new ArrayList<Map<String,Object>>();
        for(int i=0;i<files.size();i++) {
            var item=files.get(i);
            rows.add(Map.of("relativePath",paths.get(i),"kind",item.kind(),"bytes",item.bytes(),"sha256",item.sha256()));
        }
        return fingerprint(rows);
    }
    private void trySwitch(UUID draftId,boolean recovery) {
        if(!draftLock(draftId).writeLock().tryLock()) return;
        try {
            tx.executeWithoutResult(s -> {
                var pending=db.queryForList("select id, file_count, creator_id, creator_name from ar_draft_collection where draft_id=? and status='PENDING' for update",draftId);
                if(pending.isEmpty()) return;
                UUID cid=(UUID)pending.get(0).get("id");
                long expected=((Number)pending.get(0).get("file_count")).longValue();
                long available=db.queryForObject("select count(*) from ar_draft_file where collection_id=? and status='AVAILABLE' and removed_at is null and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id)",Long.class,cid);
                long total=db.queryForObject("select count(*) from ar_draft_file where collection_id=? and removed_at is null",Long.class,cid);
                if(available!=expected || total!=expected) return;
                var old=db.queryForList("select id from ar_draft_collection where draft_id=? and status='ACTIVE'",draftId);
                if(!old.isEmpty()) {
                    db.update("update ar_draft_collection set status='RETIRED', updated_at=now() where id=?",old.get(0).get("id"));
                    invalidateZips((UUID)old.get(0).get("id"));
                }
                db.update("update ar_draft_collection set status='ACTIVE', updated_at=now() where id=?",cid);
                var values=new LinkedHashMap<String,Object>();
                values.put("collectionId",cid.toString());
                if(recovery) { values.put("recovery",true); values.put("performedBy","SYSTEM_RECONCILIATION"); }
                long actor=recovery?((Number)pending.get(0).get("creator_id")).longValue():SecurityUtils.getUserId();
                String actorName=recovery?(String)pending.get(0).get("creator_name"):SecurityUtils.getUsername();
                audit(sceneOf(draftId),draftId,null,"COLLECTION_REPLACE_SWITCH",actor,actorName,values);
            });
        } finally { draftLock(draftId).writeLock().unlock(); }
        cleanupRetired(draftId,recovery);
    }
    private void cleanupRetired(UUID draftId,boolean recovery) {
        var collections=db.queryForList("select id from ar_draft_collection where draft_id=? and status in ('RETIRED','CANCELLED')",draftId);
        for(var collection:collections) {
            UUID cid=(UUID)collection.get("id");
            var files=db.queryForList("select id from ar_draft_file where collection_id=? order by id",cid);
            for(var file:files) {
                try { remove(draftId,(UUID)file.get("id"),true,recovery); }
                catch(ResponseStatusException ignored) {}
            }
        }
    }
    private void invalidateZips(UUID collectionId) {
        var rows=db.queryForList("select id from ar_zip_export where collection_id=? and status in ('PREPARING','AVAILABLE')",collectionId);
        for(var row:rows) deleteZipRow((UUID)row.get("id"),"文件集合已变化");
    }
    private void deleteZipsForDraft(UUID draftId) {
        var rows=db.queryForList("select e.id from ar_zip_export e join ar_draft_collection c on c.id=e.collection_id where c.draft_id=?",draftId);
        for(var row:rows) {
            try { zips.delete((UUID)row.get("id")); } catch(IOException ignored) {}
        }
    }
    private void deleteZipRow(UUID exportId,String reason) {
        try { zips.delete(exportId); }
        catch(IOException e) {
            db.update("update ar_zip_export set status='FAILED', failure_reason=?, completed_at=coalesce(completed_at,now()) where id=?",reason,exportId);
            return;
        }
        db.update("delete from ar_zip_export where id=?",exportId);
    }
    private void evictZipCache() {
        var expired=db.queryForList("select id from ar_zip_export where status='AVAILABLE' and expires_at is not null and expires_at<now() order by last_accessed_at,id");
        for(var row:expired) deleteZipRow((UUID)row.get("id"),"ZIP 缓存已过期");
        Long used=db.queryForObject("select coalesce(sum(bytes),0) from ar_zip_export where status='AVAILABLE'",Long.class);
        if(used==null || used<zipCacheMaxBytes) return;
        var oldest=db.queryForList("select id, bytes from ar_zip_export where status='AVAILABLE' order by last_accessed_at,id");
        for(var row:oldest) {
            if(used<zipCacheMaxBytes) return;
            deleteZipRow((UUID)row.get("id"),"ZIP 缓存超出容量上限");
            used-=((Number)row.get("bytes")).longValue();
        }
    }
    private String zipFileName(List<Map<String,Object>> files) {
        String root=null;
        for(var file:files) {
            String path=(String)file.get("relativePath");
            int slash=path.indexOf('/');
            if(slash<=0) return "draft.zip";
            String first=path.substring(0,slash);
            if(root==null) root=first;
            else if(!root.equals(first)) return "draft.zip";
        }
        return (root==null?"draft":root)+".zip";
    }
    private static MessageDigest sha256() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch(NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    /** Runs after Flyway and before application startup completes. Only unfinished files are examined; AVAILABLE files are not re-read. */
    @Override public void afterPropertiesSet() {
        reconcileDeletions();
        Set<UUID> leftovers=new HashSet<>();
        try { for(var entry:storage.inventory()) leftovers.add(entry.id()); }
        catch(IOException e) { throw new IllegalStateException("存储目录无法盘点，拒绝启动对账",e); }
        UUID cursor=new UUID(0,0);
        while(true) {
            var rows=db.queryForList("select "+FILE_COLUMNS+" from ar_draft_file where id>? and status in ('PENDING','UPLOADING','FAILED') and removed_at is null and not exists(select 1 from ar_file_deletion d where d.file_id=ar_draft_file.id) order by id limit 100",cursor);
            if(rows.isEmpty()) break;
            for(var row:rows) {
                UUID id=UUID.fromString((String)row.get("id")); cursor=id;
                UUID draftId=UUID.fromString((String)row.get("draftId"));
                String status=(String)row.get("status");
                ReentrantLock lock=lock(id); lock.lock();
                try {
                    try {
                        if(leftovers.contains(id) && storage.recover(descriptor(row))) finish(draftId,id,true,null,true);
                        else if("UPLOADING".equals(status)) finish(draftId,id,false,"重启对账未找到完整且校验通过的正式文件，请重新上传",true);
                    } catch(IOException e) {
                        if(!"FAILED".equals(status)) finish(draftId,id,false,"重启对账未找到完整且校验通过的正式文件，请重新上传",true);
                    }
                } finally { lock.unlock(); }
            }
        }
        for(var row:db.queryForList("select id from ar_zip_export where status='PREPARING'")) {
            UUID id=(UUID)row.get("id");
            try { zips.delete(id); } catch(IOException ignored) {}
            db.update("update ar_zip_export set status='FAILED', failure_reason='准备过程中断，请重新请求打包', completed_at=now() where id=? and status='PREPARING'",id);
        }
        evictZipCache();
        for(var row:db.queryForList("select distinct draft_id from ar_draft_collection where status in ('RETIRED','CANCELLED','PENDING')")) {
            UUID draftId=(UUID)row.get("draft_id");
            trySwitch(draftId,true);
            cleanupRetired(draftId,true);
        }
        for(var row:db.queryForList("select id from ar_draft_collection")) refreshCollection((UUID)row.get("id"),false);
    }
}
