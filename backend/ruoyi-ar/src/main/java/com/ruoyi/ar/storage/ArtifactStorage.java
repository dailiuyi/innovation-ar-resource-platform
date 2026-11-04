package com.ruoyi.ar.storage;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** 负责文件存储；文件提交与场景发布是两个独立步骤。 */
public interface ArtifactStorage {
    /** 文件标识、预期大小和 SHA256，构造时校验格式。 */
    record Descriptor(UUID id, long bytes, String sha256) {
        public Descriptor {
            if (id == null || bytes < 0 || sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("Expected UUID, nonnegative size and lowercase SHA256");
            }
        }

        public String storageKey() {
            return id + ".bin";
        }
    }

    /** 存储阶段：PARTIAL 接收中，STAGED 校验通过，COMMITTED 已提交；均不代表业务发布。 */
    enum Phase {PARTIAL, STAGED, COMMITTED}

    record Entry(UUID id, Phase phase, long bytes, Instant modifiedAt) {
    }

    /** 完整残留与登记信息不符；抛出时未读取新上传流。 */
    class UnverifiedLeftoverException extends IOException {
        public UnverifiedLeftoverException(String message) {
            super(message);
        }
    }

    /**
     * 锁内接收并校验后提交；完整残留只校验复用，不覆盖、不读取新 input。
     * 提交中断可能留下暂存或正式文件，交给 recover 恢复；input 由调用方关闭。
     */
    void store(Descriptor expected, InputStream input) throws IOException;

    /** 校验完整残留并提交；没有完整字节返回 false，不匹配抛异常。 */
    boolean recover(Descriptor expected) throws IOException;

    /** 调用方负责授权及关闭流。 */
    InputStream open(UUID id) throws IOException;

    /** 范围必须位于已提交文件内。 */
    InputStream open(UUID id, long offset, long length) throws IOException;

    /** 文件不存在时抛 IOException。 */
    long size(UUID id) throws IOException;

    /** 锁内删除该文件的所有存储阶段，可重复调用。 */
    void delete(UUID id) throws IOException;

    /** 只盘点文件，不与数据库对账或自动清理。 */
    List<Entry> inventory() throws IOException;
}
