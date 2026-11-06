package com.ruoyi.ar.module.scene.mapper;

import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.SceneRows;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 场景主记录、固定文件清单登记与审计日志数据访问。
 * <p>
 * 场景、文件与删除回执分别由 SceneMapper、SceneFileMapper、SceneDeletionMapper 负责；
 * 事务边界和文件 IO 由 Service 层控制。
 */
@Mapper
public interface SceneMapper {

    List<SceneRows.Summary> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    long count(@Param("name") String name);

    SceneRows.Summary summary(@Param("id") String id);

    SceneRows.Summary summaryByRequestKey(@Param("requestKey") String requestKey);

    SceneRows.Scene scene(@Param("id") String id);

    boolean sceneExists(@Param("id") String id);

    String lockScene(@Param("id") String id);

    /** 新建场景；request_key 冲突时不插入，返回 0。 */
    int insertScene(@Param("id") String id, @Param("name") String name, @Param("description") String description,
                    @Param("requestKey") String requestKey);

    /** 在同一事务内登记整份固定文件清单。 */
    void insertFiles(@Param("files") List<SceneRows.NewFile> files);

    int edit(@Param("id") String id, @Param("name") String name, @Param("description") String description,
             @Param("version") long version);

    int enabled(@Param("id") String id, @Param("enabled") boolean enabled, @Param("version") long version);

    /** 删除成功后的软删除标记；文件行与删除回执由调用方在同一事务处理。 */
    int markDeleted(@Param("id") String id);

    void audit(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName,
               @Param("action") String action, @Param("detail") String detail);

    List<AuditVO> audits(@Param("limit") int limit, @Param("offset") int offset);

    long auditCount();
}
