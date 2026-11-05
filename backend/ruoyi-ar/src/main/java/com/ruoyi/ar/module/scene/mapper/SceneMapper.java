package com.ruoyi.ar.module.scene.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.SceneDO;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 场景与审计日志数据访问 Mapper。
 * <p>
 * 继承自 MyBatis-Plus {@link BaseMapper} 获取基本 CRUD 能力，
 * 扩展场景自定义条件分页、乐观锁更新、逻辑软删除与审计入库的原生 SQL 映射。
 */
@Mapper
public interface SceneMapper extends BaseMapper<SceneDO> {

    /**
     * 条件分页查询场景列表（按创建时间降序）。
     *
     * @param name 场景名称模糊过滤字串（为 null 或空串不过滤）
     * @param limit 每页记录数限制
     * @param offset 偏移量
     * @return 场景持久化对象列表
     */
    List<SceneDO> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    /**
     * 统计满足条件的未软删除场景总数。
     *
     * @param name 场景名称模糊过滤字串
     * @return 匹配记录总数
     */
    long count(String name);

    /**
     * 条件更新场景名称并递增乐观锁版本号。
     *
     * @param id 场景 UUID 文本
     * @param name 新名称
     * @param version 预期的 lock_version
     * @return 成功更新的行数（1 表示成功，0 表示乐观锁冲突或记录已软删除）
     */
    int rename(@Param("id") String id, @Param("name") String name, @Param("version") long version);

    /**
     * 条件切换场景启停状态并递增乐观锁版本号。
     *
     * @param id 场景 UUID 文本
     * @param enabled 是否启用
     * @param version 预期的 lock_version
     * @return 成功更新的行数（1 表示成功，0 表示乐观锁冲突或记录已软删除）
     */
    int enabled(@Param("id") String id, @Param("enabled") boolean enabled, @Param("version") long version);

    /**
     * 逻辑软删除场景（设置 deleted_at 时间戳并停用）同时校验乐观锁版本号。
     *
     * @param id 场景 UUID 文本
     * @param version 预期的 lock_version
     * @return 成功软删除的行数（1 表示成功，0 表示已被删除或版本冲突）
     */
    int softDelete(@Param("id") String id, @Param("version") long version);

    /**
     * 插入场景操作审计日志。
     *
     * @param id 关联的场景 UUID 文本
     * @param actor 操作人用户 ID
     * @param actorName 操作人用户名
     * @param action 操作动作类型（CREATE、UPDATE、SET_ENABLED、DELETE 等）
     * @param detail JSON 序列化格式的详情文本
     */
    void audit(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName,
               @Param("action") String action, @Param("detail") String detail);

    /**
     * 分页查询审计日志（按主键自增 ID 降序）。
     *
     * @param limit 每页记录数限制
     * @param offset 偏移量
     * @return 审计日志视图列表
     */
    List<AuditVO> audits(@Param("limit") int limit, @Param("offset") int offset);

    /**
     * 统计全局审计日志总条数。
     *
     * @return 审计日志总条数
     */
    long auditCount();
}
