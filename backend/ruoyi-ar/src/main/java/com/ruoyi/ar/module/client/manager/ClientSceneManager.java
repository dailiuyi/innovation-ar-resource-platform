package com.ruoyi.ar.module.client.manager;

import com.ruoyi.ar.module.client.mapper.ClientSceneMapper;
import com.ruoyi.ar.module.client.model.ClientSceneFileRow;
import com.ruoyi.ar.module.client.model.ClientSceneRow;

import java.util.List;

import org.springframework.stereotype.Component;

/** 组合发布目录与详情查询；可见性错误和响应组装由 Service 负责。 */
@Component
public class ClientSceneManager {
    private final ClientSceneMapper mapper;

    public ClientSceneManager(ClientSceneMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * 查询面向客户端公开的场景分页目录。
     *
     * @param name 场景名称关键字（模糊匹配），为空时不按名称过滤
     * @param limit 本页最多获取的条数
     * @param offset 偏移量（起始位置）
     * @return 包含当前页场景记录及匹配总数的聚合对象
     */
    public Catalog list(String name, int limit, int offset) {
        return new Catalog(mapper.list(name, limit, offset), mapper.count(name));
    }

    /**
     * 查询单个场景及其当前发布版本的完整文件清单。
     *
     * @param sceneId 场景 UUID 文本
     * @return 场景及文件列表聚合对象；若场景不存在或未发布则返回 null
     */
    public Detail detail(String sceneId) {
        var scene = mapper.find(sceneId);
        return scene == null ? null : new Detail(scene, mapper.files(scene.versionId()));
    }

    /**
     * 客户端场景分页查询聚合结果。
     *
     * @param items 当前页场景持久化行列表
     * @param total 符合条件的场景总数
     */
    public record Catalog(List<ClientSceneRow> items, long total) {
    }

    /**
     * 场景详情及版本文件清单聚合对象。
     *
     * @param scene 场景基本信息行
     * @param files 该场景当前发布版本关联的文件清单列表
     */
    public record Detail(ClientSceneRow scene, List<ClientSceneFileRow> files) {
    }
}
