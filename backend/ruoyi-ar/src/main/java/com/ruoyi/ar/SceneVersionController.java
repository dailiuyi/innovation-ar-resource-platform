package com.ruoyi.ar;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1")
@Validated
@PreAuthorize("@ss.hasRole('ar_admin')")
@ConditionalOnProperty(name="ar.storage.enabled", havingValue="true")
public class SceneVersionController {
    private final SceneVersionService service;
    public SceneVersionController(SceneVersionService service) { this.service = service; }

    public record FileInput(@NotBlank @Size(max=1024) String relativePath, @NotNull @Min(1) Long bytes,
        @NotNull @Pattern(regexp="[0-9a-f]{64}") String sha256) { }
    public record CreateInput(@NotNull UUID requestKey, @NotNull @Size(max=2000) String description,
        @NotNull JsonNode descriptor, @NotEmpty List<@Valid FileInput> files) { }
    public record EditInput(@NotNull @Size(max=2000) String description, @NotNull @Min(0) Long expectedVersion) { }
    public record PublishInput(@NotNull @Min(0) Long expectedSceneVersion) { }

    @GetMapping("/scene-versions/config") public Map<String,Object> config() { return service.config(); }
    @GetMapping("/scenes/{sceneId}/versions") public Map<String,Object> list(@PathVariable UUID sceneId,
        @RequestParam(defaultValue="20") @Min(1) @Max(100) int limit,
        @RequestParam(defaultValue="0") @Min(0) int offset) { return service.list(sceneId,limit,offset); }
    @PostMapping("/scenes/{sceneId}/versions")
    public ResponseEntity<Map<String,Object>> create(@PathVariable UUID sceneId,@Valid @RequestBody CreateInput input) {
        var result=service.create(sceneId,input);
        return ResponseEntity.status(result.created()?HttpStatus.CREATED:HttpStatus.OK).body(result.version());
    }
    @GetMapping("/scene-versions/{versionId}") public Map<String,Object> detail(@PathVariable UUID versionId) { return service.detail(versionId); }
    @PutMapping("/scene-versions/{versionId}")
    public Map<String,Object> edit(@PathVariable UUID versionId,@Valid @RequestBody EditInput input) { return service.edit(versionId,input); }
    @PostMapping("/scene-versions/{versionId}/publish")
    public Map<String,Object> publish(@PathVariable UUID versionId,@Valid @RequestBody PublishInput input) {
        return service.publish(versionId,input.expectedSceneVersion());
    }
    @DeleteMapping("/scene-versions/{versionId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void remove(@PathVariable UUID versionId) { service.removeVersion(versionId); }
    @GetMapping("/scene-versions/{versionId}/files/{fileId}")
    public Map<String,Object> file(@PathVariable UUID versionId,@PathVariable UUID fileId) { return service.fileStatus(versionId,fileId); }
    @PutMapping(value="/scene-versions/{versionId}/files/{fileId}/content",consumes="application/octet-stream")
    public Map<String,Object> upload(@PathVariable UUID versionId,@PathVariable UUID fileId,HttpServletRequest request) throws java.io.IOException {
        return service.upload(versionId,fileId,request.getInputStream());
    }
    @RequestMapping(value="/scene-versions/{versionId}/files/{fileId}/content", method={RequestMethod.GET, RequestMethod.HEAD})
    public void download(@PathVariable UUID versionId,@PathVariable UUID fileId,
        HttpServletRequest request,HttpServletResponse response) throws java.io.IOException {
        service.adminDownload(versionId,fileId,request,response);
    }
}
