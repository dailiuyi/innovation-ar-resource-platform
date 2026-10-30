package com.ruoyi.ar.storage;

import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * 只负责文件操作；已提交（committed）的文件不等于已发布的产物，发布与否由数据库决定。
 */
public interface ArtifactStorage {
    /**
     * 登记的文件描述：文件 id、期望字节数和小写十六进制 SHA256。构造时校验格式。
     */
    record Descriptor(UUID id, long bytes, String sha256) {
        public Descriptor {
            if (id == null || bytes < 0 || sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("Expected UUID, nonnegative size and lowercase SHA256");
            }
        }

        /**
         * 存储内的文件名：只用 UUID 加 .bin，不使用用户提供的名字。
         */
        public String storageKey() {
            return id + ".bin";
        }
    }

    /**
     * 文件落盘阶段：PARTIAL 接收中，STAGED 已接收并校验、待发布，COMMITTED 已正式发布。
     */
    enum Phase {PARTIAL, STAGED, COMMITTED}

    /**
     * 盘点条目：文件 id、所处阶段、字节数和最后修改时间。
     */
    record Entry(UUID id, Phase phase, long bytes, Instant modifiedAt) {
    }

    /**
     * 存储里留有完整的 ready/committed 字节，但与登记的描述不符；此时没有读取传入的数据流。
     */
    class UnverifiedLeftoverException extends IOException {
        public UnverifiedLeftoverException(String message) {
            super(message);
        }
    }

    /**
     * 在按文件加的锁内接收数据、只计算一次摘要，并原子地发布。大小或摘要不符、传输中断，
     * 都不会留下可读的正式文件。若此前某次尝试已留下完整字节，则只校验一次，不覆盖，也不消费 {@code input}。
     * 输入流由调用方负责关闭；重试使用同一个描述。
     */
    void store(Descriptor expected, InputStream input) throws IOException;

    /**
     * 用已有的 ready/committed 字节完成一次被中断的写入，最多校验一次。
     * 没有完整字节（什么都没有或只有 partial）时返回 false；保留的字节与 {@code expected} 不符时抛异常。
     */
    boolean recover(Descriptor expected) throws IOException;

    /**
     * 调用方须先完成授权并负责关闭返回的流；这里不涉及 HTTP。
     */
    InputStream open(UUID id) throws IOException;

    /**
     * 按范围打开；offset + length 必须落在已提交文件之内。
     */
    InputStream open(UUID id, long offset, long length) throws IOException;

    /**
     * 已提交文件的字节数；文件不存在时抛 IOException。
     */
    long size(UUID id) throws IOException;

    /**
     * 永久删除该 id 的 partial、staged、committed 字节；在文件锁内执行，可重复调用。
     */
    void delete(UUID id) throws IOException;

    /**
     * 运维盘点，列出存储里现有的文件；不与数据库对账，也不自动清理。
     */
    List<Entry> inventory() throws IOException;
}
