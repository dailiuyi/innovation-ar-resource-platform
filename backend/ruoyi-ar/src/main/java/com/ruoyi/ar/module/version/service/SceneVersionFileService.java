package com.ruoyi.ar.module.version.service;

import com.ruoyi.ar.module.version.manager.SceneVersionManager;
import com.ruoyi.ar.module.version.manager.VersionConcurrency;
import com.ruoyi.ar.module.version.model.VersionRows;
import com.ruoyi.ar.support.FileContentType;
import com.ruoyi.ar.storage.ArtifactStorage;
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

import static com.ruoyi.ar.module.version.service.VersionChecks.error;
import static com.ruoyi.ar.module.version.service.VersionChecks.readLock;
import static com.ruoyi.ar.module.version.service.VersionChecks.required;

/** 文件上传、下载及文件状态恢复；数据库事务与文件 IO 分开提交。 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneVersionFileService {

    private final SceneVersionManager manager;
    private final TransactionTemplate tx;
    private final ArtifactStorage storage;
    private final VersionConcurrency concurrency;

    public SceneVersionFileService(SceneVersionManager manager, PlatformTransactionManager transactions,
                                   ArtifactStorage storage, VersionConcurrency concurrency) {
        this.manager = manager;
        this.tx = new TransactionTemplate(transactions);
        this.storage = storage;
        this.concurrency = concurrency;
    }

    private UUID sceneOf(UUID versionId) {
        return required(manager.sceneOf(versionId));
    }

    private void requireNotDeleting(UUID versionId) {
        if (manager.deleting(versionId)) throw error(HttpStatus.CONFLICT, "版本正在删除，暂不能操作");
    }

    /** 同时匹配版本和文件，防止跨版本读取。 */
    private VersionRows.File file(UUID versionId, UUID fileId) {
        return required(manager.file(versionId, fileId));
    }

    public Map<String, Object> fileStatus(UUID versionId, UUID fileId) {
        sceneOf(versionId);
        return file(versionId, fileId).response();
    }

    private ArtifactStorage.Descriptor descriptor(VersionRows.File row) {
        return new ArtifactStorage.Descriptor(UUID.fromString(row.fileId()), row.bytes(), row.sha256());
    }

    /** 持版本读锁并登记在途文件；发布/删除中或同文件重复上传返回 409。 */
    public Map<String, Object> upload(UUID versionId, UUID fileId, InputStream input) {
        sceneOf(versionId);
        var lock = readLock(concurrency, versionId);
        try {
            if (!concurrency.beginUpload(fileId)) throw error(HttpStatus.CONFLICT, "文件正在处理，请稍后刷新或重试");
            try {
                return uploadLocked(versionId, fileId, input);
            } finally {
                concurrency.endUpload(fileId);
            }
        } finally {
            lock.unlock();
        }
    }

    /**
     * 分三步：事务标记 UPLOADING → 事务外写文件 → finish 提交结果。
     * 大小/摘要或上限不符返回 422，其他 IO 错误返回 503；均可重传原文件。
     */
    private Map<String, Object> uploadLocked(UUID versionId, UUID fileId, InputStream input) {
        var row = tx.execute(s -> {
            UUID sceneId = sceneOf(versionId);
            requireNotDeleting(versionId);
            var current = file(versionId, fileId);
            if (!"AVAILABLE".equals(current.status())) {
                long actor = SecurityUtils.getUserId();
                String actorName = SecurityUtils.getUsername();
                manager.startUpload(fileId, actor, actorName);
                manager.audit(sceneId, versionId, fileId, "FILE_UPLOAD_START", actor, actorName, Map.of());
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
            boolean mismatch = message.contains("size mismatch") || message.contains("SHA256 mismatch") || message.contains("exceeds configured storage limit");
            String reason = message.contains("size mismatch") ? "实际文件大小与登记值不一致，请核对原文件"
                    : message.contains("SHA256 mismatch") ? "实际 SHA256 与登记摘要不一致，请核对原文件"
                    : message.contains("exceeds configured storage limit") ? "文件超过当前存储大小上限"
                    : "上传中断或存储不可用，请重新选择原文件重试；持续失败请联系管理员检查存储";
            finish(versionId, fileId, false, reason, false);
            throw mismatch ? error(HttpStatus.UNPROCESSABLE_ENTITY, reason) : error(HttpStatus.SERVICE_UNAVAILABLE, reason);
        }
        // 存储成功后，再单独提交 AVAILABLE。
        if (!wasAvailable) finish(versionId, fileId, true, null, false);
        return file(versionId, fileId).response();
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
    private void finish(UUID versionId, UUID fileId, boolean available, String reason, boolean recovery) {
        tx.executeWithoutResult(s -> {
            var before = required(manager.uploadActor(fileId));
            manager.finishUpload(fileId, available, reason);
            var values = new LinkedHashMap<String, Object>();
            values.put("status", available ? "AVAILABLE" : "FAILED");
            values.put("recovery", recovery);
            if (reason != null) values.put("reason", reason);
            if (recovery) values.put("performedBy", "SYSTEM_RECONCILIATION");
            manager.audit(UUID.fromString(before.sceneId()), versionId, fileId,
                    recovery ? "FILE_RECONCILE" : available ? "FILE_AVAILABLE" : "FILE_FAILED",
                    before.actorId(), before.actorName(), values);
        });
    }

    /** 持读锁，拒绝删除中或未就绪的文件；以附件形式返回。 */
    public void adminDownload(UUID versionId, UUID fileId, HttpServletRequest request, HttpServletResponse response) throws IOException {
        sceneOf(versionId);
        var lock = readLock(concurrency, versionId);
        try {
            requireNotDeleting(versionId);
            var file = file(versionId, fileId);
            if (!"AVAILABLE".equals(file.status())) throw error(HttpStatus.CONFLICT, "文件尚未上传完成");
            stream(file, "application/octet-stream", file.relativePath(), request, response);
        } finally {
            lock.unlock();
        }
    }

    /**
     * 锁前后检查场景发布指针；旧版本 URL 返回 409，不自动切换文件。
     * 读锁持有至传输结束，期间不再检查发布指针；URL 文件名只校验，不用于落盘。
     */
    public void clientDownload(UUID sceneId, UUID versionId, UUID fileId, String fileName, HttpServletRequest request, HttpServletResponse response) throws IOException {
        clientVersion(sceneId, versionId);
        var lock = readLock(concurrency, versionId);
        try {
            clientVersion(sceneId, versionId);
            var file = file(versionId, fileId);
            String path = file.relativePath();
            if (!RelativePath.fileName(path).equals(fileName))
                throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
            requireNotDeleting(versionId);
            if (!"AVAILABLE".equals(file.status())) throw error(HttpStatus.CONFLICT, "文件尚未就绪");
            String contentType = FileContentType.of(path);
            stream(file, contentType, null, request, response);
        } finally {
            lock.unlock();
        }
    }

    /** 场景不可见或版本不属于场景返回 404，已被替换的发布版本返回 409。 */
    private void clientVersion(UUID sceneId, UUID versionId) {
        UUID publishedId = required(manager.clientPublishedVersion(sceneId, versionId));
        if (!versionId.equals(publishedId))
            throw error(HttpStatus.CONFLICT, "该版本已不是当前发布版本，请重新获取场景详情");
    }

    /** 调用方须持版本读锁。核对长度，用登记摘要作 ETag，不重算摘要。 */
    private void stream(VersionRows.File file, String contentType, String attachmentName, HttpServletRequest request, HttpServletResponse response) throws IOException {
        UUID fileId = UUID.fromString(file.fileId());
        long size = file.bytes();
        try {
            if (storage.size(fileId) != size) throw new IOException("Artifact size mismatch");
        } catch (IOException e) {
            throw error(HttpStatus.CONFLICT, "文件已记录但存储缺失或长度不符，请联系管理员检查存储");
        }

        String etag = "\"" + file.sha256() + "\"";
        HttpRange.Slice slice = HttpRange.parse(request, size, etag);
        HttpRange.write(response, slice, etag, contentType, attachmentName == null ? null : RelativePath.fileName(attachmentName),
                !"HEAD".equalsIgnoreCase(request.getMethod()),
                (offset, length) -> storage.open(fileId, offset, length));
    }

    /**
     * 恢复 PENDING/UPLOADING/FAILED 文件，完整遗留字节校验通过才补记 AVAILABLE。
     * 不扫描 AVAILABLE 正文；存储无法盘点时拒绝启动。须在删除恢复之后调用。
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
                UUID versionId = UUID.fromString(row.versionId());
                String status = row.status();
                try {
                    // .part 不算完整文件；缺少完整字节的在途上传标记为失败。
                    if (leftovers.contains(fileId) && storage.recover(descriptor(row)))
                        finish(versionId, fileId, true, null, true);
                    else if ("UPLOADING".equals(status))
                        finish(versionId, fileId, false, "重启对账未找到完整且校验通过的正式文件，请重新上传", true);
                } catch (IOException e) {
                    if (!"FAILED".equals(status))
                        finish(versionId, fileId, false, "重启对账未找到完整且校验通过的正式文件，请重新上传", true);
                }
            }
        }
    }
}
