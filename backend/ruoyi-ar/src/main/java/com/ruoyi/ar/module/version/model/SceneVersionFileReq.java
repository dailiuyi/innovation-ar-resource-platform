package com.ruoyi.ar.module.version.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;

/**
 * 版本清单中的单个文件元数据登记请求项。
 *
 * @param relativePath 还原至目标平台的标准 POSIX 相对路径（经过规范化校验，最长 1024 字符）
 * @param bytes 该文件的确切字节大小（至少为 1 字节，不允许 0 字节资产）
 * @param sha256 整个文件内容的 SHA-256 哈希串（64 位小写十六进制正则匹配）
 */
@Schema(name = "FileInput")
public record SceneVersionFileReq(
        @Schema(description = "版本内相对路径", example = "models/a.bundle", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 1024) String relativePath,
        @Schema(description = "字节数（至少 1）", example = "1048576", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Min(1) Long bytes,
        @Schema(description = "小写十六进制 SHA256", example = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Pattern(regexp = "[0-9a-f]{64}") String sha256) {
}
