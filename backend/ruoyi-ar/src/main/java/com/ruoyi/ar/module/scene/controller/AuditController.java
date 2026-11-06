package com.ruoyi.ar.module.scene.controller;

import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.service.SceneAuditService;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * 场景审计查询控制器。
 * <p>
 * 与存储开关无关：即使产品文件能力关闭，历史审计仍可分页读取。历史版本动作标签保持原样。
 */
@Tag(name = "审计日志", description = "场景全生命周期操作记录（需 ar_admin 角色）")
@RestController
@RequestMapping("/api/v1")
@Validated
@PreAuthorize("@ss.hasRole('ar_admin')")
public class AuditController {
    private final SceneAuditService service;

    public AuditController(SceneAuditService service) {
        this.service = service;
    }

    @Operation(summary = "分页查询审计日志", description = "按自增 id 倒序（最新在前）；历史动作标签保持不变")
    @GetMapping("/audits")
    public Page<AuditVO> audits(@Parameter(description = "每页条数（1~100）", example = "20")
                                @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
                                @Parameter(description = "偏移量", example = "0")
                                @RequestParam(defaultValue = "0") @Min(0) int offset) {
        return service.audits(limit, offset);
    }
}
