package com.ruoyi.ar.module.scene.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 场景名称与说明修改请求；文件清单创建后不可变更。
 *
 * @param name 新名称（非空，最长 200 字符）
 * @param description 新说明（最长 2000 字符，null 按空串处理）
 * @param expectedVersion 场景当前乐观锁版本号
 */
@Schema(name = "SceneUpdateInput")
public record SceneUpdateReq(
        @Schema(description = "场景名称（非空，最长 200 字符）", example = "街道白天场景", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 200) String name,
        @Schema(description = "场景说明（最长 2000 字符）")
        @Size(max = 2000) String description,
        @Schema(description = "场景乐观锁版本号", example = "3", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(0) Long expectedVersion) {
}
