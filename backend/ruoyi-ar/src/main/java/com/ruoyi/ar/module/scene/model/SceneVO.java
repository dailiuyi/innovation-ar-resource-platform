package com.ruoyi.ar.module.scene.model;

import java.sql.Timestamp;

/**
 * 场景对外展示视图对象。
 *
 * @param id 场景唯一标识（UUID 字符串）
 * @param name 场景业务名称
 * @param enabled 是否处于启用状态
 * @param lockVersion 乐观锁当前版本号
 * @param createdAt 创建时间戳
 * @param updatedAt 最后修改时间戳
 */
public record SceneVO(String id, String name, boolean enabled, long lockVersion,
                      Timestamp createdAt, Timestamp updatedAt) {
}
