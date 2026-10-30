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
 * 匿名只读的“当前已发布场景版本”元数据。只查数据库，不打开任何模型文件，也不计算摘要；
 * 文件字节由 {@link SceneVersionService#clientDownload} 提供，版本锁归它管。
 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneService {
    /**
     * 客户端可见条件：场景已启用且未删除，有已发布版本，该版本所有文件均已就绪，且没有未完成的删除。
     */
    private static final String VISIBLE = " from ar_scene s join ar_scene_version v on v.id=s.published_version_id"
            + " where s.enabled and s.deleted_at is null"
            + " and not exists(select 1 from ar_version_file f where f.version_id=v.id and f.status<>'AVAILABLE')"
            + " and not exists(select 1 from ar_version_deletion d where d.version_id=v.id and d.completed_at is null)";

    private final JdbcTemplate db;

    public ClientSceneService(JdbcTemplate db) {
        this.db = db;
    }

    /**
     * 分页列表。items 与 total 共用同一组可见条件；name 为空串时 position 恒为 1，等于不过滤。
     */
    public Map<String, Object> list(String name, int limit, int offset) {
        String filter = " and position(lower(?) in lower(s.name))>0";
        var items = db.queryForList("select s.id::text as \"id\", s.name, v.id::text as \"versionId\", v.version_no as \"versionNo\""
                + VISIBLE + filter + " order by s.name, s.id limit ? offset ?", name, limit, offset);
        long total = db.queryForObject("select count(*)" + VISIBLE + filter, Long.class, name);
        return Map.of("items", items, "total", total);
    }

    /**
     * 场景详情：返回当前发布版本的全部文件（路径、大小、SHA256、类型、下载地址）及合计字节数。
     * 场景不可见，或版本没有任何文件，都按“不存在或尚未发布”处理。
     */
    public Map<String, Object> detail(UUID sceneId) {
        var rows = db.queryForList("select s.name, v.id as version_id, v.version_no" + VISIBLE + " and s.id=?", sceneId);
        if (rows.isEmpty()) throw notFound();
        var row = rows.get(0);
        UUID versionId = (UUID) row.get("version_id");
        var files = new ArrayList<Map<String, Object>>();
        long total = 0;
        // 文件按相对路径排序；大小和摘要取登记值（创建版本时由管理端提交），这里不读存储。
        for (var file : db.queryForList("select id::text as id, relative_path, expected_bytes, expected_sha256 from ar_version_file where version_id=? order by relative_path, id", versionId)) {
            String path = (String) file.get("relative_path");
            long bytes = ((Number) file.get("expected_bytes")).longValue();
            var item = new LinkedHashMap<String, Object>();
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
        var result = new LinkedHashMap<String, Object>();
        result.put("sceneId", sceneId.toString());
        result.put("name", row.get("name"));
        result.put("versionId", versionId.toString());
        result.put("versionNo", row.get("version_no"));
        result.put("files", files);
        result.put("fileCount", files.size());
        result.put("totalBytes", total);
        return result;
    }

    private static ResponseStatusException notFound() {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在或尚未发布");
    }

    /**
     * 下载路径以文件名结尾，让按 URL 选择加载器的播放器能看到扩展名；文件名做 URL 编码，空格用 %20。
     */
    static String downloadPath(String sceneId, String versionId, String fileId, String fileName) {
        return "/api/v1/client/scenes/" + sceneId + "/versions/" + versionId + "/files/" + fileId
                + "/content/" + URLEncoder.encode(fileName, StandardCharsets.UTF_8).replace("+", "%20");
    }

    /**
     * 只按扩展名判断类型，不嗅探内容。模型等未知类型一律按不透明字节流返回。
     */
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
