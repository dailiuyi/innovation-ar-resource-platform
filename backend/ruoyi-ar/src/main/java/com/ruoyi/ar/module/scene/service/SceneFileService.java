package com.ruoyi.ar.module.scene.service;

import com.ruoyi.ar.module.scene.manager.SceneConcurrency;
import com.ruoyi.ar.module.scene.manager.SceneManager;
import com.ruoyi.ar.module.scene.model.SceneRows;
import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.ar.support.FileContentType;
import com.ruoyi.ar.support.HttpRange;
import com.ruoyi.ar.support.RelativePath;
import com.ruoyi.common.utils.SecurityUtils;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import static com.ruoyi.ar.module.scene.service.SceneChecks.error;
import static com.ruoyi.ar.module.scene.service.SceneChecks.readLock;
import static com.ruoyi.ar.module.scene.service.SceneChecks.required;

/** 固定清单文件的上传、管理端下载、匿名分发与启动对账；数据库事务与文件 IO 分开提交。 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneFileService {

    private final SceneManager manager;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final SceneConcurrency concurrency;

    public SceneFileService(SceneManager manager, PlatformTransactionManager transactions,
                            ArtifactStorage storage, SceneConcurrency concurrency) {
        this.manager = manager;
        this.tx = new TransactionTemplate(transactions);
        this.storage = storage;
        this.concurrency = concurrency;
    }

    private void requireScene(UUID sceneId) {
        if (!manager.sceneExists(sceneId)) throw error(HttpStatus.NOT_FOUND, "场景不存在");
    }

    private void requireNotDeleting(UUID sceneId) {
        if (manager.deleting(sceneId)) throw error(HttpStatus.CONFLICT, "场景正在删除，暂不能操作");
    }

    public Map<String, Object> fileStatus(UUID sceneId, UUID fileId) {
        requireScene(sceneId);
        return required(manager.file(sceneId, fileId)).response();
    }

    private ArtifactStorage.Descriptor descriptor(SceneRows.File row) {
        return new ArtifactStorage.Descriptor(UUID.fromString(row.fileId()), row.bytes(), row.sha256());
    }

    /**
     * 接收并保存单个文件的原始二进制流。
     * <p>
     * 场景读锁内防止删除，同一文件由在途集合拒绝并发重复上传；事务标记 UPLOADING 后在事务外流式写入，
     * 校验通过再单独提交 AVAILABLE。已 AVAILABLE 的文件只核对已存长度，绝不覆盖正文。
     */
    public Map<String, Object> upload(UUID sceneId, UUID fileId, InputStream input) {
        requireScene(sceneId);
        var lock = readLock(concurrency, sceneId);
        try {
            requireNotDeleting(sceneId);
            if (!concurrency.beginUpload(fileId)) throw error(HttpStatus.CONFLICT, "文件正在处理，请稍后刷新或重试");
            try {
                return uploadLocked(sceneId, fileId, input);
            } finally {
                concurrency.endUpload(fileId);
            }
        } finally {
            lock.unlock();
        }
    }

    /** 事务标记 UPLOADING → 事务外写文件 → finish 提交结果。大小/摘要不符 422，其他 IO 错误 503。 */
    private Map<String, Object> uploadLocked(UUID sceneId, UUID fileId, InputStream input) {
        var row = tx.execute(s -> {
            requireScene(sceneId);
            requireNotDeleting(sceneId);
            var current = required(manager.file(sceneId, fileId));
            if (!"AVAILABLE".equals(current.status())) {
                long actor = SecurityUtils.getUserId();
                String actorName = SecurityUtils.getUsername();
                manager.startUpload(fileId, actor, actorName);
                manager.audit(sceneId, "FILE_UPLOAD_START", actor, actorName, Map.of());
            }
            return current;
        });
        // 未入库文件此时已提交 UPLOADING；落盘后未提交结果的文件由启动对账补记。
        boolean wasAvailable = "AVAILABLE".equals(row.status());
        try {
            var expected = descriptor(row);
            // 已入库文件不重写、不重算摘要，只核对长度。
            if (wasAvailable) {
                if (storage.size(expected.id()) != expected.bytes())
                    throw new IOException("Artifact missing or size mismatch");
            } else storeReplacingUnverified(expected, input);
        } catch (IOException e) {
            String message = String.valueOf(e.getMessage());
            boolean mismatch = message.contains("size mismatch") || message.contains("SHA256 mismatch")
                    || message.contains("exceeds configured storage limit");
            String reason = message.contains("size mismatch") ? "实际文件大小与登记值不一致，请核对原文件"
                    : message.contains("SHA256 mismatch") ? "实际 SHA256 与登记摘要不一致，请核对原文件"
                    : message.contains("exceeds configured storage limit") ? "文件超过当前存储大小上限"
                    : "上传中断或存储不可用，请重新选择原文件重试；持续失败请联系管理员检查存储";
            finish(sceneId, fileId, false, reason, false);
            throw mismatch ? error(HttpStatus.UNPROCESSABLE_ENTITY, reason)
                    : error(HttpStatus.SERVICE_UNAVAILABLE, reason);
        }
        // 存储成功后，再单独提交 AVAILABLE。
        if (!wasAvailable) finish(sceneId, fileId, true, null, false);
        return required(manager.file(sceneId, fileId)).response();
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
    private void finish(UUID sceneId, UUID fileId, boolean available, String reason, boolean recovery) {
        tx.executeWithoutResult(s -> {
            var before = required(manager.uploadActor(fileId));
            manager.finishUpload(fileId, available, reason);
            var values = new LinkedHashMap<String, Object>();
            values.put("status", available ? "AVAILABLE" : "FAILED");
            values.put("recovery", recovery);
            if (reason != null) values.put("reason", reason);
            if (recovery) values.put("performedBy", "SYSTEM_RECONCILIATION");
            manager.audit(UUID.fromString(before.sceneId()), recovery ? "FILE_RECONCILE"
                            : available ? "FILE_AVAILABLE" : "FILE_FAILED",
                    before.actorId(), before.actorName(), values);
        });
    }

    /** 管理端下载；场景停用仍可读，删除中不可读。 */
    public void adminDownload(UUID sceneId, UUID fileId, HttpServletRequest request,
                              HttpServletResponse response) throws IOException {
        requireScene(sceneId);
        var lock = readLock(concurrency, sceneId);
        try {
            requireNotDeleting(sceneId);
            var file = required(manager.file(sceneId, fileId));
            if (!"AVAILABLE".equals(file.status())) throw error(HttpStatus.CONFLICT, "文件尚未上传完成");
            stream(file, "application/octet-stream", file.relativePath(), request, response);
        } finally {
            lock.unlock();
        }
    }

    /**
     * 匿名终端分发：只有启用、未删除、非删除中、文件清单非空且全部 AVAILABLE 的场景可读。
     * URL 文件名只用于校验和展示扩展名，文件定位靠 UUID。
     */
    public void clientDownload(UUID sceneId, UUID fileId, String fileName, HttpServletRequest request,
                               HttpServletResponse response) throws IOException {
        requireClientVisible(sceneId);
        var lock = readLock(concurrency, sceneId);
        try {
            requireClientVisible(sceneId);
            var file = required(manager.file(sceneId, fileId));
            String path = file.relativePath();
            if (!RelativePath.fileName(path).equals(fileName))
                throw error(HttpStatus.NOT_FOUND, "场景或文件不存在");
            if (!"AVAILABLE".equals(file.status())) throw error(HttpStatus.NOT_FOUND, "场景或文件不存在");
            stream(file, FileContentType.of(path), null, request, response);
        } finally {
            lock.unlock();
        }
    }

    /** 匿名可见性是整体场景条件，任何未就绪文件都使列表、详情和文件读取统一 404。 */
    private void requireClientVisible(UUID sceneId) {
        var scene = manager.summary(sceneId);
        if (scene == null || !scene.enabled() || scene.fileCount() == 0
                || !"READY".equals(scene.uploadStatus()))
            throw error(HttpStatus.NOT_FOUND, "场景不存在或尚未就绪");
    }

    /** 调用方须持场景读锁。核对长度，用登记摘要作 ETag，不重算摘要。 */
    private void stream(SceneRows.File file, String contentType, String attachmentName,
                        HttpServletRequest request, HttpServletResponse response) throws IOException {
        UUID fileId = UUID.fromString(file.fileId());
        long size = file.bytes();
        try {
            if (storage.size(fileId) != size) throw new IOException("Artifact size mismatch");
        } catch (IOException e) {
            throw error(HttpStatus.CONFLICT, "文件已记录但存储缺失或长度不符，请联系管理员检查存储");
        }

        String etag = "\"" + file.sha256() + "\"";
        HttpRange.Slice slice = HttpRange.parse(request, size, etag);
        HttpRange.write(response, slice, etag, contentType,
                attachmentName == null ? null : RelativePath.fileName(attachmentName),
                !"HEAD".equalsIgnoreCase(request.getMethod()),
                (offset, length) -> storage.open(fileId, offset, length));
    }

    /**
     * 启动对账非 AVAILABLE 文件：磁盘存在完整且校验通过的正式文件则补记 AVAILABLE；
     * 仅处于 UPLOADING 的缺失文件标记 FAILED。必须在整场景删除恢复之后执行。
     */
    public void recoverFiles() {
        Set<UUID> leftovers = new HashSet<>();
        try {
            for (var entry : storage.inventory()) leftovers.add(entry.id());
        } catch (IOException e) {
            throw new IllegalStateException("存储目录无法盘点，拒绝启动对账", e);
        }
        UUID cursor = new UUID(0, 0);
        while (true) {
            var rows = manager.recoveryFiles(cursor);
            if (rows.isEmpty()) break;
            for (var row : rows) {
                UUID fileId = UUID.fromString(row.fileId());
                cursor = fileId;
                UUID sceneId = UUID.fromString(row.sceneId());
                String status = row.status();
                try {
                    // .part 不算完整文件；缺少完整字节的在途上传标记为失败。
                    if (leftovers.contains(fileId) && storage.recover(descriptor(row)))
                        finish(sceneId, fileId, true, null, true);
                    else if ("UPLOADING".equals(status))
                        finish(sceneId, fileId, false, "重启对账未找到完整且校验通过的正式文件，请重新上传", true);
                } catch (IOException e) {
                    if (!"FAILED".equals(status))
                        finish(sceneId, fileId, false, "重启对账未找到完整且校验通过的正式文件，请重新上传", true);
                }
            }
        }
    }
}
