package com.ruoyi.ar.module.scene.service;

import com.ruoyi.ar.module.scene.convert.SceneConvert;
import com.ruoyi.ar.module.scene.manager.SceneManager;
import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.Page;
import com.ruoyi.ar.module.scene.model.SceneDO;
import com.ruoyi.ar.module.scene.model.SceneReq;
import com.ruoyi.ar.module.scene.model.SceneVO;
import com.ruoyi.common.utils.SecurityUtils;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/** 管理场景名称、启停和软删除；业务更新与审计在同一事务提交。 */
@Service
public class SceneService {
    private final SceneManager manager;
    private final SceneConvert convert;

    public SceneService(SceneManager manager, SceneConvert convert) {
        this.manager = manager;
        this.convert = convert;
    }

    public Page<SceneVO> list(String name, int limit, int offset) {
        Page<SceneDO> page = manager.list(name, limit, offset);
        return new Page<>(convert.toVOs(page.items()), page.total());
    }

    /** 场景软删除后仍保留审计。 */
    public Page<AuditVO> audits(int limit, int offset) {
        return manager.audits(limit, offset);
    }

    public SceneVO find(String id) {
        return convert.toVO(requireScene(manager.find(id)));
    }

    private SceneDO requireScene(SceneDO scene) {
        if (scene == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "场景不存在");
        return scene;
    }

    private void audit(String id, String action, Map<String, Object> detail) {
        manager.audit(id, action, detail, SecurityUtils.getUserId(), SecurityUtils.getUsername());
    }

    @Transactional
    public SceneVO create(SceneReq s) {
        SceneVO after = convert.toVO(requireScene(manager.create(s.name())));
        audit(after.id(), "CREATE", Map.of("after", after));
        return after;
    }

    /** 更新必须匹配 expectedVersion，过期或并发删除返回 409。 */
    @Transactional
    public SceneVO update(String id, SceneReq s) {
        if (s.expectedVersion() == null)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少 expectedVersion");
        SceneVO before = find(id);
        SceneDO updated = manager.update(id, s.name(), s.expectedVersion());
        if (updated == null)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        SceneVO after = convert.toVO(updated);
        audit(id, "UPDATE", Map.of("before", before, "after", after));
        return after;
    }

    /** 只隐藏并停用场景，不清理版本和文件；物理清理走整版删除。 */
    @Transactional
    public void delete(String id, long version) {
        SceneVO before = find(id);
        if (!manager.delete(id, version))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        audit(id, "DELETE", Map.of("before", before));
    }

    /** 启停原因写入审计。 */
    @Transactional
    public SceneVO enabled(String id, boolean enabled, long version, String reason) {
        SceneVO before = find(id);
        SceneDO updated = manager.enabled(id, enabled, version);
        if (updated == null)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        SceneVO after = convert.toVO(updated);
        audit(id, "SET_ENABLED", Map.of("before", before, "after", after, "reason", reason));
        return after;
    }
}
