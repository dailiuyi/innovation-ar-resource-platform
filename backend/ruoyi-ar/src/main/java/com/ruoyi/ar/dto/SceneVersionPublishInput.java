package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 发布请求；expectedSceneVersion 是场景的乐观锁版本号，用来发现发布期间场景被改动。
 */
@Schema(name = "PublishInput")
public record SceneVersionPublishInput(
        @Schema(description = "场景的乐观锁版本号", example = "5", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(0) Long expectedSceneVersion) {
}
