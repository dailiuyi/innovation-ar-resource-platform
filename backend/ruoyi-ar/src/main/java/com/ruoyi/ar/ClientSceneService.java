package com.ruoyi.ar;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Anonymous, read-only metadata of the current published scene versions. It reads the database only:
 * no model file is opened and no digest is computed. File bytes are served by
 * {@link SceneVersionService#clientDownload}, which owns the version locks.
 */
@Service
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class ClientSceneService {
    /** Enabled, not deleted, with a published version whose files are all stored and not being deleted. */
    private static final String VISIBLE = " from ar_scene s join ar_scene_version v on v.id=s.published_version_id"
        + " where s.enabled and s.deleted_at is null"
        + " and not exists(select 1 from ar_version_file f where f.version_id=v.id and f.status<>'AVAILABLE')"
        + " and not exists(select 1 from ar_version_deletion d where d.version_id=v.id and d.completed_at is null)";

    private final JdbcTemplate db;

    public ClientSceneService(JdbcTemplate db) { this.db = db; }

    public Map<String,Object> list(String name, int limit, int offset) {
        String filter = " and position(lower(?) in lower(s.name))>0";
        var items = db.queryForList("select s.id::text as \"id\", s.name, v.id::text as \"versionId\", v.version_no as \"versionNo\""
            + VISIBLE + filter + " order by s.name, s.id limit ? offset ?", name, limit, offset);
        long total = db.queryForObject("select count(*)" + VISIBLE + filter, Long.class, name);
        return Map.of("items", items, "total", total);
    }

    public Map<String,Object> detail(UUID sceneId) {
        var rows = db.queryForList("select s.name, v.id as version_id, v.version_no" + VISIBLE + " and s.id=?", sceneId);
        if (rows.isEmpty()) throw notFound();
        var row = rows.get(0);
        UUID versionId = (UUID) row.get("version_id");
        var files = new ArrayList<Map<String,Object>>();
        long total = 0;
        for (var file : db.queryForList("select id::text as id, relative_path, expected_bytes, expected_sha256 from ar_version_file where version_id=? order by relative_path, id", versionId)) {
            String path = (String) file.get("relative_path");
            long bytes = ((Number) file.get("expected_bytes")).longValue();
            var item = new LinkedHashMap<String,Object>();
            item.put("fileId", file.get("id"));
            item.put("relativePath", path);
            item.put("bytes", bytes);
            item.put("sha256", file.get("expected_sha256"));
            item.put("contentType", contentType(path));
            item.put("downloadPath", downloadPath(sceneId.toString(), versionId.toString(), (String) file.get("id"), RelativePath.fileName(path)));
            files.add(item);
            total += bytes;
        }
        if (files.isEmpty()) throw notFound();
        var result = new LinkedHashMap<String,Object>();
        result.put("sceneId", sceneId.toString());
        result.put("name", row.get("name"));
        result.put("versionId", versionId.toString());
        result.put("versionNo", row.get("version_no"));
        result.put("files", files);
        result.put("fileCount", files.size());
        result.put("totalBytes", total);
        return result;
    }

    private static ResponseStatusException notFound() { return new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在或尚未发布"); }

    /** The trailing basename keeps the extension visible to players that choose a loader from the URL. */
    static String downloadPath(String sceneId, String versionId, String fileId, String fileName) {
        return "/api/v1/client/scenes/" + sceneId + "/versions/" + versionId + "/files/" + fileId
            + "/content/" + URLEncoder.encode(fileName, StandardCharsets.UTF_8).replace("+", "%20");
    }

    /** By extension only; never sniffed from content. Models and unknown types are opaque bytes. */
    static String contentType(String path) {
        String name = RelativePath.fileName(path).toLowerCase(Locale.ROOT);
        int dot = name.lastIndexOf('.');
        return switch (dot < 0 ? "" : name.substring(dot + 1)) {
            case "json" -> "application/json";
            case "jpg", "jpeg" -> "image/jpeg";
            case "png" -> "image/png";
            case "webp" -> "image/webp";
            case "wav" -> "audio/wav";
            case "webm" -> "video/webm";
            default -> "application/octet-stream";
        };
    }
}
