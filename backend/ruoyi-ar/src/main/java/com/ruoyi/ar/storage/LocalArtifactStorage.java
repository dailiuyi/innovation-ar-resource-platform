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

import org.apache.commons.io.input.BoundedInputStream;

/**
 * 私有本地卷存储，要求支持文件锁、原子改名和硬链接。
 * staging 保存 .part/.ready，committed 保存正式 .bin，locks 保存文件锁。
 * 文件名只用 UUID，不使用用户路径，不跟随符号链接。
 * 该目录由服务独占管理；读删互斥由业务层版本锁承担，存储锁只串行化写入、恢复和删除。
 * 正文 force(true) 不等于目录项已持久化；这里保证进程中断后的恢复，不承诺掉电恢复。
 */
public final class LocalArtifactStorage implements ArtifactStorage {

    private final Path staging;
    private final Path committed;
    private final Path locks;

    private final long maxBytes;

    public LocalArtifactStorage(Path root, long maxBytes) throws IOException {
        if (maxBytes <= 0) throw new IllegalArgumentException("maxBytes must be positive");
        Path absolute = root.toAbsolutePath().normalize();
        directory(absolute);
        staging = directory(absolute.resolve("staging"));
        committed = directory(absolute.resolve("committed"));
        locks = directory(absolute.resolve("locks"));
        this.maxBytes = maxBytes;
    }

    private static Path directory(Path path) throws IOException {
        // 同时检查上级目录，避免经符号链接写入别处。
        for (Path current = path; current != null; current = current.getParent()) {
            if (Files.isSymbolicLink(current)) throw new IOException("Storage directories cannot be symbolic links");
        }
        Files.createDirectories(path);
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Storage directory unavailable");
        return path;
    }

    /** 已有路径必须是普通文件，拒绝目录或符号链接。 */
    private static Path file(Path directory, UUID id, String suffix) throws IOException {
        Path result = directory.resolve(Objects.requireNonNull(id).toString() + suffix);
        if (Files.exists(result, LinkOption.NOFOLLOW_LINKS)
                && !Files.isRegularFile(result, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Storage entry must be a regular file");
        }
        return result;
    }

    /**
     * 锁内接收并校验，再将 .part 改名为 .ready，硬链接为 .bin。
     * 完整残留只校验复用；提交中断可能留下 .ready/.bin，交给 recover 恢复。
     */
    @Override
    public void store(Descriptor expected, InputStream input) throws IOException {
        Objects.requireNonNull(input);
        if (expected.bytes() > maxBytes) throw new IOException("Artifact exceeds configured storage limit");
        locked(expected.id(), () -> {
            Path target = file(committed, expected.id(), ".bin");
            Path ready = file(staging, expected.id(), ".ready");
            // 完整残留校验后复用，不覆盖。
            if (Files.exists(target) || Files.exists(ready)) {
                recoverLocked(expected, target, ready);
                return null;
            }
            Path partial = file(staging, expected.id(), ".part");
            // 已持文件锁，可清理上次中断的 .part。
            Files.deleteIfExists(partial);
            try {
                receive(expected, input, partial);

                Files.move(partial, ready, StandardCopyOption.ATOMIC_MOVE);
            } catch (IOException | RuntimeException error) {
                try {
                    Files.deleteIfExists(partial);
                } catch (IOException cleanup) {
                    error.addSuppressed(cleanup);
                }
                throw error;
            }
            // 正式名与暂存名短暂共用同一份字节，不复制正文。
            publish(target, ready);
            return null;
        });
    }

    /** 校验并提交完整残留；无完整字节返回 false。 */
    @Override
    public boolean recover(Descriptor expected) throws IOException {
        return locked(expected.id(), () -> recoverLocked(expected,
                file(committed, expected.id(), ".bin"), file(staging, expected.id(), ".ready")));
    }

    /** 须持文件锁；只校验实际保留的完整字节一次。 */
    private static boolean recoverLocked(Descriptor expected, Path target, Path ready) throws IOException {
        if (Files.exists(target)) {
            // 正式文件校验通过后，直接清理多余的 .ready。
            verifyFile(target, expected);
            Files.deleteIfExists(ready);
            return true;
        }
        if (!Files.exists(ready)) return false;
        verifyFile(ready, expected);
        publish(target, ready);
        return true;
    }

    /** 接收时同时校验大小和 SHA256，成功后刷盘；多收、少收或摘要不符均失败。 */
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

    /** 用硬链接保证一次可见且不覆盖；ATOMIC_MOVE 可能覆盖目标，不能替代。 */
    private static void publish(Path target, Path ready) throws IOException {
        Files.createLink(target, ready);
        Files.delete(ready);
    }

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

    /** 读取不加文件锁，授权和读删互斥由上层负责。 */
    @Override
    public InputStream open(UUID id) throws IOException {
        return Files.newInputStream(file(committed, id, ".bin"), LinkOption.NOFOLLOW_LINKS);
    }

    @Override
    public long size(UUID id) throws IOException {
        Path path = file(committed, id, ".bin");
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Artifact missing");
        return Files.size(path);
    }

    /** 范围必须落在正式文件内，返回的流最多读取 length 字节。 */
    @Override
    public InputStream open(UUID id, long offset, long length) throws IOException {
        Path path = file(committed, id, ".bin");
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Artifact missing");
        long size = Files.size(path);
        // 用减法比较剩余长度，避免 offset + length 溢出后放过越界请求。
        if (offset < 0 || length < 0 || offset > size || length > size - offset) throw new IOException("Invalid range");
        FileChannel channel = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS);
        try {
            channel.position(offset);
            return BoundedInputStream.builder()
                    .setInputStream(Channels.newInputStream(channel))
                    .setMaxCount(length)
                    .setPropagateClose(true)
                    .get();
        } catch (IOException | RuntimeException error) {
            try {
                channel.close();
            } catch (IOException cleanup) {
                error.addSuppressed(cleanup);
            }
            throw error;
        }
    }

