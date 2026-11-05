package com.ruoyi.ar.module.version.service;

import com.ruoyi.ar.module.version.manager.VersionConcurrency;

import java.util.UUID;
import java.util.concurrent.locks.Lock;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/**
 * 版本与文件操作共享的参数检查、业务异常构建及非阻塞锁工具类。
 */
final class VersionChecks {

    private VersionChecks() {
    }

    /**
     * 构建标准 Spring {@link ResponseStatusException}。
     *
     * @param status HTTP 状态码
     * @param reason 面向客户端展示的具体原因说明
     * @return 响应状态异常实例
     */
    static ResponseStatusException error(HttpStatus status, String reason) {
        return new ResponseStatusException(status, reason);
    }

    /**
     * 断言数据行非空，若为空抛出 404 NOT_FOUND。
     *
     * @param <T> 数据类型
     * @param row 待检查的对象
     * @return 原对象非空引用
     * @throws ResponseStatusException 若 row 为 null 抛出 404
     */
    static <T> T required(T row) {
        if (row == null) throw error(HttpStatus.NOT_FOUND, "场景、版本或文件不存在");
        return row;
    }

    /**
     * 非阻塞尝试获取版本的共享读锁。
     * <p>
     * 若版本正在被发布或删除（持有写锁），立即以 409 CONFLICT 抛出异常而不阻塞工作线程。
     *
     * @param concurrency 并发互斥管理器
     * @param versionId 版本唯一标识
     * @return 成功获取到的读锁实例
     * @throws ResponseStatusException 无法即时获取读锁时抛出 409
     */
    static Lock readLock(VersionConcurrency concurrency, UUID versionId) {
        Lock lock = concurrency.readLock(versionId);
        if (!lock.tryLock())
            throw error(HttpStatus.CONFLICT, "版本正在发布或删除，请稍后重试");
        return lock;
    }

    /**
     * 非阻塞尝试获取版本的排他写锁。
     * <p>
     * 若版本下存在活跃的文件上传或下载任务（持有读锁），立即以 409 CONFLICT 抛出异常。
     *
     * @param concurrency 并发互斥管理器
     * @param versionId 版本唯一标识
     * @return 成功获取到的写锁实例
     * @throws ResponseStatusException 无法即时获取写锁时抛出 409
     */
    static Lock writeLock(VersionConcurrency concurrency, UUID versionId) {
        Lock lock = concurrency.writeLock(versionId);
        if (!lock.tryLock())
            throw error(HttpStatus.CONFLICT, "版本文件正在上传或下载，请稍后重试");
        return lock;
    }
}
