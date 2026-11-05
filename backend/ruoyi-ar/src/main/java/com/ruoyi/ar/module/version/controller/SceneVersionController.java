package com.ruoyi.ar.module.version.controller;

import com.ruoyi.ar.module.version.model.SceneVersionCreateReq;
import com.ruoyi.ar.module.version.model.SceneVersionEditReq;
import com.ruoyi.ar.module.version.model.SceneVersionPublishReq;
import com.ruoyi.ar.module.version.service.SceneVersionFileService;
import com.ruoyi.ar.module.version.service.SceneVersionService;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;
import io.swagger.v3.oas.annotations.media.Schema;

/**
 * 场景成品版本管理控制器。
 * <p>
 * 面向具有 {@code ar_admin} 管理员角色的用户，提供场景版本的全生命周期管理：
 * 包括版本预检与创建（支持基于 requestKey 的幂等重试）、元数据说明修改、设为当前发布版本、
 * 整版本物理删除，以及逐个文件的原始二进制字节流上传与管理端下载。<br>
 * 仅当系统配置项 {@code ar.storage.enabled=true} 时本控制器注册生效。
 */
@Tag(name = "场景版本管理", description = "版本创建、发布、删除与逐文件上传/下载（需 ar_admin 角色）")
@RestController
@RequestMapping("/api/v1")
@Validated
@PreAuthorize("@ss.hasRole('ar_admin')")
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneVersionController {
    private final SceneVersionService service;
    private final SceneVersionFileService fileService;

    public SceneVersionController(SceneVersionService service, SceneVersionFileService fileService) {
        this.service = service;
        this.fileService = fileService;
    }

    /**
     * 查询当前服务端配置的文件与版本存储容量上限。
     *
     * @return 包含单文件字节上限 {@code maxBytes}、单版本文件数上限 {@code versionMaxFiles} 和单版本总字节数上限 {@code versionMaxBytes} 的 Map
     */
    @Operation(summary = "查询存储上限配置", description = "返回单文件大小、每版本文件数与总字节数上限，供导入前预检")
    @GetMapping("/scene-versions/config")
    public Map<String, Object> config() {
        return service.config();
    }
    /**
     * 分页查询指定场景下的所有成品版本列表（按版本序号倒序排列）。
     *
     * @param sceneId 场景唯一标识 UUID
     * @param limit 每页条数上限（1~100）
     * @param offset 偏移量
     * @return 包含版本概要列表、场景乐观锁版本及当前发布版本指针的响应 Map
     */
    @Operation(summary = "查询场景版本列表", description = "按版本号倒序，附带场景乐观锁版本号和当前发布版本")
    @GetMapping("/scenes/{sceneId}/versions")
    public Map<String, Object> list(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                    @Parameter(description = "每页条数（1~100）", example = "20")
                                    @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                    @Parameter(description = "偏移量", example = "0")
                                    @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return service.list(sceneId, limit, offset);
    }
    /**
     * 在指定场景下创建新版本（包含固定不可变的文件清单元数据）。
     * <p>
     * 支持基于请求体中 {@code requestKey} 的客户端幂等重试：首次成功返回 201 CREATED；
     * 携带相同 requestKey 且参数内容完全一致的重试请求直接返回 200 OK 及已创建的版本详情。
     *
     * @param sceneId 场景唯一标识 UUID
     * @param input 版本创建请求体（包含幂等键、说明与待登记的文件路径清单）
     * @return 状态码 201 或 200，以及版本详情 Map
     */
    @Operation(summary = "创建版本", description = "首次创建返回 201；同一 requestKey 且内容相同的重试返回 200 和已有版本")
    @PostMapping("/scenes/{sceneId}/versions")
    public ResponseEntity<Map<String, Object>> create(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                                       @Valid @RequestBody SceneVersionCreateReq input) {
        var result = service.create(sceneId, input);
        return ResponseEntity.status(result.created() ? HttpStatus.CREATED : HttpStatus.OK).body(result.version());
    }
    /**
     * 查询单个版本的详情及其下属所有文件的上传状态。
     *
     * @param versionId 版本唯一标识 UUID
     * @return 包含版本主记录信息与文件列表的详情 Map
     */
    @Operation(summary = "查询版本详情", description = "含全部文件及其上传状态")
    @GetMapping("/scene-versions/{versionId}")
    public Map<String, Object> detail(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId) {
        return service.detail(versionId);
    }
    /**
     * 修改版本的描述说明。
     * <p>
     * 仅允许修改描述文本，版本的关联文件清单一旦创建便物理固定不可篡改。
     *
     * @param versionId 版本唯一标识 UUID
     * @param input 包含新描述说明与该版本自身 expectedVersion 乐观锁版本号的请求体
     * @return 更新后的版本详情 Map
     */
    @Operation(summary = "修改版本说明", description = "只修改版本说明；文件清单创建后不可变")
    @PutMapping("/scene-versions/{versionId}")
    public Map<String, Object> edit(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                    @Valid @RequestBody SceneVersionEditReq input) {
        return service.edit(versionId, input);
    }
    /**
     * 将指定版本发布为所属场景的当前激活版本。
     * <p>
     * 发布成功后匿名客户端将可见此版本。版本的所有关联文件必须已全部处于 AVAILABLE 状态；
     * 必须传入场景的 expectedSceneVersion 确保并发场景安全。发布后原发布版本仍保留以备追溯或删除。
     *
     * @param versionId 待发布的版本唯一标识 UUID
     * @param input 包含场景乐观锁版本号 expectedSceneVersion 的请求体
     * @return 发布后的场景与版本更新结果 Map
     */
    @Operation(summary = "发布版本", description = "把该版本设为场景当前发布版本；原发布版本保留，仍可查看和删除")
    @PostMapping("/scene-versions/{versionId}/publish")
    public Map<String, Object> publish(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                        @Valid @RequestBody SceneVersionPublishReq input) {
        return service.publish(versionId, input.expectedSceneVersion());
    }
    /**
     * 整版本物理删除。
     * <p>
     * 物理清理该版本在底层存储的所有文件实体以及数据库关联行，同时保留删除审计回执。
     * 约束：当前正处于发布状态的版本禁止删除；支持幂等调用（对已删除版本重复调用仍返回 204）。
     *
     * @param versionId 待物理删除的版本唯一标识 UUID
     */
    @Operation(summary = "整版本物理删除", description = "成功 204。当前发布版本不能删；已删除的版本重复调用也返回 204")
    @DeleteMapping("/scene-versions/{versionId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void remove(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId) {
        service.removeVersion(versionId);
    }
    /**
     * 查询版本下单个文件的登记信息与实时就绪状态。
     *
     * @param versionId 版本唯一标识 UUID
     * @param fileId 文件记录唯一标识 UUID
     * @return 单个文件的元数据、状态（PENDING/AVAILABLE/FAILED 等）与上传尝试次数
     */
    @Operation(summary = "查询单个文件状态", description = "单个文件的登记信息与上传状态")
    @GetMapping("/scene-versions/{versionId}/files/{fileId}")
    public Map<String, Object> file(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                     @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId) {
        return fileService.fileStatus(versionId, fileId);
    }

    /**
     * 上传单个文件的原始二进制字节流。
     * <p>
     * 客户端直接在 HTTP 请求正文中发送 octet-stream 格式数据。服务端在文件锁内边接收边动态计算大小与 SHA-256，
     * 校验完全匹配后原子转正并标记为 AVAILABLE；不匹配或中断时自动清理暂存文件并记录重试信息。
     *
     * @param versionId 版本唯一标识 UUID
     * @param fileId 文件记录唯一标识 UUID
     * @param request HTTP 请求，用于获取文件二进制输入流
     * @return 包含更新后文件状态的 Map
     * @throws java.io.IOException 当底层磁盘 I/O 或网络流读取失败时抛出
     */
    @Operation(summary = "上传单个文件", description = "原始字节流（application/octet-stream），服务端边收边校验大小与 SHA256",
            requestBody = @io.swagger.v3.oas.annotations.parameters.RequestBody(required = true,
                    content = @io.swagger.v3.oas.annotations.media.Content(mediaType = "application/octet-stream",
                            schema = @Schema(type = "string", format = "binary"))))
    @PutMapping(value = "/scene-versions/{versionId}/files/{fileId}/content", consumes = "application/octet-stream")
    public Map<String, Object> upload(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                      @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                                      HttpServletRequest request) throws java.io.IOException {
        return fileService.upload(versionId, fileId, request.getInputStream());
    }
    /**
     * 管理端下载或预检已就绪的单个版本文件。
     * <p>
     * 要求操作员具有管理权限，支持 GET 与 HEAD 请求方法，支持 HTTP Range 区间断点续传，
     * 响应头带 Content-Disposition 附件标识。
     *
     * @param versionId 版本唯一标识 UUID
     * @param fileId 文件记录唯一标识 UUID
     * @param request HTTP 请求
     * @param response HTTP 响应
     * @throws java.io.IOException 当文件读取中断或传输异常时抛出
     */
    @Operation(summary = "下载单个文件", description = "管理端下载已就绪的文件，支持 GET/HEAD 与 Range，以附件形式返回")
    @RequestMapping(value = "/scene-versions/{versionId}/files/{fileId}/content", method = {RequestMethod.GET, RequestMethod.HEAD})
    public void download(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                         @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                         HttpServletRequest request, HttpServletResponse response) throws java.io.IOException {
        fileService.adminDownload(versionId, fileId, request, response);
    }
}
