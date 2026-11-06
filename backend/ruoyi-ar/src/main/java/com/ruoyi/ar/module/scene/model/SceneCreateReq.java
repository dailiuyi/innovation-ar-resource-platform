package com.ruoyi.ar.module.scene.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import java.util.UUID;

/**
 * 场景与固定文件清单的一次性创建请求。
 * <p>
 * requestKey 是客户端生成的幂等键：同一键且名称、说明和文件清单（路径/大小/SHA-256）一致时重试返回
 * 既有场景；同一键用于不同内容返回 409；该键对应已删除或删除中的场景返回 410。
 *
 * @param requestKey 客户端生成的幂等 UUID
 * @param name 场景名称（非空，最长 200 字符）
 * @param description 场景说明（最长 2000 字符，缺省空串）
 * @param files 固定文件清单（非空，创建后不可变更）
 */
@Schema(name = "SceneCreateInput")
public record SceneCreateReq(
        @Schema(description = "客户端生成的幂等键，重试同一导入时复用", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull UUID requestKey,
        @Schema(description = "场景名称（非空，最长 200 字符）", example = "街道白天场景", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotBlank @Size(max = 200) String name,
        @Schema(description = "场景说明（最长 2000 字符）", example = "供终端资源分发的固定文件集")
        @Size(max = 2000) String description,
        @Schema(description = "固定文件清单，创建后不可变更", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotEmpty List<@Valid SceneCreateFileReq> files) {
}
