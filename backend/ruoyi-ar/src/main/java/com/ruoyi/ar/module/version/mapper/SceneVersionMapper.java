package com.ruoyi.ar.module.version.mapper;

import com.ruoyi.ar.module.version.model.VersionRows;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 版本元数据、汇总、发布与业务审计；文件及删除回执分别由专用 Mapper 维护。 */
@Mapper
public interface SceneVersionMapper {

    String lockScene(String id);

    String sceneOf(String id);

    boolean published(String id);

    void audit(@Param("sceneId") String sceneId, @Param("actor") long actor, @Param("actorName") String actorName,
               @Param("action") String action, @Param("detail") String detail);

    VersionRows.Summary summary(String id);

    List<VersionRows.Summary> list(@Param("sceneId") String sceneId, @Param("limit") int limit, @Param("offset") int offset);

    long count(String id);

    VersionRows.Scene sceneState(String id);

    VersionRows.Published publishedVersion(String id);

    String existingRequest(@Param("sceneId") String sceneId, @Param("requestKey") String requestKey);

    int nextVersionNo(String id);

    void insertVersion(@Param("id") String id, @Param("sceneId") String sceneId, @Param("versionNo") int versionNo,
                       @Param("requestKey") String requestKey, @Param("description") String description,
                       @Param("actor") long actor, @Param("actorName") String actorName);

    Boolean sameDescription(@Param("id") String id, @Param("description") String description);

    int edit(@Param("id") String id, @Param("description") String description, @Param("expectedVersion") long expectedVersion);

    int publish(@Param("sceneId") String sceneId, @Param("versionId") String versionId, @Param("actor") long actor,
                @Param("actorName") String actorName, @Param("expectedVersion") long expectedVersion);

    boolean versionExists(String id);

    VersionRows.Version version(String id);

    void deleteVersion(String id);

    String clientPublishedVersion(@Param("sceneId") String sceneId, @Param("versionId") String versionId);

}
