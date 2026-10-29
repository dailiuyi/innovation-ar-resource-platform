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
 * Single-host storage on a private local filesystem supporting locks and hard links.
 * Only this component may write these directories. No shared/NFS volume is supported.
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
        // Reject links in all existing ancestors too, not just the final component.
        for (Path current = path; current != null; current = current.getParent()) {
            if (Files.isSymbolicLink(current)) throw new IOException("Storage directories cannot be symbolic links");
        }
        Files.createDirectories(path);
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Storage directory unavailable");
        return path;
    }

    private static Path file(Path directory, UUID id, String suffix) throws IOException {
        Path result = directory.resolve(Objects.requireNonNull(id).toString() + suffix);
        if (Files.exists(result, LinkOption.NOFOLLOW_LINKS)
                && !Files.isRegularFile(result, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Storage entry must be a regular file");
        }
        return result;
    }

    @Override
    public void store(Descriptor expected, InputStream input) throws IOException {
        Objects.requireNonNull(input);
        if (expected.bytes() > maxBytes) throw new IOException("Artifact exceeds configured storage limit");
        locked(expected.id(), () -> {
            Path target = file(committed, expected.id(), ".bin");
            Path ready = file(staging, expected.id(), ".ready");
            // Complete bytes from an earlier attempt: validate them once and never overwrite.
            if (Files.exists(target) || Files.exists(ready)) { recoverLocked(expected, target, ready); return null; }
            Path partial = file(staging, expected.id(), ".part");
            // The lock proves no active writer owns a previous interrupted attempt.
            Files.deleteIfExists(partial);
            try {
                receive(expected, input, partial);
                // Staging and committed directories live on the same volume.
                Files.move(partial, ready, StandardCopyOption.ATOMIC_MOVE);
            } catch (IOException | RuntimeException error) {
                try { Files.deleteIfExists(partial); } catch (IOException cleanup) { error.addSuppressed(cleanup); }
                throw error;
            }
            publish(target, ready);
            return null;
        });
    }

    @Override
    public boolean recover(Descriptor expected) throws IOException {
        return locked(expected.id(), () -> recoverLocked(expected,
                file(committed, expected.id(), ".bin"), file(staging, expected.id(), ".ready")));
    }

    /** One digest at most, over the bytes actually retained. Caller holds the file lock. */
    private static boolean recoverLocked(Descriptor expected, Path target, Path ready) throws IOException {
        if (Files.exists(target)) {
            // A ready entry beside a validated target is only a leftover link (or copy); drop it unread.
            verifyFile(target, expected);
            Files.deleteIfExists(ready);
            return true;
        }
        if (!Files.exists(ready)) return false;
        verifyFile(ready, expected);
        publish(target, ready);
        return true;
    }

    /** Receives exactly expected.bytes() into a new part file, hashing in the same pass. */
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
     * Atomic visibility AND no overwrite: a hard link fails if the target exists, unlike ATOMIC_MOVE which
     * may replace it. Unsupported filesystems fail closed; never fall back to a visible partial copy.
     */
    private static void publish(Path target, Path ready) throws IOException {
        Files.createLink(target, ready);
        Files.delete(ready);
    }

    private static void verifyFile(Path path, Descriptor expected) throws IOException {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) != expected.bytes()) {
            throw new IOException("Artifact missing or size mismatch");
        }
        MessageDigest digest = sha256();
        try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        if (!HexFormat.of().formatHex(digest.digest()).equals(expected.sha256())) {
            throw new IOException("Artifact SHA256 mismatch");
        }
    }

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

    @Override
    public void delete(UUID id) throws IOException {
        locked(id, () -> {
            // Validate every exact UUID path before deleting any entry. Never recurse or follow links.
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
                try { id = UUID.fromString(name.substring(0, name.length() - suffix.length())); }
                catch (IllegalArgumentException error) { throw new IOException("Unrecognized storage entry", error); }
                if (!name.equals(id + suffix) || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IOException("Invalid storage entry");
                }
                result.add(new Entry(id, phase, Files.size(path), Files.getLastModifiedTime(path).toInstant()));
            }
        }
    }

    private <T> T locked(UUID id, IoAction<T> action) throws IOException {
        // Keep lock files: unlinking them can allow different processes to lock different inodes.
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
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }

    @FunctionalInterface
    private interface IoAction<T> { T run() throws IOException; }

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
