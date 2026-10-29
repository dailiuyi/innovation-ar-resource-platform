package com.ruoyi.ar;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
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
    private final ObjectMapper json;

    public ClientSceneService(JdbcTemplate db, ObjectMapper json) { this.db = db; this.json = json; }

    public Map<String,Object> list(String name, int limit, int offset) {
        String filter = " and position(lower(?) in lower(s.name))>0";
        var rows = db.queryForList("select s.id::text as id, s.name, v.id::text as version_id, v.version_no, v.descriptor::text as descriptor,"
            + " (select pf.id::text from ar_version_file pf where pf.version_id=v.id and pf.relative_path=v.descriptor->>'poster') as poster_id"
            + VISIBLE + filter + " order by s.name, s.id limit ? offset ?", name, limit, offset);
        var items = new ArrayList<Map<String,Object>>(rows.size());
        for (var row : rows) {
            var descriptor = SceneResourceDescriptor.parse((String) row.get("descriptor"));
            var item = new LinkedHashMap<String,Object>();
            String sceneId = (String) row.get("id");
            String versionId = (String) row.get("version_id");
            item.put("id", sceneId);
            item.put("name", row.get("name"));
            item.put("versionId", versionId);
            item.put("versionNo", row.get("version_no"));
            item.put("defaultVariant", descriptor.defaultVariant());
            item.put("variants", variants(descriptor));
            String posterId = (String) row.get("poster_id");
            if (posterId != null) item.put("posterUrl", downloadPath(sceneId, versionId, posterId, RelativePath.fileName(descriptor.poster())));
            items.add(item);
        }
        long total = db.queryForObject("select count(*)" + VISIBLE + filter, Long.class, name);
        return Map.of("items", items, "total", total);
    }

    public Map<String,Object> detail(UUID sceneId) {
        var rows = db.queryForList("select s.name, v.id as version_id, v.version_no, v.descriptor::text as descriptor" + VISIBLE + " and s.id=?", sceneId);
        if (rows.isEmpty()) throw notFound();
        var row = rows.get(0);
        UUID versionId = (UUID) row.get("version_id");
        String descriptorText = (String) row.get("descriptor");
        var descriptor = SceneResourceDescriptor.parse(descriptorText);
        var files = new ArrayList<Map<String,Object>>();
        long total = 0;
        var types = new ContentTypes(descriptor);
        for (var file : db.queryForList("select id::text as id, relative_path, expected_bytes, expected_sha256 from ar_version_file where version_id=? order by relative_path, id", versionId)) {
            String path = (String) file.get("relative_path");
            long bytes = ((Number) file.get("expected_bytes")).longValue();
            var item = new LinkedHashMap<String,Object>();
            item.put("fileId", file.get("id"));
            item.put("relativePath", path);
            item.put("bytes", bytes);
            item.put("sha256", file.get("expected_sha256"));
            item.put("contentType", types.of(path));
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
        try { result.put("descriptor", json.readTree(descriptorText)); }
        catch (JsonProcessingException e) { throw new IllegalStateException(e); }
        result.put("files", files);
        result.put("fileCount", files.size());
        result.put("totalBytes", total);
        return result;
    }

    private static ResponseStatusException notFound() { return new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在或尚未发布"); }

    private static List<Map<String,Object>> variants(SceneResourceDescriptor descriptor) {
        var out = new ArrayList<Map<String,Object>>();
        for (var variant : descriptor.variants()) {
            var last = variant.segments().get(variant.segments().size() - 1);
            var item = new LinkedHashMap<String,Object>();
            item.put("id", variant.id());
            item.put("name", variant.name());
            item.put("segmentCount", variant.segments().size());
            item.put("durationSeconds", plain(last.startSeconds().add(last.durationSeconds())));
            out.add(item);
        }
        return out;
    }

    private static BigDecimal plain(BigDecimal value) {
        BigDecimal trimmed = value.stripTrailingZeros();
        return trimmed.scale() < 0 ? trimmed.setScale(0) : trimmed;
    }

    /** The trailing basename keeps the extension visible to players that choose a loader from the URL. */
    static String downloadPath(String sceneId, String versionId, String fileId, String fileName) {
        return "/api/v1/client/scenes/" + sceneId + "/versions/" + versionId + "/files/" + fileId
            + "/content/" + URLEncoder.encode(fileName, StandardCharsets.UTF_8).replace("+", "%20");
    }

    /** By declared role first (models are opaque, settings are JSON), then by extension; never sniffed from content. */
    static final class ContentTypes {
        private final Set<String> models = new HashSet<>();
        private final String settings;

        ContentTypes(SceneResourceDescriptor descriptor) {
            for (var variant : descriptor.variants()) for (var segment : variant.segments()) models.add(segment.path());
            settings = descriptor.settings();
        }

        String of(String path) {
            if (models.contains(path)) return "application/octet-stream";
            if (path.equals(settings)) return "application/json";
            String name = RelativePath.fileName(path).toLowerCase(Locale.ROOT);
            int dot = name.lastIndexOf('.');
            return switch (dot < 0 ? "" : name.substring(dot + 1)) {
                case "jpg", "jpeg" -> "image/jpeg";
                case "png" -> "image/png";
                case "webp" -> "image/webp";
                case "wav" -> "audio/wav";
                case "webm" -> "video/webm";
                default -> "application/octet-stream";
            };
        }
    }
}
