package com.ruoyi.ar.module.client.controller;

import com.ruoyi.ar.module.client.service.ClientSceneService;
import com.ruoyi.ar.module.version.service.SceneVersionFileService;

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
 * 面向终端（如 Web 3D 渲染端、Unity 或移动端）提供已发布场景的公共发现与资产下载支持。<br>
 * 权限契约：在 {@code SecurityConfig} 中单独对该类下注册的 GET / HEAD 路由放行匿名访问，无需携带认证 Token；
 * 仅当配置项 {@code ar.storage.enabled=true} 时该控制器生效。
 */
@Tag(name = "客户端只读接口", description = "匿名只读：已发布场景目录、详情与单文件 Range 下载，无需登录")
@SecurityRequirements
@RestController
@RequestMapping("/api/v1/client")
@Validated
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ClientSceneController {
    private final ClientSceneService scenes;
    private final SceneVersionFileService versions;

    public ClientSceneController(ClientSceneService scenes, SceneVersionFileService versions) {
        this.scenes = scenes;
        this.versions = versions;
    }

    /**
     * 分页查询已发布的场景列表。
     *
     * @param name 过滤关键字（模糊匹配场景名称，不区分大小写，默认空字符串不过滤）
     * @param limit 每页条数上限（1~100，默认 20）
     * @param offset 分页偏移量（起始位置，默认 0）
     * @return 包含 {@code items}（场景概要列表）与 {@code total}（匹配总条数）的响应数据
     */
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

    /**
     * 获取指定场景当前发布版本的完整文件清单及下载元数据。
     *
     * @param sceneId 场景唯一标识 UUID
     * @return 包含版本号、文件总数、总字节数以及每个文件的相对路径、SHA-256、下载链接的详情 Map
     * @throws org.springframework.web.server.ResponseStatusException 场景不存在、未启用或无已发布版本时抛出 404
     */
    @Operation(security = {}, summary = "场景发布详情", description = "场景当前发布版本的文件清单及每个文件的下载路径")
    @GetMapping("/scenes/{sceneId}")
    public Map<String, Object> detail(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId) {
        return scenes.detail(sceneId);
    }

    /**
     * 下载或预检指定版本的单个资产文件（支持 HTTP Range 断点续传）。
     *
     * @param sceneId 场景唯一标识 UUID
     * @param versionId 版本唯一标识 UUID（必须与场景当前发布的版本一致）
     * @param fileId 文件记录唯一标识 UUID
     * @param fileName 文件名（URL 尾段，仅用于客户端显式扩展名展示与合法性校验，不用于物理寻址）
     * @param request HTTP 请求对象，用于解析客户端 Range、If-Range 等请求头
     * @param response HTTP 响应对象，用于写入 200/206/416 状态码、Content-Range 及数据流
     * @throws IOException 当底层存储文件读取中断或网络传输异常时抛出
     */
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
