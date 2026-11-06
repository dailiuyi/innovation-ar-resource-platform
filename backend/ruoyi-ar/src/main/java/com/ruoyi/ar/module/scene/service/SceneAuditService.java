package com.ruoyi.ar.module.scene.service;

import com.ruoyi.ar.module.scene.manager.SceneManager;
import com.ruoyi.ar.module.scene.model.AuditVO;
import com.ruoyi.ar.module.scene.model.Page;

import org.springframework.stereotype.Service;

/** 只读审计查询；历史动作标签保持原样，不随生命周期改造改写。 */
@Service
public class SceneAuditService {
    private final SceneManager manager;

    public SceneAuditService(SceneManager manager) {
        this.manager = manager;
    }

    public Page<AuditVO> audits(int limit, int offset) {
        return manager.audits(limit, offset);
    }
}
