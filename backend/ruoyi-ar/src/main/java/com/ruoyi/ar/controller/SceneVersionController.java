package com.ruoyi.ar.controller;

import com.ruoyi.ar.dto.SceneVersionCreateInput;
import com.ruoyi.ar.dto.SceneVersionEditInput;
import com.ruoyi.ar.dto.SceneVersionPublishInput;
import com.ruoyi.ar.service.SceneVersionService;

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

/** 管理版本和文件传输，业务流程由 SceneVersionService 处理。 */
@Tag(name = "场景版本管理", description = "版本创建、发布、删除与逐文件上传/下载（需 ar_admin 角色）")
@RestController
@RequestMapping("/api/v1")
@Validated
@PreAuthorize("@ss.hasRole('ar_admin')")
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneVersionController {
    private final SceneVersionService service;

    public SceneVersionController(SceneVersionService service) {
        this.service = service;
    }

    @Operation(summary = "查询存储上限配置", description = "返回单文件大小、每版本文件数与总字节数上限，供导入前预检")
    @GetMapping("/scene-versions/config")
    public Map<String, Object> config() {
        return service.config();
    }

    @Operation(summary = "查询场景版本列表", description = "按版本号倒序，附带场景乐观锁版本号和当前发布版本")
    @GetMapping("/scenes/{sceneId}/versions")
    public Map<String, Object> list(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                    @Parameter(description = "每页条数（1~100）", example = "20")
                                    @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                    @Parameter(description = "偏移量", example = "0")
                                    @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return service.list(sceneId, limit, offset);
    }

    @Operation(summary = "创建版本", description = "首次创建返回 201；同一 requestKey 且内容相同的重试返回 200 和已有版本")
    @PostMapping("/scenes/{sceneId}/versions")
    public ResponseEntity<Map<String, Object>> create(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                                       @Valid @RequestBody SceneVersionCreateInput input) {
        var result = service.create(sceneId, input);
        return ResponseEntity.status(result.created() ? HttpStatus.CREATED : HttpStatus.OK).body(result.version());
    }

    @Operation(summary = "查询版本详情", description = "含全部文件及其上传状态")
    @GetMapping("/scene-versions/{versionId}")
    public Map<String, Object> detail(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId) {
        return service.detail(versionId);
    }

    @Operation(summary = "修改版本说明", description = "只修改版本说明；文件清单创建后不可变")
    @PutMapping("/scene-versions/{versionId}")
    public Map<String, Object> edit(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                    @Valid @RequestBody SceneVersionEditInput input) {
        return service.edit(versionId, input);
    }

    @Operation(summary = "发布版本", description = "把该版本设为场景当前发布版本；原发布版本保留，仍可查看和删除")
    @PostMapping("/scene-versions/{versionId}/publish")
    public Map<String, Object> publish(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                        @Valid @RequestBody SceneVersionPublishInput input) {
        return service.publish(versionId, input.expectedSceneVersion());
    }

    @Operation(summary = "整版本物理删除", description = "成功 204。当前发布版本不能删；已删除的版本重复调用也返回 204")
    @DeleteMapping("/scene-versions/{versionId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void remove(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId) {
        service.removeVersion(versionId);
    }

    @Operation(summary = "查询单个文件状态", description = "单个文件的登记信息与上传状态")
    @GetMapping("/scene-versions/{versionId}/files/{fileId}")
    public Map<String, Object> file(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                     @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId) {
        return service.fileStatus(versionId, fileId);
    }

    @Operation(summary = "上传单个文件", description = "原始字节流（application/octet-stream），服务端边收边校验大小与 SHA256",
            requestBody = @io.swagger.v3.oas.annotations.parameters.RequestBody(required = true,
                    content = @io.swagger.v3.oas.annotations.media.Content(mediaType = "application/octet-stream",
                            schema = @Schema(type = "string", format = "binary"))))
    @PutMapping(value = "/scene-versions/{versionId}/files/{fileId}/content", consumes = "application/octet-stream")
    public Map<String, Object> upload(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                      @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                                      HttpServletRequest request) throws java.io.IOException {
        return service.upload(versionId, fileId, request.getInputStream());
    }

    @Operation(summary = "下载单个文件", description = "管理端下载已就绪的文件，支持 GET/HEAD 与 Range，以附件形式返回")
    @RequestMapping(value = "/scene-versions/{versionId}/files/{fileId}/content", method = {RequestMethod.GET, RequestMethod.HEAD})
    public void download(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                         @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                         HttpServletRequest request, HttpServletResponse response) throws java.io.IOException {
        service.adminDownload(versionId, fileId, request, response);
    }
}
