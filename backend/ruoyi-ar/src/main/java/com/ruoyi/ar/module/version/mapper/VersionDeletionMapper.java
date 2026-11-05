package com.ruoyi.ar.module.version.mapper;

import com.ruoyi.ar.module.version.model.VersionRows;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 整版删除意图、重试与幂等回执；不执行文件或版本行删除。 */
@Mapper
public interface VersionDeletionMapper {
    boolean deleting(String id);

    boolean deletedRequest(@Param("sceneId") String sceneId, @Param("requestKey") String requestKey);

    boolean deletionCompleted(String id);

    boolean deletionExists(String id);

    void requestDeletion(@Param("id") String id, @Param("sceneId") String sceneId, @Param("requestKey") String requestKey,
                         @Param("actor") long actor, @Param("actorName") String actorName);

    void retryDeletion(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName);

    VersionRows.Actor deletionActor(String id);

    void failDeletion(@Param("id") String id, @Param("reason") String reason);

    void completeDeletion(String id);

    List<String> pendingDeletions();
}
