package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/** 按场景修订号发布，防止覆盖上传期间的场景修改。 */
@Schema(name = "PublishInput")
public record SceneVersionPublishInput(
        @Schema(description = "场景的乐观锁版本号", example = "5", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(0) Long expectedSceneVersion) {
}
