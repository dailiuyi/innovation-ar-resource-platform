package com.ruoyi.ar;

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

import java.util.List;
import java.util.Map;
import java.util.UUID;
import io.swagger.v3.oas.annotations.media.Schema;

/**
 * 管理端场景版本接口。一个版本是一次导入目录的不可变文件清单（相对路径、字节数、SHA256）加可编辑说明；
 * 文件逐个上传并校验。类上要求 ar_admin 角色，且仅在 ar.storage.enabled=true 时注册。
 * 具体业务与并发规则见 {@link SceneVersionService}。
 */
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

    /**
     * 登记的单个文件：相对路径、字节数（至少 1）和小写十六进制 SHA256。
     */
    public record FileInput(
            @Schema(description = "版本内相对路径", example = "models/a.bundle", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotBlank @Size(max = 1024) String relativePath,
            @Schema(description = "字节数（至少 1）", example = "1048576", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull @Min(1) Long bytes,
            @Schema(description = "小写十六进制 SHA256", example = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull @Pattern(regexp = "[0-9a-f]{64}") String sha256) {
    }

    /**
     * 创建版本请求。requestKey 是客户端生成的幂等键，重试同一导入时复用；
     * files 是整个版本的固定文件清单。
     */
    public record CreateInput(
            @Schema(description = "客户端生成的幂等键，重试同一导入时复用", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull UUID requestKey,
            @Schema(description = "版本说明（最长 2000 字符）", example = "街道白天场景 v2", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull @Size(max = 2000) String description,
            @Schema(description = "整个版本的固定文件清单", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotEmpty List<@Valid FileInput> files) {
    }

    /**
     * 修改版本说明；expectedVersion 是版本自身的乐观锁版本号。
     */
    public record EditInput(
            @Schema(description = "版本说明（最长 2000 字符）", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull @Size(max = 2000) String description,
            @Schema(description = "版本自身的乐观锁版本号", example = "2", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull @Min(0) Long expectedVersion) {
    }

    /**
     * 发布请求；expectedSceneVersion 是场景的乐观锁版本号，用来发现发布期间场景被改动。
     */
    public record PublishInput(
            @Schema(description = "场景的乐观锁版本号", example = "5", requiredMode = Schema.RequiredMode.REQUIRED)
            @NotNull @Min(0) Long expectedSceneVersion) {
    }


    /**
     * 返回存储相关的上限（单文件大小、每版本文件数与总字节数），供前端导入前预检。
     */
    @Operation(summary = "查询存储上限配置", description = "返回单文件大小、每版本文件数与总字节数上限，供导入前预检")
    @GetMapping("/scene-versions/config")
    public Map<String, Object> config() {
        return service.config();
    }

    /**
     * 某场景的版本列表（版本号倒序），附带场景版本号和当前发布版本。
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
     * 创建版本：首次创建返回 201；同一 requestKey 且内容相同的重试返回 200 和已有版本。
     */
    @Operation(summary = "创建版本", description = "首次创建返回 201；同一 requestKey 且内容相同的重试返回 200 和已有版本")
    @PostMapping("/scenes/{sceneId}/versions")
    public ResponseEntity<Map<String, Object>> create(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                                       @Valid @RequestBody CreateInput input) {
        var result = service.create(sceneId, input);
        return ResponseEntity.status(result.created() ? HttpStatus.CREATED : HttpStatus.OK).body(result.version());
    }

    /**
     * 版本详情，含全部文件及其上传状态。
     */
    @Operation(summary = "查询版本详情", description = "含全部文件及其上传状态")
    @GetMapping("/scene-versions/{versionId}")
    public Map<String, Object> detail(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId) {
        return service.detail(versionId);
    }

    /**
     * 只修改版本说明；文件清单创建后不可变。
     */
    @Operation(summary = "修改版本说明", description = "只修改版本说明；文件清单创建后不可变")
    @PutMapping("/scene-versions/{versionId}")
    public Map<String, Object> edit(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                    @Valid @RequestBody EditInput input) {
        return service.edit(versionId, input);
    }

    /**
     * 把该版本设为场景当前发布版本；原发布版本保留，仍可查看和删除。
     */
    @Operation(summary = "发布版本", description = "把该版本设为场景当前发布版本；原发布版本保留，仍可查看和删除")
    @PostMapping("/scene-versions/{versionId}/publish")
    public Map<String, Object> publish(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                        @Valid @RequestBody PublishInput input) {
        return service.publish(versionId, input.expectedSceneVersion());
    }

    /**
     * 整版本物理删除，成功 204。当前发布版本不能删；已删除的版本重复调用也返回 204。
     */
    @Operation(summary = "整版本物理删除", description = "成功 204。当前发布版本不能删；已删除的版本重复调用也返回 204")
    @DeleteMapping("/scene-versions/{versionId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void remove(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId) {
        service.removeVersion(versionId);
    }

    /**
     * 单个文件的登记信息与上传状态。
     */
    @Operation(summary = "查询单个文件状态", description = "单个文件的登记信息与上传状态")
    @GetMapping("/scene-versions/{versionId}/files/{fileId}")
    public Map<String, Object> file(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                                     @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId) {
        return service.fileStatus(versionId, fileId);
    }

    /**
     * 上传单个文件的原始字节（application/octet-stream），服务端边收边校验大小与 SHA256。
     */
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

    /**
     * 管理端下载已就绪的文件，支持 GET/HEAD 与 Range，以附件形式返回。
     */
    @Operation(summary = "下载单个文件", description = "管理端下载已就绪的文件，支持 GET/HEAD 与 Range，以附件形式返回")
    @RequestMapping(value = "/scene-versions/{versionId}/files/{fileId}/content", method = {RequestMethod.GET, RequestMethod.HEAD})
    public void download(@Parameter(description = "版本 ID", required = true) @PathVariable UUID versionId,
                         @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                         HttpServletRequest request, HttpServletResponse response) throws java.io.IOException {
        service.adminDownload(versionId, fileId, request, response);
    }
}
