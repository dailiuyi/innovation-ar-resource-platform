package com.ruoyi.ar.module.scene.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.SceneDO;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface SceneMapper extends BaseMapper<SceneDO> {

    List<SceneDO> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    long count(String name);

    int rename(@Param("id") String id, @Param("name") String name, @Param("version") long version);

    int enabled(@Param("id") String id, @Param("enabled") boolean enabled, @Param("version") long version);

    int softDelete(@Param("id") String id, @Param("version") long version);

    void audit(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName,
               @Param("action") String action, @Param("detail") String detail);

    List<AuditVO> audits(@Param("limit") int limit, @Param("offset") int offset);

    long auditCount();
}
