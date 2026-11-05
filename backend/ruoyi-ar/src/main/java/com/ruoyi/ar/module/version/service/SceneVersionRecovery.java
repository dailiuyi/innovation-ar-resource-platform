package com.ruoyi.ar.module.version.service;

import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.stereotype.Service;

/** 数据库初始化后同步续做删除，再对账文件；恢复失败时拒绝完成启动。 */
@Service
@DependsOnDatabaseInitialization
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class SceneVersionRecovery implements InitializingBean {

    private final SceneVersionService versions;
    private final SceneVersionFileService files;

    public SceneVersionRecovery(SceneVersionService versions, SceneVersionFileService files) {
        this.versions = versions;
        this.files = files;
    }

    @Override
    public void afterPropertiesSet() {
        versions.recoverDeletions();
        files.recoverFiles();
    }
}
