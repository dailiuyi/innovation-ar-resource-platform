# 0002：Symphony 开发任务调度

日期：2026-09-19。状态：采纳。维护责任：项目负责人。

## 决定

按用户要求安装 OpenAI Symphony，使用当前 GitHub 账号的公开 innovation 仓库作为任务入口。在独立 Docker 容器和每个 Issue 的独立副本中执行，初期并发为 1，仅领取 symphony:ready 标签任务。

新增 WORKFLOW.md 固化任务范围、现有 Harness 调用、阻塞处理和 draft PR 交付。完成后移除领取标签，停在人工审查；不启用自动合并或部署。

## 原因与影响

人工恢复和跟进任务可以交给外层调度。0001 的 Harness 证据规则继续有效，Harness 本身仍不调度模型。这里改变的是开发工具流程，不引入业务 Worker、后台队列或新的产品角色。

本机入库验收依赖 Windows，Linux 容器不能完成该 profile。相关交付必须标明等待宿主机验收，不能仅凭 quick 或 frontend 通过判定完成。登录凭据只在明确授权的本地运行环境使用，不进入仓库。

## 后续状态

本记录保留初期并发为 1 的决策背景。仓库现行 `WORKFLOW.md` 已配置并发上限 4；操作与变更记录见 [Symphony 手册](../15-symphony.md) 和 [验证记录](../06-validation.md)，不据历史 ADR 推断运行容器的实时状态。

Windows `review.py`/ingestion profile 的运行时限制仍保留；Linux 宿主已有固定隔离 Compose 入库/真实样包流程（`127.0.0.1:18082`），见 [Harness](../13-harness.md)。这不表示 Symphony 容器能运行 Windows profile，也不替代独立 PR 审查与人工验收。

## 重新考虑条件

实测 Windows 验收接入、真实 Issue 到 PR 流程和独立审查稳定后再考虑提高并发。扩大 Token 权限、增加自动合并或部署需要新的明确要求。
