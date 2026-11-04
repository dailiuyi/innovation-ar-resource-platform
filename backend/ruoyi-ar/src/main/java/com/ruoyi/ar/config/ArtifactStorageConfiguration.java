package com.ruoyi.ar.config;

import com.ruoyi.ar.storage.ArtifactStorage;
import com.ruoyi.ar.storage.LocalArtifactStorage;

import java.io.IOException;
import java.nio.file.Path;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 仅在启用存储时装配本地文件存储。 */
@Configuration
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ArtifactStorageConfiguration {
    @Bean
    public ArtifactStorage artifactStorage(@Value("${ar.storage.root}") String root,
                                           @Value("${ar.storage.max-bytes}") long maxBytes) throws IOException {
        return new LocalArtifactStorage(Path.of(root), maxBytes);
    }
}
