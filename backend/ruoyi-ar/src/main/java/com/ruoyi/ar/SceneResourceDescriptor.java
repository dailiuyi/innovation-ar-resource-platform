package com.ruoyi.ar;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonMappingException;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectReader;
import com.fasterxml.jackson.databind.json.JsonMapper;
import java.math.BigDecimal;
import java.util.List;
import java.util.stream.Collectors;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** resource.json v1：一个场景成品的统一描述；路径均相对资源目录根。 */
public record SceneResourceDescriptor(
    Integer formatVersion,
    String defaultVariant,
    Transform transform,
    String settings,
    String poster,
    String audio,
    List<BigDecimal> audioPosition,
    String preview,
    List<Variant> variants
) {
    /** 三元数值数组；rotation 单位为度。 */
    public record Transform(List<BigDecimal> position, List<BigDecimal> rotation, List<BigDecimal> scale) {}

    public record Variant(String id, String name, String format, List<Segment> segments) {}

    public record Segment(String path, BigDecimal startSeconds, BigDecimal durationSeconds) {}

    private static final ObjectReader READER = JsonMapper.builder()
        .disable(MapperFeature.ALLOW_COERCION_OF_SCALARS)
        .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
        .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
        .build()
        .readerFor(SceneResourceDescriptor.class);

    /** 严格解析：未知字段、类型错误和非法 JSON 返回 400 并指出 JSON 字段。 */
    public static SceneResourceDescriptor parse(String json) {
        try {
            return READER.readValue(json);
        } catch (JsonMappingException e) {
            String field = e.getPath().stream()
                .map(r -> r.getFieldName() != null ? "." + r.getFieldName() : "[" + r.getIndex() + "]")
                .collect(Collectors.joining());
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "resource.json" + field + " 无法解析：" + e.getOriginalMessage());
        } catch (JsonProcessingException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "resource.json 不是合法 JSON：" + e.getOriginalMessage());
        }
    }
}
