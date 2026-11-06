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

/**
 * 匿名终端资源分发服务。
 * <p>
 * 只返回启用、未删除、非空且全部文件就绪的场景；只组装登记的大小与摘要，不读取文件正文。
 * 下载由 {@link com.ruoyi.ar.module.scene.service.SceneFileService} 再次核验可见性并输出 Range。
 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneService {

    private final ClientSceneManager manager;

    public ClientSceneService(ClientSceneManager manager) {
        this.manager = manager;
    }

    public Map<String, Object> list(String name, int limit, int offset) {
        var catalog = manager.list(name, limit, offset);
        return Map.of("items", catalog.items(), "total", catalog.total());
    }

    /** 场景不可见、空清单或任一文件未就绪时统一 404，避免泄露未完成上传。 */
    public Map<String, Object> detail(UUID sceneId) {
        String sceneIdText = sceneId.toString();
        var detail = manager.detail(sceneIdText);
        if (detail == null) throw notFound();
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
            item.put("downloadPath", downloadPath(sceneIdText, file.id(), RelativePath.fileName(path)));
            files.add(item);
            total += bytes;
        }
        if (files.isEmpty()) throw notFound();
        var result = new LinkedHashMap<String, Object>();
        result.put("sceneId", sceneIdText);
        result.put("name", detail.scene().name());
        result.put("files", files);
        result.put("fileCount", files.size());
        result.put("totalBytes", total);
        return result;
    }

    private static ResponseStatusException notFound() {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在或尚未就绪");
    }

    /** URL 保留文件扩展名，供客户端选择加载器；文件名编码时将空格写作 %20。 */
    static String downloadPath(String sceneId, String fileId, String fileName) {
        return "/api/v1/client/scenes/" + sceneId + "/files/" + fileId
                + "/content/" + URLEncoder.encode(fileName, StandardCharsets.UTF_8).replace("+", "%20");
    }
}
