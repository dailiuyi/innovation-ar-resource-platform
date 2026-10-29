package com.ruoyi.ar;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import java.io.IOException;
import java.util.Map;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * Anonymous read-only routes for the demo client. Deliberately no class-level role: SecurityConfig permits
 * exactly these three GET routes (plus file HEAD); every other method and path stays authenticated or denied.
 */
@RestController
@RequestMapping("/api/v1/client")
@Validated
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class ClientSceneController {
    private final ClientSceneService scenes;
    private final SceneVersionService versions;

    public ClientSceneController(ClientSceneService scenes, SceneVersionService versions) {
        this.scenes = scenes;
        this.versions = versions;
    }

    @GetMapping("/scenes")
    public Map<String,Object> list(@RequestParam(defaultValue="") @Size(max=200) String name,
        @RequestParam(defaultValue="20") @Min(1) @Max(100) int limit,
        @RequestParam(defaultValue="0") @Min(0) int offset) {
        return scenes.list(name, limit, offset);
    }

    @GetMapping("/scenes/{sceneId}")
    public Map<String,Object> detail(@PathVariable UUID sceneId) { return scenes.detail(sceneId); }

    @RequestMapping(value="/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}",
        method={RequestMethod.GET, RequestMethod.HEAD})
    public void content(@PathVariable UUID sceneId, @PathVariable UUID versionId, @PathVariable UUID fileId,
        @PathVariable String fileName, HttpServletRequest request, HttpServletResponse response) throws IOException {
        versions.clientDownload(sceneId, versionId, fileId, fileName, request, response);
    }
}
