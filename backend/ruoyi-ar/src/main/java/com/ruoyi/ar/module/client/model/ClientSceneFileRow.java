package com.ruoyi.ar.module.client.model;

/** 只查询登记的文件元数据，不读取存储正文。 */
public record ClientSceneFileRow(String id, String relativePath, long expectedBytes, String expectedSha256) {
}
