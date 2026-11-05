package com.ruoyi.ar.support;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 跨平台相对路径校验与 Unicode NFC 规范化工具。
 * <p>
 * <b>背景说明</b>：
 * 资源入库后的物理文件在服务端一律按 {@code <UUID>.bin} 独立存储，但清单中记录的相对路径
 * 将在终端（Windows / macOS / Linux / Android / iOS / Unity）下载并依此解压还原本土文件系统树。
 * 因此本工具实施跨平台最严交集约束：
 * <ul>
 *   <li>统一正斜杠 {@code /}，深度上限 32，路径总长 1024 字符，单片段 255 字符。</li>
 *   <li>禁止任何形式的绝对路径、反斜杠、空片段与目录回溯片段（{@code .}、{@code ..}）。</li>
 *   <li>拒绝 Windows 历史保留设备名称（如 CON、PRN、AUX、NUL、COM1~9、LPT1~9 及其变体）。</li>
 *   <li>拒绝非法控制字符与 Windows 不安全特殊字符（{@code <>:"|?*}）。</li>
 * </ul>
 */
public final class RelativePath {
    /** 长度按 Java UTF-16 字符单元计数，不是 UTF-8 字节数。 */
    public static final int MAX_PATH = 1024;
    public static final int MAX_SEGMENT = 255;
    public static final int MAX_DEPTH = 32;
    /** Windows 设备名含扩展名时仍不可用。 */
    private static final Pattern RESERVED = Pattern.compile("^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\\..*)?$", Pattern.CASE_INSENSITIVE);

    private RelativePath() {
    }

    /** 返回 NFC 路径；非法路径抛 IllegalArgumentException，原因可展示给用户。 */
    public static String normalizeOne(String raw) {
        if (raw == null || raw.isEmpty()) throw new IllegalArgumentException("相对路径不能为空");
        if (raw.indexOf('\0') >= 0) throw new IllegalArgumentException("相对路径不能包含空字符");
        if (raw.length() > MAX_PATH) throw new IllegalArgumentException("相对路径过长");
        if (raw.startsWith("/") || raw.startsWith("\\")
                || (raw.length() >= 2 && Character.isLetter(raw.charAt(0)) && raw.charAt(1) == ':')) {
            throw new IllegalArgumentException("相对路径不能为绝对路径");
        }
        if (raw.indexOf('\\') >= 0) throw new IllegalArgumentException("相对路径不能包含反斜杠");
        String path = Normalizer.normalize(raw, Normalizer.Form.NFC);
        if (path.startsWith("/") || path.endsWith("/") || path.contains("//")) {
            throw new IllegalArgumentException("相对路径格式不合法");
        }
        String[] parts = path.split("/", -1);
        if (parts.length > MAX_DEPTH) throw new IllegalArgumentException("相对路径层级不合法");
        for (String part : parts) validateSegment(part);
        if (path.length() > MAX_PATH) throw new IllegalArgumentException("相对路径过长");
        return path;
    }

    /** 规范化后检查重复、大小写冲突和文件/目录同名冲突，保留输入顺序。 */
    public static List<String> normalizeAll(List<String> paths) {
        List<String> result = new ArrayList<>(paths.size());
        Set<String> seen = new HashSet<>();
        Set<String> seenLower = new HashSet<>();
        for (String raw : paths) result.add(normalizeOne(raw));
        for (String path : result) {
            if (!seen.add(path)) throw new IllegalArgumentException("相对路径重复");
            if (!seenLower.add(path.toLowerCase(Locale.ROOT)))
                throw new IllegalArgumentException("相对路径存在规范化或大小写冲突");
        }
        // 检查每个目录前缀是否已登记为文件；相似名称（a 与 a.b）不是目录冲突。
        for (String path : seenLower) {
            for (int slash = path.indexOf('/'); slash >= 0; slash = path.indexOf('/', slash + 1)) {
                if (seenLower.contains(path.substring(0, slash)))
                    throw new IllegalArgumentException("文件与目录路径冲突");
            }
        }
        return result;
    }

    /** 提取已通过清单校验的 POSIX 相对路径末段；不访问文件系统。 */
    public static String fileName(String relativePath) {
        int index = relativePath.lastIndexOf('/');
        return index < 0 ? relativePath : relativePath.substring(index + 1);
    }

    private static void validateSegment(String segment) {
        if (segment.isEmpty()) throw new IllegalArgumentException("相对路径含有空片段");
        if (segment.length() > MAX_SEGMENT) throw new IllegalArgumentException("路径片段过长");
        if (".".equals(segment) || "..".equals(segment)) throw new IllegalArgumentException("相对路径不能包含越界片段");
        if (segment.charAt(0) == ' ' || segment.endsWith(" ") || segment.endsWith(".")) {
            throw new IllegalArgumentException("路径片段不能以空格开头，也不能以空格或点号结尾");
        }
        for (int i = 0; i < segment.length(); i++) {
            char c = segment.charAt(i);
            if (c < 32 || c == 127 || "<>:\"|?*".indexOf(c) >= 0) {
                throw new IllegalArgumentException("路径包含不能安全还原的字符");
            }
        }
        if (RESERVED.matcher(segment).matches()) throw new IllegalArgumentException("路径包含目标环境保留名称");
    }
}
