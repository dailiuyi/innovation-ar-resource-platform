package com.ruoyi.ar.module.scene.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 固定清单中的单个文件登记项。
 *
 * @param relativePath 还原至目标平台的标准 POSIX 相对路径（创建时规范化校验，最长 1024 字符）
 * @param bytes 该文件的确切字节大小（至少 1 字节）
 * @param sha256 整个文件内容的 SHA-256 小写十六进制摘要
 */
@Schema(name = "SceneFileInput")
public record SceneCreateFileReq(
        @Schema(description = "场景内相对路径", example = "models/a.bundle", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 1024) String relativePath,
        @Schema(description = "字节数（至少 1）", example = "1048576", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(1) Long bytes,
        @Schema(description = "小写十六进制 SHA256", example = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Pattern(regexp = "[0-9a-f]{64}") String sha256) {
}
