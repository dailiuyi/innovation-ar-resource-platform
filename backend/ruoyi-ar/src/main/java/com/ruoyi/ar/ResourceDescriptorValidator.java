package com.ruoyi.ar;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** 校验 resource.json v1 与上传文件清单一致；错误均为 400 并指出 JSON 字段或文件路径。 */
public final class ResourceDescriptorValidator {
    public static final String MODEL_FORMAT = "4dv-compressed-ply";
    private static final Pattern VARIANT_ID = Pattern.compile("^[a-z][a-z0-9_-]{0,63}$");

    private ResourceDescriptorValidator() {}

    /** 返回去重后的引用路径集合；它必须与 relativePaths 完全相等。 */
    public static Set<String> validate(SceneResourceDescriptor descriptor, Collection<String> relativePaths) {
        if (descriptor == null) throw invalid("resource.json", "不能为空");
        if (descriptor.formatVersion() == null) throw invalid("formatVersion", "必填");
        if (descriptor.formatVersion() != 1) throw invalid("formatVersion", "只支持 1");
        transform(descriptor.transform());
        Map<String, String> references = new LinkedHashMap<>();
        reference(references, "settings", descriptor.settings(), true);
        reference(references, "poster", descriptor.poster(), false);
        reference(references, "audio", descriptor.audio(), false);
        reference(references, "preview", descriptor.preview(), false);
        if (descriptor.audioPosition() != null) {
            if (descriptor.audio() == null) throw invalid("audioPosition", "未声明 audio 时不能提供");
            vector3("audioPosition", descriptor.audioPosition());
        }
        List<SceneResourceDescriptor.Variant> variants = descriptor.variants();
        if (variants == null || variants.isEmpty()) throw invalid("variants", "必须是非空数组");
        Set<String> ids = new HashSet<>();
        for (int i = 0; i < variants.size(); i++) {
            variant("variants[" + i + "]", variants.get(i), ids, references);
        }
        if (descriptor.defaultVariant() == null) throw invalid("defaultVariant", "必填");
        if (!ids.contains(descriptor.defaultVariant())) {
            throw invalid("defaultVariant", "未在 variants 中声明：" + descriptor.defaultVariant());
        }
        compare(references, relativePaths);
        return new LinkedHashSet<>(references.keySet());
    }

    private static void transform(SceneResourceDescriptor.Transform transform) {
        if (transform == null) throw invalid("transform", "必填");
        vector3("transform.position", transform.position());
        vector3("transform.rotation", transform.rotation());
        vector3("transform.scale", transform.scale());
    }

    private static void vector3(String field, List<BigDecimal> values) {
        if (values == null) throw invalid(field, "必填");
        if (values.size() != 3) throw invalid(field, "必须是三个数值");
        for (int i = 0; i < 3; i++) {
            if (values.get(i) == null) throw invalid(field + "[" + i + "]", "必须是数值");
        }
    }

    private static void variant(String field, SceneResourceDescriptor.Variant variant, Set<String> ids,
                                Map<String, String> references) {
        if (variant == null) throw invalid(field, "不能为空");
        if (variant.id() == null) throw invalid(field + ".id", "必填");
        if (!VARIANT_ID.matcher(variant.id()).matches()) throw invalid(field + ".id", "格式不合法：" + variant.id());
        if (!ids.add(variant.id())) throw invalid(field + ".id", "档位重复：" + variant.id());
        if (variant.name() == null || variant.name().isBlank()) throw invalid(field + ".name", "必须是非空展示名");
        if (!MODEL_FORMAT.equals(variant.format())) throw invalid(field + ".format", "只支持 " + MODEL_FORMAT);
        List<SceneResourceDescriptor.Segment> segments = variant.segments();
        if (segments == null || segments.isEmpty()) throw invalid(field + ".segments", "必须是非空数组");
        BigDecimal previousEnd = null;
        for (int i = 0; i < segments.size(); i++) {
            String segmentField = field + ".segments[" + i + "]";
            SceneResourceDescriptor.Segment segment = segments.get(i);
            if (segment == null) throw invalid(segmentField, "不能为空");
            reference(references, segmentField + ".path", segment.path(), true);
            if (segment.startSeconds() == null) throw invalid(segmentField + ".startSeconds", "必填");
            if (segment.durationSeconds() == null) throw invalid(segmentField + ".durationSeconds", "必填");
            if (segment.startSeconds().signum() < 0) throw invalid(segmentField + ".startSeconds", "不能为负数");
            if (segment.durationSeconds().signum() <= 0) throw invalid(segmentField + ".durationSeconds", "必须大于 0");
            if (previousEnd != null && segment.startSeconds().compareTo(previousEnd) < 0) {
                throw invalid(segmentField + ".startSeconds", "必须按时间升序且不与上一段重叠");
            }
            previousEnd = segment.startSeconds().add(segment.durationSeconds());
        }
    }

    private static void reference(Map<String, String> references, String field, String path, boolean required) {
        if (path == null) {
            if (required) throw invalid(field, "必填");
            return;
        }
        String normalized;
        try {
            normalized = RelativePath.normalizeOne(path);
        } catch (IllegalArgumentException e) {
            throw invalid(field, e.getMessage() + "：" + path);
        }
        references.putIfAbsent(normalized, field);
    }

    private static void compare(Map<String, String> references, Collection<String> relativePaths) {
        List<String> provided = new ArrayList<>(relativePaths.size());
        for (String path : relativePaths) {
            try {
                provided.add(RelativePath.normalizeOne(path));
            } catch (IllegalArgumentException e) {
                throw invalid("files", e.getMessage() + "：" + path);
            }
        }
        try {
            RelativePath.normalizeAll(provided);
            RelativePath.normalizeAll(new ArrayList<>(references.keySet()));
        } catch (IllegalArgumentException e) {
            throw invalid("files", e.getMessage());
        }
        Set<String> providedSet = new HashSet<>(provided);
        for (Map.Entry<String, String> reference : references.entrySet()) {
            if (!providedSet.contains(reference.getKey())) {
                throw invalid(reference.getValue(), "引用的文件未在 files 中提供：" + reference.getKey());
            }
        }
        for (String path : provided) {
            if (!references.containsKey(path)) throw invalid("files", "文件未被描述引用：" + path);
        }
    }

    private static ResponseStatusException invalid(String field, String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " " + message);
    }
}
