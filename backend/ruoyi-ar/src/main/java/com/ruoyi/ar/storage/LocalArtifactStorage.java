package com.ruoyi.ar.storage;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * 单机本地文件系统存储，要求私有卷、支持文件锁和硬链接；只有本组件可以写这些目录，不支持共享盘或 NFS。
 *
 * <p>目录布局（根目录下）：
 * <ul>
 *   <li>{@code staging/<uuid>.part}：正在接收的内容；</li>
 *   <li>{@code staging/<uuid>.ready}：已接收且大小、SHA256 校验通过，等待发布；</li>
 *   <li>{@code committed/<uuid>.bin}：正式文件，对外读取只看这里；</li>
 *   <li>{@code locks/<uuid>.lock}：每个文件一把文件锁，保护写入、恢复和删除。</li>
 * </ul>
 * 文件名只用 UUID，从不使用用户提供的名字；所有路径操作都不跟随符号链接。
 */
public final class LocalArtifactStorage implements ArtifactStorage {
    /** 三个子目录：接收暂存、正式文件、文件锁。同在一个卷上，保证 staging → committed 的硬链接和原子改名可用。 */
    private final Path staging;
    private final Path committed;
    private final Path locks;
    /** 单个文件的字节数上限，超过则拒绝存储。 */
    private final long maxBytes;

    /** 创建根目录和三个子目录；maxBytes 必须为正，根目录及其所有上级不能是符号链接。 */
    public LocalArtifactStorage(Path root, long maxBytes) throws IOException {
        if (maxBytes <= 0) throw new IllegalArgumentException("maxBytes must be positive");
        Path absolute = root.toAbsolutePath().normalize();
        directory(absolute);
        staging = directory(absolute.resolve("staging"));
        committed = directory(absolute.resolve("committed"));
        locks = directory(absolute.resolve("locks"));
        this.maxBytes = maxBytes;
    }

    /** 确保目录存在且是真正的目录（不是符号链接）。 */
    private static Path directory(Path path) throws IOException {
        // 已存在的所有上级目录也不能是链接，不只检查最后一级
        for (Path current = path; current != null; current = current.getParent()) {
            if (Files.isSymbolicLink(current)) throw new IOException("Storage directories cannot be symbolic links");
        }
        Files.createDirectories(path);
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Storage directory unavailable");
        return path;
    }

