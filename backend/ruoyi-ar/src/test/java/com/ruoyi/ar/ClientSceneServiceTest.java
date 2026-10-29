package com.ruoyi.ar;

import static org.junit.jupiter.api.Assertions.*;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/** Pure rules of the client file URLs; catalogue queries and routes are covered by the PostgreSQL gate. */
class ClientSceneServiceTest {
    private static final SceneResourceDescriptor DESCRIPTOR = SceneResourceDescriptor.parse("""
        {"formatVersion":1,"defaultVariant":"standard","transform":{"position":[0,0,0],"rotation":[0,0,0],"scale":[1,1,1]},
         "settings":"common/settings.json","poster":"common/poster.png","audio":"common/a.wav","preview":"common/p.webm",
         "variants":[{"id":"standard","name":"标准","format":"4dv-compressed-ply",
           "segments":[{"path":"standard/00.c.ply","startSeconds":0,"durationSeconds":5},
                       {"path":"standard/01.4dv","startSeconds":5,"durationSeconds":3}]}]}""");

    @Test void contentTypeFollowsRoleThenExtension() {
        var types = new ClientSceneService.ContentTypes(DESCRIPTOR);
        assertEquals("application/octet-stream", types.of("standard/00.c.ply"));
        assertEquals("application/octet-stream", types.of("standard/01.4dv"));
        assertEquals("application/json", types.of("common/settings.json"));
        assertEquals("image/png", types.of("common/poster.png"));
        assertEquals("audio/wav", types.of("common/a.wav"));
        assertEquals("video/webm", types.of("common/p.webm"));
        assertEquals("image/jpeg", types.of("x/COVER.JPG"));
        assertEquals("image/webp", types.of("x/c.webp"));
        assertEquals("application/octet-stream", types.of("x/unknown.bin"));
        assertEquals("application/octet-stream", types.of("x/noextension"));
        // A model path keeps its role even if it carries a media-looking extension.
        var odd = SceneResourceDescriptor.parse("""
            {"formatVersion":1,"defaultVariant":"s","transform":{"position":[0,0,0],"rotation":[0,0,0],"scale":[1,1,1]},
             "settings":"s.json","variants":[{"id":"s","name":"s","format":"4dv-compressed-ply",
               "segments":[{"path":"m.png","startSeconds":0,"durationSeconds":1}]}]}""");
        assertEquals("application/octet-stream", new ClientSceneService.ContentTypes(odd).of("m.png"));
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
