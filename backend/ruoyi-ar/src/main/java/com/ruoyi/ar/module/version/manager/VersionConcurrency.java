package com.ruoyi.ar.module.version.manager;

import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantReadWriteLock;

import org.springframework.stereotype.Component;

/**
 * 场景版本与文件上传单实例内存并发互斥管理器。
 * <p>
 * 机制说明：
 * <ul>
 *   <li><b>版本读写锁</b>：每个 {@code versionId} 对应一个独立 {@link ReentrantReadWriteLock}。
 *       文件上传（{@code upload}）与下载（{@code download}）获取读锁，支持同一版本多文件并发传输；
 *       版本发布（{@code publish}）与整版本删除（{@code removeVersion}）获取写锁，确保版本发布或销毁时无在途文件传输。</li>
 *   <li><b>文件排重集合</b>：通过并发 Set（{@code activeUploads}）记录正在上传的文件 ID，拒绝针对同一文件条目的并发重复上传请求。</li>
 * </ul>
 */
@Component
public class VersionConcurrency {

    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> versionLocks = new ConcurrentHashMap<>();
    private final Set<UUID> activeUploads = ConcurrentHashMap.newKeySet();

    /**
     * 获取版本的共享读锁。
     *
     * @param versionId 版本唯一标识
     * @return 读锁对象
     */
    public Lock readLock(UUID versionId) {
        return versionLock(versionId).readLock();
    }

    /**
     * 获取版本的排他写锁。
     *
     * @param versionId 版本唯一标识
     * @return 写锁对象
     */
    public Lock writeLock(UUID versionId) {
        return versionLock(versionId).writeLock();
    }

    /**
     * 尝试将指定文件登记为正在上传。
     *
     * @param fileId 文件记录唯一标识
     * @return 若当前无在途上传且登记成功返回 true，否则返回 false
     */
    public boolean beginUpload(UUID fileId) {
        return activeUploads.add(fileId);
    }

    /**
     * 上传结束或异常时移除在途标记。
     *
     * @param fileId 文件记录唯一标识
     */
    public void endUpload(UUID fileId) {
        activeUploads.remove(fileId);
    }

    private ReentrantReadWriteLock versionLock(UUID versionId) {
        return versionLocks.computeIfAbsent(versionId, id -> new ReentrantReadWriteLock());
    }
}
