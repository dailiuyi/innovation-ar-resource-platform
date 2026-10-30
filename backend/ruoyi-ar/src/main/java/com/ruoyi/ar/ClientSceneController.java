package com.ruoyi.ar;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import java.io.IOException;
import java.util.Map;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * 给演示客户端用的匿名只读接口。刻意不在类上加角色限制：SecurityConfig 只放行下面这三个 GET 路由
 * （以及文件内容的 HEAD），其余方法和路径仍然要求登录或被拒绝。
 */
@RestController
@RequestMapping("/api/v1/client")
@Validated
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class ClientSceneController {
    private final ClientSceneService scenes;
    private final SceneVersionService versions;

    public ClientSceneController(ClientSceneService scenes, SceneVersionService versions) {
        this.scenes = scenes;
        this.versions = versions;
    }

    /** 已发布且可下载的场景列表，name 为大小写不敏感的子串过滤，按名称排序。 */
    @GetMapping("/scenes")
    public Map<String,Object> list(@RequestParam(defaultValue="") @Size(max=200) String name,
        @RequestParam(defaultValue="20") @Min(1) @Max(100) int limit,
        @RequestParam(defaultValue="0") @Min(0) int offset) {
        return scenes.list(name, limit, offset);
    }

    /** 场景当前发布版本的文件清单及每个文件的下载路径。 */
    @GetMapping("/scenes/{sceneId}")
    public Map<String,Object> detail(@PathVariable UUID sceneId) { return scenes.detail(sceneId); }

    /**
     * 下载单个文件，支持 GET/HEAD 和 Range。路径末尾的 fileName 只用于校验和让播放器看到扩展名，
     * 文件定位靠前面的 UUID。
     */
    @RequestMapping(value="/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}",
        method={RequestMethod.GET, RequestMethod.HEAD})
    public void content(@PathVariable UUID sceneId, @PathVariable UUID versionId, @PathVariable UUID fileId,
        @PathVariable String fileName, HttpServletRequest request, HttpServletResponse response) throws IOException {
        versions.clientDownload(sceneId, versionId, fileId, fileName, request, response);
    }
}
