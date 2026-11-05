package com.ruoyi.ar.module.version.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 场景版本描述说明修改请求载体。
 *
 * @param description 新的版本描述说明文本（最长 2000 字符）
 * @param expectedVersion 该版本自身当前的乐观锁版本号（用于防止并发覆盖说明）
 */
@Schema(name = "EditInput")
public record SceneVersionEditReq(
        @Schema(description = "版本说明（最长 2000 字符）", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Size(max = 2000) String description,
        @Schema(description = "版本自身的乐观锁版本号", example = "2", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(0) Long expectedVersion) {
}
