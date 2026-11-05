package com.ruoyi.ar.module.scene.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 场景新建与重命名请求载体。
 *
 * @param name 场景业务名称（必填，非空白，最长 200 字符）
 * @param expectedVersion 预期的乐观锁版本号（新建时忽略，重命名与更新时必填）
 */
@Schema(name = "SceneInput")
public record SceneReq(
        @Schema(description = "场景名称（非空，最长 200 字符）", example = "街道白天场景", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 200) String name,
        @Schema(description = "乐观锁版本号；新建时忽略，更新时必填", example = "3")
        @Min(0) Long expectedVersion) {
}
