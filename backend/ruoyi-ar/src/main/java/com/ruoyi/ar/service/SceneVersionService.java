package com.ruoyi.ar.service;

import com.ruoyi.ar.dto.SceneVersionCreateInput;
import com.ruoyi.ar.dto.SceneVersionEditInput;
import com.ruoyi.ar.dto.SceneVersionFileInput;
import com.ruoyi.ar.support.HttpRange;
import com.ruoyi.ar.support.RelativePath;

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
 * 管理版本创建、上传、发布、删除及启动恢复。
 * 文件清单创建后固定，只能编辑说明；数据库事务与文件 IO 分开提交。
 * 仅支持单实例：上传/下载持版本读锁，发布/删除持写锁；同一文件不允许并发上传。
 */
@Service
@DependsOnDatabaseInitialization
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneVersionService implements InitializingBean {
    /**
     * 版本状态由文件和删除回执实时聚合，不单独存储。
     * 优先级：删除中/删除失败 → 上传中 → 失败 → 全部就绪 → 待上传。
     * READY 表示文件已入库；published 表示场景当前指向此版本，两者独立。
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
    /** 拒绝同一文件的并发上传，不限制不同文件的并行传输。 */
    private final Set<UUID> activeUploads = ConcurrentHashMap.newKeySet();
    /** 版本锁按需创建，不回收；只在当前进程内有效。 */
    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> versionLocks = new ConcurrentHashMap<>();

    public SceneVersionService(JdbcTemplate db, PlatformTransactionManager transactions, ArtifactStorage storage, ObjectMapper json,
                               @Value("${ar.storage.max-bytes}") long maxBytes,
                               @Value("${ar.storage.version-max-files}") int versionMaxFiles,
                               @Value("${ar.storage.version-max-bytes}") long versionMaxBytes) {
        this.db = db;
        this.tx = new TransactionTemplate(transactions);
        this.storage = storage;
        this.json = json;
        this.maxBytes = maxBytes;
        this.versionMaxFiles = versionMaxFiles;
        this.versionMaxBytes = versionMaxBytes;
    }

    public Map<String, Object> config() {
        return Map.of("maxBytes", maxBytes, "versionMaxFiles", versionMaxFiles, "versionMaxBytes", versionMaxBytes);
    }

    private static ResponseStatusException error(HttpStatus status, String reason) {
        return new ResponseStatusException(status, reason);
    }

    /** 无匹配记录时返回 404。 */
    private Map<String, Object> one(String sql, Object... args) {
        var rows = db.queryForList(sql, args);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
        return rows.get(0);
    }

    /** lock=true 时锁场景行，串行处理同一场景的版本变更；须在事务内调用。 */
    private void scene(UUID id, boolean lock) {
        one("select id from ar_scene where id=? and deleted_at is null" + (lock ? " for update" : ""), id);
    }

    private UUID sceneOf(UUID versionId) {
        return (UUID) one("select v.scene_id from ar_scene_version v join ar_scene s on s.id=v.scene_id and s.deleted_at is null where v.id=?", versionId).get("scene_id");
    }

    private boolean deleting(UUID versionId) {
        return Boolean.TRUE.equals(db.queryForObject("select " + PENDING_DELETION.formatted("?"), Boolean.class, versionId));
    }

    private void requireNotDeleting(UUID versionId) {
        if (deleting(versionId)) throw error(HttpStatus.CONFLICT, "版本正在删除，暂不能操作");
    }

    private boolean published(UUID versionId) {
        return Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_scene where published_version_id=?)", Boolean.class, versionId));
    }

    private ReentrantReadWriteLock versionLock(UUID id) {
        return versionLocks.computeIfAbsent(id, k -> new ReentrantReadWriteLock());
    }

    /** 发布和删除独占版本；拿不到锁立即返回 409。 */
    private void lockWrite(UUID versionId) {
        if (!versionLock(versionId).writeLock().tryLock())
            throw error(HttpStatus.CONFLICT, "版本文件正在上传或下载，请稍后重试");
    }

    /** 上传和下载可并行；版本正在发布或删除时立即返回 409。 */
    private void lockRead(UUID versionId) {
        if (!versionLock(versionId).readLock().tryLock())
            throw error(HttpStatus.CONFLICT, "版本正在发布或删除，请稍后重试");
    }

    /** 审计随调用方事务提交。actor 可指定，供启动恢复沿用原操作者。 */
    private void audit(UUID sceneId, UUID versionId, UUID fileId, String action, long actor, String actorName, Map<String, Object> values) {
        var detail = new LinkedHashMap<String, Object>(values);
        detail.put("versionId", versionId.toString());
        if (fileId != null) detail.put("fileId", fileId.toString());
        try {
            db.update("insert into ar_audit(scene_id,actor_id,actor_name,action,detail) values(?,?,?,?,?::jsonb)",
                    sceneId, actor, actorName, action, json.writeValueAsString(detail));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private void audit(UUID sceneId, UUID versionId, UUID fileId, String action, Map<String, Object> values) {
        audit(sceneId, versionId, fileId, action, SecurityUtils.getUserId(), SecurityUtils.getUsername(), values);
    }

    // 查询

    private Map<String, Object> summary(UUID versionId) {
        return one(SUMMARY + " where v.id=?", versionId);
    }

    private List<Map<String, Object>> fileViews(UUID versionId) {
        return db.queryForList("select " + FILE_COLUMNS + " from ar_version_file where version_id=? order by relative_path,id", versionId);
    }

    public Map<String, Object> detail(UUID versionId) {
        var row = new LinkedHashMap<>(summary(versionId));
        row.put("files", fileViews(versionId));
        return row;
    }

    /** 附带场景修订号，供发布时校验；不同于版本说明的修订号。 */
    public Map<String, Object> list(UUID sceneId, int limit, int offset) {
        var sceneRow = one("select lock_version as \"lockVersion\", published_version_id as \"publishedVersionId\" from ar_scene where id=? and deleted_at is null", sceneId);
        var result = new LinkedHashMap<String, Object>();
        result.put("items", db.queryForList(SUMMARY + " where v.scene_id=? order by v.version_no desc limit ? offset ?", sceneId, limit, offset));
        result.put("total", db.queryForObject("select count(*) from ar_scene_version where scene_id=?", Long.class, sceneId));
        result.put("sceneLockVersion", sceneRow.get("lockVersion"));
        if (sceneRow.get("publishedVersionId") != null)
            result.put("published", one("select v.id::text as id, v.version_no as \"versionNo\", v.description, s.published_at as \"publishedAt\", s.published_by_name as \"publishedByName\" from ar_scene s join ar_scene_version v on v.id=s.published_version_id where s.id=?", sceneId));
        return result;
    }

    /** 同时匹配版本和文件，防止跨版本读取。 */
    private Map<String, Object> file(UUID versionId, UUID id) {
        return one("select " + FILE_COLUMNS + " from ar_version_file where version_id=? and id=?", versionId, id);
    }

    public Map<String, Object> fileStatus(UUID versionId, UUID id) {
        sceneOf(versionId);
        return file(versionId, id);
    }

    private ArtifactStorage.Descriptor descriptor(Map<String, Object> row) {
        return new ArtifactStorage.Descriptor(UUID.fromString((String) row.get("fileId")), ((Number) row.get("bytes")).longValue(), (String) row.get("sha256"));
    }

    // 创建与编辑

    /** created=false 表示复用同一 requestKey 的既有版本。 */
    public record Created(Map<String, Object> version, boolean created) {
    }

    private record FileSpec(String path, long bytes, String sha256) {
        String key() {
            return path + '\0' + bytes + '\0' + sha256;
        }
    }

    /**
     * 先校验清单，再锁场景行登记版本、文件和审计，不接收文件正文。
     * 同一 requestKey：内容相同则复用，不同返回 409；有删除回执则返回 410。
     */
    public Created create(UUID sceneId, SceneVersionCreateInput input) {
        var files = input.files();
        if (files.size() > versionMaxFiles) throw error(HttpStatus.PAYLOAD_TOO_LARGE, "超过每个版本的文件数量上限");
        long total = 0;
        for (var file : files) {
            if (file.bytes() > maxBytes)
                throw error(HttpStatus.PAYLOAD_TOO_LARGE, "文件超过配置的大小上限：" + file.relativePath());
            total += file.bytes();
        }
        if (total > versionMaxBytes) throw error(HttpStatus.PAYLOAD_TOO_LARGE, "超过每个版本的总大小上限");
        List<String> paths;
        try {
            paths = RelativePath.normalizeAll(files.stream().map(SceneVersionFileInput::relativePath).toList());
        } catch (IllegalArgumentException e) {
            throw error(HttpStatus.BAD_REQUEST, "files " + e.getMessage());
        }
        for (String path : paths) {
            String name = RelativePath.fileName(path);
            // 文件名含 % 或 ; 时下载 URL 无法承载，在导入时拒绝。
            if (name.indexOf('%') >= 0 || name.indexOf(';') >= 0)
                throw error(HttpStatus.BAD_REQUEST, "files 文件名不能包含 % 或 ;，客户端下载地址无法承载：" + path);
        }
        var specs = new ArrayList<FileSpec>(files.size());
        for (int i = 0; i < files.size(); i++)
            specs.add(new FileSpec(paths.get(i), files.get(i).bytes(), files.get(i).sha256()));
        final long totalBytes = total;
        return tx.execute(s -> {
            // 同一场景的幂等检查、版本号分配和插入必须一起串行处理。
            scene(sceneId, true);
            // 删除回执阻止旧请求重新创建已删除版本。
            if (Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_version_deletion where scene_id=? and request_key=?)", Boolean.class, sceneId, input.requestKey())))
                throw error(HttpStatus.GONE, "该版本已删除或正在删除，重新导入请使用新的请求标识");
            var existing = db.queryForList("select id from ar_scene_version where scene_id=? and request_key=?", sceneId, input.requestKey());
            if (!existing.isEmpty()) {
                UUID id = (UUID) existing.get(0).get("id");
                if (!sameRequest(id, input.description(), specs))
                    throw error(HttpStatus.CONFLICT, "同一请求标识已用于不同内容，请刷新核对");
                return new Created(detail(id), false);
            }
            UUID id = UUID.randomUUID();
            long actor = SecurityUtils.getUserId();
            String name = SecurityUtils.getUsername();
            int versionNo = db.queryForObject("select coalesce(max(version_no),0)+1 from ar_scene_version where scene_id=?", Integer.class, sceneId);
            db.update("insert into ar_scene_version(id,scene_id,version_no,request_key,description,creator_id,creator_name) values(?,?,?,?,?,?,?)",
                    id, sceneId, versionNo, input.requestKey(), input.description(), actor, name);
            var rows = new ArrayList<Object[]>(specs.size());
            for (var spec : specs) {
                UUID fileId = UUID.randomUUID();
                rows.add(new Object[]{fileId, id, spec.path(), spec.bytes(), spec.sha256(), fileId + ".bin", actor, name, actor, name});
            }
            db.batchUpdate("insert into ar_version_file(id,version_id,relative_path,expected_bytes,expected_sha256,storage_key,creator_id,creator_name,last_actor_id,last_actor_name) values(?,?,?,?,?,?,?,?,?,?)", rows);
            audit(sceneId, id, null, "VERSION_CREATE", Map.of("versionNo", versionNo, "description", input.description(), "fileCount", specs.size(), "totalBytes", totalBytes));
            return new Created(detail(id), true);
        });
    }

    /** 幂等比较包含说明及路径/大小/摘要集合，不要求文件排列顺序相同。 */
    private boolean sameRequest(UUID id, String description, List<FileSpec> specs) {
        if (!Boolean.TRUE.equals(db.queryForObject("select description=? from ar_scene_version where id=?", Boolean.class, description, id)))
            return false;
        Set<String> stored = new HashSet<>();
        for (var row : db.queryForList("select relative_path,expected_bytes,expected_sha256 from ar_version_file where version_id=?", id))
            stored.add(new FileSpec((String) row.get("relative_path"), ((Number) row.get("expected_bytes")).longValue(), (String) row.get("expected_sha256")).key());
        Set<String> requested = new HashSet<>();
        for (var spec : specs) requested.add(spec.key());
        return stored.equals(requested);
    }

    /** 按版本修订号更新说明；删除中的版本不可编辑，文件清单不可改。 */
    public Map<String, Object> edit(UUID versionId, SceneVersionEditInput input) {
        return tx.execute(s -> {
            UUID sceneId = sceneOf(versionId);
            scene(sceneId, true);
            requireNotDeleting(versionId);
            var before = summary(versionId);
            if (db.update("update ar_scene_version set description=?,lock_version=lock_version+1,updated_at=now() where id=? and lock_version=?",
                    input.description(), versionId, input.expectedVersion()) != 1)
                throw error(HttpStatus.CONFLICT, "版本已修改，请刷新后重试");
            audit(sceneId, versionId, null, "VERSION_EDIT", Map.of("before", before.get("description"), "after", input.description()));
            return detail(versionId);
        });
    }

    // 上传

    /** 持版本读锁并登记在途文件；发布/删除中或同文件重复上传返回 409。 */
    public Map<String, Object> upload(UUID versionId, UUID id, InputStream input) {
        sceneOf(versionId);
        lockRead(versionId);
        try {
            if (!activeUploads.add(id)) throw error(HttpStatus.CONFLICT, "文件正在处理，请稍后刷新或重试");
            try {
                return uploadLocked(versionId, id, input);
            } finally {
                activeUploads.remove(id);
            }
        } finally {
            versionLock(versionId).readLock().unlock();
        }
    }

    /**
     * 分三步：事务标记 UPLOADING → 事务外写文件 → finish 提交结果。
     * 大小/摘要或上限不符返回 422，其他 IO 错误返回 503；均可重传原文件。
     */
    private Map<String, Object> uploadLocked(UUID versionId, UUID id, InputStream input) {
        var row = tx.execute(s -> {
            UUID sceneId = sceneOf(versionId);
            requireNotDeleting(versionId);
            var current = file(versionId, id);
            if (!"AVAILABLE".equals(current.get("status"))) {
                db.update("update ar_version_file set status='UPLOADING',failure_reason=null,verified_bytes=null,verified_sha256=null,attempts=attempts+1,last_actor_id=?,last_actor_name=?,updated_at=now() where id=?",
                        SecurityUtils.getUserId(), SecurityUtils.getUsername(), id);
                audit(sceneId, versionId, id, "FILE_UPLOAD_START", Map.of());
            }
            return current;
        });
        // 未入库文件此时已提交 UPLOADING；落盘后未提交结果的文件由启动对账补记。
        boolean wasAvailable = "AVAILABLE".equals(row.get("status"));
        try {
            var expected = descriptor(row);
            // 已入库文件不重写、不重算摘要，只核对长度。
            if (wasAvailable) {
                if (storage.size(expected.id()) != expected.bytes())
                    throw new IOException("Artifact missing or size mismatch");
            } else storeReplacingUnverified(expected, input);
        } catch (IOException e) {
            String message = String.valueOf(e.getMessage());
            boolean mismatch = message.contains("size mismatch") || message.contains("SHA256 mismatch") || message.contains("exceeds configured storage limit");
            String reason = message.contains("size mismatch") ? "实际文件大小与登记值不一致，请核对原文件"
                    : message.contains("SHA256 mismatch") ? "实际 SHA256 与登记摘要不一致，请核对原文件"
                    : message.contains("exceeds configured storage limit") ? "文件超过当前存储大小上限"
                    : "上传中断或存储不可用，请重新选择原文件重试；持续失败请联系管理员检查存储";
            finish(versionId, id, false, reason, false);
            throw mismatch ? error(HttpStatus.UNPROCESSABLE_ENTITY, reason) : error(HttpStatus.SERVICE_UNAVAILABLE, reason);
        }
        // 存储成功后，再单独提交 AVAILABLE。
        if (!wasAvailable) finish(versionId, id, true, null, false);
        return file(versionId, id);
    }

    /** 仅对尚未就绪的文件，删除校验失败的残留后重新接收。 */
    private void storeReplacingUnverified(ArtifactStorage.Descriptor expected, InputStream input) throws IOException {
        try {
            storage.store(expected, input);
        } catch (ArtifactStorage.UnverifiedLeftoverException leftover) {
            storage.delete(expected.id());
            storage.store(expected, input);
        }
    }

    /** 状态、校验结果和审计在同一事务提交；沿用最后上传者，恢复操作另标系统执行。 */
    private void finish(UUID versionId, UUID id, boolean available, String reason, boolean recovery) {
        tx.executeWithoutResult(s -> {
            var before = one("select f.last_actor_id,f.last_actor_name,v.scene_id from ar_version_file f join ar_scene_version v on v.id=f.version_id where f.id=?", id);
            db.update("update ar_version_file set status=?,verified_bytes=case when ? then expected_bytes else null end,verified_sha256=case when ? then expected_sha256 else null end,failure_reason=?,updated_at=now() where id=?",
                    available ? "AVAILABLE" : "FAILED", available, available, reason, id);
            var values = new LinkedHashMap<String, Object>();
            values.put("status", available ? "AVAILABLE" : "FAILED");
            values.put("recovery", recovery);
            if (reason != null) values.put("reason", reason);
            if (recovery) values.put("performedBy", "SYSTEM_RECONCILIATION");
            audit((UUID) before.get("scene_id"), versionId, id, recovery ? "FILE_RECONCILE" : available ? "FILE_AVAILABLE" : "FILE_FAILED",
                    ((Number) before.get("last_actor_id")).longValue(), (String) before.get("last_actor_name"), values);
        });
    }

    // 发布

    /**
     * 锁版本和场景行，按场景修订号切换发布指针；已发布同一版本则直接返回。
     * 只检查数据库就绪状态，不搬文件、不重算摘要，旧版本保留。
     */
    public Map<String, Object> publish(UUID versionId, long expectedSceneVersion) {
        if (Boolean.TRUE.equals(summary(versionId).get("published"))) return detail(versionId);
        UUID sceneId = sceneOf(versionId);
        lockWrite(versionId);
        try {
            return tx.execute(s -> {
                scene(sceneId, true);
                // 锁前检查后状态可能已变化，持锁再确认一次。
                if (Boolean.TRUE.equals(summary(versionId).get("published"))) return detail(versionId);
                var sceneRow = one("select lock_version as \"lockVersion\", published_version_id as \"publishedVersionId\" from ar_scene where id=? and deleted_at is null", sceneId);
                if (((Number) sceneRow.get("lockVersion")).longValue() != expectedSceneVersion)
                    throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
                requireComplete(versionId);
                UUID from = (UUID) sceneRow.get("publishedVersionId");
                if (db.update("update ar_scene set published_version_id=?,published_at=now(),published_by_id=?,published_by_name=?,lock_version=lock_version+1,updated_at=now() where id=? and deleted_at is null and lock_version=?",
                        versionId, SecurityUtils.getUserId(), SecurityUtils.getUsername(), sceneId, expectedSceneVersion) != 1)
                    throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
                var values = new LinkedHashMap<String, Object>();
                values.put("fromVersionId", from == null ? null : from.toString());
                values.put("toVersionId", versionId.toString());
                audit(sceneId, versionId, null, "VERSION_PUBLISH", values);
                return detail(versionId);
            });
        } finally {
            versionLock(versionId).writeLock().unlock();
        }
    }

    private void requireComplete(UUID versionId) {
        var row = summary(versionId);
        switch ((String) row.get("uploadStatus")) {
            case "READY" -> {
            }
            case "DELETING", "DELETE_FAILED" -> throw error(HttpStatus.CONFLICT, "版本正在删除，不能发布");
            case "UPLOADING" -> throw error(HttpStatus.CONFLICT, "文件正在处理，请稍后刷新再发布");
            default -> throw error(HttpStatus.BAD_REQUEST, "存在未完成或失败的文件，不能发布");
        }
    }

    // 整版删除

    /**
     * 持版本写锁：先提交删除意图，再删文件，最后删行并保留完成回执。
     * 当前发布版本不可删；失败可重试，已有完成回执则直接成功。
     */
    public void removeVersion(UUID versionId) {
        if (db.queryForList("select id from ar_scene_version where id=?", versionId).isEmpty()) {
            if (Boolean.TRUE.equals(db.queryForObject("select exists(select 1 from ar_version_deletion where version_id=? and completed_at is not null)", Boolean.class, versionId)))
                return;
            throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
        }
        lockWrite(versionId);
        try {
            boolean needed = Boolean.TRUE.equals(tx.execute(s -> {
                var version = db.queryForList("select scene_id,request_key,version_no,description from ar_scene_version where id=?", versionId);
                if (version.isEmpty()) return false;
                UUID sceneId = (UUID) version.get(0).get("scene_id");
                scene(sceneId, true);
                if (published(versionId)) throw error(HttpStatus.CONFLICT, "当前发布版本不能删除，请先发布其他版本");
                var detail = new LinkedHashMap<String, Object>();
                detail.put("versionNo", version.get(0).get("version_no"));
                detail.put("description", version.get(0).get("description"));
                detail.put("fileCount", db.queryForObject("select count(*) from ar_version_file where version_id=?", Long.class, versionId));
                // 删除重试沿用回执，更新操作者并清除旧错误。
                if (db.queryForList("select 1 from ar_version_deletion where version_id=?", versionId).isEmpty()) {
                    db.update("insert into ar_version_deletion(version_id,scene_id,request_key,actor_id,actor_name) values(?,?,?,?,?)",
                            versionId, sceneId, version.get(0).get("request_key"), SecurityUtils.getUserId(), SecurityUtils.getUsername());
                } else {
                    db.update("update ar_version_deletion set failure_reason=null,actor_id=?,actor_name=? where version_id=?",
                            SecurityUtils.getUserId(), SecurityUtils.getUsername(), versionId);
                    detail.put("retry", true);
                }
                audit(sceneId, versionId, null, "VERSION_DELETE_REQUEST", detail);
                return true;
            }));
            // 删除意图已提交；部分文件删除失败时保留记录供重试。
            if (needed && !completeDeletion(versionId, false))
                throw error(HttpStatus.SERVICE_UNAVAILABLE, "物理删除未完成，请查看失败原因并重试删除版本");
        } finally {
            versionLock(versionId).writeLock().unlock();
        }
    }

    /**
     * 调用方须持版本写锁。全部文件删除后才提交删行和完成回执。
     * 部分删除失败不回滚文件，保留行和失败原因供重试；审计沿用回执操作者。
     */
    private boolean completeDeletion(UUID versionId, boolean recovery) {
        var receipts = db.queryForList("select scene_id,actor_id,actor_name from ar_version_deletion where version_id=? and completed_at is null", versionId);
        if (receipts.isEmpty()) return true;
        UUID sceneId = (UUID) receipts.get(0).get("scene_id");
        long actor = ((Number) receipts.get(0).get("actor_id")).longValue();
        String actorName = (String) receipts.get(0).get("actor_name");
        var performed = recovery ? Map.<String, Object>of("recovery", true, "performedBy", "SYSTEM_RECONCILIATION") : Map.<String, Object>of("recovery", false);
        var fileIds = db.queryForList("select id from ar_version_file where version_id=? order by id", versionId);
        try {
            for (var row : fileIds) storage.delete((UUID) row.get("id"));
        } catch (IOException e) {
            tx.executeWithoutResult(s -> {
                db.update("update ar_version_deletion set failure_reason=? where version_id=? and completed_at is null",
                        "存储文件删除失败，请检查存储权限或文件占用后重试删除", versionId);
                audit(sceneId, versionId, null, "VERSION_DELETE_FAILED", actor, actorName, performed);
            });
            return false;
        }
        tx.executeWithoutResult(s -> {
            db.update("delete from ar_version_file where version_id=?", versionId);
            db.update("delete from ar_scene_version where id=?", versionId);
            db.update("update ar_version_deletion set completed_at=now(),failure_reason=null where version_id=?", versionId);
            var values = new LinkedHashMap<String, Object>(performed);
            values.put("physicalFilesDeleted", true);
            values.put("fileCount", fileIds.size());
            audit(sceneId, versionId, null, "VERSION_DELETE", actor, actorName, values);
        });
        return true;
    }

    // 文件传输

    /** 持读锁，拒绝删除中或未就绪的文件；以附件形式返回。 */
    public void adminDownload(UUID versionId, UUID fileId, HttpServletRequest request, HttpServletResponse response) throws IOException {
        sceneOf(versionId);
        lockRead(versionId);
        try {
            requireNotDeleting(versionId);
            var file = file(versionId, fileId);
            if (!"AVAILABLE".equals(file.get("status"))) throw error(HttpStatus.CONFLICT, "文件尚未上传完成");
            stream(file, "application/octet-stream", (String) file.get("relativePath"), request, response);
        } finally {
            versionLock(versionId).readLock().unlock();
        }
    }

    /**
     * 锁前后检查场景发布指针；旧版本 URL 返回 409，不自动切换文件。
     * 读锁持有至传输结束，期间不再检查发布指针；URL 文件名只校验，不用于落盘。
     */
    public void clientDownload(UUID sceneId, UUID versionId, UUID fileId, String fileName, HttpServletRequest request, HttpServletResponse response) throws IOException {
        clientVersion(sceneId, versionId);
        lockRead(versionId);
        try {
            clientVersion(sceneId, versionId);
            var file = file(versionId, fileId);
            String path = (String) file.get("relativePath");
            if (!RelativePath.fileName(path).equals(fileName))
                throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
            requireNotDeleting(versionId);
            if (!"AVAILABLE".equals(file.get("status"))) throw error(HttpStatus.CONFLICT, "文件尚未就绪");
            String contentType = ClientSceneService.contentType(path);
            stream(file, contentType, null, request, response);
        } finally {
            versionLock(versionId).readLock().unlock();
        }
    }

    /** 场景不可见或版本不属于场景返回 404，已被替换的发布版本返回 409。 */
    private void clientVersion(UUID sceneId, UUID versionId) {
        var rows = db.queryForList("select s.published_version_id from ar_scene s join ar_scene_version v on v.scene_id=s.id"
                + " where s.id=? and v.id=? and s.enabled and s.deleted_at is null and s.published_version_id is not null", sceneId, versionId);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
        if (!versionId.equals(rows.get(0).get("published_version_id")))
            throw error(HttpStatus.CONFLICT, "该版本已不是当前发布版本，请重新获取场景详情");
    }

    /** 调用方须持版本读锁。核对长度，用登记摘要作 ETag，不重算摘要。 */
    private void stream(Map<String, Object> file, String contentType, String attachmentName, HttpServletRequest request, HttpServletResponse response) throws IOException {
        UUID fileId = UUID.fromString((String) file.get("fileId"));
        long size = ((Number) file.get("bytes")).longValue();
        try {
            if (storage.size(fileId) != size) throw new IOException("Artifact size mismatch");
        } catch (IOException e) {
            throw error(HttpStatus.CONFLICT, "文件已记录但存储缺失或长度不符，请联系管理员检查存储");
        }

        String etag = "\"" + file.get("sha256") + "\"";
        HttpRange.Slice slice = HttpRange.parse(request, size, etag);
        HttpRange.write(response, slice, etag, contentType, attachmentName == null ? null : RelativePath.fileName(attachmentName),
                !"HEAD".equalsIgnoreCase(request.getMethod()),
                (offset, length) -> storage.open(fileId, offset, length));
    }

    // 启动恢复

    /**
     * 数据库初始化后先续做删除，再恢复 PENDING/UPLOADING/FAILED 文件。
     * 完整遗留字节校验通过才补记 AVAILABLE；中断上传无完整字节则记 FAILED。
     * 不扫描 AVAILABLE 正文；存储无法盘点时拒绝启动。
     */
    @Override
    public void afterPropertiesSet() {
        // 先续做删除，避免把删除中的文件恢复为可用。
        for (var row : db.queryForList("select version_id from ar_version_deletion where completed_at is null order by version_id")) {
            UUID versionId = (UUID) row.get("version_id");
            lockWrite(versionId);
            try {
                completeDeletion(versionId, true);
            } finally {
                versionLock(versionId).writeLock().unlock();
            }
        }
        // 只核对存储中有遗留数据的文件。
        Set<UUID> leftovers = new HashSet<>();
        try {
            for (var entry : storage.inventory()) leftovers.add(entry.id());
        } catch (IOException e) {
            throw new IllegalStateException("存储目录无法盘点，拒绝启动对账", e);
        }
        UUID cursor = new UUID(0, 0);
        while (true) {
            var rows = db.queryForList("select " + FILE_COLUMNS + ", version_id::text as \"versionId\" from ar_version_file where id>? and status in ('PENDING','UPLOADING','FAILED') and not "
                    + PENDING_DELETION.formatted("ar_version_file.version_id") + " order by id limit 100", cursor);
            if (rows.isEmpty()) break;
            for (var row : rows) {
                UUID id = UUID.fromString((String) row.get("fileId"));
                cursor = id;
                UUID versionId = UUID.fromString((String) row.get("versionId"));
                String status = (String) row.get("status");
                try {

                    // .part 不算完整文件；缺少完整字节的在途上传标记为失败。
                    if (leftovers.contains(id) && storage.recover(descriptor(row)))
                        finish(versionId, id, true, null, true);
                    else if ("UPLOADING".equals(status))
                        finish(versionId, id, false, "重启对账未找到完整且校验通过的正式文件，请重新上传", true);
                } catch (IOException e) {
                    if (!"FAILED".equals(status))
                        finish(versionId, id, false, "重启对账未找到完整且校验通过的正式文件，请重新上传", true);
                }
            }
        }
    }
}
