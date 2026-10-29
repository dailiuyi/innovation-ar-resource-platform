package com.ruoyi.ar;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.*;

@Mapper
public interface SceneMapper {
    String COLUMNS = "id::text as id,name,enabled,lock_version as \"lockVersion\",created_at as \"createdAt\",updated_at as \"updatedAt\"";
    @Select("select " + COLUMNS + " from ar_scene where deleted_at is null and id=cast(#{id} as uuid)")
    Map<String,Object> find(String id);
    @Select("select " + COLUMNS + " from ar_scene where deleted_at is null and position(lower(#{name}) in lower(name))>0 order by created_at desc,id limit #{limit} offset #{offset}")
    List<Map<String,Object>> list(@Param("name") String name,@Param("limit") int limit,@Param("offset") int offset);
    @Select("select count(*) from ar_scene where deleted_at is null and position(lower(#{name}) in lower(name))>0")
    long count(String name);
    @Insert("insert into ar_scene(id,name) values(cast(#{id} as uuid),#{s.name})")
    void insert(@Param("id") String id,@Param("s") SceneInput input);
    @Update("update ar_scene set name=#{s.name},lock_version=lock_version+1,updated_at=now() where deleted_at is null and id=cast(#{id} as uuid) and lock_version=#{s.expectedVersion}")
    int update(@Param("id") String id,@Param("s") SceneInput input);
    @Update("update ar_scene set enabled=#{enabled},lock_version=lock_version+1,updated_at=now() where deleted_at is null and id=cast(#{id} as uuid) and lock_version=#{version}")
    int enabled(@Param("id") String id,@Param("enabled") boolean enabled,@Param("version") long version);
    @Update("update ar_scene set deleted_at=now(),enabled=false,lock_version=lock_version+1,updated_at=now() where id=cast(#{id} as uuid) and deleted_at is null and lock_version=#{version}")
    int delete(@Param("id") String id,@Param("version") long version);
    @Insert("insert into ar_audit(scene_id,actor_id,actor_name,action,detail) values(cast(#{id} as uuid),#{actor},#{actorName},#{action},cast(#{detail} as jsonb))")
    void audit(@Param("id") String id,@Param("actor") long actor,@Param("actorName") String actorName,@Param("action") String action,@Param("detail") String detail);
    @Select("select id,scene_id::text as \"sceneId\",actor_id as \"actorId\",actor_name as \"actorName\",action,detail::text as detail,created_at as \"createdAt\" from ar_audit order by id desc limit #{limit} offset #{offset}")
    List<Map<String,Object>> audits(@Param("limit") int limit,@Param("offset") int offset);
    @Select("select count(*) from ar_audit") long auditCount();
}
