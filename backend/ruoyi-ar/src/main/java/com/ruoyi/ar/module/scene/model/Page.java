package com.ruoyi.ar.module.scene.model;

import java.util.List;

/**
 * 通用分页响应容器对象。
 *
 * @param <T> 分页列表中的元素数据类型
 * @param items 当前页的数据元素列表
 * @param total 满足查询条件的总记录数
 */
public record Page<T>(List<T> items, long total) {
}
