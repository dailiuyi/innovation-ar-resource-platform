package com.ruoyi.ar.module.client.model;

/**
 * 客户端可见的发布版本关联文件清单元数据行记录。
 * <p>
 * 承载数据库中已登记的期望大小与摘要信息，在清单响应中直接复用，不触发对底层物理存储实体的读取。
 *
 * @param id 文件记录唯一标识（UUID 文本表示）
 * @param relativePath 还原至客户端时的标准 POSIX 相对路径
 * @param expectedBytes 文件的精确字节大小
 * @param expectedSha256 文件全量内容的 SHA-256 十六进制哈希串（64 位小写）
 */
public record ClientSceneFileRow(String id, String relativePath, long expectedBytes, String expectedSha256) {
}
