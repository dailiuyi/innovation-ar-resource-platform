package com.ruoyi.ar;

import static org.junit.jupiter.api.Assertions.*;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/** Pure rules of the client file metadata; catalogue queries and routes are covered by the PostgreSQL gate. */
class ClientSceneServiceTest {
    @Test void contentTypeFollowsTheExtensionOnly() {
        assertEquals("application/octet-stream", ClientSceneService.contentType("standard/00.c.ply"));
        assertEquals("application/octet-stream", ClientSceneService.contentType("standard/01.4dv"));
        assertEquals("application/json", ClientSceneService.contentType("common/settings.JSON"));
        assertEquals("image/png", ClientSceneService.contentType("common/poster.png"));
        assertEquals("audio/wav", ClientSceneService.contentType("common/a.wav"));
        assertEquals("video/webm", ClientSceneService.contentType("common/p.webm"));
        assertEquals("image/jpeg", ClientSceneService.contentType("x/COVER.JPG"));
        assertEquals("image/webp", ClientSceneService.contentType("x/c.webp"));
        assertEquals("application/octet-stream", ClientSceneService.contentType("x/unknown.bin"));
        assertEquals("application/octet-stream", ClientSceneService.contentType("x/noextension"));
    }

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
