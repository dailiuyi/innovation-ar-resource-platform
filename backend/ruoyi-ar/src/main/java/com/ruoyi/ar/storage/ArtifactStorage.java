package com.ruoyi.ar.storage;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** File operations only. A committed file is not necessarily a published artifact. */
public interface ArtifactStorage {
    record Descriptor(UUID id, long bytes, String sha256) {
        public Descriptor {
            if (id == null || bytes < 0 || sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("Expected UUID, nonnegative size and lowercase SHA256");
            }
        }

        public String storageKey() { return id + ".bin"; }
    }

    enum Phase { PARTIAL, STAGED, COMMITTED }
    record Entry(UUID id, Phase phase, long bytes, Instant modifiedAt) { }

    /**
     * Receives, digests once, and atomically publishes the bytes under the per-file lock. A mismatch or
     * transport failure leaves no readable formal file. If complete bytes from an earlier attempt already
     * exist, they are validated once, never overwritten, and {@code input} is not consumed.
     * Caller owns the input stream. Retry uses the same descriptor.
     */
    void store(Descriptor expected, InputStream input) throws IOException;

    /**
     * Finishes an interrupted write from existing ready/committed bytes, validating the retained bytes at
     * most once. Returns false when no complete bytes exist (nothing or only a partial). Throws when the
     * retained bytes do not match {@code expected}.
     */
    boolean recover(Descriptor expected) throws IOException;

    /** Caller must authorize access and close the returned stream. No HTTP exposure here. */
    InputStream open(UUID id) throws IOException;

    /** Range open; offset+length must lie within the committed file. */
    InputStream open(UUID id, long offset, long length) throws IOException;

    long size(UUID id) throws IOException;

    /** Permanently removes this ID's partial, staged and committed bytes; idempotent under the file lock. */
    void delete(UUID id) throws IOException;

    /** Operational inventory, not a database reconciliation or automatic cleanup. */
    List<Entry> inventory() throws IOException;
}
