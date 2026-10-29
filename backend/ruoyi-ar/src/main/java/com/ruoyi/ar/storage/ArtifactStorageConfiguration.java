package com.ruoyi.ar.storage;

import java.io.IOException;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnProperty(name = "ar.storage.enabled", havingValue = "true")
public class ArtifactStorageConfiguration {
    @Bean
    public ArtifactStorage artifactStorage(@Value("${ar.storage.root}") String root,
            @Value("${ar.storage.max-bytes}") long maxBytes) throws IOException {
        return new LocalArtifactStorage(Path.of(root), maxBytes);
    }
}
