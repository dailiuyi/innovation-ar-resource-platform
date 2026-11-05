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
 * 客户端只读业务服务。
 * <p>
 * 查询当前已发布版本的元数据并组装响应，不直接读取存储中的文件二进制正文。
 * 实际下载请求将流转至版本文件服务（{@code SceneVersionFileService}）进行严格的场景可见性二次核验。
 */
@Service
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneService {

    private final ClientSceneManager manager;

    public ClientSceneService(ClientSceneManager manager) {
        this.manager = manager;
    }

    /**
     * 查询符合客户端可见性条件的场景目录列表与匹配总数。
     *
     * @param name 场景名称过滤字串（模糊匹配），为空时不进行过滤
     * @param limit 本次查询分页条数上限
     * @param offset 分页偏移量
     * @return 包含场景概要列表 {@code items} 与总数 {@code total} 的 Map
     */
    public Map<String, Object> list(String name, int limit, int offset) {
        var catalog = manager.list(name, limit, offset);
        return Map.of("items", catalog.items(), "total", catalog.total());
    }

    /**
     * 获取指定场景当前发布版本的文件清单与下载详情。
     * <p>
     * 仅当场景存在、未删除、已启用且包含可用的当前发布版本及有效文件时才返回结果；
     * 否则统一抛出 404 状态异常，避免向外界泄露场景的未发布草稿细节。
     *
     * @param sceneId 场景唯一标识 UUID
     * @return 包含文件清单、版本号和统计信息的完整响应 Map
     * @throws ResponseStatusException 若场景不存在、不可见或无有效就绪文件，则抛出 404 异常
     */
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
