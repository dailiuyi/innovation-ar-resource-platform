package com.ruoyi.ar.module.client.mapper;

import com.ruoyi.ar.module.client.model.ClientSceneFileRow;
import com.ruoyi.ar.module.client.model.ClientSceneRow;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 发布目录查询；列表、计数和详情共用 XML 中的可见性条件。 */
@Mapper
public interface ClientSceneMapper {
    List<ClientSceneRow> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    long count(@Param("name") String name);

    ClientSceneRow find(@Param("sceneId") String sceneId);

    List<ClientSceneFileRow> files(@Param("versionId") String versionId);
}
