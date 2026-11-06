package com.ruoyi.ar.module.client.model;

/**
 * 客户端可见的场景概要行记录。
 *
 * @param id 场景唯一标识（UUID 文本表示）
 * @param name 场景业务名称
 */
public record ClientSceneRow(String id, String name) {
}
