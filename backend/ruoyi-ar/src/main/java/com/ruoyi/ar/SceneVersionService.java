package com.ruoyi.ar;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.common.utils.SecurityUtils;
import java.io.IOException;
import java.io.InputStream;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
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
 * 场景版本的全部业务：创建、改说明、逐文件上传、发布、整版本物理删除、文件下载和启动对账。
 *
 * <p>前提：单个应用实例 + 一个私有本地存储卷，没有后台上传 Worker。
 * <p>版本的文件清单（相对路径、字节数、SHA256）在创建时固定，之后只能改说明。
 * <p>并发规则：
 * <ul>
 *   <li>数据库层：创建、编辑、发布、删除版本时，先对所属场景行 {@code for update}，把同一场景的这些操作串行化。</li>
 *   <li>进程内：每个版本一把读写锁。上传和文件下载持读锁，可并行；发布和整版本删除持写锁，独占。
 *       全部用 tryLock，拿不到立即返回 409，不排队等待。锁只在本进程内有效，所以只支持单实例部署。</li>
 *   <li>{@code activeUploads} 记录正在上传的文件 id；同一文件的第二个上传请求直接返回 409。</li>
 * </ul>
 */
@Service
@DependsOnDatabaseInitialization
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class SceneVersionService implements InitializingBean {
    /**
     * 版本摘要查询（不含文件明细）。uploadStatus 由文件状态聚合得出，优先级从高到低：
     * DELETING（有未完成的删除，且没有失败原因）、DELETE_FAILED（有未完成的删除，且已记录失败原因）、
     * UPLOADING（有文件在上传）、FAILED（有文件失败）、READY（全部文件 AVAILABLE）、否则 PENDING。
     * published 表示它是否是所属场景当前的发布版本。场景已软删除时查不到。
     */
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
    /** 文件登记信息的查询列：status 取 PENDING / UPLOADING / AVAILABLE / FAILED，attempts 为上传尝试次数。 */
    private static final String FILE_COLUMNS = "id::text as \"fileId\", relative_path as \"relativePath\", expected_bytes as bytes, expected_sha256 as sha256,"
        + " status, failure_reason as \"failureReason\", attempts";
    /** “该版本存在未完成的删除”的 SQL 条件片段，%s 填版本 id 的表达式或占位符。 */
    private static final String PENDING_DELETION = "exists(select 1 from ar_version_deletion d where d.version_id=%s and d.completed_at is null)";

    /** 以下为注入的依赖：JDBC、事务模板（让多步数据库操作显式地成组提交）、文件存储、JSON 序列化。 */
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final ObjectMapper json;
    /** 存储配置的上限：单个文件字节数、每个版本的文件数、每个版本的总字节数，在创建版本时检查。 */
    private final long maxBytes;
    private final int versionMaxFiles;
    private final long versionMaxBytes;
    /** 正在上传的文件 id 集合，用来拒绝同一文件的并发上传。 */
    private final Set<UUID> activeUploads = ConcurrentHashMap.newKeySet();
    /** 版本 id → 读写锁。按需创建，不回收。 */
    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> versionLocks = new ConcurrentHashMap<>();

    public SceneVersionService(JdbcTemplate db,PlatformTransactionManager transactions,ArtifactStorage storage,ObjectMapper json,
            @Value("${ar.storage.max-bytes}") long maxBytes,
            @Value("${ar.storage.version-max-files}") int versionMaxFiles,
            @Value("${ar.storage.version-max-bytes}") long versionMaxBytes) {
        this.db=db; this.tx=new TransactionTemplate(transactions); this.storage=storage; this.json=json;
        this.maxBytes=maxBytes; this.versionMaxFiles=versionMaxFiles; this.versionMaxBytes=versionMaxBytes;
    }

    /** 返回存储上限，供管理端前端在导入前预检。 */
    public Map<String,Object> config() {
        return Map.of("maxBytes",maxBytes,"versionMaxFiles",versionMaxFiles,"versionMaxBytes",versionMaxBytes);
    }

    /** 构造带状态码和原因的异常，原因会原样返回给调用方（见 ArExceptionHandler）。 */
    private static ResponseStatusException error(HttpStatus status,String reason) { return new ResponseStatusException(status,reason); }
    /** 查询并返回第一行，没有则抛 404。 */
    private Map<String,Object> one(String sql,Object... args) {
        var rows=db.queryForList(sql,args);
        if(rows.isEmpty()) throw error(HttpStatus.NOT_FOUND,"场景、版本或文件不存在");
        return rows.get(0);
    }
    /** 校验场景存在且未删除；lock 为 true 时对场景行 for update，在事务内串行化同一场景的版本变更。 */
    private void scene(UUID id,boolean lock) {
        one("select id from ar_scene where id=? and deleted_at is null"+(lock?" for update":""),id);
    }
    /** 由版本 id 反查所属场景 id；版本不存在或场景已删除抛 404。 */
    private UUID sceneOf(UUID versionId) {
        return (UUID)one("select v.scene_id from ar_scene_version v join ar_scene s on s.id=v.scene_id and s.deleted_at is null where v.id=?",versionId).get("scene_id");
    }
    /** 版本是否存在未完成的删除（包括已失败等待重试的）。 */
    private boolean deleting(UUID versionId) {
        return Boolean.TRUE.equals(db.queryForObject("select "+PENDING_DELETION.formatted("?"),Boolean.class,versionId));
    }
    /** 版本正在删除时拒绝继续操作，返回 409。 */
    private void requireNotDeleting(UUID versionId) {
        if(deleting(versionId)) throw error(HttpStatus.CONFLICT,"版本正在删除，暂不能操作");
    }
    /** 该版本是否是某场景当前的发布版本。 */
    private boolean published(UUID versionId) {
        return Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_scene where published_version_id=?)",Boolean.class,versionId));
    }
    /** 取版本锁，不存在则创建。 */
    private ReentrantReadWriteLock versionLock(UUID id) { return versionLocks.computeIfAbsent(id,k -> new ReentrantReadWriteLock()); }
    /** 取写锁（发布、删除用）：有上传或下载正在进行时拿不到，返回 409。 */
    private void lockWrite(UUID versionId) {
        if(!versionLock(versionId).writeLock().tryLock()) throw error(HttpStatus.CONFLICT,"版本文件正在上传或下载，请稍后重试");
    }
    /** 取读锁（上传、下载用）：版本正在发布或删除时拿不到，返回 409。 */
    private void lockRead(UUID versionId) {
        if(!versionLock(versionId).readLock().tryLock()) throw error(HttpStatus.CONFLICT,"版本正在发布或删除，请稍后重试");
    }

    /**
     * 写审计。detail 在调用方给的内容之上补充 versionId 和 fileId；actor 由调用方指定，
     * 供启动对账这类没有登录用户的场景沿用原操作者。使用调用方当前的事务，随其提交或回滚。
     */
    private void audit(UUID sceneId,UUID versionId,UUID fileId,String action,long actor,String actorName,Map<String,Object> values) {
        var detail=new LinkedHashMap<String,Object>(values);
        detail.put("versionId",versionId.toString());
        if(fileId!=null) detail.put("fileId",fileId.toString());
        try {
            db.update("insert into ar_audit(scene_id,actor_id,actor_name,action,detail) values(?,?,?,?,?::jsonb)",
                sceneId,actor,actorName,action,json.writeValueAsString(detail));
        } catch(JsonProcessingException e) { throw new IllegalStateException(e); }
    }
    /** 以当前登录用户写审计。 */
    private void audit(UUID sceneId,UUID versionId,UUID fileId,String action,Map<String,Object> values) {
        audit(sceneId,versionId,fileId,action,SecurityUtils.getUserId(),SecurityUtils.getUsername(),values);
    }

    // ---- reads -------------------------------------------------------------------------------------------

    /** 单个版本的摘要，不存在抛 404。 */
    private Map<String,Object> summary(UUID versionId) { return one(SUMMARY+" where v.id=?",versionId); }
    /** 版本的文件列表，按相对路径排序。 */
    private List<Map<String,Object>> fileViews(UUID versionId) {
        return db.queryForList("select "+FILE_COLUMNS+" from ar_version_file where version_id=? order by relative_path,id",versionId);
    }
    /** 版本详情：摘要加全部文件。 */
    public Map<String,Object> detail(UUID versionId) {
        var row=new LinkedHashMap<>(summary(versionId));
        row.put("files",fileViews(versionId));
        return row;
    }
    /** 场景下的版本分页（版本号倒序），附场景版本号（供发布时做乐观锁）和当前发布版本信息。 */
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
    /** 单个文件的登记信息，文件须属于该版本，否则 404。 */
    private Map<String,Object> file(UUID versionId,UUID id) {
        return one("select "+FILE_COLUMNS+" from ar_version_file where version_id=? and id=?",versionId,id);
    }
    /** 管理端查询单个文件状态，同时确认所属场景仍然存在。 */
    public Map<String,Object> fileStatus(UUID versionId,UUID id) {
        sceneOf(versionId);
        return file(versionId,id);
    }
    /** 把文件行转成存储层的描述（id、登记字节数、登记 SHA256）。 */
    private ArtifactStorage.Descriptor descriptor(Map<String,Object> row) {
        return new ArtifactStorage.Descriptor(UUID.fromString((String)row.get("fileId")),((Number)row.get("bytes")).longValue(),(String)row.get("sha256"));
    }

    // ---- create / edit -----------------------------------------------------------------------------------

    /** 创建结果：created 为 false 表示命中了同一 requestKey 的既有版本（幂等重试）。 */
    public record Created(Map<String,Object> version,boolean created) {}
    /** 创建请求里一个文件的规范化形态；key() 用于判断两次请求的文件清单是否完全相同。 */
    private record FileSpec(String path,long bytes,String sha256) {
        String key() { return path+'\0'+bytes+'\0'+sha256; }
    }

    /**
     * 创建版本。先在事务外做纯参数检查（数量、大小上限、路径规范与冲突、文件名不能含 % 或 ;），
     * 再在事务内锁场景行完成：
     * <ol>
     *   <li>requestKey 已对应被删除或正在删除的版本 → 410，重新导入要换新的 requestKey；</li>
     *   <li>requestKey 已对应现有版本 → 内容完全相同返回既有版本（幂等重试），不同则 409；</li>
     *   <li>否则版本号取场景内最大值加 1，写入版本、全部文件（状态为初始值，存储名固定为 id.bin）和审计。</li>
     * </ol>
     * 不上传任何字节；上传由 {@link #upload} 逐个文件进行。
     */
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
            // % 和 ; 无法放进客户端下载地址的路径片段，导入时就拒绝，避免发布后才发现
            if(name.indexOf('%')>=0 || name.indexOf(';')>=0)
                throw error(HttpStatus.BAD_REQUEST,"files 文件名不能包含 % 或 ;，客户端下载地址无法承载："+path);
        }
        var specs=new ArrayList<FileSpec>(files.size());
        for(int i=0;i<files.size();i++) specs.add(new FileSpec(paths.get(i),files.get(i).bytes(),files.get(i).sha256()));
        final long totalBytes=total;
        return tx.execute(s -> {
            scene(sceneId,true);
            // 幂等键与删除回执：已删除的版本留有回执，不能静默重建同一个 requestKey
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
    /** 说明相同，且文件的（路径、大小、摘要）集合完全一致，才算同一次导入请求。 */
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

    /** 修改版本说明，用版本的 lock_version 做乐观锁；版本正在删除时拒绝。文件清单不可改。 */
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

    /**
     * 上传单个文件的字节。持版本读锁，并把文件 id 登记进 activeUploads；
     * 版本正在发布/删除或同一文件正在上传，都立即返回 409。
     */
    public Map<String,Object> upload(UUID versionId,UUID id,InputStream input) {
        sceneOf(versionId);
        lockRead(versionId);
        try {
            if(!activeUploads.add(id)) throw error(HttpStatus.CONFLICT,"文件正在处理，请稍后刷新或重试");
            try { return uploadLocked(versionId,id,input); }
            finally { activeUploads.remove(id); }
        } finally { versionLock(versionId).readLock().unlock(); }
    }
    /**
     * 上传的实际流程，分三段：
     * <ol>
     *   <li>事务 1：状态置为 UPLOADING，清空此前的校验结果，尝试次数加 1（文件已就绪则不改）；</li>
     *   <li>事务外：把字节交给存储层，边收边校验大小与 SHA256（耗时的 IO 不放在数据库事务里）；</li>
     *   <li>事务 2（{@link #finish}）：成功置 AVAILABLE，失败置 FAILED 并写明原因。</li>
     * </ol>
     * 失败原因按错误类型区分：大小或摘要不符、超出存储大小上限是 422，其余（中断、存储不可用）是 503；
     * 两种都可以重新选择原文件重试。
     */
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
            // 已就绪的文件不重写也不重读，只确认文件还在、长度对；用于客户端重复上传同一文件
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
    /** 存储层不会覆盖已有字节。对尚未就绪的上传，可以丢弃那份未通过校验的残留，再接收新内容。 */
    private void storeReplacingUnverified(ArtifactStorage.Descriptor expected, InputStream input) throws IOException {
        try {
            storage.store(expected, input);
        } catch (ArtifactStorage.UnverifiedLeftoverException leftover) {
            storage.delete(expected.id());
            storage.store(expected, input);
        }
    }
    /**
     * 把文件状态落库并写审计，在一个事务内完成。审计的操作者沿用最后一次发起上传的人，
     * 这样启动对账（recovery=true）也能追溯到原操作者，并标注由 SYSTEM_RECONCILIATION 执行。
     * 成功时记录已校验的字节数和摘要，失败时清空。
     */
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

    /**
     * 发布：把版本设为场景当前版本，原发布版本不受影响。已经是发布版本则直接返回（幂等）。
     * 持版本写锁，并在事务里锁场景行；用场景的 lock_version 做乐观锁，不一致返回 409。
     * 只检查数据库里的文件状态，不读存储、不重算摘要。
     */
    public Map<String,Object> publish(UUID versionId,long expectedSceneVersion) {
        if(Boolean.TRUE.equals(summary(versionId).get("published"))) return detail(versionId);
        UUID sceneId=sceneOf(versionId);
        lockWrite(versionId);
        try {
            return tx.execute(s -> {
                scene(sceneId,true);
                // 持锁后再查一次：等锁期间可能已被别的请求发布
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
    /** 只看数据库状态，不读存储也不算摘要：全部文件 AVAILABLE 才允许发布。 */
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

    /**
     * 整版本物理删除。分两步，以便中途失败后可重试、可在重启时续做：
     * <ol>
     *   <li>事务内登记删除回执（ar_version_deletion）并写审计；此时版本对客户端和管理端操作立即变为“删除中”；</li>
     *   <li>{@link #completeDeletion} 删除全部存储文件，再在一个事务里删行并标记完成。</li>
     * </ol>
     * 版本已不存在但有完成的回执时直接成功（幂等）；当前发布版本不能删除。持版本写锁。
     * 存储删除失败返回 503，失败原因记在回执上，再次调用即为重试。
     */
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
                // 已有回执说明这是对失败删除的重试：清掉失败原因，操作者改为本次调用者
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
    /**
     * 执行删除：先按 id 删除全部存储文件，成功后才在一个事务里删除文件行、版本行并把回执标记完成，
     * 因此不会出现行没了而字节还在的状态。存储删除失败只记录失败原因和审计，保留数据库行以便重试。
     * 审计的操作者取自回执（发起删除的人）。调用方须持版本写锁。返回 true 表示已完成。
     */
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

    /** 管理端下载：持读锁，版本不在删除中且文件已就绪才允许，以附件形式返回。 */
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
     * 匿名读取“当前发布版本”的单个文件。URL 里写明了发放时的版本：场景一旦指向别的版本就返回 409，
     * 所以一次下载过程不会混入两个版本。存在性检查先于加锁，避免任意 id 都创建一把锁；
     * 加锁后再检查一次，读锁一直持有到响应流结束。URL 末尾的文件名只做比对，从不用作路径。
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
    /** 场景不可见或不含该版本返回 404；该版本已不是当前发布版本返回 409，提示客户端重新获取场景详情。 */
    private void clientVersion(UUID sceneId,UUID versionId) {
        var rows=db.queryForList("select s.published_version_id from ar_scene s join ar_scene_version v on v.scene_id=s.id"
            +" where s.id=? and v.id=? and s.enabled and s.deleted_at is null and s.published_version_id is not null",sceneId,versionId);
        if(rows.isEmpty()) throw error(HttpStatus.NOT_FOUND,"场景、版本或文件不存在");
        if(!versionId.equals(rows.get(0).get("published_version_id"))) throw error(HttpStatus.CONFLICT,"该版本已不是当前发布版本，请重新获取场景详情");
    }
    /** 只确认存储里的长度与登记值一致，不重算摘要；把登记的 SHA256 作为强 ETag。调用方须持版本读锁。 */
    private void stream(Map<String,Object> file,String contentType,String attachmentName,HttpServletRequest request,HttpServletResponse response) throws IOException {
        UUID fileId=UUID.fromString((String)file.get("fileId"));
        long size=((Number)file.get("bytes")).longValue();
        try {
            if(storage.size(fileId)!=size) throw new IOException("Artifact size mismatch");
        } catch(IOException e) {
            throw error(HttpStatus.CONFLICT,"文件已记录但存储缺失或长度不符，请联系管理员检查存储");
        }
        // ETag 直接用登记摘要；If-Range 与 Range 的处理见 HttpRange
        String etag="\""+file.get("sha256")+"\"";
        HttpRange.Slice slice=HttpRange.parse(request,size,etag);
        HttpRange.write(response,slice,etag,contentType,attachmentName==null?null:RelativePath.fileName(attachmentName),
            !"HEAD".equalsIgnoreCase(request.getMethod()),
            (offset,length) -> storage.open(fileId,offset,length));
    }

    // ---- startup recovery --------------------------------------------------------------------------------

    /**
     * 启动对账，在 Flyway 迁移之后、应用启动完成之前执行：
     * 先续做未完成的删除；再盘点存储目录，只处理状态为 PENDING / UPLOADING / FAILED 的文件：
     * 存储里有完整且校验通过的字节就补记为 AVAILABLE；仍是 UPLOADING 的说明上传被重启打断，置为 FAILED 要求重传。
     * 存储目录无法盘点时拒绝启动。用 id 游标每批 100 条，避免一次性载入全部文件行。
     */
    @Override public void afterPropertiesSet() {
        for(var row:db.queryForList("select version_id from ar_version_deletion where completed_at is null order by version_id")) {
            UUID versionId=(UUID)row.get("version_id");
            lockWrite(versionId);
            try { completeDeletion(versionId,true); }
            finally { versionLock(versionId).writeLock().unlock(); }
        }
        // 存储里现有的文件 id；只有这些文件才可能被补记，其余无需读磁盘
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
                try {
                    if(leftovers.contains(id) && storage.recover(descriptor(row))) finish(versionId,id,true,null,true);
                    else if("UPLOADING".equals(status)) finish(versionId,id,false,"重启对账未找到完整且校验通过的正式文件，请重新上传",true);
                } catch(IOException e) {
                    if(!"FAILED".equals(status)) finish(versionId,id,false,"重启对账未找到完整且校验通过的正式文件，请重新上传",true);
                }
            }
        }
    }
}
