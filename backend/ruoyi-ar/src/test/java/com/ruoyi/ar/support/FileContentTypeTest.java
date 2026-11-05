package com.ruoyi.ar.support;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class FileContentTypeTest {
    @Test void contentTypeFollowsTheExtensionOnly() {
        assertEquals("application/octet-stream", FileContentType.of("standard/00.c.ply"));
        assertEquals("application/octet-stream", FileContentType.of("standard/01.4dv"));
        assertEquals("application/json", FileContentType.of("common/settings.JSON"));
        assertEquals("image/png", FileContentType.of("common/poster.png"));
        assertEquals("audio/wav", FileContentType.of("common/a.wav"));
        assertEquals("video/webm", FileContentType.of("common/p.webm"));
        assertEquals("image/jpeg", FileContentType.of("x/COVER.JPG"));
        assertEquals("image/webp", FileContentType.of("x/c.webp"));
        assertEquals("application/octet-stream", FileContentType.of("x/unknown.bin"));
        assertEquals("application/octet-stream", FileContentType.of("x/noextension"));
    }
}
