package com.ruoyi.ar;

import jakarta.validation.constraints.*;

public record SceneInput(@NotBlank @Size(max=200) String name,@Min(0) Long expectedVersion) {}