    @Override
    public void delete(UUID id) throws IOException {
        locked(id, () -> {

            Path partial = file(staging, id, ".part");
            Path ready = file(staging, id, ".ready");
            Path target = file(committed, id, ".bin");
            Files.deleteIfExists(partial);
            Files.deleteIfExists(ready);
            Files.deleteIfExists(target);
            // 保留锁文件，避免重建后出现两把互不相干的锁。
            return null;
        });
    }

    /** 盘点 .part/.ready/.bin；非规范名称或非普通文件直接报错。 */
    @Override
    public List<Entry> inventory() throws IOException {
        List<Entry> result = new ArrayList<>();
        collect(staging, ".part", Phase.PARTIAL, result);
        collect(staging, ".ready", Phase.STAGED, result);
        collect(committed, ".bin", Phase.COMMITTED, result);
        result.sort(Comparator.comparing((Entry entry) -> entry.id().toString()).thenComparing(Entry::phase));
        return List.copyOf(result);
    }

    private static void collect(Path directory, String suffix, Phase phase, List<Entry> result) throws IOException {
        try (var files = Files.list(directory)) {
            for (Path path : files.filter(p -> p.getFileName().toString().endsWith(suffix)).toList()) {
                String name = path.getFileName().toString();
                UUID id;
                try {
                    id = UUID.fromString(name.substring(0, name.length() - suffix.length()));
                } catch (IllegalArgumentException error) {
                    throw new IOException("Unrecognized storage entry", error);
                }
                if (!name.equals(id + suffix) || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IOException("Invalid storage entry");
                }
                result.add(new Entry(id, phase, Files.size(path), Files.getLastModifiedTime(path).toInstant()));
            }
        }
    }

    /** 文件锁不等待，争用时抛 IOException，由业务层决定重试。 */
    private <T> T locked(UUID id, IoAction<T> action) throws IOException {

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

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException(error);
        }
    }

    @FunctionalInterface
    private interface IoAction<T> {
        T run() throws IOException;
    }

}
