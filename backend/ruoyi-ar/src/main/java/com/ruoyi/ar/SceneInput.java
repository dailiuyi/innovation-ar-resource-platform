package com.ruoyi.ar;

import jakarta.validation.constraints.*;

/**
 * 场景新建/重命名的请求体。
 *
 * @param name            场景名称，非空，最长 200 字符
 * @param expectedVersion 乐观锁版本号（对应 ar_scene.lock_version）；新建时忽略，更新时必填
 */
public record SceneInput(@NotBlank @Size(max=200) String name,@Min(0) Long expectedVersion) {}
