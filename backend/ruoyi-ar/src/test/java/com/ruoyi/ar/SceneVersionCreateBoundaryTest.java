package com.ruoyi.ar;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/**
 * Request-boundary rules of version creation. They are decided before any database access, so this
 * runs without a database; constraints, locking and idempotency are covered by the PostgreSQL gate.
 */
class SceneVersionCreateBoundaryTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String SHA = "a".repeat(64);
    private static final String DESCRIPTOR = """
        {"formatVersion":1,"defaultVariant":"standard","transform":{"position":[0,0,0],"rotation":[0,0,0],"scale":[1,1,1]},
         "settings":"common/settings.json",
         "variants":[{"id":"standard","name":"标准","format":"4dv-compressed-ply",
           "segments":[{"path":"standard/00.c.ply","startSeconds":0,"durationSeconds":5}]}]}""";

    private static SceneVersionService service(long maxBytes, int maxFiles, long versionBytes) {
        return new SceneVersionService(null, null, null, JSON, maxBytes, maxFiles, versionBytes);
    }

    private static SceneVersionController.FileInput file(String path, long bytes) {
        return new SceneVersionController.FileInput(path, bytes, SHA);
    }

    private static SceneVersionController.CreateInput input(String descriptor, SceneVersionController.FileInput... files)
            throws Exception {
        return new SceneVersionController.CreateInput(UUID.randomUUID(), "", JSON.readTree(descriptor), List.of(files));
    }

    private static ResponseStatusException rejected(SceneVersionService service, SceneVersionController.CreateInput input) {
        return assertThrows(ResponseStatusException.class, () -> service.create(UUID.randomUUID(), input));
    }

    @Test void configExposesLimitsUnderVersionNames() {
        assertEquals(Map.of("maxBytes", 10L, "versionMaxFiles", 3, "versionMaxBytes", 30L), service(10, 3, 30).config());
    }

    @Test void tooManyFilesAreRejectedWith413() throws Exception {
        var e = rejected(service(100, 1, 1000), input(DESCRIPTOR, file("common/settings.json", 1), file("standard/00.c.ply", 1)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    @Test void singleFileAboveConfiguredLimitIsRejectedWith413() throws Exception {
        var e = rejected(service(10, 10, 1000), input(DESCRIPTOR, file("common/settings.json", 1), file("standard/00.c.ply", 11)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    @Test void versionTotalAboveConfiguredLimitIsRejectedWith413() throws Exception {
        var e = rejected(service(10, 10, 15), input(DESCRIPTOR, file("common/settings.json", 8), file("standard/00.c.ply", 8)));
        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, e.getStatusCode());
    }

    @Test void unsafeOrConflictingPathsAreRejectedWith400() throws Exception {
        var service = service(100, 10, 1000);
        for (var paths : List.of(List.of("../settings.json", "standard/00.c.ply"),
                List.of("common/settings.json", "COMMON/settings.json"),
                List.of("common/settings.json", "common/settings.json"))) {
            var e = rejected(service, input(DESCRIPTOR, file(paths.get(0), 1), file(paths.get(1), 1)));
            assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode(), paths.toString());
        }
    }

    @Test void descriptorMustReferenceExactlyTheRegisteredFiles() throws Exception {
        var service = service(100, 10, 1000);
        var missing = rejected(service, input(DESCRIPTOR, file("common/settings.json", 1)));
        assertEquals(HttpStatus.BAD_REQUEST, missing.getStatusCode());
        assertTrue(missing.getReason().contains("standard/00.c.ply"), missing.getReason());
        var extra = rejected(service, input(DESCRIPTOR, file("common/settings.json", 1), file("standard/00.c.ply", 1),
            file("notes/report.md", 1)));
        assertEquals(HttpStatus.BAD_REQUEST, extra.getStatusCode());
        assertTrue(extra.getReason().contains("notes/report.md"), extra.getReason());
    }

    @Test void nonObjectDescriptorIsRejectedWith400() throws Exception {
        var e = rejected(service(100, 10, 1000), input("null", file("common/settings.json", 1)));
        assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode());
    }
}
