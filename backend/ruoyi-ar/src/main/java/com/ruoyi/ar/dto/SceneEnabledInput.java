package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/** 启停原因将写入审计。 */
@Schema(name = "EnabledInput")
public record SceneEnabledInput(@NotNull Boolean enabled, @NotNull @Min(0) Long expectedVersion,
                               @NotBlank @Size(max = 1000) String reason) {
}
