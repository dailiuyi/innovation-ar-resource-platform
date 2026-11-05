package com.ruoyi.ar.support;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.apache.commons.io.IOUtils;
import org.springframework.http.ContentDisposition;

/**
 * 处理强 ETag 和单区间下载；权限、文件归属和就绪状态由调用方校验。
 * 保留项目的 200/206/416 策略：多区间忽略、超大数字饱和处理，不直接套用 Spring 的区间解析。
 */
public final class HttpRange {
    private static final Pattern BYTES = Pattern.compile("(?i)bytes=(\\d*)-(\\d*)");
    private static final int BUFFER = 64 * 1024;

    /** start/end 为闭区间；status 为完整 200、区间 206 或不可满足 416。 */
    public record Slice(int status, long start, long end, long size) {
        public long length() {
            return size == 0 ? 0 : Math.max(0, end - start + 1);
        }
    }

    /** 延迟打开指定范围；HEAD、空正文与 416 不调用，返回流由 write 关闭。 */
    @FunctionalInterface
    public interface StreamOpen {
        InputStream open(long offset, long length) throws IOException;
    }

    private HttpRange() {
    }

    /**
     * 支持 a-b、a-、-n；合法但不可满足返回 416。
     * 非法或多区间、HEAD、If-Range 不匹配时按完整 200 处理。
     */
    public static Slice parse(HttpServletRequest request, long size, String etag) {
        boolean body = !"HEAD".equalsIgnoreCase(request.getMethod());
        String range = body ? request.getHeader("Range") : null;
        if (range == null || range.isBlank()) return full(size);
        String ifRange = request.getHeader("If-Range");
        if (ifRange != null && !ifRange.equals(etag)) return full(size);
        Matcher match = BYTES.matcher(range.trim());
        if (!match.matches()) return full(size);
        String first = match.group(1);
        String last = match.group(2);
        if (first.isEmpty()) {
            if (last.isEmpty()) return full(size);
            long suffix = number(last);
            if (suffix == 0 || size <= 0) return new Slice(416, 0, -1, size);
            return new Slice(206, Math.max(0, size - suffix), size - 1, size);
        }
        long start = number(first);
        long end = last.isEmpty() ? Long.MAX_VALUE : number(last);
        if (end < start) return full(size);
        if (size <= 0 || start >= size) return new Slice(416, 0, -1, size);
        return new Slice(206, start, Math.min(end, size - 1), size);
    }

    /** 超大数字取 Long.MAX_VALUE，让后续区间规则处理。 */
    private static long number(String digits) {
        try {
            return Long.parseLong(digits);
        } catch (NumberFormatException e) {
            return Long.MAX_VALUE;
        }
    }

    private static Slice full(long size) {
        return new Slice(200, 0, Math.max(0, size - 1), size);
    }

    /**
     * HEAD 和 416 不打开正文；GET 按长度输出，提前结束则抛 IOException。
     * filename 非空时返回附件名，中文名使用 UTF-8 编码。
     */
    public static void write(HttpServletResponse response, Slice slice, String etag, String contentType,
                             String filename, boolean sendBody, StreamOpen open) throws IOException {
        response.setHeader("Accept-Ranges", "bytes");
        response.setHeader("ETag", etag);
        response.setHeader("Cache-Control", "no-store, no-transform");
        response.setHeader("Content-Type", contentType);
        if (filename != null && !filename.isBlank()) {
            response.setHeader("Content-Disposition", ContentDisposition.attachment()
                    .filename(filename, StandardCharsets.UTF_8).build().toString());
        }
        if (slice.status() == 416) {
            response.setStatus(416);
            response.setHeader("Content-Range", "bytes */" + slice.size());
            response.setContentLength(0);
            return;
        }
        long length = slice.length();
        response.setStatus(slice.status());
        response.setContentLengthLong(length);
        if (slice.status() == 206) {
            response.setHeader("Content-Range", "bytes " + slice.start() + "-" + slice.end() + "/" + slice.size());
        }
        if (!sendBody || length == 0) return;
        try (InputStream in = open.open(slice.start(), length); OutputStream out = response.getOutputStream()) {
            // 复用限长复制；底层文件意外变短时仍须报错，不能把截断正文当作完整响应。
            long copied = IOUtils.copyLarge(in, out, 0, length, new byte[BUFFER]);
            if (copied != length) throw new IOException("Short content read");
        }
    }
}
