# Architecture Decisions

## ADR-001 复用已有 workflow 的边界

已有 Agent Workflow 已验证 Skill 分层、模型注入、稳定 ID、ReviewGate 和幂等生成的业务思想，因此平台保留这些概念；但参考实现的状态生命周期不满足跨进程恢复。本项目新增 `WorkflowAdapter` 接口，并让 Runtime 接管持久化、Attempt、Checkpoint、事件和错误分类。`LegacyWorkflowAdapter` 允许部署时注入一个兼容对象，但默认安装不依赖参考目录。

## ADR-002 Workflow 与持久化 Runtime 解耦

Workflow 只回答“给定上下文如何执行一个步骤”，不拥有数据库事务、线程、审核状态或重试策略。Runtime 在安全边界包裹每次调用：记录 Attempt → 记录 ExternalCall → 校验 → 写 Artifact → 保存 Checkpoint → 发 RunEvent。这样未来增加 `script-to-shotlist` 或 `storyboard-to-production-plan` 时，可以复用同一可靠性外壳。

## ADR-003 不把 RAG 作为平台核心

第一条工作流的证据可以由原文 offset 和稳定 scene range 精确提供；事实和分镜必须引用 Evidence。向量库会引入额外索引一致性、召回不确定性和部署依赖，不能替代可审计的 source_start/source_end/source_text。未来若某个业务真的需要语义检索，将作为独立 Adapter，不改变核心 Run/Attempt/Artifact 模型。

## ADR-004 模块化单体优先

Control Plane、Workflow Runtime、Execution Plane、Data Plane 和 Observability 在包和接口层分界，部署先保持一个进程和一个数据库。这样离线演示、SQLite 测试和个人仓库维护成本可控；未来可以按队列、模型调用、Artifact 存储和 Web/API 的边界拆分，而无需先承担微服务运维。

## ADR-005 Adapter/扩展点的暂缓能力

`ModelProvider`、`ToolRegistry`、`WorkflowAdapter`、`ArtifactStore` 和 `AnthropicModelAdapter` 是扩展点。默认仍是 FakeModel、本地文件和同步 API；阶段 7 已补充官方 Anthropic SDK 边界、SQLite 本地队列 Worker、S3-compatible adapter 和 `script-to-shotlist` 示例。生产级多 worker lease、云端端到端演练、OpenTelemetry、权限系统和更多业务工作流仍独立延期。
