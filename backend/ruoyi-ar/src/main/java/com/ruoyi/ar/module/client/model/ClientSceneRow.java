package com.ruoyi.ar.module.client.model;

/** 当前可见的发布版本，供客户端列表和详情共用。UUID 按数据库文本输出。 */
public record ClientSceneRow(String id, String name, String versionId, int versionNo) {
}
