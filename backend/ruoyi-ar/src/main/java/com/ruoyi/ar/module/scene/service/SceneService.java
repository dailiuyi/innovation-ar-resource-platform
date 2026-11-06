package com.ruoyi.ar.module.scene.service;

import com.ruoyi.ar.module.scene.manager.SceneConcurrency;
import com.ruoyi.ar.module.scene.manager.SceneManager;
import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.model.SceneCreateReq;
import com.ruoyi.ar.module.scene.model.SceneCreateFileReq;
import com.ruoyi.ar.module.scene.model.SceneRows;
import com.ruoyi.ar.module.scene.model.SceneUpdateReq;
import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.ar.support.RelativePath;
import com.ruoyi.common.utils.SecurityUtils;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import static com.ruoyi.ar.module.scene.service.SceneChecks.error;
import static com.ruoyi.ar.module.scene.service.SceneChecks.required;
import static com.ruoyi.ar.module.scene.service.SceneChecks.writeLock;

/**
 * 场景生命周期服务：创建（含固定文件清单）、查询、元数据编辑、启停与整场景删除。
 * <p>
 * 一个场景只有一份创建后不可变的文件清单；不存在版本、发布或替换操作。
 * 删除先持久化意图，再在事务外清理物理文件，成功后删除文件行并保留最小回执与审计。
 * 仅支持单实例：删除与文件传输共用场景锁。
 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneService {
    private final SceneManager manager;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final SceneConcurrency concurrency;
    private final long maxBytes;
    private final int sceneMaxFiles;
    private final long sceneMaxBytes;

    public SceneService(SceneManager manager, PlatformTransactionManager transactions, ArtifactStorage storage,
                        SceneConcurrency concurrency,
                        @Value("${ar.storage.max-bytes}") long maxBytes,
                        @Value("${ar.storage.scene-max-files}") int sceneMaxFiles,
                        @Value("${ar.storage.scene-max-bytes}") long sceneMaxBytes) {
        this.manager = manager;
        this.tx = new TransactionTemplate(transactions);
        this.storage = storage;
        this.concurrency = concurrency;
        this.maxBytes = maxBytes;
        this.sceneMaxFiles = sceneMaxFiles;
        this.sceneMaxBytes = sceneMaxBytes;
    }

    /** 单文件、单场景文件数与总字节数上限，供导入前预检。 */
    public Map<String, Object> config() {
        return Map.of("maxBytes", maxBytes, "sceneMaxFiles", sceneMaxFiles, "sceneMaxBytes", sceneMaxBytes);
    }

    public Page<SceneRows.Summary> list(String name, int limit, int offset) {
        return manager.list(name, limit, offset);
    }

    /** 场景概要加固定文件清单；DELETING/DELETE_FAILED 场景仍可查看以支持重试。 */
    public Map<String, Object> detail(UUID sceneId) {
        return detail(required(manager.summary(sceneId)));
    }

    private Map<String, Object> detail(SceneRows.Summary scene) {
        var result = new LinkedHashMap<String, Object>();
        result.put("id", scene.id());
        result.put("name", scene.name());
        result.put("description", scene.description());
        result.put("enabled", scene.enabled());
        result.put("lockVersion", scene.lockVersion());
        result.put("uploadStatus", scene.uploadStatus());
        result.put("fileCount", scene.fileCount());
        result.put("availableCount", scene.availableCount());
        result.put("failedCount", scene.failedCount());
        result.put("totalBytes", scene.totalBytes());
        result.put("createdAt", scene.createdAt());
        result.put("updatedAt", scene.updatedAt());
        result.put("files", manager.files(UUID.fromString(scene.id())).stream()
                .map(SceneRows.File::response).toList());
        return result;
    }

    /** 创建结果：首次创建为 201，同一创建键的相同请求重试为 200。 */
    public record Created(Map<String, Object> scene, boolean created) {
    }

    /**
     * 校验并原子创建场景与固定文件清单。
     * <p>
     * 幂等规则：同一 requestKey 且名称、说明和文件清单（路径/大小/SHA-256 集合）一致返回既有场景；
     * 内容不同返回 409；创建键已被删除回执或软删除场景占用返回 410。
     */
    public Created create(SceneCreateReq input) {
        var files = input.files();
        if (files.isEmpty()) throw error(HttpStatus.BAD_REQUEST, "files 不能为空");
        if (files.size() > sceneMaxFiles) throw error(HttpStatus.PAYLOAD_TOO_LARGE, "超过每个场景的文件数量上限");
        long total = 0;
        for (var file : files) {
            if (file.bytes() > maxBytes)
                throw error(HttpStatus.PAYLOAD_TOO_LARGE, "文件超过配置的大小上限：" + file.relativePath());
            // 用剩余额度比较，避免多个合法大文件求和时 long 溢出为负。
            if (file.bytes() > sceneMaxBytes - total)
                throw error(HttpStatus.PAYLOAD_TOO_LARGE, "超过每个场景的总大小上限");
            total += file.bytes();
        }
        List<String> paths;
        try {
            paths = RelativePath.normalizeAll(files.stream().map(SceneCreateFileReq::relativePath).toList());
        } catch (IllegalArgumentException e) {
            throw error(HttpStatus.BAD_REQUEST, "files " + e.getMessage());
        }
        for (String path : paths) {
            String name = RelativePath.fileName(path);
            // 文件名含 % 或 ; 时下载 URL 无法承载，在导入时拒绝。
            if (name.indexOf('%') >= 0 || name.indexOf(';') >= 0)
                throw error(HttpStatus.BAD_REQUEST, "files 文件名不能包含 % 或 ;，客户端下载地址无法承载：" + path);
        }
        var specs = new ArrayList<SceneRows.FileSpec>(files.size());
        for (int i = 0; i < files.size(); i++)
            specs.add(new SceneRows.FileSpec(paths.get(i), files.get(i).bytes(), files.get(i).sha256()));
        String description = input.description() == null ? "" : input.description();
        final long totalBytes = total;
        return tx.execute(s -> {
            UUID requestKey = input.requestKey();
            if (manager.requestKeyBlocked(requestKey))
                throw error(HttpStatus.GONE, "该场景已删除或正在删除，重新创建请使用新的请求标识");
            var existing = manager.summaryByRequestKey(requestKey);
            if (existing != null) return reuse(existing, input.name(), description, specs);
            UUID id = UUID.randomUUID();
            long actor = SecurityUtils.getUserId();
            String actorName = SecurityUtils.getUsername();
            if (!manager.create(id, requestKey, input.name(), description, specs, actor, actorName)) {
                // 并发的相同创建键已先提交；按幂等规则返回或拒绝。
                if (manager.requestKeyBlocked(requestKey))
                    throw error(HttpStatus.GONE, "该场景已删除或正在删除，重新创建请使用新的请求标识");
                existing = required(manager.summaryByRequestKey(requestKey));
                return reuse(existing, input.name(), description, specs);
            }
            manager.audit(id, "CREATE", actor, actorName, Map.of(
                    "name", input.name(), "description", description,
                    "fileCount", specs.size(), "totalBytes", totalBytes));
            return new Created(detail(id), true);
        });
    }

    private Created reuse(SceneRows.Summary existing, String name, String description,
                          List<SceneRows.FileSpec> specs) {
        UUID id = UUID.fromString(existing.id());
        if (!existing.name().equals(name) || !existing.description().equals(description)
                || !sameManifest(id, specs))
            throw error(HttpStatus.CONFLICT, "同一请求标识已用于不同内容，请刷新核对");
        return new Created(detail(existing), false);
    }

    /** 清单比较不要求输入顺序一致。 */
    static boolean sameManifest(List<SceneRows.File> stored, List<SceneRows.FileSpec> specs) {
        if (stored.size() != specs.size()) return false;
        Set<SceneRows.FileSpec> files = new HashSet<>();
        for (var row : stored) files.add(new SceneRows.FileSpec(row.relativePath(), row.bytes(), row.sha256()));
        return files.equals(new HashSet<>(specs));
    }

    private boolean sameManifest(UUID sceneId, List<SceneRows.FileSpec> specs) {
        return sameManifest(manager.files(sceneId), specs);
    }

    /** 修改名称和说明；文件清单不可修改。删除中的场景不可编辑。 */
    public Map<String, Object> update(UUID sceneId, SceneUpdateReq input) {
        String description = input.description() == null ? "" : input.description();
        return tx.execute(s -> {
            if (!manager.lockScene(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景不存在");
            if (manager.deleting(sceneId)) throw error(HttpStatus.CONFLICT, "场景正在删除，暂不能操作");
            var before = required(manager.summary(sceneId));
            if (!manager.edit(sceneId, input.name(), description, input.expectedVersion()))
                throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
            manager.audit(sceneId, "UPDATE", SecurityUtils.getUserId(), SecurityUtils.getUsername(), Map.of(
                    "before", Map.of("name", before.name(), "description", before.description()),
                    "after", Map.of("name", input.name(), "description", description)));
            return detail(sceneId);
        });
    }

    /** 启停只影响新的匿名读取；已有下载流继续完成，上传与恢复从不启用场景。 */
    public Map<String, Object> enabled(UUID sceneId, boolean enabled, long expectedVersion, String reason) {
        return tx.execute(s -> {
            if (!manager.lockScene(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景不存在");
            if (manager.deleting(sceneId)) throw error(HttpStatus.CONFLICT, "场景正在删除，暂不能操作");
            var before = required(manager.summary(sceneId));
            if (!manager.enabled(sceneId, enabled, expectedVersion))
                throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
            manager.audit(sceneId, "SET_ENABLED", SecurityUtils.getUserId(), SecurityUtils.getUsername(), Map.of(
                    "before", before.enabled(), "after", enabled, "reason", reason));
            return detail(sceneId);
        });
    }

    /**
     * 整场景物理删除。
     * <p>
     * 先提交删除意图（之后的重试忽略过期 expectedVersion），再删除该场景所有存储阶段的文件，
     * 最后删除文件行、软删除场景行并完成回执。物理删除失败保留意图，接口返回 503 供重试。
     */
    public void delete(UUID sceneId, long expectedVersion) {
        var lock = writeLock(concurrency, sceneId);
        try {
            boolean needed = Boolean.TRUE.equals(tx.execute(s -> {
                if (!manager.lockScene(sceneId)) {
                    if (manager.deletionCompleted(sceneId)) return false;
                    throw error(HttpStatus.NOT_FOUND, "场景不存在");
                }
                long actor = SecurityUtils.getUserId();
                String actorName = SecurityUtils.getUsername();
                var scene = required(manager.summary(sceneId));
                if (manager.deletionExists(sceneId)) {
                    if (manager.deletionCompleted(sceneId)) return false;
                    // 意图已持久化：重试沿用回执，允许调用方使用过期 expectedVersion。
                    manager.retryDeletion(sceneId, actor, actorName);
                    manager.audit(sceneId, "SCENE_DELETE_REQUEST", actor, actorName, Map.of(
                            "fileCount", scene.fileCount(), "totalBytes", scene.totalBytes(), "retry", true));
                    return true;
                }
                if (scene.lockVersion() != expectedVersion)
                    throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
                manager.requestDeletion(sceneId, required(manager.scene(sceneId)).requestKey(), actor, actorName);
                manager.audit(sceneId, "SCENE_DELETE_REQUEST", actor, actorName, Map.of(
                        "fileCount", scene.fileCount(), "totalBytes", scene.totalBytes()));
                return true;
            }));
            if (needed && !completeDeletion(sceneId, false))
                throw error(HttpStatus.SERVICE_UNAVAILABLE, "物理删除未完成，请查看失败原因并重试删除场景");
        } finally {
            lock.unlock();
        }
    }

    /**
     * 调用方须持场景写锁。全部文件删除后才提交删行、场景标记和完成回执。
     * 部分删除失败不回滚已删除文件，保留意图和失败原因供重试；审计沿用回执操作者。
     */
    private boolean completeDeletion(UUID sceneId, boolean recovery) {
        var receipt = manager.deletionActor(sceneId);
        if (receipt == null) return true;
        long actor = receipt.actorId();
        String actorName = receipt.actorName();
        var performed = recovery
                ? Map.<String, Object>of("recovery", true, "performedBy", "SYSTEM_RECONCILIATION")
                : Map.<String, Object>of("recovery", false);
        var fileIds = manager.fileIds(sceneId);
        try {
            for (String id : fileIds) storage.delete(UUID.fromString(id));
        } catch (IOException e) {
            tx.executeWithoutResult(s -> {
                manager.failDeletion(sceneId, "存储文件删除失败，请检查存储权限或文件占用后重试删除");
                if (manager.sceneExists(sceneId))
                    manager.audit(sceneId, "SCENE_DELETE_FAILED", actor, actorName, performed);
            });
            return false;
        }
        tx.executeWithoutResult(s -> {
            if (manager.sceneExists(sceneId)) {
                var values = new LinkedHashMap<String, Object>(performed);
                values.put("physicalFilesDeleted", true);
                values.put("fileCount", fileIds.size());
                manager.audit(sceneId, "SCENE_DELETE", actor, actorName, values);
            }
            manager.completeDeletion(sceneId);
        });
        return true;
    }

    /** 启动时先续做删除，避免把删除中的文件恢复为可用。 */
    public void recoverDeletions() {
        for (String id : manager.pendingDeletions()) {
            UUID sceneId = UUID.fromString(id);
            var lock = writeLock(concurrency, sceneId);
            try {
                completeDeletion(sceneId, true);
            } finally {
                lock.unlock();
            }
        }
    }
}
