package com.ruoyi.ar.module.scene.controller;

import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.model.SceneEnabledReq;
import com.ruoyi.ar.module.scene.model.SceneReq;
import com.ruoyi.ar.module.scene.model.SceneVO;
import com.ruoyi.ar.module.scene.service.SceneService;

import java.util.UUID;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * 场景管理控制器。
 * <p>
 * 面向具有管理权限的操作员提供场景创建、查询、重命名、启停切换、软删除与操作审计追溯。<br>
 * 控制器层负责参数校验与 HTTP 状态码映射，乐观锁与审计事务保证交由 {@link SceneService} 编排。
 */
@Tag(name = "场景管理", description = "场景的增删改查、启停与审计日志查询（需登录）")
@RestController
@RequestMapping("/api/v1")
@Validated
public class SceneController {
    private final SceneService service;

    public SceneController(SceneService service) {
        this.service = service;
    }
    /**
     * 分页查询后台场景列表。
     *
     * @param name 场景名称模糊过滤关键字（为空不过滤）
     * @param limit 每页记录条数限制（1~100）
     * @param offset 分页偏移量
     * @return 包含场景视图对象列表与总记录数的分页数据包
     */
    @Operation(summary = "分页查询场景", description = "name 为大小写不敏感的子串过滤（空串表示不过滤），limit 1~100，按创建时间倒序")
    @GetMapping("/scenes")
    public Page<SceneVO> list(@Parameter(description = "名称过滤（子串，不区分大小写）", example = "街区")
                              @RequestParam(defaultValue = "") @Size(max = 200) String name,
                              @Parameter(description = "每页条数（1~100）", example = "20")
                              @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                              @Parameter(description = "偏移量", example = "0")
                              @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return service.list(name, limit, offset);
    }

    /**
     * 获取单个场景的详细信息。
     *
     * @param id 场景唯一标识 UUID
     * @return 场景视图对象
     * @throws org.springframework.web.server.ResponseStatusException 若场景不存在或已被软删除则抛出 404
     */
    @Operation(summary = "查询单个场景", description = "不存在或已软删除返回 404")
    @GetMapping("/scenes/{id}")
    public SceneVO detail(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id) {
        return service.find(id.toString());
    }

    /**
     * 软删除指定场景。
     * <p>
     * 逻辑删除场景记录并同时强制置为停用，使终端客户端不再可见。物理成品的清理则由版本删除接口处理。
     *
     * @param id 场景唯一标识 UUID
     * @param expectedVersion 预期的乐观锁版本号
     * @throws org.springframework.web.server.ResponseStatusException 若版本号冲突或记录已变动抛出 409
     */
    @Operation(summary = "软删除场景", description = "同时置为停用。expectedVersion 是乐观锁版本号，不匹配返回 409。成功返回 204")
    @DeleteMapping("/scenes/{id}")
    @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    public void delete(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id,
                       @Parameter(description = "乐观锁版本号", required = true) @RequestParam @Min(0) long expectedVersion) {
        service.delete(id.toString(), expectedVersion);
    }

    /**
     * 创建新场景。
     *
     * @param s 场景新建请求对象（包含必填名称）
     * @return 创建成功后的场景视图对象（包含服务端生成的 UUID 与初始乐观锁版本 0）
     */
    @Operation(summary = "新建场景", description = "返回 201 与新建后的场景")
    @PostMapping("/scenes")
    @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
    public SceneVO create(@Valid @RequestBody SceneReq s) {
        return service.create(s);
    }

    /**
     * 重命名场景。
     *
     * @param id 待修改的场景唯一标识 UUID
     * @param s 场景修改请求对象（包含新名称与必填的 expectedVersion 乐观锁版本号）
     * @return 更新后的场景视图对象
     * @throws org.springframework.web.server.ResponseStatusException 缺少版本号时报 400，版本不匹配或已变动时报 409
     */
    @Operation(summary = "重命名场景", description = "请求体的 expectedVersion 必填，与库中版本不一致返回 409")
    @PutMapping("/scenes/{id}")
    public SceneVO update(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id,
                          @Valid @RequestBody SceneReq s) {
        return service.update(id.toString(), s);
    }

    /**
     * 切换场景的启用/停用状态。
     *
     * @param id 场景唯一标识 UUID
     * @param s 启停请求对象（包含启停布尔值、乐观锁版本号及必填的操作原因）
     * @return 更新状态后的场景视图对象
     * @throws org.springframework.web.server.ResponseStatusException 乐观锁冲突时报 409
     */
    @Operation(summary = "启用/停用场景", description = "停用后匿名客户端看不到该场景。reason 必填，写入审计日志")
    @PutMapping("/scenes/{id}/enabled")
    public SceneVO enabled(@Parameter(description = "场景 ID", required = true) @PathVariable UUID id,
                           @Valid @RequestBody SceneEnabledReq s) {
        return service.enabled(id.toString(), s.enabled(), s.expectedVersion(), s.reason());
    }

    /**
     * 分页查询场景全生命周期操作审计日志。
     *
     * @param limit 每页数量限制（1~100）
     * @param offset 偏移量
     * @return 包含审计记录列表与总条数的分页对象
     */
    @Operation(summary = "分页查询审计日志", description = "按自增 id 倒序（最新在前）")
    @GetMapping("/audits")
    public Page<AuditVO> audits(@Parameter(description = "每页条数（1~100）", example = "20")
                                @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                @Parameter(description = "偏移量", example = "0")
                                @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return service.audits(limit, offset);
    }
}
