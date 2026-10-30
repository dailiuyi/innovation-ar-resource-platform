package com.ruoyi.ar;

import java.util.Map;
import java.util.UUID;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

/**
 * 本模块（com.ruoyi.ar）控制器的统一异常出口。优先级高于若依自带的全局异常处理（Order -100），
 * 保证 /api/v1 下的错误响应都是 {code, message, traceId} 结构，而不是若依的 AjaxResult。
 */
@RestControllerAdvice(basePackages="com.ruoyi.ar") @Order(-100)
public class ArExceptionHandler {
    /**
     * 把异常映射为 HTTP 状态码和对外文案：
     * 业务层抛出的 ResponseStatusException 沿用其状态码和原因；未授权为 403；参数校验/解析类异常为 400；
     * 其余视为 500，对外只给通用文案，细节只写日志。
     * traceId 每次响应随机生成；仅 500 会把它连同堆栈写入日志，用于按用户反馈定位问题。
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String,String>> handle(Exception e) {
        int status=500;String message="服务内部错误";
        if(e instanceof ResponseStatusException r) {status=r.getStatusCode().value();message=r.getReason();}
        else if(e instanceof org.springframework.security.access.AccessDeniedException) {status=403;message="仅管理员可操作";}
        else if(e instanceof org.springframework.web.bind.MethodArgumentNotValidException
             || e instanceof org.springframework.web.bind.MissingServletRequestParameterException
             || e instanceof jakarta.validation.ConstraintViolationException
             || e instanceof org.springframework.http.converter.HttpMessageNotReadableException
             || e instanceof org.springframework.web.method.annotation.MethodArgumentTypeMismatchException) {status=400;message="请求字段不合法";}
        String trace=UUID.randomUUID().toString();
        if(status==500) LoggerFactory.getLogger(getClass()).error("AR failure traceId={}",trace,e);
        return ResponseEntity.status(status).body(Map.of("code","AR_"+status,"message",message==null?"请求失败":message,"traceId",trace));
    }
}
