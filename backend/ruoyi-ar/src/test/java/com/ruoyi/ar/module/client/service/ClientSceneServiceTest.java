package com.ruoyi.ar.module.client.service;

import static org.junit.jupiter.api.Assertions.*;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class ClientSceneServiceTest {
    @Test void downloadPathKeepsExtensionAndRoundTripsTheBasename() {
        String name = "第 1段+a,b[1]#2.c.ply";
        String path = ClientSceneService.downloadPath("s", "v", "f", name);
        assertTrue(path.startsWith("/api/v1/client/scenes/s/versions/v/files/f/content/"));
        assertTrue(path.endsWith(".c.ply"));
        String last = path.substring(path.lastIndexOf('/') + 1);
        assertEquals(-1, last.indexOf('+'));
        assertEquals(-1, last.indexOf(','));
        assertEquals(name, URI.create(path).getPath().substring(URI.create(path).getPath().lastIndexOf('/') + 1));
        assertEquals(name, java.net.URLDecoder.decode(last, StandardCharsets.UTF_8));
    }
}
