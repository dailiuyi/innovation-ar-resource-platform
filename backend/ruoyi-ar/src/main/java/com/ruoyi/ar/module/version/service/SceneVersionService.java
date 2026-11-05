package com.ruoyi.ar.module.version.service;

import com.ruoyi.ar.module.version.manager.SceneVersionManager;
import com.ruoyi.ar.module.version.manager.VersionConcurrency;
import com.ruoyi.ar.module.version.model.SceneVersionCreateReq;
import com.ruoyi.ar.module.version.model.SceneVersionEditReq;
import com.ruoyi.ar.module.version.model.SceneVersionFileReq;
import com.ruoyi.ar.module.version.model.VersionRows.FileSpec;
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

import static com.ruoyi.ar.module.version.service.VersionChecks.error;
import static com.ruoyi.ar.module.version.service.VersionChecks.required;
import static com.ruoyi.ar.module.version.service.VersionChecks.writeLock;

/**
 * 管理版本创建、查询、说明编辑、发布和整版删除。
 * 文件清单创建后固定；删除意图、物理文件删除和完成回执分阶段提交。
 * 仅支持单实例：发布和删除与文件传输共用版本锁。
 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneVersionService {
    private final SceneVersionManager manager;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final VersionConcurrency concurrency;
    private final long maxBytes;
    private final int versionMaxFiles;
    private final long versionMaxBytes;

    public SceneVersionService(SceneVersionManager manager, PlatformTransactionManager transactions, ArtifactStorage storage,
                               VersionConcurrency concurrency,
                               @Value("${ar.storage.max-bytes}") long maxBytes,
                               @Value("${ar.storage.version-max-files}") int versionMaxFiles,
                               @Value("${ar.storage.version-max-bytes}") long versionMaxBytes) {
        this.manager = manager;
        this.tx = new TransactionTemplate(transactions);
        this.storage = storage;
        this.concurrency = concurrency;
        this.maxBytes = maxBytes;
        this.versionMaxFiles = versionMaxFiles;
        this.versionMaxBytes = versionMaxBytes;
    }

    public Map<String, Object> config() {
        return Map.of("maxBytes", maxBytes, "versionMaxFiles", versionMaxFiles, "versionMaxBytes", versionMaxBytes);
    }

    public Map<String, Object> detail(UUID versionId) {
        var row = required(manager.summary(versionId)).response();
        row.put("files", manager.files(versionId));
        return row;
    }

    /** 附带场景修订号，供发布时校验；不同于版本说明的修订号。 */
    public Map<String, Object> list(UUID sceneId, int limit, int offset) {
        var sceneRow = required(manager.sceneState(sceneId));
        var result = new LinkedHashMap<String, Object>();
        result.put("items", manager.list(sceneId, limit, offset));
        result.put("total", manager.count(sceneId));
        result.put("sceneLockVersion", sceneRow.lockVersion());
        if (sceneRow.publishedVersionId() != null)
            result.put("published", required(manager.publishedVersion(sceneId)));
        return result;
    }

    /** created=false 表示复用同一 requestKey 的既有版本。 */
    public record Created(Map<String, Object> version, boolean created) {
    }

    /**
     * 先校验清单，再锁场景行登记版本、文件和审计，不接收文件正文。
     * 同一 requestKey：内容相同则复用，不同返回 409；有删除回执则返回 410。
     */
    public Created create(UUID sceneId, SceneVersionCreateReq input) {
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
            paths = RelativePath.normalizeAll(files.stream().map(SceneVersionFileReq::relativePath).toList());
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
            if (!manager.lockScene(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
            // 删除回执阻止旧请求重新创建已删除版本。
            if (manager.deletedRequest(sceneId, input.requestKey()))
                throw error(HttpStatus.GONE, "该版本已删除或正在删除，重新导入请使用新的请求标识");
            UUID existing = manager.existingRequest(sceneId, input.requestKey());
            if (existing != null) {
                if (!sameRequest(existing, input.description(), specs))
                    throw error(HttpStatus.CONFLICT, "同一请求标识已用于不同内容，请刷新核对");
                return new Created(detail(existing), false);
            }
            UUID id = UUID.randomUUID();
            long actor = SecurityUtils.getUserId();
            String name = SecurityUtils.getUsername();
            int versionNo = manager.create(id, sceneId, input.requestKey(), input.description(), specs, actor, name);
            manager.audit(sceneId, id, null, "VERSION_CREATE", actor, name,
                    Map.of("versionNo", versionNo, "description", input.description(), "fileCount", specs.size(), "totalBytes", totalBytes));
            return new Created(detail(id), true);
        });
    }

    /** 幂等比较包含说明及路径/大小/摘要集合，不要求文件排列顺序相同。 */
    private boolean sameRequest(UUID id, String description, List<FileSpec> specs) {
        if (!manager.descriptionMatches(id, description)) return false;
        Set<FileSpec> stored = new HashSet<>();
        for (var row : manager.files(id))
            stored.add(new FileSpec(row.relativePath(), row.bytes(), row.sha256()));
        return stored.equals(new HashSet<>(specs));
    }

    /** 按版本修订号更新说明；删除中的版本不可编辑，文件清单不可改。 */
    public Map<String, Object> edit(UUID versionId, SceneVersionEditReq input) {
        return tx.execute(s -> {
            UUID sceneId = required(manager.sceneOf(versionId));
            if (!manager.lockScene(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
            requireNotDeleting(versionId);
            var before = required(manager.summary(versionId));
            if (!manager.edit(versionId, input.description(), input.expectedVersion()))
                throw error(HttpStatus.CONFLICT, "版本已修改，请刷新后重试");
            manager.audit(sceneId, versionId, null, "VERSION_EDIT", SecurityUtils.getUserId(), SecurityUtils.getUsername(),
                    Map.of("before", before.description(), "after", input.description()));
            return detail(versionId);
        });
    }

    private void requireNotDeleting(UUID versionId) {
        if (manager.deleting(versionId)) throw error(HttpStatus.CONFLICT, "版本正在删除，暂不能操作");
    }

    /**
     * 锁版本和场景行，按场景修订号切换发布指针；已发布同一版本则直接返回。
     * 只检查数据库就绪状态，不搬文件、不重算摘要，旧版本保留。
     */
    public Map<String, Object> publish(UUID versionId, long expectedSceneVersion) {
        if (required(manager.summary(versionId)).published()) return detail(versionId);
        UUID sceneId = required(manager.sceneOf(versionId));
        var lock = writeLock(concurrency, versionId);
        try {
            return tx.execute(s -> {
                if (!manager.lockScene(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
                // 锁前检查后状态可能已变化，持锁再确认一次。
                if (required(manager.summary(versionId)).published()) return detail(versionId);
                var sceneRow = required(manager.sceneState(sceneId));
                if (sceneRow.lockVersion() != expectedSceneVersion)
                    throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
                requireComplete(versionId);
                String from = sceneRow.publishedVersionId();
                if (!manager.publish(sceneId, versionId, SecurityUtils.getUserId(), SecurityUtils.getUsername(), expectedSceneVersion))
                    throw error(HttpStatus.CONFLICT, "场景已修改，请刷新后重试");
                var values = new LinkedHashMap<String, Object>();
                values.put("fromVersionId", from);
                values.put("toVersionId", versionId.toString());
                manager.audit(sceneId, versionId, null, "VERSION_PUBLISH", SecurityUtils.getUserId(), SecurityUtils.getUsername(), values);
                return detail(versionId);
            });
        } finally {
            lock.unlock();
        }
    }

    private void requireComplete(UUID versionId) {
        var row = required(manager.summary(versionId));
        switch (row.uploadStatus()) {
            case "READY" -> {
            }
            case "DELETING", "DELETE_FAILED" -> throw error(HttpStatus.CONFLICT, "版本正在删除，不能发布");
            case "UPLOADING" -> throw error(HttpStatus.CONFLICT, "文件正在处理，请稍后刷新再发布");
            default -> throw error(HttpStatus.BAD_REQUEST, "存在未完成或失败的文件，不能发布");
        }
    }

    /**
     * 持版本写锁：先提交删除意图，再删文件，最后删行并保留完成回执。
     * 当前发布版本不可删；失败可重试，已有完成回执则直接成功。
     */
    public void removeVersion(UUID versionId) {
        if (!manager.versionExists(versionId)) {
            if (manager.deletionCompleted(versionId)) return;
            throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
        }
        var lock = writeLock(concurrency, versionId);
        try {
            boolean needed = Boolean.TRUE.equals(tx.execute(s -> {
                var version = manager.version(versionId);
                if (version == null) return false;
                UUID sceneId = UUID.fromString(version.sceneId());
                if (!manager.lockScene(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
                if (manager.published(versionId)) throw error(HttpStatus.CONFLICT, "当前发布版本不能删除，请先发布其他版本");
                var detail = new LinkedHashMap<String, Object>();
                detail.put("versionNo", version.versionNo());
                detail.put("description", version.description());
                detail.put("fileCount", manager.fileCount(versionId));
                // 删除重试沿用回执，更新操作者并清除旧错误。
                if (manager.requestDeletion(versionId, version, SecurityUtils.getUserId(), SecurityUtils.getUsername()))
                    detail.put("retry", true);
                manager.audit(sceneId, versionId, null, "VERSION_DELETE_REQUEST", SecurityUtils.getUserId(), SecurityUtils.getUsername(), detail);
                return true;
            }));
            // 删除意图已提交；部分文件删除失败时保留记录供重试。
            if (needed && !completeDeletion(versionId, false))
                throw error(HttpStatus.SERVICE_UNAVAILABLE, "物理删除未完成，请查看失败原因并重试删除版本");
        } finally {
            lock.unlock();
        }
    }

    /**
     * 调用方须持版本写锁。全部文件删除后才提交删行和完成回执。
     * 部分删除失败不回滚文件，保留行和失败原因供重试；审计沿用回执操作者。
     */
    private boolean completeDeletion(UUID versionId, boolean recovery) {
        var receipt = manager.deletionActor(versionId);
        if (receipt == null) return true;
        UUID sceneId = UUID.fromString(receipt.sceneId());
        long actor = receipt.actorId();
        String actorName = receipt.actorName();
        var performed = recovery ? Map.<String, Object>of("recovery", true, "performedBy", "SYSTEM_RECONCILIATION") : Map.<String, Object>of("recovery", false);
        var fileIds = manager.fileIds(versionId);
        try {
            for (String id : fileIds) storage.delete(UUID.fromString(id));
        } catch (IOException e) {
            tx.executeWithoutResult(s -> {
                manager.failDeletion(versionId, "存储文件删除失败，请检查存储权限或文件占用后重试删除");
                manager.audit(sceneId, versionId, null, "VERSION_DELETE_FAILED", actor, actorName, performed);
            });
            return false;
        }
        tx.executeWithoutResult(s -> {
            manager.completeDeletion(versionId);
            var values = new LinkedHashMap<String, Object>(performed);
            values.put("physicalFilesDeleted", true);
            values.put("fileCount", fileIds.size());
            manager.audit(sceneId, versionId, null, "VERSION_DELETE", actor, actorName, values);
        });
        return true;
    }

    /** 启动时先续做删除，避免把删除中的文件恢复为可用。 */
    public void recoverDeletions() {
        for (String id : manager.pendingDeletions()) {
            UUID versionId = UUID.fromString(id);
            var lock = writeLock(concurrency, versionId);
            try {
                completeDeletion(versionId, true);
            } finally {
                lock.unlock();
            }
        }
    }
}
