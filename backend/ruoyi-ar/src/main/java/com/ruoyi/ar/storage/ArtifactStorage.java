package com.ruoyi.ar.storage;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * 私有文件存储边界，不读写业务表，也不判断授权、文件就绪状态或场景发布状态。
 * 文件按 UUID 定位；物理提交与数据库状态更新分开，由 Service 编排事务和恢复。
 */
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

    /** 磁盘盘点快照；大小和修改时间不是完整性或数据库归属证明。 */
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

    /** 打开已提交正文；调用方负责授权、与删除互斥及关闭流，读取时不重新计算 SHA256。 */
    InputStream open(UUID id) throws IOException;

    /** 范围必须位于已提交文件内；允许文件末尾零长度，关闭范围流同时关闭底层文件。 */
    InputStream open(UUID id, long offset, long length) throws IOException;

    /** 文件不存在时抛 IOException。 */
    long size(UUID id) throws IOException;

    /** 锁内删除该文件的所有存储阶段，可重复调用。 */
    void delete(UUID id) throws IOException;

    /** 只盘点文件，不与数据库对账或自动清理；并发写入时不保证一致快照。 */
    List<Entry> inventory() throws IOException;
}
