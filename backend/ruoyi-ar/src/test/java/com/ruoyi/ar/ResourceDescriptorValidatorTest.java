package com.ruoyi.ar;

import static org.junit.jupiter.api.Assertions.*;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.function.UnaryOperator;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

class ResourceDescriptorValidatorTest {
    private static final List<String> WEDDING_FILES = List.of(
        "standard_quality/00.c.ply", "standard_quality/01.c.ply",
        "high_quality/00.c.ply", "high_quality/01.c.ply",
        "vr_foreground/00.c.ply", "vr_foreground/01.c.ply",
        "media_and_settings/wedding_settings.json", "media_and_settings/wedding_1205.jpg",
        "media_and_settings/wedding.wav", "media_and_settings/wedding.webm");

    private static final String WEDDING = descriptorJson("");

    private static String descriptorJson(String audioPosition) {
        StringBuilder variants = new StringBuilder();
        for (String id : List.of("standard_quality", "high_quality", "vr_foreground")) {
            if (variants.length() > 0) variants.append(',');
            variants.append("{\"id\":\"").append(id).append("\",\"name\":\"").append(id)
                .append("\",\"format\":\"4dv-compressed-ply\",\"segments\":[")
                .append("{\"path\":\"").append(id).append("/00.c.ply\",\"startSeconds\":0,\"durationSeconds\":5},")
                .append("{\"path\":\"").append(id).append("/01.c.ply\",\"startSeconds\":5,\"durationSeconds\":3}]}");
        }
        return "{\"formatVersion\":1,\"defaultVariant\":\"standard_quality\","
            + "\"transform\":{\"position\":[0,0,0],\"rotation\":[0,0,0],\"scale\":[1,1,1]},"
            + "\"settings\":\"media_and_settings/wedding_settings.json\",\"poster\":\"media_and_settings/wedding_1205.jpg\","
            + "\"audio\":\"media_and_settings/wedding.wav\"," + audioPosition
            + "\"preview\":\"media_and_settings/wedding.webm\",\"variants\":[" + variants + "]}";
    }

