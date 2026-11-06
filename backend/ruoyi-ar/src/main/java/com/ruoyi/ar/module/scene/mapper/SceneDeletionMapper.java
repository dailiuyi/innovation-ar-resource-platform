package com.ruoyi.ar.module.scene.mapper;

import com.ruoyi.ar.module.scene.model.SceneRows;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 整场景删除意图、失败原因和最小幂等回执。 */
@Mapper
public interface SceneDeletionMapper {

    boolean deleting(@Param("id") String id);

    boolean deletionCompleted(@Param("id") String id);

    boolean deletionExists(@Param("id") String id);

    /** 场景创建键已被删除回执占用时不得再创建。 */
    boolean deletionRequestKeyExists(@Param("requestKey") String requestKey);

    /** 软删除场景仍占用创建键时不得再创建。 */
    boolean deletedSceneRequestKeyExists(@Param("requestKey") String requestKey);

    void requestDeletion(@Param("id") String id, @Param("requestKey") String requestKey,
                         @Param("actor") long actor, @Param("actorName") String actorName);

    void retryDeletion(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName);

    SceneRows.Actor deletionActor(@Param("id") String id);

    void failDeletion(@Param("id") String id, @Param("reason") String reason);

    void completeDeletion(@Param("id") String id);

    List<String> pendingDeletions();
}
