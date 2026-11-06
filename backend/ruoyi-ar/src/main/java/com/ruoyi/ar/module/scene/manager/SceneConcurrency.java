package com.ruoyi.ar.module.scene.manager;

import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantReadWriteLock;

import org.springframework.stereotype.Component;

/**
 * 场景与文件传输的单实例内存并发互斥管理器。
 * <ul>
 *   <li>每个场景一把读写锁：上传与下载持读锁，可并发传输不同文件；整场景删除持写锁，先尝试获取，
 *       有在途传输时立即以 409 拒绝，避免截断正文或删除正在写入的文件。</li>
 *   <li>在途上传集合按文件 ID 登记，同一文件并发上传立即 409，不同文件互不影响。</li>
 * </ul>
 */
@Component
public class SceneConcurrency {

    private final ConcurrentHashMap<UUID, ReentrantReadWriteLock> sceneLocks = new ConcurrentHashMap<>();
    private final Set<UUID> activeUploads = ConcurrentHashMap.newKeySet();

    public Lock readLock(UUID sceneId) {
        return sceneLock(sceneId).readLock();
    }

    public Lock writeLock(UUID sceneId) {
        return sceneLock(sceneId).writeLock();
    }

    public boolean beginUpload(UUID fileId) {
        return activeUploads.add(fileId);
    }

    public void endUpload(UUID fileId) {
        activeUploads.remove(fileId);
    }

    private ReentrantReadWriteLock sceneLock(UUID sceneId) {
        return sceneLocks.computeIfAbsent(sceneId, id -> new ReentrantReadWriteLock());
    }
}
