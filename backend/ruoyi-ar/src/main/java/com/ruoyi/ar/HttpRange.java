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

/** Strong ETag and single-range responses. ETag must match the bytes actually sent. */
public final class HttpRange {
    private static final Pattern BYTES = Pattern.compile("(?i)bytes=(\\d*)-(\\d*)");
    private static final int BUFFER = 64 * 1024;

    public record Slice(int status, long start, long end, long size) {
        public long length() { return size == 0 ? 0 : Math.max(0, end - start + 1); }
    }

    @FunctionalInterface
    public interface StreamOpen { InputStream open(long offset, long length) throws IOException; }

    private HttpRange() {}

    /**
     * Single range only: {@code a-b}, {@code a-} and suffix {@code -n}. Other forms and syntactically invalid
     * ranges are ignored (full 200); valid but unsatisfiable ranges are 416. Oversized numbers never throw.
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

    /** Digits only; saturates instead of throwing on values beyond a long. */
    private static long number(String digits) {
        try { return Long.parseLong(digits); }
        catch (NumberFormatException e) { return Long.MAX_VALUE; }
    }

    private static Slice full(long size) { return new Slice(200, 0, Math.max(0, size - 1), size); }

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
                int read = in.read(buffer, 0, (int)Math.min(buffer.length, remaining));
                if (read < 0) throw new IOException("Short content read");
                out.write(buffer, 0, read);
                remaining -= read;
            }
        }
    }
}
