package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 修改版本说明；expectedVersion 是版本自身的乐观锁版本号。
 */
@Schema(name = "EditInput")
public record SceneVersionEditInput(
        @Schema(description = "版本说明（最长 2000 字符）", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Size(max = 2000) String description,
        @Schema(description = "版本自身的乐观锁版本号", example = "2", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(0) Long expectedVersion) {
}
