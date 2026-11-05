package com.ruoyi.ar.module.scene.convert;

import com.ruoyi.ar.module.scene.model.SceneDO;
import com.ruoyi.ar.module.scene.model.SceneVO;
import java.util.List;
import org.mapstruct.Mapper;
import org.mapstruct.ReportingPolicy;

@Mapper(componentModel = "spring", unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface SceneConvert {
    SceneVO toVO(SceneDO source);

    List<SceneVO> toVOs(List<SceneDO> source);
}
