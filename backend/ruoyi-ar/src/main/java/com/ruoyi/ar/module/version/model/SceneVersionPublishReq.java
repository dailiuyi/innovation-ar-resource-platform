package com.ruoyi.ar.module.version.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 场景版本发布生效请求载体。
 *
 * @param expectedSceneVersion 该版本所属场景目前的乐观锁版本号（确保发布指针切换时的场景一致性）
 */
@Schema(name = "PublishInput")
public record SceneVersionPublishReq(
        @Schema(description = "场景的乐观锁版本号", example = "5", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(0) Long expectedSceneVersion) {
}
