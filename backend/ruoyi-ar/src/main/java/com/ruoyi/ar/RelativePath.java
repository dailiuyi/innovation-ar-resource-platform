package com.ruoyi.ar;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 导入目录里文件的相对路径规则：只用于导出和展示，服务端存储始终用 UUID.bin，从不用这些名字落盘。
 * 规则按“能在 Windows、macOS、Linux 上安全还原”来定：拒绝绝对路径、反斜杠、越界片段、
 * Windows 保留名和不可见字符，并统一为 Unicode NFC。
 */
public final class RelativePath {
    public static final int MAX_PATH = 1024;
    public static final int MAX_SEGMENT = 255;
    public static final int MAX_DEPTH = 32;
    /**
     * Windows 设备保留名（CON、NUL、COM1…），带不带扩展名都不能做文件名。
     */
    private static final Pattern RESERVED = Pattern.compile("^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\\..*)?$", Pattern.CASE_INSENSITIVE);

    private RelativePath() {
    }

    /**
     * 校验并规范化单个相对路径，返回 NFC 形式；不合法抛 IllegalArgumentException，消息可直接展示给用户。
     * 校验顺序：空值 → 空字符 → 总长度 → 绝对路径（含盘符）→ 反斜杠 → NFC 后的斜杠格式 → 层级 → 逐段检查。
     */
    public static String normalizeOne(String raw) {
        if (raw == null || raw.isEmpty()) throw new IllegalArgumentException("相对路径不能为空");
        if (raw.indexOf('\0') >= 0) throw new IllegalArgumentException("相对路径不能包含空字符");
        if (raw.length() > MAX_PATH) throw new IllegalArgumentException("相对路径过长");
        if (raw.startsWith("/") || raw.startsWith("\\") || raw.startsWith("//")
                || (raw.length() >= 2 && Character.isLetter(raw.charAt(0)) && raw.charAt(1) == ':')) {
            throw new IllegalArgumentException("相对路径不能为绝对路径");
        }
        if (raw.indexOf('\\') >= 0) throw new IllegalArgumentException("相对路径不能包含反斜杠");
        String path = Normalizer.normalize(raw, Normalizer.Form.NFC);
        if (path.startsWith("/") || path.endsWith("/") || path.contains("//")) {
            throw new IllegalArgumentException("相对路径格式不合法");
        }
        String[] parts = path.split("/", -1);
        if (parts.length == 0 || parts.length > MAX_DEPTH) throw new IllegalArgumentException("相对路径层级不合法");
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < parts.length; i++) {
            validateSegment(parts[i]);
            if (i > 0) out.append('/');
            out.append(parts[i]);
        }
        String result = out.toString();
        if (result.length() > MAX_PATH) throw new IllegalArgumentException("相对路径过长");
        return result;
    }

    /**
     * 校验一批路径并返回规范化结果（顺序与输入一致）。除逐个校验外，还检查整批之间的冲突：
     * 完全重复、NFC 或大小写折叠后相同（大小写不敏感的文件系统会互相覆盖），
     * 以及某路径同时被当作文件和目录（如 a 与 a/b）。
     */
    public static List<String> normalizeAll(List<String> paths) {
        List<String> result = new ArrayList<>(paths.size());
        Set<String> seen = new HashSet<>();
        Set<String> seenLower = new HashSet<>();
        for (String raw : paths) result.add(normalizeOne(raw));
        List<String> sorted = new ArrayList<>(result);
        sorted.sort(String::compareTo);
        for (String path : sorted) {
            if (!seen.add(path)) throw new IllegalArgumentException("相对路径重复");
            if (!seenLower.add(path.toLowerCase(Locale.ROOT)))
                throw new IllegalArgumentException("相对路径存在规范化或大小写冲突");
        }
        List<String> folded = new ArrayList<>();
        for (String path : result) folded.add(path.toLowerCase(Locale.ROOT));
        folded.sort(String::compareTo);
        for (int i = 0; i < folded.size(); i++) {
            String prefix = folded.get(i);
            for (int j = i + 1; j < folded.size(); j++) {
                String next = folded.get(j);
                if (!next.startsWith(prefix)) break;
                if (next.startsWith(prefix + "/")) throw new IllegalArgumentException("文件与目录路径冲突");
            }
        }
        return result;
    }

    /**
     * 把任意文件名转成确定性的安全导出路径。本身合法就原样（规范化后）返回；
     * 否则逐字符清洗，并去掉开头空格和结尾的点与空格，结果始终是单个片段（不含目录）。
     * 清洗后为空、为 . / .. 或是保留名时，改用 export-&lt;文件 id 前 8 位&gt; 加原扩展名（扩展名仅限 1~20 位字母数字）。
     * 最后截断到 255 字符。
     */
    public static String safeExportPath(String fileName, java.util.UUID fileId) {
        if (fileName == null || fileId == null) throw new IllegalArgumentException("相对路径不能为空");
        try {
            return normalizeOne(fileName);
        } catch (IllegalArgumentException ignored) {
        }
        String segment = fileName.replace('\\', '_');
        StringBuilder cleaned = new StringBuilder();
        for (int i = 0; i < segment.length(); i++) {
            char c = segment.charAt(i);
            cleaned.append(c < 32 || c == 127 || "<>:\"|?*".indexOf(c) >= 0 ? '_' : c);
        }
        segment = cleaned.toString().replaceAll("^[ ]+", "").replaceAll("[. ]+$", "");
        if (segment.isEmpty() || ".".equals(segment) || "..".equals(segment) || RESERVED.matcher(segment).matches()) {
            int dot = fileName.lastIndexOf('.');
            String ext = "";
            if (dot > 0 && fileName.substring(dot).matches("\\.[A-Za-z0-9]{1,20}")) ext = fileName.substring(dot);
            segment = "export-" + fileId.toString().substring(0, 8) + ext;
        }
        if (segment.length() > MAX_SEGMENT) segment = segment.substring(0, MAX_SEGMENT);
        return segment;
    }

    /**
     * 取最后一个 / 之后的部分；没有 / 时就是整个路径。
     */
    public static String fileName(String relativePath) {
        int index = relativePath.lastIndexOf('/');
        return index < 0 ? relativePath : relativePath.substring(index + 1);
    }

    /**
     * 校验单个路径片段：不能为空、不能过长、不能是 . 或 ..、不能以空格开头或以空格/点结尾、不含控制字符和 Windows 非法字符、不是保留名。
     */
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
