package com.ruoyi.ar.module.scene.model;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import java.sql.Timestamp;
import java.util.UUID;

/**
 * 场景实体持久化对象（对应数据库表 {@code ar_scene}）。
 * <p>
 * 承载场景基本元数据与并发乐观锁控制。支持基于 {@link TableLogic} 的逻辑软删除，
 * 物理成品的生命周期独立于该对象。
 */
@TableName("ar_scene")
public class SceneDO {
    /** 场景唯一主键 UUID（采用手工生成输入策略） */
    @TableId(type = IdType.INPUT)
    private UUID id;
    /** 场景业务名称 */
    private String name;
    /** 场景启停状态（true 为启用，false 为停用） */
    private Boolean enabled;
    /** 乐观锁版本号（每次更新自增） */
    private Long lockVersion;
    /** 记录创建时间戳 */
    private Timestamp createdAt;
    /** 记录最后更新时间戳 */
    private Timestamp updatedAt;
    /** 逻辑软删除时间戳（null 为正常未删除，有值表示软删除时间） */
    @TableLogic(value = "null", delval = "now()")
    private Timestamp deletedAt;
    public UUID getId() { return id; }
    public void setId(UUID id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public Boolean getEnabled() { return enabled; }
    public void setEnabled(Boolean enabled) { this.enabled = enabled; }
    public Long getLockVersion() { return lockVersion; }
    public void setLockVersion(Long lockVersion) { this.lockVersion = lockVersion; }
    public Timestamp getCreatedAt() { return createdAt; }
    public void setCreatedAt(Timestamp createdAt) { this.createdAt = createdAt; }
    public Timestamp getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Timestamp updatedAt) { this.updatedAt = updatedAt; }
    public Timestamp getDeletedAt() { return deletedAt; }
    public void setDeletedAt(Timestamp deletedAt) { this.deletedAt = deletedAt; }
}
