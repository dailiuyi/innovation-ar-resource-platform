package com.ruoyi.ar.config;

import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.ar.storage.LocalArtifactStorage;

import java.io.IOException;
import java.nio.file.Path;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 物理存储基础设施自动化装配配置类。
 * <p>
 * 仅当配置项 {@code ar.storage.enabled=true} 时被激活加载，
 * 负责从环境变量或配置文件注入存储根目录与单文件最大尺寸，
 * 实例化 {@link LocalArtifactStorage} 并作为 {@link ArtifactStorage} 注册至 Spring 容器。
 */
@Configuration
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ArtifactStorageConfiguration {
    /**
     * 创建并注册本地卷存储单例 Bean。
     *
     * @param root 存储物理根路径（对应配置 {@code ar.storage.root}）
     * @param maxBytes 单文件最大字节上限（对应配置 {@code ar.storage.max-bytes}）
     * @return 初始化的本地存储实例
     * @throws IOException 当存储目录初始化或软链接安全校验失败时抛出
     */
    @Bean
    public ArtifactStorage artifactStorage(@Value("${ar.storage.root}") String root,
                                           @Value("${ar.storage.max-bytes}") long maxBytes) throws IOException {
        return new LocalArtifactStorage(Path.of(root), maxBytes);
    }
}
