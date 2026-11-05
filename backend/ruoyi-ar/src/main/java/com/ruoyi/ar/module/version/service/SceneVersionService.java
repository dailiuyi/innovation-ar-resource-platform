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

    /**
     * 查询当前服务端配置的存储配额限制。
     *
     * @return 包含单文件最大字节数、版本最大文件数和版本最大总字节数的 Map
     */
    public Map<String, Object> config() {
        return Map.of("maxBytes", maxBytes, "versionMaxFiles", versionMaxFiles, "versionMaxBytes", versionMaxBytes);
    }

    /**
     * 查询单个版本的详情及其下全部关联文件的上传就绪状态。
     *
     * @param versionId 版本唯一标识 UUID
     * @return 包含版本概要字段与文件数组的详情 Map
     */
    public Map<String, Object> detail(UUID versionId) {
        var row = required(manager.summary(versionId)).response();
        row.put("files", manager.files(versionId));
        return row;
    }

    /**
     * 分页查询指定场景下的版本列表，并附带场景当前的乐观锁版本号及发布指针。
     *
     * @param sceneId 场景唯一标识 UUID
     * @param limit 每页条数限制（1~100）
     * @param offset 偏移量
     * @return 包含 {@code items}、{@code total}、{@code sceneLockVersion} 及可选 {@code published} 的响应 Map
     */
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

    /**
     * 版本创建操作结果载体。
     *
     * @param version 版本详情 Map
     * @param created 是否为新创建（true 为新生成，false 为复用相同 requestKey 的既有幂等版本）
     */
    public record Created(Map<String, Object> version, boolean created) {
    }

    /**
     * 校验文件清单并在单事务中原子登记版本、文件列表及创建审计（不接收实际文件二进制正文）。
     * <p>
     * <b>幂等性契约</b>：
     * <ul>
     *   <li>若传入的 {@code requestKey} 已存在且描述、文件路径、大小、SHA-256 集合完全一致，直接复用返回已有版本；</li>
     *   <li>若相同 {@code requestKey} 对应的内容不同，抛出 409 CONFLICT；</li>
     *   <li>若该 {@code requestKey} 曾被物理删除且存在删除回执，抛出 410 GONE，要求客户端换用新键。</li>
     * </ul>
     *
     * @param sceneId 场景唯一标识 UUID
     * @param input 版本创建请求体
     * @return 包含版本详情与创建标记的 {@link Created} 结果
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

    /**
     * 修改版本描述说明。
     * <p>
     * 文件的相对路径、大小与 SHA-256 清单在版本创建后物理锁定不可变；
     * 处于删除流程（DELETING）中的版本禁止修改说明；必须匹配版本自身的乐观锁版本号。
     *
     * @param versionId 版本唯一标识 UUID
     * @param input 包含新说明及 expectedVersion 的请求体
     * @return 更新后的版本详情 Map
     */
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
     * 将指定版本切换发布为场景的当前生效版本。
     * <p>
     * <b>并发与一致性保证</b>：
     * <ul>
     *   <li>在版本写锁保护下执行，排他阻止该版本下的并发上传与下载；</li>
     *   <li>严格核验版本下所有文件均处于 AVAILABLE 就绪状态；</li>
     *   <li>核验场景当前的乐观锁版本号等于 {@code expectedSceneVersion}，原子更新场景的当前发布指针；</li>
     *   <li>旧版本保持不动，可随时被重新发布或删除。</li>
     * </ul>
     *
     * @param versionId 待发布的版本唯一标识 UUID
     * @param expectedSceneVersion 场景当前的乐观锁版本号
     * @return 发布后的版本详情 Map
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
     * 执行整版本物理清理与删除。
     * <p>
     * <b>三阶段删除流程</b>：
     * <ol>
     *   <li><b>提交删除意图</b>：持版本写锁与场景行锁，校验非当前发布版本后，向删除回执表记录意图并置状态为 DELETING；</li>
     *   <li><b>物理文件清理</b>：逐个删除版本在底层文件存储中的所有物理实体文件；若部分文件删除异常，保留记录供重试；</li>
     *   <li><b>数据行清理与留痕</b>：所有物理文件清理完毕后，物理删除版本主表与文件表行，并在回执表持久化已完成状态。</li>
     * </ol>
     *
     * @param versionId 待删除的版本唯一标识 UUID
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
