package com.ruoyi.ar.module.scene.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/** 启停原因将写入审计。 */
@Schema(name = "EnabledInput")
public record SceneEnabledReq(@NotNull Boolean enabled, @NotNull @Min(0) Long expectedVersion,
                              @NotBlank @Size(max = 1000) String reason) {
}
