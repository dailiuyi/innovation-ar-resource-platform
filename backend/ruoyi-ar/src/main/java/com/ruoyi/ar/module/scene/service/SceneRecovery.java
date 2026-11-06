package com.ruoyi.ar.module.scene.service;

import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.stereotype.Service;

/**
 * 场景文件启动恢复协调器。
 * <p>
 * 数据库初始化完成后先续做整场景删除，避免把删除中的文件恢复为可用；随后对账非就绪文件。
 * 磁盘盘点异常会阻止容器就绪，防止把不一致状态对外提供服务。
 */
@Service
@DependsOnDatabaseInitialization
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneRecovery implements InitializingBean {
    private final SceneService scenes;
    private final SceneFileService files;

    public SceneRecovery(SceneService scenes, SceneFileService files) {
        this.scenes = scenes;
        this.files = files;
    }

    @Override
    public void afterPropertiesSet() {
        scenes.recoverDeletions();
        files.recoverFiles();
    }
}
