package com.ruoyi.ar.module.client.mapper;

import com.ruoyi.ar.module.client.model.ClientSceneFileRow;
import com.ruoyi.ar.module.client.model.ClientSceneRow;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 发布目录查询；列表、计数和详情共用 XML 中的可见性条件。 */
@Mapper
public interface ClientSceneMapper {
    /**
     * 分页查询面向客户端可见的已发布场景列表。
     *
     * @param name 场景名称关键字（模糊匹配），为 null 或空时不按名称过滤
     * @param limit 每页记录数限制
     * @param offset 偏移量
     * @return 场景持久化行列表
     */
    List<ClientSceneRow> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    /**
     * 统计满足客户端可见条件的已发布场景总数。
     *
     * @param name 场景名称关键字（模糊匹配），为 null 或空时不按名称过滤
     * @return 符合条件的场景总数
     */
    long count(@Param("name") String name);

    /**
     * 根据场景 ID 查询面向客户端可见的单个场景信息及其当前发布版本。
     *
     * @param sceneId 场景 UUID 文本
     * @return 场景信息；若不存在、未启用、已删除或无当前发布版本则返回 null
     */
    ClientSceneRow find(@Param("sceneId") String sceneId);

    /**
     * 查询指定场景版本下所有已就绪可供下载的文件清单。
     *
     * @param versionId 版本 UUID 文本
     * @return 该版本下的文件清单列表
     */
    List<ClientSceneFileRow> files(@Param("versionId") String versionId);
}
