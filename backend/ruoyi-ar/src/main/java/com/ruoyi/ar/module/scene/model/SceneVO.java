package com.ruoyi.ar.module.scene.model;

import java.sql.Timestamp;

public record SceneVO(String id, String name, boolean enabled, long lockVersion,
                      Timestamp createdAt, Timestamp updatedAt) {
}
