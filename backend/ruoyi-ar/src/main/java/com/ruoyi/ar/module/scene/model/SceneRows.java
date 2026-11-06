package com.ruoyi.ar.module.scene.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import java.sql.Timestamp;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 场景与固定文件清单的强类型持久化行记录定义集合。
 * <p>
 * 字段名与对外 JSON 契约一致；上传状态由删除意图、文件状态和聚合计数共同推导。
 */
public final class SceneRows {
    private SceneRows() {
    }

    /** 场景概要；uploadStatus 取值为 PENDING、UPLOADING、FAILED、READY、DELETING、DELETE_FAILED。 */
    public record Summary(String id, String name, String description, boolean enabled, long lockVersion,
                          String uploadStatus, long fileCount, long availableCount, long failedCount,
                          long totalBytes, Timestamp createdAt, Timestamp updatedAt) {
    }

    @JsonInclude(JsonInclude.Include.ALWAYS)
    public record File(String fileId, @JsonIgnore String sceneId, String relativePath, long bytes, String sha256,
                       String status, String failureReason, int attempts) {
        public Map<String, Object> response() {
            var result = new LinkedHashMap<String, Object>();
            result.put("fileId", fileId);
            result.put("relativePath", relativePath);
            result.put("bytes", bytes);
            result.put("sha256", sha256);
            result.put("status", status);
            result.put("failureReason", failureReason);
            result.put("attempts", attempts);
            return result;
        }
    }

    /** 创建幂等比较所需的场景主记录。 */
    public record Scene(long lockVersion, String name, String description, boolean enabled, String requestKey) {
    }

    public record Actor(String sceneId, long actorId, String actorName) {
    }

    public record FileSpec(String path, long bytes, String sha256) {
    }

    public record NewFile(String id, String sceneId, String path, long bytes, String sha256,
                          long actor, String actorName) {
    }
}
