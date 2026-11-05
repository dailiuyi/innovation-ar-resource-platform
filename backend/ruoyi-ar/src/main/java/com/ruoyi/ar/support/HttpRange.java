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
     * 根据请求头计算文件响应范围，不读取文件，也不直接写入响应。
     * 支持 bytes=a-b、bytes=a- 和 bytes=-n，返回的起止位置均包含在范围内。
     *
     * @param request 用于读取请求方法、Range 和 If-Range 请求头
     * @param size 文件总字节数
     * @param etag 文件当前的强 ETag；If-Range 存在时须与其完全相等
     * @return 完整响应为 200，区间响应为 206，合法但无法满足的范围为 416；
     *         HEAD、无效或多区间、If-Range 不匹配时忽略范围并返回 200
     */
    public static Slice parse(HttpServletRequest request, long size, String etag) {
        // HEAD 只返回完整文件的响应头，不按 Range 计算部分响应。
        boolean body = !"HEAD".equalsIgnoreCase(request.getMethod());
        String range = body ? request.getHeader("Range") : null;
        if (range == null || range.isBlank()) return full(size);
        // If-Range 用于避免文件变化后，将不同版本的数据拼接起来。
        String ifRange = request.getHeader("If-Range");
        if (ifRange != null && !ifRange.equals(etag)) return full(size);
        // 仅接受完整匹配的单区间格式；其他格式按完整文件处理。
        Matcher match = BYTES.matcher(range.trim());
        if (!match.matches()) return full(size);
        String first = match.group(1);
        String last = match.group(2);
        // bytes=-n：请求末尾 n 个字节；n 超过文件大小时返回整个文件的区间。
        if (first.isEmpty()) {
            if (last.isEmpty()) return full(size);
            long suffix = number(last);
            if (suffix == 0 || size <= 0) return new Slice(416, 0, -1, size);
            return new Slice(206, Math.max(0, size - suffix), size - 1, size);
        }
        // bytes=a-b 或 bytes=a-：未指定结束位置时，后续裁剪到文件末尾。
        long start = number(first);
        long end = last.isEmpty() ? Long.MAX_VALUE : number(last);
        // 结束位置早于起始位置视为无效；起始位置超出文件则无法满足。
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
