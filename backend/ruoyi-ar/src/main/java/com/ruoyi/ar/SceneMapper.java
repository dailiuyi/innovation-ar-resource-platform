package com.ruoyi.ar;

import java.util.List;
import java.util.Map;

import org.apache.ibatis.annotations.*;

/**
 * ar_scene / ar_audit 的 MyBatis 注解映射（PostgreSQL 语法）。
 * 所有场景查询都带 deleted_at is null，即已软删除的场景对外不可见；
 * 写操作用 lock_version 做乐观锁，返回受影响行数，0 表示版本已变化，由 SceneService 转成 409。
 */
@Mapper
public interface SceneMapper {
    /**
     * 场景对外字段；id 转 text，驼峰别名与 API 字段一致。
     */
    String COLUMNS = "id::text as id,name,enabled,lock_version as \"lockVersion\",created_at as \"createdAt\",updated_at as \"updatedAt\"";

    /**
     * 按 id 查单个未删除的场景，没有则返回 null。
     */
    @Select("select " + COLUMNS + " from ar_scene where deleted_at is null and id=cast(#{id} as uuid)")
    Map<String, Object> find(String id);

    /**
     * 名称过滤用 position(lower() in lower())：大小写不敏感，且不把 % 和 _ 当通配符。
     */
    @Select("select " + COLUMNS + " from ar_scene where deleted_at is null and position(lower(#{name}) in lower(name))>0 order by created_at desc,id limit #{limit} offset #{offset}")
    List<Map<String, Object>> list(@Param("name") String name, @Param("limit") int limit, @Param("offset") int offset);

    @Select("select count(*) from ar_scene where deleted_at is null and position(lower(#{name}) in lower(name))>0")
    long count(String name);

    /**
     * 新建场景；其余列（enabled、lock_version 等）取表默认值。
     */
    @Insert("insert into ar_scene(id,name) values(cast(#{id} as uuid),#{s.name})")
    void insert(@Param("id") String id, @Param("s") SceneInput input);

    /**
     * 重命名，lock_version 与 expectedVersion 相同才更新，并使版本号加 1。
     */
    @Update("update ar_scene set name=#{s.name},lock_version=lock_version+1,updated_at=now() where deleted_at is null and id=cast(#{id} as uuid) and lock_version=#{s.expectedVersion}")
    int update(@Param("id") String id, @Param("s") SceneInput input);

    /**
     * 启停，同样做乐观锁校验。
     */
    @Update("update ar_scene set enabled=#{enabled},lock_version=lock_version+1,updated_at=now() where deleted_at is null and id=cast(#{id} as uuid) and lock_version=#{version}")
    int enabled(@Param("id") String id, @Param("enabled") boolean enabled, @Param("version") long version);

    /**
     * 软删除：写 deleted_at、置为停用；不物理删除行，也不会清理该场景下的版本文件。
     */
    @Update("update ar_scene set deleted_at=now(),enabled=false,lock_version=lock_version+1,updated_at=now() where id=cast(#{id} as uuid) and deleted_at is null and lock_version=#{version}")
    int delete(@Param("id") String id, @Param("version") long version);

    /**
     * 写一条审计；detail 是 JSON 字符串，入库时转为 jsonb。
     */
    @Insert("insert into ar_audit(scene_id,actor_id,actor_name,action,detail) values(cast(#{id} as uuid),#{actor},#{actorName},#{action},cast(#{detail} as jsonb))")
    void audit(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName, @Param("action") String action, @Param("detail") String detail);

    /**
     * 审计日志分页，id 倒序。
     */
    @Select("select id,scene_id::text as \"sceneId\",actor_id as \"actorId\",actor_name as \"actorName\",action,detail::text as detail,created_at as \"createdAt\" from ar_audit order by id desc limit #{limit} offset #{offset}")
    List<Map<String, Object>> audits(@Param("limit") int limit, @Param("offset") int offset);

    @Select("select count(*) from ar_audit")
    long auditCount();
}