    /** 拼出 {目录}/{uuid}{后缀}；该路径若已存在则必须是普通文件，不能是目录或链接。 */
    private static Path file(Path directory, UUID id, String suffix) throws IOException {
        Path result = directory.resolve(Objects.requireNonNull(id).toString() + suffix);
        if (Files.exists(result, LinkOption.NOFOLLOW_LINKS)
                && !Files.isRegularFile(result, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Storage entry must be a regular file");
        }
        return result;
    }

    /**
     * 存储流程：在文件锁内，若已有完整字节（.bin 或 .ready）就只校验、不覆盖，并且不读取 input；
     * 否则写入 .part，边写边算大小和 SHA256，校验通过后改名为 .ready，最后硬链接成 .bin 并删除 .ready。
     * 任何一步失败都会删除 .part，不留下可读的正式文件。拿不到文件锁时抛 IOException，由调用方重试。
     */
    @Override
    public void store(Descriptor expected, InputStream input) throws IOException {
        Objects.requireNonNull(input);
        if (expected.bytes() > maxBytes) throw new IOException("Artifact exceeds configured storage limit");
        locked(expected.id(), () -> {
            Path target = file(committed, expected.id(), ".bin");
            Path ready = file(staging, expected.id(), ".ready");
            // 已有上一次留下的完整字节：只校验一次，绝不覆盖
            if (Files.exists(target) || Files.exists(ready)) { recoverLocked(expected, target, ready); return null; }
            Path partial = file(staging, expected.id(), ".part");
            // 持有文件锁，说明没有活跃的写入者，上一次中断留下的 .part 可以直接丢弃
            Files.deleteIfExists(partial);
            try {
                receive(expected, input, partial);
                // staging 与 committed 在同一个卷上，改名是原子的
                Files.move(partial, ready, StandardCopyOption.ATOMIC_MOVE);
            } catch (IOException | RuntimeException error) {
                try { Files.deleteIfExists(partial); } catch (IOException cleanup) { error.addSuppressed(cleanup); }
                throw error;
            }
            publish(target, ready);
            return null;
        });
    }

    /** 恢复一次被中断的写入：把留下的完整字节校验后发布；没有完整字节返回 false。 */
    @Override
    public boolean recover(Descriptor expected) throws IOException {
        return locked(expected.id(), () -> recoverLocked(expected,
                file(committed, expected.id(), ".bin"), file(staging, expected.id(), ".ready")));
    }

    /** 最多算一次摘要，对象是实际保留下来的字节。调用方须持有文件锁。 */
    private static boolean recoverLocked(Descriptor expected, Path target, Path ready) throws IOException {
        if (Files.exists(target)) {
            // .bin 校验通过后，旁边的 .ready 只是多余的链接（或副本），不读直接删
            verifyFile(target, expected);
            Files.deleteIfExists(ready);
            return true;
        }
        if (!Files.exists(ready)) return false;
        verifyFile(ready, expected);
        publish(target, ready);
        return true;
    }

    /** 把输入恰好收下 expected.bytes() 个字节写入新的 .part 文件，同一遍里计算 SHA256，最后 fsync。多收、少收或摘要不符都抛异常。 */
    private static void receive(Descriptor expected, InputStream input, Path partial) throws IOException {
        MessageDigest digest = sha256();
        long count = 0;
        try (FileChannel output = FileChannel.open(partial, StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer = new byte[64 * 1024];
            ByteBuffer window = ByteBuffer.wrap(buffer);
            int read;
            while ((read = input.read(buffer)) != -1) {
                if (read == 0) continue;
                if (read > expected.bytes() - count) throw new IOException("Artifact size mismatch");
                count += read;
                digest.update(buffer, 0, read);
                window.clear().limit(read);
                while (window.hasRemaining()) output.write(window);
            }
            if (count != expected.bytes()) throw new IOException("Artifact size mismatch");
            if (!HexFormat.of().formatHex(digest.digest()).equals(expected.sha256())) {
                throw new IOException("Artifact SHA256 mismatch");
            }
            output.force(true);
        }
    }

    /**
     * 既要原子可见又不能覆盖：硬链接在目标已存在时会失败，而 ATOMIC_MOVE 可能替换掉目标。
     * 文件系统不支持硬链接时直接失败，绝不退化成复制出一个可见的半成品。
     */
    private static void publish(Path target, Path ready) throws IOException {
        Files.createLink(target, ready);
        Files.delete(ready);
    }

    /** 校验文件是普通文件、长度和 SHA256 都与登记值一致；不一致抛 UnverifiedLeftoverException。 */
    private static void verifyFile(Path path, Descriptor expected) throws IOException {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) != expected.bytes()) {
            throw new ArtifactStorage.UnverifiedLeftoverException("Artifact missing or size mismatch");
        }
        MessageDigest digest = sha256();
        try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        if (!HexFormat.of().formatHex(digest.digest()).equals(expected.sha256())) {
            throw new ArtifactStorage.UnverifiedLeftoverException("Artifact SHA256 mismatch");
        }
    }

    /** 不加锁读取整个正式文件；调用方负责授权和关闭流。 */
    @Override
    public InputStream open(UUID id) throws IOException {
        return Files.newInputStream(file(committed, id, ".bin"), LinkOption.NOFOLLOW_LINKS);
    }

    /** 正式文件的字节数；不存在或不是普通文件抛 IOException。 */
    @Override
    public long size(UUID id) throws IOException {
        Path path = file(committed, id, ".bin");
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Artifact missing");
        return Files.size(path);
    }