    private static ResponseStatusException rejected(String json, Iterable<String> files) {
        ResponseStatusException e = assertThrows(ResponseStatusException.class,
            () -> ResourceDescriptorValidator.validate(SceneResourceDescriptor.parse(json), toList(files)));
        assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode());
        return e;
    }

    private static List<String> toList(Iterable<String> files) {
        List<String> list = new ArrayList<>();
        files.forEach(list::add);
        return list;
    }

    private static ResponseStatusException rejected(UnaryOperator<String> edit) {
        return rejected(edit.apply(WEDDING), WEDDING_FILES);
    }

    @Test void acceptsWeddingThreeVariantsAndReturnsDedupedReferences() {
        Set<String> references = ResourceDescriptorValidator.validate(SceneResourceDescriptor.parse(WEDDING), WEDDING_FILES);
        assertEquals(Set.copyOf(WEDDING_FILES), references);
        assertEquals(10, references.size());
    }

    @Test void sharedPathAcrossVariantsIsRegisteredOnce() {
        String shared = WEDDING.replace("high_quality/00.c.ply", "standard_quality/00.c.ply");
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.remove("high_quality/00.c.ply");
        assertEquals(9, ResourceDescriptorValidator.validate(SceneResourceDescriptor.parse(shared), files).size());
        rejected(shared, WEDDING_FILES);
    }

    @Test void rejectsMissingModelReferenceAndNamesTheField() {
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.remove("high_quality/01.c.ply");
        String message = rejected(WEDDING, files).getReason();
        assertTrue(message.contains("variants[1].segments[1].path"), message);
        assertTrue(message.contains("high_quality/01.c.ply"), message);
    }

    @Test void rejectsMissingSettingsFile() {
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.remove("media_and_settings/wedding_settings.json");
        assertTrue(rejected(WEDDING, files).getReason().startsWith("settings "));
    }

    @Test void rejectsFileNotReferencedByDescriptor() {
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.add("report.md");
        assertTrue(rejected(WEDDING, files).getReason().contains("report.md"));
    }

    @Test void rejectsRegisteringSamePathTwice() {
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.add("standard_quality/00.c.ply");
        assertTrue(rejected(WEDDING, files).getReason().contains("重复"));
    }

    @Test void rejectsDuplicateVariantAndUnknownDefault() {
        assertTrue(rejected(s -> s.replace("\"id\":\"high_quality\"", "\"id\":\"standard_quality\"")).getReason()
            .startsWith("variants[1].id "));
        assertTrue(rejected(s -> s.replace("\"defaultVariant\":\"standard_quality\"", "\"defaultVariant\":\"missing\""))
            .getReason().startsWith("defaultVariant "));
    }

    @Test void rejectsPathTraversalAndAbsolutePath() {
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.set(0, "../outside.ply");
        String traversal = WEDDING.replace("standard_quality/00.c.ply", "../outside.ply");
        assertTrue(rejected(traversal, files).getReason().startsWith("variants[0].segments[0].path "));
        assertTrue(rejected(s -> s.replace("media_and_settings/wedding.wav", "/etc/passwd")).getReason().startsWith("audio "));
    }

    @Test void rejectsOverlapDescendingAndNonPositiveDuration() {
        assertTrue(rejected(s -> s.replaceFirst(literal("standard_quality/01.c.ply\",\"startSeconds\":5,"),
            "standard_quality/01.c.ply\",\"startSeconds\":4.9,")).getReason()
            .startsWith("variants[0].segments[1].startSeconds "));
        assertTrue(rejected(s -> s.replaceFirst(literal("standard_quality/01.c.ply\",\"startSeconds\":5,"),
            "standard_quality/01.c.ply\",\"startSeconds\":1,")).getReason().contains("升序"));
        assertTrue(rejected(s -> s.replaceFirst("\"durationSeconds\":5", "\"durationSeconds\":0")).getReason()
            .startsWith("variants[0].segments[0].durationSeconds "));
        assertTrue(rejected(s -> s.replaceFirst("\"startSeconds\":0", "\"startSeconds\":-1")).getReason()
            .startsWith("variants[0].segments[0].startSeconds "));
    }

    @Test void rejectsUnknownFormatVersionFormatAndMissingTransform() {
        assertTrue(rejected(s -> s.replace("\"formatVersion\":1", "\"formatVersion\":2")).getReason().startsWith("formatVersion "));
        assertTrue(rejected(s -> s.replaceFirst("4dv-compressed-ply", "glb")).getReason().startsWith("variants[0].format "));
        assertTrue(rejected(s -> s.replace("\"scale\":[1,1,1]", "\"scale\":[1,1]")).getReason().startsWith("transform.scale "));
        assertTrue(rejected(s -> s.replaceFirst("\"transform\":\\{[^}]*\\},", "")).getReason().startsWith("transform "));
    }

    @Test void rejectsAudioPositionWithoutAudio() {
        String json = descriptorJson("\"audioPosition\":[0,1,0],").replace("\"audio\":\"media_and_settings/wedding.wav\",", "");
        List<String> files = new ArrayList<>(WEDDING_FILES);
        files.remove("media_and_settings/wedding.wav");
        assertTrue(rejected(json, files).getReason().startsWith("audioPosition "));
        ResourceDescriptorValidator.validate(SceneResourceDescriptor.parse(descriptorJson("\"audioPosition\":[0,1,0],")), WEDDING_FILES);
    }

    @Test void parseRejectsUnknownFieldWrongTypeAndInvalidJson() {
        assertTrue(rejected(s -> s.replace("\"formatVersion\":1,", "\"formatVersion\":1,\"address\":\"x\",")).getReason()
            .contains("address"));
        assertTrue(rejected(s -> s.replace("\"startSeconds\":0", "\"startSeconds\":\"0\"")).getReason()
            .contains("variants[0].segments[0].startSeconds"));
        assertTrue(rejected(s -> s + "x").getReason().contains("resource.json"));
    }

    private static String literal(String literal) {
        return java.util.regex.Pattern.quote(literal);
    }
}
