package com.ruoyi.ar.module.client.mapper;

import com.ruoyi.ar.module.client.model.ClientSceneFileRow;
import com.ruoyi.ar.module.client.model.ClientSceneRow;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 匿名分发查询；列表、计数、详情和文件清单共用 XML 中的场景可见性条件。 */
@Mapper
public interface ClientSceneMapper {
    List<ClientSceneRow> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    long count(@Param("name") String name);

    ClientSceneRow find(@Param("sceneId") String sceneId);

    List<ClientSceneFileRow> files(@Param("sceneId") String sceneId);
}
