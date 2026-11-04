package com.ruoyi.ar.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import java.util.UUID;

/** 同次导入重试复用 requestKey，文件清单创建后不可改。 */
@Schema(name = "CreateInput")
public record SceneVersionCreateInput(
        @Schema(description = "客户端生成的幂等键，重试同一导入时复用", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull UUID requestKey,
        @Schema(description = "版本说明（最长 2000 字符）", example = "街道白天场景 v2", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotNull @Size(max = 2000) String description,
        @Schema(description = "整个版本的固定文件清单", requiredMode = Schema.RequiredMode.REQUIRED)
        @NotEmpty List<@Valid SceneVersionFileInput> files) {
}
