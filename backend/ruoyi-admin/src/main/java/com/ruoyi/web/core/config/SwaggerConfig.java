package com.ruoyi.web.core.config;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import com.ruoyi.common.config.RuoYiConfig;
import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.servers.Server;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;

/**
 * OpenAPI 接口文档配置（springdoc + knife4j）。
 *
 * @author ruoyi
 */
@Configuration
public class SwaggerConfig
{
    /** 系统基础配置 */
    @Autowired
    private RuoYiConfig ruoyiConfig;

    /**
     * 自定义的 OpenAPI 对象
     */
    @Bean
    public OpenAPI customOpenApi()
    {
        return new OpenAPI().components(new Components()
            // 设置认证的请求头
            .addSecuritySchemes("bearerAuth", securityScheme()))
            .addSecurityItem(new SecurityRequirement().addList("bearerAuth"))
            .addServersItem(new Server().url("/prod-api").description("同源管理网关"))
            .info(getApiInfo());
    }

    @Bean
    public SecurityScheme securityScheme()
    {
        return new SecurityScheme()
            .type(SecurityScheme.Type.HTTP)
            .scheme("bearer")
            .bearerFormat("JWT");
    }

    /**
     * 添加摘要信息
     */
    public Info getApiInfo()
    {
        return new Info()
            // 设置标题
            .title("AR 场景资源管理平台接口文档")
            // 描述
            .description("场景、固定文件清单、逐文件入库与匿名客户端直接分发接口；管理端接口需 Bearer 登录，并按 ar_admin 角色授权")
            // 作者信息
            .contact(new Contact().name(ruoyiConfig.getName()))
            // 版本
            .version("版本号:" + ruoyiConfig.getVersion());
    }
}
