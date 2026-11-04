package com.ruoyi.ar.service;

import com.ruoyi.ar.dto.SceneInput;
import com.ruoyi.ar.mapper.SceneMapper;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.common.utils.SecurityUtils;

import java.util.*;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

/** 管理场景名称、启停和软删除；业务更新与审计在同一事务提交。 */
@Service
public class SceneService {
    private final SceneMapper mapper;
    private final ObjectMapper json;

    public SceneService(SceneMapper mapper, ObjectMapper json) {
        this.mapper = mapper;
        this.json = json;
    }

    public Map<String, Object> list(String name, int limit, int offset) {
        return Map.of("items", mapper.list(name, limit, offset), "total", mapper.count(name));
    }

    /** 场景软删除后仍保留审计。 */
    public Map<String, Object> audits(int limit, int offset) {
        return Map.of("items", mapper.audits(limit, offset), "total", mapper.auditCount());
    }

    public Map<String, Object> find(String id) {
        Map<String, Object> row = mapper.find(id);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在");
        return row;
    }

    private void invalid(String message) {
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    private void audit(String id, String action, Map<String, Object> detail) {
        try {
            mapper.audit(id, SecurityUtils.getUserId(), SecurityUtils.getUsername(), action, json.writeValueAsString(detail));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Audit serialization failed", e);
        }
    }

    @Transactional
    public Map<String, Object> create(SceneInput s) {
        String id = UUID.randomUUID().toString();
        mapper.insert(id, s);
        var after = find(id);
        audit(id, "CREATE", Map.of("after", after));
        return after;
    }

    /** 更新必须匹配 expectedVersion，过期或并发删除返回 409。 */
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

    /** 只隐藏并停用场景，不清理版本和文件；物理清理走整版删除。 */
    @Transactional
    public void delete(String id, long version) {
        var before = find(id);
        if (mapper.delete(id, version) != 1)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        audit(id, "DELETE", Map.of("before", before));
    }

    /** 启停原因写入审计。 */
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
