package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/** 新建或重命名场景；expectedVersion 新建时忽略，更新时必填。 */
public record SceneInput(
        @Schema(description = "场景名称（非空，最长 200 字符）", example = "街道白天场景", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 200) String name,
        @Schema(description = "乐观锁版本号；新建时忽略，更新时必填", example = "3")
        @Min(0) Long expectedVersion) {
}
