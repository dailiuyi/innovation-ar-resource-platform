package com.ruoyi.ar.module.scene.mapper;

import com.ruoyi.ar.module.scene.model.SceneRows;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 固定文件清单的状态、摘要与物理删除登记。 */
@Mapper
public interface SceneFileMapper {

    List<SceneRows.File> files(@Param("sceneId") String sceneId);

    SceneRows.File file(@Param("sceneId") String sceneId, @Param("fileId") String fileId);

    void startUpload(@Param("fileId") String fileId, @Param("actor") long actor, @Param("actorName") String actorName);

    SceneRows.Actor uploadActor(@Param("fileId") String fileId);

    void finishUpload(@Param("fileId") String fileId, @Param("status") String status,
                      @Param("available") boolean available, @Param("reason") String reason);

    List<String> fileIds(@Param("sceneId") String sceneId);

    void deleteFiles(@Param("sceneId") String sceneId);

    /** 扫描非 AVAILABLE 文件；删除中的场景由 SQL 排除。 */
    List<SceneRows.File> recoveryFiles(@Param("cursor") String cursor);
}
