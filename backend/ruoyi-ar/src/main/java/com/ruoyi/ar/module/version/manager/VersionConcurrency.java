package com.ruoyi.ar.module.version.manager;

import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantReadWriteLock;

import org.springframework.stereotype.Component;

/** 单实例版本互斥：版本锁按需保留，同一文件不允许并发上传。 */
@Component
public class VersionConcurrency {

    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> versionLocks = new ConcurrentHashMap<>();
    private final Set<UUID> activeUploads = ConcurrentHashMap.newKeySet();

    public Lock readLock(UUID versionId) {
        return versionLock(versionId).readLock();
    }

    public Lock writeLock(UUID versionId) {
        return versionLock(versionId).writeLock();
    }

    public boolean beginUpload(UUID fileId) {
        return activeUploads.add(fileId);
    }

    public void endUpload(UUID fileId) {
        activeUploads.remove(fileId);
    }

    private ReentrantReadWriteLock versionLock(UUID versionId) {
        return versionLocks.computeIfAbsent(versionId, id -> new ReentrantReadWriteLock());
    }
}