    /** 读取正式文件的一段：offset 与 length 越界抛异常；返回的流最多给出 length 个字节。 */
    @Override
    public InputStream open(UUID id, long offset, long length) throws IOException {
        Path path = file(committed, id, ".bin");
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Artifact missing");
        long size = Files.size(path);
        if (offset < 0 || length < 0 || offset > size || offset + length > size) throw new IOException("Invalid range");
        FileChannel channel = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS);
        channel.position(offset);
        return new BoundedInputStream(Channels.newInputStream(channel), length);
    }

    /** 在文件锁内删除该 id 的 .part、.ready 和 .bin，不存在也不报错。 */
    @Override
    public void delete(UUID id) throws IOException {
        locked(id, () -> {
            // 先确认三个确切的 UUID 路径都合法，再逐个删除；不递归，不跟随链接
            Path partial = file(staging, id, ".part");
            Path ready = file(staging, id, ".ready");
            Path target = file(committed, id, ".bin");
            Files.deleteIfExists(partial);
            Files.deleteIfExists(ready);
            Files.deleteIfExists(target);
            // Keep the zero-byte lock inode; deleting it could split mutual exclusion.
            return null;
        });
    }

    /** 盘点三类文件（接收中、已就绪、已提交），按 id 和阶段排序；带对应后缀但名字不规范的条目直接抛异常，不静默忽略。 */
    @Override
    public List<Entry> inventory() throws IOException {
        List<Entry> result = new ArrayList<>();
        collect(staging, ".part", Phase.PARTIAL, result);
        collect(staging, ".ready", Phase.STAGED, result);
        collect(committed, ".bin", Phase.COMMITTED, result);
        result.sort(Comparator.comparing((Entry entry) -> entry.id().toString()).thenComparing(Entry::phase));
        return List.copyOf(result);
    }

    /** 列出目录里指定后缀的文件并转成盘点条目；名字必须是规范小写 UUID 加后缀，且是普通文件。 */
    private static void collect(Path directory, String suffix, Phase phase, List<Entry> result) throws IOException {
        try (var files = Files.list(directory)) {
            for (Path path : files.filter(p -> p.getFileName().toString().endsWith(suffix)).toList()) {
                String name = path.getFileName().toString();
                UUID id;
                try { id = UUID.fromString(name.substring(0, name.length() - suffix.length())); }
                catch (IllegalArgumentException error) { throw new IOException("Unrecognized storage entry", error); }
                if (!name.equals(id + suffix) || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IOException("Invalid storage entry");
                }
                result.add(new Entry(id, phase, Files.size(path), Files.getLastModifiedTime(path).toInstant()));
            }
        }
    }

    /** 在该 id 的文件锁内执行 action。tryLock 不阻塞：别的进程或线程持锁时立即抛 IOException，由上层决定重试。 */
    private <T> T locked(UUID id, IoAction<T> action) throws IOException {
        // 锁文件保留不删：删掉后不同进程可能锁住不同的 inode，互斥就失效了
        try (FileChannel channel = FileChannel.open(file(locks, id, ".lock"), StandardOpenOption.CREATE,
                StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
            try (FileLock lock = channel.tryLock()) {
                if (lock == null) throw new IOException("Artifact operation already in progress; retry later");
                return action.run();
            } catch (OverlappingFileLockException error) {
                throw new IOException("Artifact operation already in progress; retry later", error);
            }
        }
    }

    /** SHA-256 是 JDK 必备算法，取不到属于环境错误。 */
    private static MessageDigest sha256() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    /** 会抛出 IOException 的动作，供 {@link #locked} 使用。 */
    @FunctionalInterface
    private interface IoAction<T> { T run() throws IOException; }

    /** 限长输入流：最多读出 remaining 个字节后返回 -1，关闭时一并关闭底层流；用于 Range 读取。 */
    static final class BoundedInputStream extends InputStream {
        private final InputStream in;
        private long remaining;
        BoundedInputStream(InputStream in, long remaining) { this.in = in; this.remaining = remaining; }
        @Override public int read() throws IOException {
            if (remaining <= 0) return -1;
            int value = in.read();
            if (value >= 0) remaining--;
            return value;
        }
        @Override public int read(byte[] buffer, int offset, int length) throws IOException {
            if (remaining <= 0) return -1;
            int count = in.read(buffer, offset, (int)Math.min(length, remaining));
            if (count > 0) remaining -= count;
            return count;
        }
        @Override public void close() throws IOException { in.close(); }
    }
}
