package com.ruoyi.ar.module.scene.convert;

import com.ruoyi.ar.module.scene.model.SceneDO;
import com.ruoyi.ar.module.scene.model.SceneVO;
import java.util.List;
import org.mapstruct.Mapper;
import org.mapstruct.ReportingPolicy;

/**
 * 场景实体与视图对象转换器（基于 MapStruct 编译期生成）。
 */
@Mapper(componentModel = "spring", unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface SceneConvert {
    /**
     * 将场景持久化实体转换为对外的视图对象。
     *
     * @param source 场景持久化对象
     * @return 场景视图对象
     */
    SceneVO toVO(SceneDO source);

    /**
     * 批量将场景持久化实体列表转换为视图对象列表。
     *
     * @param source 场景持久化对象列表
     * @return 场景视图对象列表
     */
    List<SceneVO> toVOs(List<SceneDO> source);
}
