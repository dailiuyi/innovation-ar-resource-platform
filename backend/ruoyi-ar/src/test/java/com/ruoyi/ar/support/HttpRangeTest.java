package com.ruoyi.ar.support;

import static org.junit.jupiter.api.Assertions.*;

import jakarta.servlet.ServletOutputStream;
import jakarta.servlet.WriteListener;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class HttpRangeTest {
    private static final byte[] DATA = new byte[100];
    private static final String ETAG = "\"" + "a".repeat(64) + "\"";
    static { for (int i = 0; i < DATA.length; i++) DATA[i] = (byte) i; }

    private static HttpServletRequest request(String method, String range, String ifRange) {
        Map<String, String> headers = new HashMap<>();
        if (range != null) headers.put("Range", range);
        if (ifRange != null) headers.put("If-Range", ifRange);
        return (HttpServletRequest) Proxy.newProxyInstance(HttpRangeTest.class.getClassLoader(),
            new Class<?>[]{HttpServletRequest.class}, (proxy, m, args) -> switch (m.getName()) {
                case "getMethod" -> method;
                case "getHeader" -> headers.get((String) args[0]);
                default -> throw new UnsupportedOperationException(m.getName());
            });
    }

    private static HttpRange.Slice parse(String range) { return HttpRange.parse(request("GET", range, null), DATA.length, ETAG); }

    private static void assertSlice(HttpRange.Slice slice, int status, long start, long end) {
        assertEquals(status, slice.status());
        if (status != 416) { assertEquals(start, slice.start()); assertEquals(end, slice.end()); }
    }

    @Test void noRangeIsFull() { assertSlice(parse(null), 200, 0, 99); assertSlice(parse("  "), 200, 0, 99); }

    @Test void closedOpenAndClampedRanges() {
        assertSlice(parse("bytes=0-31"), 206, 0, 31);
        assertSlice(parse("bytes=32-"), 206, 32, 99);
        assertSlice(parse("bytes=90-5000"), 206, 90, 99);
        assertSlice(parse("BYTES=0-0"), 206, 0, 0);
        assertEquals(1, parse("bytes=0-0").length());
    }

    @Test void suffixRange() {
        assertSlice(parse("bytes=-32"), 206, 68, 99);
        assertEquals(32, parse("bytes=-32").length());
        assertSlice(parse("bytes=-100"), 206, 0, 99);
        assertSlice(parse("bytes=-5000"), 206, 0, 99);
        assertSlice(parse("bytes=-99999999999999999999999"), 206, 0, 99);
        assertSlice(parse("bytes=-0"), 416, 0, 0);
    }

    @Test void unsatisfiableRangesAre416WithoutThrowing() {
        assertSlice(parse("bytes=100-"), 416, 0, 0);
        assertSlice(parse("bytes=500-600"), 416, 0, 0);
        assertSlice(parse("bytes=99999999999999999999999-"), 416, 0, 0);
        assertSlice(parse("bytes=0-99999999999999999999999"), 206, 0, 99);
        assertSlice(HttpRange.parse(request("GET", "bytes=-1", null), 0, ETAG), 416, 0, 0);
    }

    @Test void invalidOrMultipleRangesAreIgnored() {
        for (String range : new String[]{"bytes=-", "bytes=5-2", "bytes=0-1,5-6", "items=0-1", "bytes=a-b", "0-1"}) {
            assertSlice(parse(range), 200, 0, 99);
        }
        assertSlice(parse(" bytes=0-1 "), 206, 0, 1);  // surrounding whitespace is trimmed
    }

    @Test void headIgnoresRangeAndKeepsFullLength() {
        var slice = HttpRange.parse(request("HEAD", "bytes=0-31", null), 100, ETAG);
        assertSlice(slice, 200, 0, 99);
        assertEquals(100, slice.length());
    }

    @Test void onlyMatchingStrongIfRangeAllowsPartialContent() {
        assertSlice(HttpRange.parse(request("GET", "bytes=2-4", ETAG), DATA.length, ETAG), 206, 2, 4);
        for (String ifRange : new String[]{"\"different\"", "W/" + ETAG, "Wed, 21 Oct 2015 07:28:00 GMT"}) {
            assertSlice(HttpRange.parse(request("GET", "bytes=2-4", ifRange), DATA.length, ETAG), 200, 0, 99);
        }
    }

    private record Output(Map<String, String> headers, int[] status, ByteArrayOutputStream body) { }

    private static Output send(HttpRange.Slice slice, String filename, boolean sendBody) throws IOException {
        return send(slice, filename, sendBody,
                (offset, length) -> new ByteArrayInputStream(DATA, (int) offset, (int) length));
    }

    private static Output send(HttpRange.Slice slice, String filename, boolean sendBody,
                               HttpRange.StreamOpen open) throws IOException {
        var out = new Output(new HashMap<>(), new int[]{200}, new ByteArrayOutputStream());
        var stream = new ServletOutputStream() {
            @Override public boolean isReady() { return true; }
            @Override public void setWriteListener(WriteListener listener) { }
            @Override public void write(int b) { out.body().write(b); }
            @Override public void write(byte[] b, int off, int len) { out.body().write(b, off, len); }
        };
        var response = (HttpServletResponse) Proxy.newProxyInstance(HttpRangeTest.class.getClassLoader(),
            new Class<?>[]{HttpServletResponse.class}, (proxy, m, args) -> {
                switch (m.getName()) {
                    case "setHeader" -> out.headers().put((String) args[0], (String) args[1]);
                    case "setStatus" -> out.status()[0] = (Integer) args[0];
                    case "setContentLength" -> out.headers().put("Content-Length", String.valueOf(args[0]));
                    case "setContentLengthLong" -> out.headers().put("Content-Length", String.valueOf(args[0]));
                    case "getOutputStream" -> { return stream; }
                    default -> throw new UnsupportedOperationException(m.getName());
                }
                return null;
            });
        HttpRange.write(response, slice, ETAG, "application/octet-stream", filename, sendBody, open);
        return out;
    }

    @Test void partialResponseCarriesExactBytesAndContentRange() throws IOException {
        var out = send(parse("bytes=-32"), null, true);
        assertEquals(206, out.status()[0]);
        assertEquals("bytes 68-99/100", out.headers().get("Content-Range"));
        assertEquals("32", out.headers().get("Content-Length"));
        assertArrayEquals(Arrays.copyOfRange(DATA, 68, 100), out.body().toByteArray());
        assertEquals(ETAG, out.headers().get("ETag"));
        assertEquals("bytes", out.headers().get("Accept-Ranges"));
        assertEquals("no-store, no-transform", out.headers().get("Cache-Control"));
    }

    @Test void unsatisfiableResponseHasStarSizeAndNoBody() throws IOException {
        var out = send(parse("bytes=200-"), null, true);
        assertEquals(416, out.status()[0]);
        assertEquals("bytes */100", out.headers().get("Content-Range"));
        assertEquals(0, out.body().size());
    }

    @Test void headResponseHasLengthButNoBody() throws IOException {
        var out = send(HttpRange.parse(request("HEAD", null, null), 100, ETAG), null, false);
        assertEquals(200, out.status()[0]);
        assertEquals("100", out.headers().get("Content-Length"));
        assertEquals(0, out.body().size());
    }

    @Test void attachmentOnlyWhenFilenameGiven() throws IOException {
        assertFalse(send(parse(null), null, true).headers().containsKey("Content-Disposition"));
        assertFalse(send(parse(null), " ", true).headers().containsKey("Content-Disposition"));
        for (String filename : new String[]{"模型 a+b[1].ply", "café's texture.png"}) {
            String header = send(parse(null), filename, true).headers().get("Content-Disposition");
            assertTrue(header.startsWith("attachment;"));
            String encoded = header.substring(header.indexOf("filename*=UTF-8''") + "filename*=UTF-8''".length());
            // RFC 5987 的 + 是字面量，不是表单空格；独立解码后应完整保留文件名。
            assertEquals(filename, java.net.URLDecoder.decode(encoded.replace("+", "%2B"), StandardCharsets.UTF_8));
            assertTrue(header.chars().allMatch(c -> c >= 32 && c < 127));
        }
    }

    @Test void noBodyResponsesNeverOpenStorage() throws IOException {
        HttpRange.StreamOpen forbidden = (offset, length) -> { throw new AssertionError("unexpected body read"); };
        send(parse("bytes=200-"), null, true, forbidden);
        send(parse(null), null, false, forbidden);
        send(HttpRange.parse(request("GET", null, null), 0, ETAG), null, true, forbidden);
    }

    @Test void truncatedStorageFailsAndClosesStream() {
        boolean[] closed = {false};
        var truncated = new ByteArrayInputStream(new byte[]{1, 2}) {
            @Override public void close() throws IOException { closed[0] = true; super.close(); }
        };
        assertThrows(IOException.class,
                () -> send(parse("bytes=0-4"), null, true, (offset, length) -> truncated));
        assertTrue(closed[0]);
    }

    @Test void responseDoesNotReadBeyondDeclaredSlice() throws IOException {
        var input = new ByteArrayInputStream(DATA);
        var out = send(parse("bytes=0-4"), null, true, (offset, length) -> input);
        assertArrayEquals(Arrays.copyOfRange(DATA, 0, 5), out.body().toByteArray());
        assertEquals(DATA[5] & 0xff, input.read());
    }
}
