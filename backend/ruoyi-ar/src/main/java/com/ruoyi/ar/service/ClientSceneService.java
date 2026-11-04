package com.ruoyi.ar.service;

import com.ruoyi.ar.support.RelativePath;

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

/** 查询当前发布版本的元数据，不读文件正文。下载时由 SceneVersionService 重新校验可见性。 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneService {
    /** 只展示启用、未删除、文件全部就绪且无删除意图的当前发布版本。 */
    private static final String VISIBLE = " from ar_scene s join ar_scene_version v on v.id=s.published_version_id"
            + " where s.enabled and s.deleted_at is null"
            + " and not exists(select 1 from ar_version_file f where f.version_id=v.id and f.status<>'AVAILABLE')"
            + " and not exists(select 1 from ar_version_deletion d where d.version_id=v.id and d.completed_at is null)";

    private final JdbcTemplate db;

    public ClientSceneService(JdbcTemplate db) {
        this.db = db;
    }

    /** 列表与总数共用可见条件；名称为空时不过滤。 */
    public Map<String, Object> list(String name, int limit, int offset) {
        String filter = " and position(lower(?) in lower(s.name))>0";
        var items = db.queryForList("select s.id::text as \"id\", s.name, v.id::text as \"versionId\", v.version_no as \"versionNo\""
                + VISIBLE + filter + " order by s.name, s.id limit ? offset ?", name, limit, offset);
        long total = db.queryForObject("select count(*)" + VISIBLE + filter, Long.class, name);
        return Map.of("items", items, "total", total);
    }

    /** 返回发布版本的文件清单和下载地址；场景不可见或无文件时返回 404。 */
    public Map<String, Object> detail(UUID sceneId) {
        var rows = db.queryForList("select s.name, v.id as version_id, v.version_no" + VISIBLE + " and s.id=?", sceneId);
        if (rows.isEmpty()) throw notFound();
        var row = rows.get(0);
        UUID versionId = (UUID) row.get("version_id");
        var files = new ArrayList<Map<String, Object>>();
        long total = 0;
        // 使用登记的大小和摘要，不读取正文。
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

    /** URL 保留文件扩展名，供客户端选择加载器；文件名编码时将空格写作 %20。 */
    static String downloadPath(String sceneId, String versionId, String fileId, String fileName) {
        return "/api/v1/client/scenes/" + sceneId + "/versions/" + versionId + "/files/" + fileId
                + "/content/" + URLEncoder.encode(fileName, StandardCharsets.UTF_8).replace("+", "%20");
    }

    /** 仅按扩展名选 Content-Type；未知类型返回 application/octet-stream。 */
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
