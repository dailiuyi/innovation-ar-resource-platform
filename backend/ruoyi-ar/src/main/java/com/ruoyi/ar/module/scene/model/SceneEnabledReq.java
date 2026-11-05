package com.ruoyi.ar.module.scene.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/**
 * 场景启停状态变更请求载体。
 *
 * @param enabled 目标状态（true 为启用，false 为停用）
 * @param expectedVersion 预期的乐观锁版本号
 * @param reason 启停操作原因说明（必填，最长 1000 字符，写入审计记录）
 */
@Schema(name = "EnabledInput")
public record SceneEnabledReq(@NotNull Boolean enabled, @NotNull @Min(0) Long expectedVersion,
                              @NotBlank @Size(max = 1000) String reason) {
}
