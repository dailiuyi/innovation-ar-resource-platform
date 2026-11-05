package com.ruoyi.ar.module.scene.model;

import java.util.List;

public record Page<T>(List<T> items, long total) {
}
