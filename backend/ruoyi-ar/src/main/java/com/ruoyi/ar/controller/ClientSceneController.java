package com.ruoyi.ar.controller;

import com.ruoyi.ar.service.ClientSceneService;
import com.ruoyi.ar.service.SceneVersionService;

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

/** 匿名只读接口；SecurityConfig 仅放行指定的 GET/HEAD 路由。 */
@Tag(name = "客户端只读接口", description = "匿名只读：已发布场景目录、详情与单文件 Range 下载，无需登录")
@SecurityRequirements
@RestController
@RequestMapping("/api/v1/client")
@Validated
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneController {
    private final ClientSceneService scenes;
    private final SceneVersionService versions;

    public ClientSceneController(ClientSceneService scenes, SceneVersionService versions) {
        this.scenes = scenes;
        this.versions = versions;
    }

    @Operation(security = {}, summary = "已发布场景列表", description = "匿名读取已发布且可下载的场景；name 子串过滤，按名称排序")
    @GetMapping("/scenes")
    public Map<String, Object> list(@Parameter(description = "名称过滤（子串，不区分大小写）", example = "街区")
                                    @RequestParam(defaultValue = "") @Size(max = 200) String name,
                                    @Parameter(description = "每页条数（1~100）", example = "20")
                                    @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                    @Parameter(description = "偏移量", example = "0")
                                    @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return scenes.list(name, limit, offset);
    }

    @Operation(security = {}, summary = "场景发布详情", description = "场景当前发布版本的文件清单及每个文件的下载路径")
    @GetMapping("/scenes/{sceneId}")
    public Map<String, Object> detail(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId) {
        return scenes.detail(sceneId);
    }

    @Operation(security = {}, summary = "下载单个文件", description = "支持 GET/HEAD 和 Range 断点续传。路径末尾的 fileName 只用于校验和展示扩展名，文件定位靠 UUID")
    @RequestMapping(value = "/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}",
            method = {RequestMethod.GET, RequestMethod.HEAD})
    public void content(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                       @Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                       @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                       @Parameter(description = "文件名（仅用于校验与扩展名展示）", required = true) @PathVariable String fileName,
                       HttpServletRequest request, HttpServletResponse response) throws IOException {
        versions.clientDownload(sceneId, versionId, fileId, fileName, request, response);
    }
}
