package com.ruoyi.ar.module.scene.model;

import java.sql.Timestamp;

public record AuditVO(long id, String sceneId, long actorId, String actorName,
                      String action, String detail, Timestamp createdAt) {
}
