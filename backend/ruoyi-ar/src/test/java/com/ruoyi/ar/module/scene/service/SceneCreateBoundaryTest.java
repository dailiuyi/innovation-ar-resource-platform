package com.ruoyi.ar.module.scene.service;

import com.ruoyi.ar.module.scene.model.SceneCreateFileReq;
import com.ruoyi.ar.module.scene.model.SceneCreateReq;
import com.ruoyi.ar.module.scene.model.SceneRows;

import static org.junit.jupiter.api.Assertions.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/**
 * Request-boundary rules of combined scene creation. They are decided before any database access, so
 * this runs without a database; constraints, locking and idempotency are covered by the PostgreSQL gate.
 */
class SceneCreateBoundaryTest {
    private static final String SHA = "a".repeat(64);

    private static SceneService service(long maxBytes, int maxFiles, long sceneBytes) {
        return new SceneService(null, null, null, null, maxBytes, maxFiles, sceneBytes);
    }

    private static SceneCreateFileReq file(String path, long bytes) {
        return new SceneCreateFileReq(path, bytes, SHA);
    }

    private static SceneCreateReq input(SceneCreateFileReq... files) {
        return new SceneCreateReq(UUID.randomUUID(), "场景", "", List.of(files));
    }

    private static ResponseStatusException rejected(SceneService service, SceneCreateReq input) {
        return assertThrows(ResponseStatusException.class, () -> service.create(input));
    }

    @Test void configExposesSceneLimits() {
        assertEquals(Map.of("maxBytes", 10L, "sceneMaxFiles", 3, "sceneMaxBytes", 30L),
                service(10, 3, 30).config());
    }

    @Test void emptyManifestIsRejectedWith400() {
        var e = rejected(service(100, 10, 1000), input());
        assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode());
    }

    @Test void tooManyFilesAreRejectedWith413() {
        var e = rejected(service(100, 1, 1000), input(file("common/settings.json", 1), file("standard/00.c.ply", 1)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    @Test void singleFileAboveConfiguredLimitIsRejectedWith413() {
        var e = rejected(service(10, 10, 1000), input(file("common/settings.json", 1), file("standard/00.c.ply", 11)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    @Test void sceneTotalAboveConfiguredLimitIsRejectedWith413() {
        var e = rejected(service(10, 10, 15), input(file("common/settings.json", 8), file("standard/00.c.ply", 8)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    /** Two individually legal huge files must still be rejected, not overflow into a negative total. */
    @Test void hugeTotalsCannotWrapPastTheSceneLimit() {
        long half = Long.MAX_VALUE / 2 + 1;
        var e = rejected(service(Long.MAX_VALUE, 10, Long.MAX_VALUE),
                input(file("a.bin", half), file("b.bin", half)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    @Test void unsafeOrConflictingPathsAreRejectedWith400() {
        var service = service(100, 10, 1000);
        for (var paths : List.of(List.of("../settings.json", "standard/00.c.ply"),
                List.of("common/settings.json", "COMMON/settings.json"),
                List.of("common/settings.json", "common/settings.json"))) {
            var e = rejected(service, input(file(paths.get(0), 1), file(paths.get(1), 1)));
            assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode(), paths.toString());
        }
    }

    @Test void fileNamesTheClientUrlCannotCarryAreRejectedWith400() {
        var service = service(100, 10, 1000);
        for (String name : List.of("100%.json", "a;b.json")) {
            var e = rejected(service, input(file("common/" + name, 1), file("standard/00.c.ply", 1)));
            assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode(), name);
            assertTrue(e.getReason().contains(name), e.getReason());
        }
    }

    /** Retry comparison ignores declaration order but detects any path, size or digest change. */
    @Test void manifestComparisonIsOrderIndependentAndContentStrict() {
        var stored = List.of(
                new SceneRows.File("f1", "s", "a.bin", 1, SHA, "PENDING", null, 0),
                new SceneRows.File("f2", "s", "b.bin", 2, SHA, "PENDING", null, 0));
        var same = List.of(new SceneRows.FileSpec("b.bin", 2, SHA), new SceneRows.FileSpec("a.bin", 1, SHA));
        assertTrue(SceneService.sameManifest(stored, same));
        assertFalse(SceneService.sameManifest(stored,
                List.of(new SceneRows.FileSpec("b.bin", 3, SHA), new SceneRows.FileSpec("a.bin", 1, SHA))));
        assertFalse(SceneService.sameManifest(stored,
                List.of(new SceneRows.FileSpec("b.bin", 2, "b".repeat(64)), new SceneRows.FileSpec("a.bin", 1, SHA))));
        assertFalse(SceneService.sameManifest(stored,
                List.of(new SceneRows.FileSpec("b.bin", 2, SHA), new SceneRows.FileSpec("c.bin", 1, SHA))));
    }
}
