package com.ruoyi.ar.module.scene.controller;

import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.model.SceneCreateReq;
import com.ruoyi.ar.module.scene.model.SceneEnabledReq;
import com.ruoyi.ar.module.scene.model.SceneRows;
import com.ruoyi.ar.module.scene.model.SceneUpdateReq;
import com.ruoyi.ar.module.scene.service.SceneFileService;
import com.ruoyi.ar.module.scene.service.SceneService;

import java.io.IOException;
import java.util.Map;
import java.util.UUID;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Schema;
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

/**
 * 场景与固定文件清单管理控制器。
 * <p>
 * 面向 {@code ar_admin} 管理员：一次性创建场景及固定清单（requestKey 幂等重试）、查询、
 * 名称/说明编辑、启停、整场景物理删除，以及逐文件原始字节上传与管理端下载。
 * 无版本、发布或替换接口。仅当 {@code ar.storage.enabled=true} 时注册。
 */
@Tag(name = "场景管理", description = "场景创建、查询、编辑、启停、删除与逐文件上传/下载（需 ar_admin 角色）")
@RestController
@RequestMapping("/api/v1")
@Validated
@PreAuthorize("@ss.hasRole('ar_admin')")
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneController {
    private final SceneService service;
    private final SceneFileService fileService;

    public SceneController(SceneService service, SceneFileService fileService) {
        this.service = service;
        this.fileService = fileService;
    }

    @Operation(summary = "查询存储上限配置", description = "返回单文件大小、每场景文件数与总字节数上限，供导入前预检")
    @GetMapping("/scenes/config")
    public Map<String, Object> config() {
        return service.config();
    }

    @Operation(summary = "分页查询场景", description = "name 为大小写不敏感子串过滤；删除中或删除失败的场景仍可见以便重试")
    @GetMapping("/scenes")
    public Page<SceneRows.Summary> list(
            @Parameter(description = "名称过滤（子串，不区分大小写）", example = "街区")
            @RequestParam(defaultValue = "") @Size(max = 200) String name,
            @Parameter(description = "每页条数（1~100）", example = "20")
            @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
            @Parameter(description = "偏移量", example = "0")
            @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return service.list(name, limit, offset);
    }

    @Operation(summary = "创建场景与固定文件清单", description = "首次创建返回 201；同一 requestKey 且内容相同的重试返回 200；内容不同 409；已删除 410")
    @PostMapping("/scenes")
    public ResponseEntity<Map<String, Object>> create(@Valid @RequestBody SceneCreateReq input) {
        var result = service.create(input);
        return ResponseEntity.status(result.created() ? HttpStatus.CREATED : HttpStatus.OK).body(result.scene());
    }

    @Operation(summary = "查询场景详情", description = "场景概要加固定文件清单及每个文件的上传状态")
    @GetMapping("/scenes/{sceneId}")
    public Map<String, Object> detail(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId) {
        return service.detail(sceneId);
    }

    @Operation(summary = "修改场景名称与说明", description = "文件清单不可修改；删除中的场景返回 409")
    @PutMapping("/scenes/{sceneId}")
    public Map<String, Object> update(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                      @Valid @RequestBody SceneUpdateReq input) {
        return service.update(sceneId, input);
    }

    @Operation(summary = "启用/停用场景", description = "停用后匿名客户端看不到该场景；reason 必填并写入审计")
    @PutMapping("/scenes/{sceneId}/enabled")
    public Map<String, Object> enabled(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                       @Valid @RequestBody SceneEnabledReq input) {
        return service.enabled(sceneId, input.enabled(), input.expectedVersion(), input.reason());
    }

    @Operation(summary = "整场景物理删除", description = "成功或重复完成返回 204；有在途传输或乐观锁不一致返回 409；物理删除失败 503 并可重试")
    @DeleteMapping("/scenes/{sceneId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                       @Parameter(description = "乐观锁版本号", required = true) @RequestParam @Min(0) long expectedVersion) {
        service.delete(sceneId, expectedVersion);
    }

    @Operation(summary = "查询单个文件状态", description = "固定清单中的文件登记信息与实时上传状态")
    @GetMapping("/scenes/{sceneId}/files/{fileId}")
    public Map<String, Object> file(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                    @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId) {
        return fileService.fileStatus(sceneId, fileId);
    }

    @Operation(summary = "上传单个文件", description = "原始字节流（application/octet-stream），服务端边收边校验大小与 SHA256；已就绪文件不覆盖正文",
            requestBody = @io.swagger.v3.oas.annotations.parameters.RequestBody(required = true,
                    content = @io.swagger.v3.oas.annotations.media.Content(mediaType = "application/octet-stream",
                            schema = @Schema(type = "string", format = "binary"))))
    @PutMapping(value = "/scenes/{sceneId}/files/{fileId}/content", consumes = "application/octet-stream")
    public Map<String, Object> upload(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                                      @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                                      HttpServletRequest request) throws IOException {
        return fileService.upload(sceneId, fileId, request.getInputStream());
    }

    @Operation(summary = "管理端下载文件", description = "支持 GET/HEAD 与 Range；场景停用仍可读，删除中不可读")
    @RequestMapping(value = "/scenes/{sceneId}/files/{fileId}/content",
            method = {RequestMethod.GET, RequestMethod.HEAD})
    public void download(@Parameter(description = "场景 ID", required = true) @PathVariable UUID sceneId,
                         @Parameter(description = "文件 ID", required = true) @PathVariable UUID fileId,
                         HttpServletRequest request, HttpServletResponse response) throws IOException {
        fileService.adminDownload(sceneId, fileId, request, response);
    }
}
