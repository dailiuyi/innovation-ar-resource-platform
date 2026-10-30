package com.ruoyi.ar.storage;

import java.io.IOException;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 存储装配。仅当 ar.storage.enabled=true 时创建 {@link ArtifactStorage}，当前只有本地文件系统一种实现。
 * ar.storage.root 是存储根目录，ar.storage.max-bytes 是单个文件的大小上限。
 */
@Configuration
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ArtifactStorageConfiguration {
    @Bean
    public ArtifactStorage artifactStorage(@Value("${ar.storage.root}") String root,
            @Value("${ar.storage.max-bytes}") long maxBytes) throws IOException {
        return new LocalArtifactStorage(Path.of(root), maxBytes);
    }
}
