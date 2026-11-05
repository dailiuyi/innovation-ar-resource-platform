package com.ruoyi.ar.module.version.service;

import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.stereotype.Service;

/**
 * 场景成品版本与文件启动恢复协调器。
 * <p>
 * 服务启动阶段在数据库初始化完成（{@link DependsOnDatabaseInitialization}）后自动触发执行。
 * 执行顺序：
 * <ol>
 *   <li>优先调用 {@link SceneVersionService#recoverDeletions()}，接续推进上次因服务崩溃未完结的整版本物理删除与对账回执；</li>
 *   <li>随后调用 {@link SceneVersionFileService#recoverFiles()}，扫描并对齐处于中间状态或暂存态的文件记录。</li>
 * </ol>
 * 契约规范：若启动恢复阶段校验出严重不一致或磁盘异常将抛出异常并阻止 Spring 容器继续就绪，防止脏数据对外提供服务。
 */
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
