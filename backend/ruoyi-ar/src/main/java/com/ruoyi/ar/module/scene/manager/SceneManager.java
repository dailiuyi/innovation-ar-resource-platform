package com.ruoyi.ar.module.scene.manager;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.ar.module.scene.mapper.SceneDeletionMapper;
import com.ruoyi.ar.module.scene.mapper.SceneFileMapper;
import com.ruoyi.ar.module.scene.mapper.SceneMapper;
import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.model.SceneRows;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Component;

/**
 * 场景域持久化聚合管理者。
 * <p>
 * 组合场景、固定文件清单和删除回执三个 Mapper，并负责审计详情 JSON 序列化。
 * 事务边界、业务状态判断和物理文件 IO 由 Service 层负责。
 */
@Component
public class SceneManager {
    private final SceneMapper mapper;
    private final SceneFileMapper fileMapper;
    private final SceneDeletionMapper deletionMapper;
    private final ObjectMapper json;

    public SceneManager(SceneMapper mapper, SceneFileMapper fileMapper,
                        SceneDeletionMapper deletionMapper, ObjectMapper json) {
        this.mapper = mapper;
        this.fileMapper = fileMapper;
        this.deletionMapper = deletionMapper;
        this.json = json;
    }

    public Page<SceneRows.Summary> list(String name, int limit, int offset) {
        return new Page<>(mapper.list(name, limit, offset), mapper.count(name));
    }

    public Page<AuditVO> audits(int limit, int offset) {
        return new Page<>(mapper.audits(limit, offset), mapper.auditCount());
    }

    public SceneRows.Summary summary(UUID sceneId) {
        return mapper.summary(sceneId.toString());
    }

    public SceneRows.Summary summaryByRequestKey(UUID requestKey) {
        return mapper.summaryByRequestKey(requestKey.toString());
    }

    public SceneRows.Scene scene(UUID sceneId) {
        return mapper.scene(sceneId.toString());
    }

    public boolean sceneExists(UUID sceneId) {
        return mapper.sceneExists(sceneId.toString());
    }

    /** 锁住未删除的场景行；返回 false 表示场景不存在或已删除。 */
    public boolean lockScene(UUID sceneId) {
        return mapper.lockScene(sceneId.toString()) != null;
    }

    /** 尝试插入场景；创建键冲突时返回 false 且不写入文件行。 */
    public boolean create(UUID id, UUID requestKey, String name, String description,
                          List<SceneRows.FileSpec> specs, long actor, String actorName) {
        if (mapper.insertScene(id.toString(), name, description, requestKey.toString()) == 0) return false;
        var files = new ArrayList<SceneRows.NewFile>(specs.size());
        for (var spec : specs) {
            files.add(new SceneRows.NewFile(UUID.randomUUID().toString(), id.toString(),
                    spec.path(), spec.bytes(), spec.sha256(), actor, actorName));
        }
        // 每条多行 INSERT 的参数数量不随配置上限无限增长。
        for (int start = 0; start < files.size(); start += 1000) {
            mapper.insertFiles(files.subList(start, Math.min(start + 1000, files.size())));
        }
        return true;
    }

    public List<SceneRows.File> files(UUID sceneId) {
        return fileMapper.files(sceneId.toString());
    }

    public SceneRows.File file(UUID sceneId, UUID fileId) {
        return fileMapper.file(sceneId.toString(), fileId.toString());
    }

    public boolean edit(UUID id, String name, String description, long expectedVersion) {
        return mapper.edit(id.toString(), name, description, expectedVersion) == 1;
    }

    public boolean enabled(UUID id, boolean enabled, long expectedVersion) {
        return mapper.enabled(id.toString(), enabled, expectedVersion) == 1;
    }

    public boolean deleting(UUID sceneId) {
        return deletionMapper.deleting(sceneId.toString());
    }

    public boolean deletionCompleted(UUID sceneId) {
        return deletionMapper.deletionCompleted(sceneId.toString());
    }

    public boolean deletionExists(UUID sceneId) {
        return deletionMapper.deletionExists(sceneId.toString());
    }

    /** 创建键是否已被删除回执或软删除场景占用。 */
    public boolean requestKeyBlocked(UUID requestKey) {
        return deletionMapper.deletionRequestKeyExists(requestKey.toString())
                || deletionMapper.deletedSceneRequestKeyExists(requestKey.toString());
    }

    public void requestDeletion(UUID sceneId, String requestKey, long actor, String actorName) {
        deletionMapper.requestDeletion(sceneId.toString(), requestKey, actor, actorName);
    }

    public void retryDeletion(UUID sceneId, long actor, String actorName) {
        deletionMapper.retryDeletion(sceneId.toString(), actor, actorName);
    }

    public SceneRows.Actor deletionActor(UUID sceneId) {
        return deletionMapper.deletionActor(sceneId.toString());
    }

    public void failDeletion(UUID sceneId, String reason) {
        deletionMapper.failDeletion(sceneId.toString(), reason);
    }

    /** 仅在物理文件清理完毕后调用；文件行、场景标记和回执使用调用方的同一事务。 */
    public void completeDeletion(UUID sceneId) {
        fileMapper.deleteFiles(sceneId.toString());
        mapper.markDeleted(sceneId.toString());
        deletionMapper.completeDeletion(sceneId.toString());
    }

    public List<String> pendingDeletions() {
        return deletionMapper.pendingDeletions();
    }

    public List<String> fileIds(UUID sceneId) {
        return fileMapper.fileIds(sceneId.toString());
    }

    public void startUpload(UUID fileId, long actor, String actorName) {
        fileMapper.startUpload(fileId.toString(), actor, actorName);
    }

    public SceneRows.Actor uploadActor(UUID fileId) {
        return fileMapper.uploadActor(fileId.toString());
    }

    public void finishUpload(UUID fileId, boolean available, String reason) {
        fileMapper.finishUpload(fileId.toString(), available ? "AVAILABLE" : "FAILED", available, reason);
    }

    public List<SceneRows.File> recoveryFiles(UUID cursor) {
        return fileMapper.recoveryFiles(cursor.toString());
    }

    public void audit(UUID sceneId, String action, long actor, String actorName, Map<String, Object> values) {
        try {
            mapper.audit(sceneId.toString(), actor, actorName, action, json.writeValueAsString(values));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
