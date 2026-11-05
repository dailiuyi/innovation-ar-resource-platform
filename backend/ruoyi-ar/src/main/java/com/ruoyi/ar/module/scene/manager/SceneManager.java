package com.ruoyi.ar.module.scene.manager;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.ar.module.scene.mapper.SceneMapper;
import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.model.SceneDO;

import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Component;

/**
 * 场景域持久化聚合管理者。
 * <p>
 * 组合 {@link SceneMapper} 的原生 SQL 与 MyBatis-Plus 基础操作，
 * 负责场景实体、分页查询以及 JSON 序列化审计日志的存取。业务事务由 Service 层控制。
 */
@Component
public class SceneManager {
    private final SceneMapper mapper;
    private final ObjectMapper json;

    public SceneManager(SceneMapper mapper, ObjectMapper json) {
        this.mapper = mapper;
        this.json = json;
    }

    /**
     * 查询场景列表并封装分页模型。
     *
     * @param name 场景名称模糊过滤字串
     * @param limit 每页记录数限制
     * @param offset 偏移量
     * @return 包含持久化对象列表与总数的分页包装
     */
    public Page<SceneDO> list(String name, int limit, int offset) {
        return new Page<>(mapper.list(name, limit, offset), mapper.count(name));
    }

    /**
     * 查询场景审计日志列表并封装分页模型。
     *
     * @param limit 每页记录数限制
     * @param offset 偏移量
     * @return 包含审计视图列表与总数的分页包装
     */
    public Page<AuditVO> audits(int limit, int offset) {
        return new Page<>(mapper.audits(limit, offset), mapper.auditCount());
    }

    /**
     * 根据 UUID 字符串查询单个场景实体。
     *
     * @param id 场景 UUID 文本
     * @return 场景持久化对象；不存在或已被逻辑删除时返回 null
     */
    public SceneDO find(String id) {
        return mapper.selectById(UUID.fromString(id));
    }

    /**
     * 插入新场景记录（生成随机 UUID，初始版本号 0，默认启用）。
     *
     * @param name 场景名称
     * @return 插入成功后重新回查的最新场景持久化对象
     */
    public SceneDO create(String name) {
        var scene = new SceneDO();
        scene.setId(UUID.randomUUID());
        scene.setName(name);
        mapper.insert(scene);
        return mapper.selectById(scene.getId());
    }

    /**
     * 带乐观锁版本校验的重命名操作。
     *
     * @param id 场景 UUID 文本
     * @param name 新名称
     * @param version 预期的 lock_version
     * @return 更新成功返回最新的场景实体；受影响行数不为 1 时返回 null 表示乐观锁冲突
     */
    public SceneDO update(String id, String name, long version) {
        return mapper.rename(id, name, version) == 1 ? find(id) : null;
    }

    /**
     * 带乐观锁版本校验的启停切换操作。
     *
     * @param id 场景 UUID 文本
     * @param enabled 新的启停状态
     * @param version 预期的 lock_version
     * @return 更新成功返回最新的场景实体；受影响行数不为 1 时返回 null 表示乐观锁冲突
     */
    public SceneDO enabled(String id, boolean enabled, long version) {
        return mapper.enabled(id, enabled, version) == 1 ? find(id) : null;
    }

    /**
     * 带乐观锁版本校验的逻辑软删除操作。
     *
     * @param id 场景 UUID 文本
     * @param version 预期的 lock_version
     * @return 成功软删除一行返回 true；版本不匹配或已删除返回 false
     */
    public boolean delete(String id, long version) {
        return mapper.softDelete(id, version) == 1;
    }

    /**
     * 序列化并写入场景操作审计日志。
     *
     * @param id 场景 UUID 文本
     * @param action 操作动作类型（CREATE、UPDATE、SET_ENABLED、DELETE 等）
     * @param detail 结构化详情键值 Map，将序列化为 JSON 字符串入库
     * @param actor 操作人用户 ID
     * @param actorName 操作人用户名
     */
    public void audit(String id, String action, Map<String, Object> detail, long actor, String actorName) {
        try {
            mapper.audit(id, actor, actorName, action, json.writeValueAsString(detail));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Audit serialization failed", e);
        }
    }
}
