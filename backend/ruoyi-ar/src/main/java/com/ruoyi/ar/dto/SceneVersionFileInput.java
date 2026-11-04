package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/** 版本内固定的文件路径、大小和摘要。 */
@Schema(name = "FileInput")
public record SceneVersionFileInput(
        @Schema(description = "版本内相对路径", example = "models/a.bundle", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 1024) String relativePath,
        @Schema(description = "字节数（至少 1）", example = "1048576", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(1) Long bytes,
        @Schema(description = "小写十六进制 SHA256", example = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Pattern(regexp = "[0-9a-f]{64}") String sha256) {
}
