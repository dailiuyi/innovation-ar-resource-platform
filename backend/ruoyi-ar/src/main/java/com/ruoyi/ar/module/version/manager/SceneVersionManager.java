package com.ruoyi.ar.module.version.manager;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.ar.module.version.mapper.SceneVersionMapper;
import com.ruoyi.ar.module.version.mapper.VersionFileMapper;
import com.ruoyi.ar.module.version.mapper.VersionDeletionMapper;
import com.ruoyi.ar.module.version.model.VersionRows;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Component;

/** 组合版本持久化操作及审计序列化；事务、业务状态判断和文件 IO 由 Service 负责。 */
@Component
public class SceneVersionManager {
    private final SceneVersionMapper mapper;
    private final VersionFileMapper fileMapper;
    private final VersionDeletionMapper deletionMapper;
    private final ObjectMapper json;

    public SceneVersionManager(SceneVersionMapper mapper, VersionFileMapper fileMapper,
                               VersionDeletionMapper deletionMapper, ObjectMapper json) {
        this.mapper = mapper;
        this.fileMapper = fileMapper;
        this.deletionMapper = deletionMapper;
        this.json = json;
    }

    public boolean lockScene(UUID sceneId) {
        return mapper.lockScene(sceneId.toString()) != null;
    }

    public UUID sceneOf(UUID versionId) {
        return uuid(mapper.sceneOf(versionId.toString()));
    }

    public boolean deleting(UUID versionId) {
        return deletionMapper.deleting(versionId.toString());
    }

    public boolean published(UUID versionId) {
        return mapper.published(versionId.toString());
    }

    public VersionRows.Summary summary(UUID versionId) {
        return mapper.summary(versionId.toString());
    }

    public VersionRows.Scene sceneState(UUID sceneId) {
        return mapper.sceneState(sceneId.toString());
    }

    public VersionRows.Published publishedVersion(UUID sceneId) {
        return mapper.publishedVersion(sceneId.toString());
    }

    public List<VersionRows.Summary> list(UUID sceneId, int limit, int offset) {
        return mapper.list(sceneId.toString(), limit, offset);
    }

    public long count(UUID sceneId) {
        return mapper.count(sceneId.toString());
    }

    public List<VersionRows.File> files(UUID versionId) {
        return fileMapper.files(versionId.toString());
    }

    public VersionRows.File file(UUID versionId, UUID fileId) {
        return fileMapper.file(versionId.toString(), fileId.toString());
    }

    public boolean deletedRequest(UUID sceneId, UUID requestKey) {
        return deletionMapper.deletedRequest(sceneId.toString(), requestKey.toString());
    }

    public UUID existingRequest(UUID sceneId, UUID requestKey) {
        return uuid(mapper.existingRequest(sceneId.toString(), requestKey.toString()));
    }

    public boolean descriptionMatches(UUID versionId, String description) {
        return Boolean.TRUE.equals(mapper.sameDescription(versionId.toString(), description));
    }

    /** 调用方已在事务内锁住场景行，版本号分配与整份文件清单一起写入。 */
    public int create(UUID id, UUID sceneId, UUID requestKey, String description,
                      List<VersionRows.FileSpec> specs, long actor, String actorName) {
        String idText = id.toString();
        String sceneText = sceneId.toString();
        int versionNo = mapper.nextVersionNo(sceneText);
        mapper.insertVersion(idText, sceneText, versionNo, requestKey.toString(), description, actor, actorName);
        var files = new ArrayList<VersionRows.NewFile>(specs.size());
        for (var spec : specs) {
            files.add(new VersionRows.NewFile(UUID.randomUUID().toString(), idText,
                    spec.path(), spec.bytes(), spec.sha256(), actor, actorName));
        }
        // 每条多行 INSERT 的参数数量不随配置上限无限增长。
        for (int start = 0; start < files.size(); start += 1000) {
            fileMapper.insertFiles(files.subList(start, Math.min(start + 1000, files.size())));
        }
        return versionNo;
    }

    public boolean edit(UUID id, String description, long expectedVersion) {
        return mapper.edit(id.toString(), description, expectedVersion) == 1;
    }

    public boolean publish(UUID sceneId, UUID versionId, long actor, String actorName, long expectedVersion) {
        return mapper.publish(sceneId.toString(), versionId.toString(), actor, actorName, expectedVersion) == 1;
    }

    public boolean versionExists(UUID versionId) {
        return mapper.versionExists(versionId.toString());
    }

    public boolean deletionCompleted(UUID versionId) {
        return deletionMapper.deletionCompleted(versionId.toString());
    }

    public VersionRows.Version version(UUID versionId) {
        return mapper.version(versionId.toString());
    }

    public long fileCount(UUID versionId) {
        return fileMapper.fileCount(versionId.toString());
    }

    /** 返回是否复用已有删除回执；调用方继续在同一事务记录业务审计。 */
    public boolean requestDeletion(UUID versionId, VersionRows.Version version, long actor, String actorName) {
        String id = versionId.toString();
        boolean retry = deletionMapper.deletionExists(id);
        if (retry) {
            deletionMapper.retryDeletion(id, actor, actorName);
        } else {
            deletionMapper.requestDeletion(id, version.sceneId(), version.requestKey(), actor, actorName);
        }
        return retry;
    }

    public VersionRows.Actor deletionActor(UUID versionId) {
        return deletionMapper.deletionActor(versionId.toString());
    }

    public List<String> fileIds(UUID versionId) {
        return fileMapper.fileIds(versionId.toString());
    }

    public void failDeletion(UUID versionId, String reason) {
        deletionMapper.failDeletion(versionId.toString(), reason);
    }

    /** 仅在物理文件已清理后调用；三个写操作使用调用方的同一事务。 */
    public void completeDeletion(UUID versionId) {
        String id = versionId.toString();
        fileMapper.deleteFiles(id);
        mapper.deleteVersion(id);
        deletionMapper.completeDeletion(id);
    }

    public List<String> pendingDeletions() {
        return deletionMapper.pendingDeletions();
    }

    public void startUpload(UUID fileId, long actor, String actorName) {
        fileMapper.startUpload(fileId.toString(), actor, actorName);
    }

    public VersionRows.Actor uploadActor(UUID fileId) {
        return fileMapper.uploadActor(fileId.toString());
    }

    public void finishUpload(UUID fileId, boolean available, String reason) {
        fileMapper.finishUpload(fileId.toString(), available ? "AVAILABLE" : "FAILED", available, reason);
    }

    public UUID clientPublishedVersion(UUID sceneId, UUID versionId) {
        return uuid(mapper.clientPublishedVersion(sceneId.toString(), versionId.toString()));
    }

    public List<VersionRows.File> recoveryFiles(UUID cursor) {
        return fileMapper.recoveryFiles(cursor.toString());
    }

    public void audit(UUID sceneId, UUID versionId, UUID fileId, String action, long actor, String actorName,
                      Map<String, Object> values) {
        var detail = new LinkedHashMap<String, Object>(values);
        detail.put("versionId", versionId.toString());
        if (fileId != null) detail.put("fileId", fileId.toString());
        try {
            mapper.audit(sceneId.toString(), actor, actorName, action, json.writeValueAsString(detail));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private static UUID uuid(String value) {
        return value == null ? null : UUID.fromString(value);
    }
}
