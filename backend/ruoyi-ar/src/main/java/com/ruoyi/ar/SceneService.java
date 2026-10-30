package com.ruoyi.ar;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.common.utils.SecurityUtils;

import java.util.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

/**
 * 场景自身（名称、启用状态、软删除）的业务逻辑。每个写操作都在同一事务内完成：
 * 先读修改前的快照，再按乐观锁更新，最后写审计，审计里保存修改前后的完整快照。
 */
@Service
public class SceneService {
    private final SceneMapper mapper;
    private final ObjectMapper json;

    public SceneService(SceneMapper mapper, ObjectMapper json) {
        this.mapper = mapper;
        this.json = json;
    }

    /**
     * 查询未删除的场景，不存在抛 404。
     */
    public Map<String, Object> find(String id) {
        Map<String, Object> row = mapper.find(id);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在");
        return row;
    }

    /**
     * 抛出 400，供 expectedVersion 缺失这类请求错误使用。
     */
    private void invalid(String message) {
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    /**
     * 以当前登录用户的身份写审计；序列化失败属于程序错误，直接抛出。
     */
    private void audit(String id, String action, Map<String, Object> detail) {
        try {
            mapper.audit(id, SecurityUtils.getUserId(), SecurityUtils.getUsername(), action, json.writeValueAsString(detail));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Audit serialization failed", e);
        }
    }

    /**
     * 新建场景；乐观锁版本号由数据库默认值 0 起算。
     */
    @Transactional
    public Map<String, Object> create(SceneInput s) {
        String id = UUID.randomUUID().toString();
        mapper.insert(id, s);
        var after = find(id);
        audit(id, "CREATE", Map.of("after", after));
        return after;
    }

    /**
     * 重命名。update 影响 0 行说明 expectedVersion 已过期（或场景刚被删除），返回 409 让用户刷新。
     */
    @Transactional
    public Map<String, Object> update(String id, SceneInput s) {
        if (s.expectedVersion() == null) invalid("缺少 expectedVersion");
        var before = find(id);
        if (mapper.update(id, s) != 1)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        var after = find(id);
        audit(id, "UPDATE", Map.of("before", before, "after", after));
        return after;
    }

    /**
     * 软删除。同样以 expectedVersion 防止基于过期页面误删。
     */
    @Transactional
    public void delete(String id, long version) {
        var before = find(id);
        if (mapper.delete(id, version) != 1)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        audit(id, "DELETE", Map.of("before", before));
    }

    /**
     * 启用或停用；reason 写入审计。
     */
    @Transactional
    public Map<String, Object> enabled(String id, boolean enabled, long version, String reason) {
        var before = find(id);
        if (mapper.enabled(id, enabled, version) != 1)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        var after = find(id);
        audit(id, "SET_ENABLED", Map.of("before", before, "after", after, "reason", reason));
        return after;
    }
}
