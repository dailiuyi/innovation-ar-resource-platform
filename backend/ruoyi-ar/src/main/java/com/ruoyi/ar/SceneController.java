package com.ruoyi.ar;

import java.util.*;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * 管理端场景（scene）的增删改查与审计日志查询，路径前缀 /api/v1。
 * 一个场景对应一个独立的 4DGS 重建产物；场景自身只保存名称和启用状态，内容文件由“场景版本”承载
 * （见 {@link SceneVersionController}）。访问控制在 SecurityConfig 中配置，这些路径要求已登录。
 */
@Tag(name = "场景管理", description = "场景的增删改查、启停与审计日志查询（需登录）")
@RestController
@RequestMapping("/api/v1")
@Validated
public class SceneController {
    private final SceneService service;
    private final SceneMapper mapper;

    public SceneController(SceneService service, SceneMapper mapper) {
        this.service = service;
        this.mapper = mapper;
    }

    /**
     * 分页查询场景：name 为大小写不敏感的子串过滤（空串表示不过滤），limit 1~100，按创建时间倒序。
     */
    @Operation(summary = "分页查询场景", description = "name 为大小写不敏感的子串过滤（空串表示不过滤），limit 1~100，按创建时间倒序")
    @GetMapping("/scenes")
    public Map<String, Object> list(@Parameter(description = "名称过滤（子串，不区分大小写）", example = "街区")
                                    @RequestParam(defaultValue = "") @Size(max = 200) String name,
                                    @Parameter(description = "每页条数（1~100）", example = "20")
                                    @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                    @Parameter(description = "偏移量", example = "0")
                                    @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return Map.of("items", mapper.list(name, limit, offset), "total", mapper.count(name));
    }

    /**
     * 查询单个场景；不存在或已软删除返回 404。
     */
    @Operation(summary = "查询单个场景", description = "不存在或已软删除返回 404")
    @GetMapping("/scenes/{id}")
    public Map<String, Object> detail(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id) {
        return service.find(id.toString());
    }

    /**
     * 软删除场景（同时置为停用）。expectedVersion 是乐观锁版本号，不匹配返回 409。成功返回 204。
     */
    @Operation(summary = "软删除场景", description = "同时置为停用。expectedVersion 是乐观锁版本号，不匹配返回 409。成功返回 204")
    @DeleteMapping("/scenes/{id}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    public void delete(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id,
                       @Parameter(description = "乐观锁版本号", required = true) @RequestParam @Min(0) long expectedVersion) {
        service.delete(id.toString(), expectedVersion);
    }

    /**
     * 新建场景，返回 201 与新建后的场景。
     */
    @Operation(summary = "新建场景", description = "返回 201 与新建后的场景")
    @PostMapping("/scenes")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    public Map<String, Object> create(@Valid @RequestBody SceneInput s) {
        return service.create(s);
    }

    /**
     * 重命名场景。请求体的 expectedVersion 必填，与库中版本不一致返回 409。
     */
    @Operation(summary = "重命名场景", description = "请求体的 expectedVersion 必填，与库中版本不一致返回 409")
    @PutMapping("/scenes/{id}")
    public Map<String, Object> update(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id,
                                      @Valid @RequestBody SceneInput s) {
        return service.update(id.toString(), s);
    }

    /**
     * 启停请求体。reason 必填，会写入审计日志。
     */
    public record EnabledInput(@NotNull Boolean enabled, @NotNull @Min(0) Long expectedVersion,
                               @NotBlank @Size(max = 1000) String reason) {
    }

    /**
     * 启用/停用场景。停用后匿名客户端看不到该场景（见 ClientSceneService 的可见性条件）。
     */
    @Operation(summary = "启用/停用场景", description = "停用后匿名客户端看不到该场景。reason 必填，写入审计日志")
    @PutMapping("/scenes/{id}/enabled")
    public Map<String, Object> enabled(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id,
                                       @Valid @RequestBody EnabledInput s) {
        return service.enabled(id.toString(), s.enabled(), s.expectedVersion(), s.reason());
    }

    /**
     * 分页查询审计日志，按自增 id 倒序（最新在前）。
     */
    @Operation(summary = "分页查询审计日志", description = "按自增 id 倒序（最新在前）")
    @GetMapping("/audits")
    public Map<String, Object> audits(@Parameter(description = "每页条数（1~100）", example = "20")
                                      @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                      @Parameter(description = "偏移量", example = "0")
                                      @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return Map.of("items", mapper.audits(limit, offset), "total", mapper.auditCount());
    }
}
