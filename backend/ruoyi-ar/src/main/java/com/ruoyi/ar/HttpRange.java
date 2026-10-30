package com.ruoyi.ar;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * 强 ETag 与单区间 Range 响应。ETag 必须与实际发送的字节一致（这里取登记的 SHA256）。
 */
public final class HttpRange {
    private static final Pattern BYTES = Pattern.compile("(?i)bytes=(\\d*)-(\\d*)");
    private static final int BUFFER = 64 * 1024;

    /**
     * 解析结果。status 为 200（完整）、206（区间）或 416（区间不可满足）；
     * start/end 为闭区间字节位置，size 为文件总长。
     */
    public record Slice(int status, long start, long end, long size) {
        public long length() {
            return size == 0 ? 0 : Math.max(0, end - start + 1);
        }
    }

    /**
     * 按偏移和长度打开存储流，由调用方（存储层）提供。
     */
    @FunctionalInterface
    public interface StreamOpen {
        InputStream open(long offset, long length) throws IOException;
    }

    private HttpRange() {
    }

    /**
     * 只支持单个区间：{@code a-b}、{@code a-} 和后缀 {@code -n}。其他形式及语法非法的区间一律忽略，
     * 返回完整的 200；语法合法但无法满足的返回 416。HEAD 请求和 If-Range 与 ETag 不符时同样返回完整内容。
     * 超大数字不会抛异常。
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

    /**
     * 纯数字串转 long；超出 long 范围时取最大值而不是抛异常。
     */
    private static long number(String digits) {
        try {
            return Long.parseLong(digits);
        } catch (NumberFormatException e) {
            return Long.MAX_VALUE;
        }
    }

    /**
     * 完整内容：200，区间覆盖 0 到 size-1。
     */
    private static Slice full(long size) {
        return new Slice(200, 0, Math.max(0, size - 1), size);
    }

    /**
     * 写响应头与正文。固定带 Accept-Ranges 和 ETag，Cache-Control 为 no-store；
     * filename 非空时以附件下载，同时给出 ASCII 兜底名和 RFC 5987 的 filename*（UTF-8）。
     * 416 只写 Content-Range 头（RFC 9110 的未满足区间写法，附文件总长度）；
     * sendBody 为 false（HEAD）或长度为 0 时只发响应头。
     * 响应头已发出后若流提前结束会抛 IOException，连接会被中断，客户端能发现内容不全。
     */
    public static void write(HttpServletResponse response, Slice slice, String etag, String contentType,
                             String filename, boolean sendBody, StreamOpen open) throws IOException {
        response.setHeader("Accept-Ranges", "bytes");
        response.setHeader("ETag", etag);
        response.setHeader("Cache-Control", "no-store, no-transform");
        response.setHeader("Content-Type", contentType);
        if (filename != null && !filename.isBlank()) {
            String fallback = filename.replaceAll("[^\\x20-\\x7E]", "_").replace("\"", "'");
            String encoded = URLEncoder.encode(filename, StandardCharsets.UTF_8).replace("+", "%20");
            response.setHeader("Content-Disposition",
                    "attachment; filename=\"" + fallback + "\"; filename*=UTF-8''" + encoded);
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
            byte[] buffer = new byte[BUFFER];
            long remaining = length;
            while (remaining > 0) {
                int read = in.read(buffer, 0, (int) Math.min(buffer.length, remaining));
                if (read < 0) throw new IOException("Short content read");
                out.write(buffer, 0, read);
                remaining -= read;
            }
        }
    }
}
