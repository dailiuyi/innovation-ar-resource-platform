package com.ruoyi.ar.support;

import java.util.Locale;

/**
 * 文件清单和下载响应共用的 MIME 白名单；只看扩展名，不读取正文。
 * 不用系统探测或 Spring 全量映射：wav 保持 audio/wav，未知类型（含 HTML/SVG）按二进制下载。
 */
public final class FileContentType {
    private FileContentType() {
    }

    /** 输入为已校验的相对路径；扩展名不区分大小写，无扩展名时返回 application/octet-stream。 */
    public static String of(String path) {
        String name = RelativePath.fileName(path).toLowerCase(Locale.ROOT);
        int dot = name.lastIndexOf('.');
        return switch (dot < 0 ? "" : name.substring(dot + 1)) {
            case "json" -> "application/json";
            case "jpg", "jpeg" -> "image/jpeg";
            case "png" -> "image/png";
            case "webp" -> "image/webp";
            case "wav" -> "audio/wav";
            case "webm" -> "video/webm";
            default -> "application/octet-stream";
        };
    }
}
