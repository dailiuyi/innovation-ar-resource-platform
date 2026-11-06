package com.ruoyi.ar.module.client.controller;

import com.ruoyi.ar.module.client.service.ClientSceneService;
import com.ruoyi.ar.module.scene.service.SceneFileService;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirements;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
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
 * 客户端匿名只读控制器。
 * <p>
 * 面向终端提供已就绪场景的目录、固定文件清单与直接文件分发。权限契约：SecurityConfig 只放行
 * 本类注册的 GET/HEAD 路由；仅当 {@code ar.storage.enabled=true} 时生效。
 */
@Tag(name = "客户端只读接口", description = "匿名只读：已就绪场景目录、详情与单文件 Range 下载，无需登录")
@SecurityRequirements
@RestController
@RequestMapping("/api/v1/client")
@Validated
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneController {
    private final ClientSceneService scenes;
    private final SceneFileService files;

    public ClientSceneController(ClientSceneService scenes, SceneFileService files) {
        this.scenes = scenes;
        this.files = files;
    }

    @Operation(security = {}, summary = "已就绪场景列表", description = "匿名读取启用、非空且全部文件就绪的场景；name 子串过滤，按名称排序")
    @GetMapping("/scenes")
    public Map<String, Object> list(@Parameter(description = "名称过滤（子串，不区分大小写）", example = "街区")
                                    @RequestParam(defaultValue = "") @Size(max = 200) String name,
                                    @Parameter(description = "每页条数（1~100）", example = "20")
                                    @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                    @Parameter(description = "偏移量", example = "0")
                                    @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return scenes.list(name, limit, offset);
    }

    @Operation(security = {}, summary = "场景文件清单", description = "场景固定文件清单及每个文件的直接下载路径与 MIME")
    @GetMapping("/scenes/{sceneId}")
    public Map<String, Object> detail(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId) {
        return scenes.detail(sceneId);
    }

    @Operation(security = {}, summary = "下载单个文件", description = "支持 GET/HEAD 和 Range 断点续传；路径末尾 fileName 只用于校验和展示扩展名，文件定位靠 UUID")
    @RequestMapping(value = "/scenes/{sceneId}/files/{fileId}/content/{fileName}",
            method = {RequestMethod.GET, RequestMethod.HEAD})
    public void content(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                        @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                        @Parameter(description = "文件名（仅用于校验与扩展名展示）", required = true) @PathVariable String fileName,
                        HttpServletRequest request, HttpServletResponse response) throws IOException {
        files.clientDownload(sceneId, fileId, fileName, request, response);
    }
}
