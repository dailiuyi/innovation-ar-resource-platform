package com.ruoyi.ar.module.version.service;

import com.ruoyi.ar.module.version.manager.VersionConcurrency;

import java.util.UUID;
import java.util.concurrent.locks.Lock;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** 生命周期和文件操作共用的业务错误与非阻塞锁获取。 */
final class VersionChecks {

    private VersionChecks() {
    }

    static ResponseStatusException error(HttpStatus status, String reason) {
        return new ResponseStatusException(status, reason);
    }

    static <T> T required(T row) {
        if (row == null) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
        return row;
    }

    /** 上传和下载可并行；版本正在发布或删除时立即返回 409。 */
    static Lock readLock(VersionConcurrency concurrency, UUID versionId) {
        Lock lock = concurrency.readLock(versionId);
        if (!lock.tryLock())
            throw error(HttpStatus.CONFLICT, "版本正在发布或删除，请稍后重试");
        return lock;
    }

    /** 发布和删除独占版本；拿不到锁立即返回 409。 */
    static Lock writeLock(VersionConcurrency concurrency, UUID versionId) {
        Lock lock = concurrency.writeLock(versionId);
        if (!lock.tryLock())
            throw error(HttpStatus.CONFLICT, "版本文件正在上传或下载，请稍后重试");
        return lock;
    }
}
