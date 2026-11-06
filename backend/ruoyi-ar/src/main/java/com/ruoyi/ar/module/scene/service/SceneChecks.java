package com.ruoyi.ar.module.scene.service;

import com.ruoyi.ar.module.scene.manager.SceneConcurrency;

import java.util.UUID;
import java.util.concurrent.locks.Lock;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** 场景与文件操作共享的参数检查、业务异常构建及非阻塞锁工具类。 */
final class SceneChecks {

    private SceneChecks() {
    }

    static ResponseStatusException error(HttpStatus status, String reason) {
        return new ResponseStatusException(status, reason);
    }

    static <T> T required(T row) {
        if (row == null) throw error(HttpStatus.NOT_FOUND, "场景或文件不存在");
        return row;
    }

    /** 在途传输持读锁；整场景删除持写锁，因此删除与传输互斥。 */
    static Lock readLock(SceneConcurrency concurrency, UUID sceneId) {
        Lock lock = concurrency.readLock(sceneId);
        if (!lock.tryLock())
            throw error(HttpStatus.CONFLICT, "场景正在删除，请稍后重试");
        return lock;
    }

    /** 有上传或下载在途时立即 409，不排队等待。 */
    static Lock writeLock(SceneConcurrency concurrency, UUID sceneId) {
        Lock lock = concurrency.writeLock(sceneId);
        if (!lock.tryLock())
            throw error(HttpStatus.CONFLICT, "场景文件正在上传或下载，请稍后重试");
        return lock;
    }
}
