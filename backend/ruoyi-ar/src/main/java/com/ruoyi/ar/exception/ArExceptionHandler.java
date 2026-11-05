package com.ruoyi.ar.exception;

import java.util.Map;
import java.util.UUID;

import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

/**
 * AR 模块专用全局控制器异常统一处理器。
 * <p>
 * 拦截 {@code com.ruoyi.ar} 包下所有控制器抛出的未捕获异常并映射为结构化 JSON 响应。
 * 约定契约：
 * <ul>
 *   <li>{@link ResponseStatusException} 保留原始状态码与 reason 说明；</li>
 *   <li>Spring Security 拒绝访问统一映射为 403；</li>
 *   <li>Spring MVC 参数校验与格式错误统一映射为 400；</li>
 *   <li>其余不可预知异常统一收敛为 500 并记录附带 traceId 的堆栈日志。</li>
 * </ul>
 * 注意：底层过滤器链（Filter）中的安全拦截异常与通用框架登录异常不流经本 Handler。
 */
@RestControllerAdvice(basePackages = "com.ruoyi.ar")
@Order(-100)
public class ArExceptionHandler {
    /**
     * 统一处理 AR 控制器异常并构筑错误响应实体。
     *
     * @param e 捕获的异常实例
     * @return 包含 code、message 和 traceId 的统一响应包
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> handle(Exception e) {
        int status = 500;
        String message = "服务内部错误";
        if (e instanceof ResponseStatusException r) {
            status = r.getStatusCode().value();
            message = r.getReason();
        } else if (e instanceof org.springframework.security.access.AccessDeniedException) {
            status = 403;
            message = "仅管理员可操作";
        } else if (e instanceof org.springframework.web.bind.MethodArgumentNotValidException
                || e instanceof org.springframework.web.bind.MissingServletRequestParameterException
                || e instanceof jakarta.validation.ConstraintViolationException
                || e instanceof org.springframework.http.converter.HttpMessageNotReadableException
                || e instanceof org.springframework.web.method.annotation.MethodArgumentTypeMismatchException) {
            status = 400;
            message = "请求字段不合法";
        }
        String trace = UUID.randomUUID().toString();
        if (status == 500) LoggerFactory.getLogger(getClass()).error("AR failure traceId={}", trace, e);
        return ResponseEntity.status(status).body(Map.of("code", "AR_" + status, "message", message == null ? "请求失败" : message, "traceId", trace));
    }
}
