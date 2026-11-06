package com.ruoyi.ar.module.client.manager;

import com.ruoyi.ar.module.client.mapper.ClientSceneMapper;
import com.ruoyi.ar.module.client.model.ClientSceneFileRow;
import com.ruoyi.ar.module.client.model.ClientSceneRow;

import java.util.List;

import org.springframework.stereotype.Component;

/** 组合匿名可见场景目录与固定文件清单查询；可见性错误和响应组装由 Service 负责。 */
@Component
public class ClientSceneManager {
    private final ClientSceneMapper mapper;

    public ClientSceneManager(ClientSceneMapper mapper) {
        this.mapper = mapper;
    }

    public Catalog list(String name, int limit, int offset) {
        return new Catalog(mapper.list(name, limit, offset), mapper.count(name));
    }

    /** 场景不存在、未启用、空清单、文件未全部就绪或删除中时返回 null。 */
    public Detail detail(String sceneId) {
        var scene = mapper.find(sceneId);
        return scene == null ? null : new Detail(scene, mapper.files(sceneId));
    }

    public record Catalog(List<ClientSceneRow> items, long total) {
    }

    public record Detail(ClientSceneRow scene, List<ClientSceneFileRow> files) {
    }
}
