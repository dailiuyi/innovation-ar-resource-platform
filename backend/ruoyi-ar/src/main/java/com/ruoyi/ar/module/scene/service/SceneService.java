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

/**
 * 场景域核心业务服务。
 * <p>
 * 负责场景元数据（名称、启停状态、逻辑删除）的变更控制与乐观锁校验。
 * 契约规范：所有写操作均在单事务中联动写入结构化审计日志（{@code ar_scene_audit}），
 * 并确保并发更新时乐观锁冲突以 409 CONFLICT 明确抛出。
 */
@Service
public class SceneService {
    private final SceneManager manager;
    private final SceneConvert convert;

    public SceneService(SceneManager manager, SceneConvert convert) {
        this.manager = manager;
        this.convert = convert;
    }

    /**
     * 分页查询场景列表并转换为视图对象。
     *
     * @param name 名称模糊过滤关键字（为空不过滤）
     * @param limit 每页条数
     * @param offset 偏移量
     * @return 包含 {@link SceneVO} 列表和满足条件总数的分页包装类
     */
    public Page<SceneVO> list(String name, int limit, int offset) {
        Page<SceneDO> page = manager.list(name, limit, offset);
        return new Page<>(convert.toVOs(page.items()), page.total());
    }

    /**
     * 分页查询操作审计日志。
     * <p>
     * 记录场景的 CREATE、UPDATE、SET_ENABLED、DELETE 等动作，场景软删除后审计日志永久保留。
     *
     * @param limit 每页数量
     * @param offset 偏移量
     * @return 包含 {@link AuditVO} 列表和总数的分页包装类
     */
    public Page<AuditVO> audits(int limit, int offset) {
        return manager.audits(limit, offset);
    }

    /**
     * 根据 UUID 字符串查询单个未删除的场景详情。
     *
     * @param id 场景 UUID 文本
     * @return 场景视图对象
     * @throws ResponseStatusException 若不存在或已软删除则抛出 404
     */
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

    /**
     * 创建新场景并在同一事务中记录 CREATE 审计。
     *
     * @param s 包含名称的新建请求
     * @return 刚创建的场景视图
     */
    @Transactional
    public SceneVO create(SceneReq s) {
        SceneVO after = convert.toVO(requireScene(manager.create(s.name())));
        audit(after.id(), "CREATE", Map.of("after", after));
        return after;
    }

    /**
     * 重命名场景并在同一事务中记录 UPDATE 审计。
     *
     * @param id 场景 UUID 文本
     * @param s 请求体（包含新名称和非空 expectedVersion）
     * @return 更新后的场景视图
     * @throws ResponseStatusException 缺少版本号报 400；版本不匹配或已软删除报 409
     */
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

    /**
     * 软删除场景并在同一事务中记录 DELETE 审计。
     * <p>
     * 仅置 soft-delete 标记和停用状态，保留关联的历史版本与文件行；物理清理通过版本物理删除完成。
     *
     * @param id 场景 UUID 文本
     * @param version 预期的乐观锁版本号
     * @throws ResponseStatusException 版本不匹配或已变动时报 409
     */
    @Transactional
    public void delete(String id, long version) {
        SceneVO before = find(id);
        if (!manager.delete(id, version))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "场景已被修改，请刷新后重试");
        audit(id, "DELETE", Map.of("before", before));
    }

    /**
     * 启停场景并在同一事务中记录 SET_ENABLED 审计。
     *
     * @param id 场景 UUID 文本
     * @param enabled 是否启用
     * @param version 预期的乐观锁版本号
     * @param reason 操作原因（非空，存入审计详情）
     * @return 更新后的场景视图
     * @throws ResponseStatusException 乐观锁冲突报 409
     */
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
