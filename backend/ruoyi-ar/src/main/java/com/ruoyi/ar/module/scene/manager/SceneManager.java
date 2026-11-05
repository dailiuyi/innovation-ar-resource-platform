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

/** 组合场景持久化操作；业务判断和事务由 Service 负责。 */
@Component
public class SceneManager {
    private final SceneMapper mapper;
    private final ObjectMapper json;

    public SceneManager(SceneMapper mapper, ObjectMapper json) {
        this.mapper = mapper;
        this.json = json;
    }

    public Page<SceneDO> list(String name, int limit, int offset) {
        return new Page<>(mapper.list(name, limit, offset), mapper.count(name));
    }

    public Page<AuditVO> audits(int limit, int offset) {
        return new Page<>(mapper.audits(limit, offset), mapper.auditCount());
    }

    public SceneDO find(String id) {
        return mapper.selectById(UUID.fromString(id));
    }

    public SceneDO create(String name) {
        var scene = new SceneDO();
        scene.setId(UUID.randomUUID());
        scene.setName(name);
        mapper.insert(scene);
        return mapper.selectById(scene.getId());
    }

    public SceneDO update(String id, String name, long version) {
        return mapper.rename(id, name, version) == 1 ? find(id) : null;
    }

    public SceneDO enabled(String id, boolean enabled, long version) {
        return mapper.enabled(id, enabled, version) == 1 ? find(id) : null;
    }

    public boolean delete(String id, long version) {
        return mapper.softDelete(id, version) == 1;
    }

    public void audit(String id, String action, Map<String, Object> detail, long actor, String actorName) {
        try {
            mapper.audit(id, actor, actorName, action, json.writeValueAsString(detail));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Audit serialization failed", e);
        }
    }
}
