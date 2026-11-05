package com.ruoyi.ar.module.version.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import java.sql.Timestamp;
import java.util.LinkedHashMap;
import java.util.Map;

/** Typed persistence results; response maps retain the existing field and JDBC timestamp contract. */
public final class VersionRows {
    private VersionRows() {
    }

    public record Summary(String id, String sceneId, int versionNo, String description, long lockVersion,
                          boolean published, String uploadStatus, long fileCount, long availableCount,
                          long failedCount, long totalBytes, long creatorId, String creatorName,
                          Timestamp createdAt, Timestamp updatedAt) {
        public Map<String, Object> response() {
            var result = new LinkedHashMap<String, Object>();
            result.put("id", id);
            result.put("sceneId", sceneId);
            result.put("versionNo", versionNo);
            result.put("description", description);
            result.put("lockVersion", lockVersion);
            result.put("published", published);
            result.put("uploadStatus", uploadStatus);
            result.put("fileCount", fileCount);
            result.put("availableCount", availableCount);
            result.put("failedCount", failedCount);
            result.put("totalBytes", totalBytes);
            result.put("creatorId", creatorId);
            result.put("creatorName", creatorName);
            result.put("createdAt", createdAt);
            result.put("updatedAt", updatedAt);
            return result;
        }
    }

    @JsonInclude(JsonInclude.Include.ALWAYS)
    public record File(String fileId, @JsonIgnore String versionId, String relativePath, long bytes, String sha256,
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

    public record Scene(long lockVersion, String publishedVersionId) {
    }

    @JsonInclude(JsonInclude.Include.ALWAYS)
    public record Published(String id, int versionNo, String description, Timestamp publishedAt, String publishedByName) {
    }

    public record Version(String sceneId, String requestKey, int versionNo, String description) {
    }

    public record Actor(String sceneId, long actorId, String actorName) {
    }

    public record FileSpec(String path, long bytes, String sha256) {
    }

    public record NewFile(String id, String versionId, String path, long bytes, String sha256, long actor, String actorName) {
    }
}
