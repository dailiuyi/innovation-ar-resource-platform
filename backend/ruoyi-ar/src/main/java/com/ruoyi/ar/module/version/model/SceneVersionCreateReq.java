package com.ruoyi.ar.module.version.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import java.util.UUID;

/**
 * 场景版本创建请求载体。
 * <p>
 * 客户端发起版本创建时，必须提交固定、有序且不可篡改的相对路径文件清单。
 * 相同的 {@code requestKey} 被用作服务端幂等判定键。
 *
 * @param requestKey 客户端生成的幂等 UUID，用于网络超时后安全重试
 * @param description 版本业务描述说明文本（最长 2000 字符）
 * @param files 本版本所包含的全部文件期望清单（非空，至少包含 1 个文件）
 */
@Schema(name = "CreateInput")
public record SceneVersionCreateReq(
        @Schema(description = "客户端生成的幂等键，重试同一导入时复用", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull UUID requestKey,
        @Schema(description = "版本说明（最长 2000 字符）", example = "街道白天场景 v2", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Size(max = 2000) String description,
        @Schema(description = "整个版本的固定文件清单", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotEmpty List<@Valid SceneVersionFileReq> files) {
}
