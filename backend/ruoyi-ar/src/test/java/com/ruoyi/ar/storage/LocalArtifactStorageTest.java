package com.ruoyi.ar.storage;

import static org.junit.jupiter.api.Assertions.*;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class LocalArtifactStorageTest {
    @TempDir Path root;
    private static final byte[] DATA = "synthetic artifact; no client format assumed".getBytes(java.nio.charset.StandardCharsets.UTF_8);

    private ArtifactStorage.Descriptor descriptor(UUID id, byte[] data) throws Exception {
        return new ArtifactStorage.Descriptor(id, data.length,
                HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data)));
    }

    /** Same length as DATA, different content. */
    private static byte[] sameLengthOther() {
        byte[] other = DATA.clone();
        other[0] ^= 1;
        return other;
    }

    private Path ready(ArtifactStorage.Descriptor d) { return root.resolve("staging/" + d.id() + ".ready"); }
    private Path part(ArtifactStorage.Descriptor d) { return root.resolve("staging/" + d.id() + ".part"); }
    private Path formal(ArtifactStorage.Descriptor d) { return root.resolve("committed/" + d.storageKey()); }

    private static byte[] read(ArtifactStorage storage, UUID id) throws IOException {
        try (InputStream stream = storage.open(id)) { return stream.readAllBytes(); }
    }

    /** A stream that fails the test if anyone reads it. */
    private static InputStream unread() {
        return new InputStream() {
            @Override public int read() { throw new AssertionError("input must not be consumed"); }
            @Override public int read(byte[] bytes, int offset, int length) { throw new AssertionError("input must not be consumed"); }
        };
    }

    private static void assertNothingStored(LocalArtifactStorage storage, ArtifactStorage.Descriptor d) throws IOException {
        assertTrue(storage.inventory().isEmpty());
        assertThrows(IOException.class, () -> storage.open(d.id()));
        assertThrows(IOException.class, () -> storage.size(d.id()));
    }

    @Test void storedBytesAreReadableIdenticalAndSurviveRestart() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        storage.store(expected, new ByteArrayInputStream(DATA));

        assertArrayEquals(DATA, read(storage, expected.id()));
        assertEquals(DATA.length, storage.size(expected.id()));
        var entries = storage.inventory();
        assertEquals(1, entries.size());
        assertEquals(ArtifactStorage.Phase.COMMITTED, entries.getFirst().phase());
        assertEquals(expected.id() + ".bin", expected.storageKey());

        var restarted = new LocalArtifactStorage(root, 1024);
        assertArrayEquals(DATA, read(restarted, expected.id()));
        assertEquals(1, restarted.inventory().size());
    }

    @Test void emptyArtifactCanBeStored() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), new byte[0]);
        storage.store(expected, new ByteArrayInputStream(new byte[0]));
        assertEquals(0, storage.size(expected.id()));
        assertEquals(0, read(storage, expected.id()).length);
    }

    @Test void sameLengthDifferentBytesAreRejectedAndLeaveNoReadableFile() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(sameLengthOther())));
        assertNothingStored(storage, expected);
        assertFalse(Files.exists(formal(expected)));

        storage.store(expected, new ByteArrayInputStream(DATA));
        assertArrayEquals(DATA, read(storage, expected.id()));
    }

    @Test void wrongSizesAndConfiguredLimitAreRejectedWithoutResidue() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(Arrays.copyOf(DATA, DATA.length + 1))));
        assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(Arrays.copyOf(DATA, DATA.length - 1))));
        assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(new byte[0])));
        assertNothingStored(storage, expected);

        var small = new LocalArtifactStorage(root, 1);
        assertThrows(IOException.class, () -> small.store(expected, new ByteArrayInputStream(DATA)));
        assertNothingStored(storage, expected);
    }

    @Test void interruptedInputLeavesNothingAndCanBeRetried() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        InputStream failing = new InputStream() {
            private int calls;
            @Override public int read() throws IOException { throw new IOException("Injected transport failure"); }
            @Override public int read(byte[] bytes) throws IOException {
                if (calls++ == 0) { bytes[0] = DATA[0]; return 1; }
                throw new IOException("Injected transport failure");
            }
        };
        assertThrows(IOException.class, () -> storage.store(expected, failing));
        assertNothingStored(storage, expected);

        storage.store(expected, new ByteArrayInputStream(DATA));
        assertArrayEquals(DATA, read(storage, expected.id()));
    }

    @Test void largePayloadSpanningManyBuffersIsStoredExactly() throws Exception {
        byte[] large = new byte[3 * 64 * 1024 + 17];
        new java.util.Random(7).nextBytes(large);
        var storage = new LocalArtifactStorage(root, large.length);
        var expected = descriptor(UUID.randomUUID(), large);
        storage.store(expected, new ByteArrayInputStream(large));
        assertArrayEquals(large, read(storage, expected.id()));
    }

    @Test void repeatedStoreNeverOverwritesAndDoesNotConsumeInput() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        storage.store(expected, new ByteArrayInputStream(DATA));
        Object before = Files.readAttributes(formal(expected), java.nio.file.attribute.BasicFileAttributes.class).fileKey();

        storage.store(expected, unread());

        assertEquals(before, Files.readAttributes(formal(expected), java.nio.file.attribute.BasicFileAttributes.class).fileKey());
        assertArrayEquals(DATA, read(storage, expected.id()));
        assertEquals(1, storage.inventory().size());

        var conflicting = descriptor(expected.id(), sameLengthOther());
        assertThrows(IOException.class, () -> storage.store(conflicting, new ByteArrayInputStream(sameLengthOther())));
        assertArrayEquals(DATA, read(storage, expected.id()));
    }

    @Test void storeReplacesStalePartialFromInterruptedAttempt() throws Exception {
        new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        Files.write(part(expected), new byte[] {1, 2});
        var restarted = new LocalArtifactStorage(root, 1024);
        assertEquals(ArtifactStorage.Phase.PARTIAL, restarted.inventory().getFirst().phase());

        restarted.store(expected, new ByteArrayInputStream(DATA));

        assertArrayEquals(DATA, read(restarted, expected.id()));
        assertEquals(1, restarted.inventory().size());
        assertFalse(Files.exists(part(expected)));
    }

    @Test void storeFinishesCompleteBytesLeftByInterruptedAttempt() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        Files.write(ready(expected), DATA);

        storage.store(expected, unread());

        assertArrayEquals(DATA, read(storage, expected.id()));
        assertFalse(Files.exists(ready(expected)));
    }

    @Test void storeRejectsLeftoverReadyBytesThatDoNotMatch() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        Files.write(ready(expected), sameLengthOther());

        assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(DATA)));
        assertThrows(IOException.class, () -> storage.open(expected.id()));
        assertFalse(Files.exists(formal(expected)));
    }

    @Test void recoverCompletesReadyBytesWithoutDuplicateWrite() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        Files.write(ready(expected), DATA);
        assertEquals(ArtifactStorage.Phase.STAGED, storage.inventory().getFirst().phase());
        assertThrows(IOException.class, () -> storage.open(expected.id()));

        var restarted = new LocalArtifactStorage(root, 1024);
        assertTrue(restarted.recover(expected));

        assertArrayEquals(DATA, read(restarted, expected.id()));
        assertEquals(1, restarted.inventory().size());
        assertEquals(ArtifactStorage.Phase.COMMITTED, restarted.inventory().getFirst().phase());
        assertTrue(restarted.recover(expected));
        assertArrayEquals(DATA, read(restarted, expected.id()));
    }

    @Test void recoverCleansReadyLeftBesideCommittedAfterCrashAtLinkTime() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        Files.write(ready(expected), DATA);
        Files.createLink(formal(expected), ready(expected));
        var restarted = new LocalArtifactStorage(root, 1024);
        assertEquals(2, restarted.inventory().size());

        assertTrue(restarted.recover(expected));

        assertEquals(1, restarted.inventory().size());
        assertFalse(Files.exists(ready(expected)));
        assertArrayEquals(DATA, read(restarted, expected.id()));
    }

    @Test void recoverAcceptsAlreadyCommittedAndRemovesUnrelatedReadyCopy() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        storage.store(expected, new ByteArrayInputStream(DATA));
        Files.write(ready(expected), new byte[] {9});

        assertTrue(storage.recover(expected));

        assertFalse(Files.exists(ready(expected)));
        assertArrayEquals(DATA, read(storage, expected.id()));
    }

    @Test void recoverRejectsCorruptRetainedBytesAndKeepsExplicitFailure() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var corruptReady = descriptor(UUID.randomUUID(), DATA);
        Files.write(ready(corruptReady), sameLengthOther());
        assertThrows(IOException.class, () -> storage.recover(corruptReady));
        assertThrows(IOException.class, () -> storage.open(corruptReady.id()));
        assertFalse(Files.exists(formal(corruptReady)));

        var corruptCommitted = descriptor(UUID.randomUUID(), DATA);
        storage.store(corruptCommitted, new ByteArrayInputStream(DATA));
        Files.write(formal(corruptCommitted), sameLengthOther());
        assertThrows(IOException.class, () -> storage.recover(corruptCommitted));

        var truncated = descriptor(UUID.randomUUID(), DATA);
        Files.write(ready(truncated), Arrays.copyOf(DATA, DATA.length - 1));
        assertThrows(IOException.class, () -> storage.recover(truncated));
        assertFalse(Files.exists(formal(truncated)));
    }

    @Test void partialBytesAreNeverRecoveredAsComplete() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        assertFalse(storage.recover(expected));

        Files.write(part(expected), DATA);
        assertFalse(storage.recover(expected));
        assertThrows(IOException.class, () -> storage.open(expected.id()));
        assertFalse(Files.exists(formal(expected)));
        assertEquals(ArtifactStorage.Phase.PARTIAL, storage.inventory().getFirst().phase());
    }

    @Test void physicalDeleteRemovesAllPayloadsButPreservesOtherIdsAndLock() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var selected = descriptor(UUID.randomUUID(), DATA);
        var other = descriptor(UUID.randomUUID(), DATA);
        storage.store(selected, new ByteArrayInputStream(DATA));
        storage.store(other, new ByteArrayInputStream(DATA));
        Files.write(part(selected), DATA);
        Files.write(ready(selected), DATA);

        storage.delete(selected.id());
        storage.delete(selected.id());

        assertFalse(Files.exists(formal(selected)));
        assertFalse(Files.exists(part(selected)));
        assertFalse(Files.exists(ready(selected)));
        assertTrue(Files.exists(root.resolve("locks/" + selected.id() + ".lock")));
        assertArrayEquals(DATA, read(storage, other.id()));
        assertEquals(1, storage.inventory().size());
    }

    @Test void physicalDeleteFailsClosedForNonRegularTargetsAndBusyLocks() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var id = UUID.randomUUID();
        Path invalid = root.resolve("committed/" + id + ".bin");
        Files.createDirectory(invalid);
        Files.write(root.resolve("staging/" + id + ".part"), DATA);
        assertThrows(IOException.class, () -> storage.delete(id));
        assertTrue(Files.exists(root.resolve("staging/" + id + ".part")));
        Files.delete(invalid);
        try (var channel = FileChannel.open(root.resolve("locks/" + id + ".lock"), StandardOpenOption.CREATE, StandardOpenOption.WRITE);
             var lock = channel.lock()) {
            assertThrows(IOException.class, () -> storage.delete(id));
        }
        storage.delete(id);
        assertTrue(storage.inventory().isEmpty());
    }

    @Test void concurrentWriterReceivesRetryableFailure() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        try (var channel = FileChannel.open(root.resolve("locks/" + expected.id() + ".lock"),
                StandardOpenOption.CREATE, StandardOpenOption.WRITE); var lock = channel.lock()) {
            assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(DATA)));
            assertThrows(IOException.class, () -> storage.recover(expected));
        }
        assertNothingStored(storage, expected);
        storage.store(expected, new ByteArrayInputStream(DATA));
        assertArrayEquals(DATA, read(storage, expected.id()));
    }

    @Test void rangeOpenReturnsRequestedSliceAndRejectsBounds() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        storage.store(expected, new ByteArrayInputStream(DATA));
        assertEquals(DATA.length, storage.size(expected.id()));
        try (InputStream slice = storage.open(expected.id(), 2, 3)) {
            assertArrayEquals(Arrays.copyOfRange(DATA, 2, 5), slice.readAllBytes());
        }
        try (InputStream empty = storage.open(expected.id(), DATA.length, 0)) {
            assertEquals(0, empty.readAllBytes().length);
        }
        assertThrows(IOException.class, () -> storage.open(expected.id(), DATA.length, 1));
        assertThrows(IOException.class, () -> storage.open(expected.id(), -1, 1));
    }

    @Test void invalidDescriptorCannotIntroducePaths() {
        assertThrows(IllegalArgumentException.class, () -> new ArtifactStorage.Descriptor(null, 1, "../file"));
        assertThrows(IllegalArgumentException.class, () -> new ArtifactStorage.Descriptor(UUID.randomUUID(), -1, "0".repeat(64)));
        assertThrows(IllegalArgumentException.class, () -> new LocalArtifactStorage(root, 0));
    }

    @Test void nonRegularEntriesFailClosed() throws Exception {
        var storage = new LocalArtifactStorage(root, 1024);
        var expected = descriptor(UUID.randomUUID(), DATA);
        Files.createDirectory(formal(expected));
        assertThrows(IOException.class, () -> storage.open(expected.id()));
        assertThrows(IOException.class, () -> storage.store(expected, new ByteArrayInputStream(DATA)));
        assertThrows(IOException.class, () -> storage.recover(expected));
        assertThrows(IOException.class, storage::inventory);
    }
}
