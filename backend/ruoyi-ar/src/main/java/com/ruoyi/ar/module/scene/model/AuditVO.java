package com.ruoyi.ar.module.scene.model;

import java.sql.Timestamp;

/**
 * 场景全生命周期操作审计日志视图对象。
 *
 * @param id 审计日志自增主键 ID
 * @param sceneId 关联的场景唯一标识（UUID 字符串）
 * @param actorId 执行操作的用户 ID
 * @param actorName 执行操作的用户名
 * @param action 操作类型（如 CREATE、UPDATE、SET_ENABLED、DELETE 等）
 * @param detail 变更详细信息的 JSON 序列化字符串
 * @param createdAt 审计记录生成时间戳
 */
public record AuditVO(long id, String sceneId, long actorId, String actorName,
                      String action, String detail, Timestamp createdAt) {
}
