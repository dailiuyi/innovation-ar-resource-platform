package com.ruoyi.ar.module.version.mapper;

import com.ruoyi.ar.module.version.model.VersionRows;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 文件清单、上传结果与恢复游标查询；不负责版本发布和删除回执。 */
@Mapper
public interface VersionFileMapper {
    List<VersionRows.File> files(String id);

    VersionRows.File file(@Param("versionId") String versionId, @Param("id") String id);

    void insertFiles(@Param("files") List<VersionRows.NewFile> files);

    void startUpload(@Param("id") String id, @Param("actor") long actor, @Param("actorName") String actorName);

    VersionRows.Actor uploadActor(String id);

    void finishUpload(@Param("id") String id, @Param("status") String status,
                      @Param("available") boolean available, @Param("reason") String reason);

    long fileCount(String id);

    List<String> fileIds(String id);

    void deleteFiles(String id);

    List<VersionRows.File> recoveryFiles(String cursor);
}
