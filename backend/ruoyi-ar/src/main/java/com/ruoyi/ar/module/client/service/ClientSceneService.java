package com.ruoyi.ar.module.client.service;

import com.ruoyi.ar.module.client.manager.ClientSceneManager;
import com.ruoyi.ar.support.FileContentType;
import com.ruoyi.ar.support.RelativePath;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/** 查询当前发布版本的元数据，不读文件正文。下载时由版本文件 Service 重新校验可见性。 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneService {

    private final ClientSceneManager manager;

    public ClientSceneService(ClientSceneManager manager) {
        this.manager = manager;
    }

    /** 列表与总数共用可见条件；名称为空时不过滤。 */
    public Map<String, Object> list(String name, int limit, int offset) {
        var catalog = manager.list(name, limit, offset);
        return Map.of("items", catalog.items(), "total", catalog.total());
    }

    /** 返回发布版本的文件清单和下载地址；场景不可见或无文件时返回 404。 */
    public Map<String, Object> detail(UUID sceneId) {
        String sceneIdText = sceneId.toString();
        var detail = manager.detail(sceneIdText);
        if (detail == null) throw notFound();
        var scene = detail.scene();
        String versionId = scene.versionId();
        var files = new ArrayList<Map<String, Object>>(detail.files().size());
        long total = 0;
        // 使用登记的大小和摘要，不读取正文。
        for (var file : detail.files()) {
            String path = file.relativePath();
            long bytes = file.expectedBytes();
            var item = new LinkedHashMap<String, Object>();
            item.put("fileId", file.id());
            item.put("relativePath", path);
            item.put("bytes", bytes);
            item.put("sha256", file.expectedSha256());
            item.put("contentType", FileContentType.of(path));
            item.put("downloadPath", downloadPath(sceneIdText, versionId, file.id(), RelativePath.fileName(path)));
            files.add(item);
            total += bytes;
        }
        if (files.isEmpty()) throw notFound();
        var result = new LinkedHashMap<String, Object>();
        result.put("sceneId", sceneIdText);
        result.put("name", scene.name());
        result.put("versionId", versionId);
        result.put("versionNo", scene.versionNo());
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

}
