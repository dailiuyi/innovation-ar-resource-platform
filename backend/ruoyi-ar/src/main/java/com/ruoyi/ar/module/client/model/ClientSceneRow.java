package com.ruoyi.ar.module.client.model;

/**
 * 客户端可见的场景及其当前发布版本概要持久化行记录。
 *
 * @param id 场景唯一标识（UUID 文本表示）
 * @param name 场景业务名称
 * @param versionId 当前发布版本的唯一标识（UUID 文本表示）
 * @param versionNo 当前发布版本序号（递增正整数）
 */
public record ClientSceneRow(String id, String name, String versionId, int versionNo) {
}
