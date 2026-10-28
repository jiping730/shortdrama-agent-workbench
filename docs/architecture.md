# Architecture

```mermaid
flowchart LR
  UI[Management UI / REST / CLI] --> CP[Control Plane]
  CP --> RT[Workflow Runtime]
  RT --> WA[WorkflowAdapter]
  WA --> BP[script-to-storyboard]
  RT --> EP[Execution Plane\nModelProvider / ToolRegistry / LocalWorker]
  RT --> DP[(SQLite / PostgreSQL)]
  RT --> AR[ArtifactRepository\nlocal file / S3-compatible]
  RT --> OBS[RunEvent / metrics / structured logs]
```

核心生命周期：

`WorkflowDefinition → WorkflowVersion → Run → Task/StepExecution → Attempt → Artifact → ReviewTask → Recovery → RunEvent`

## 模块边界

- Control Plane：Workspace、Project、工作流版本、Run 查询/操作、Review API、Error Inbox、CLI。
- Workflow Runtime：状态转换、步骤顺序、幂等、局部重试、审核暂停、Checkpoint、恢复。
- Execution Plane：`ModelProvider`、`ToolRegistry`、可选 `LocalWorker` 队列、FakeModel、官方 Anthropic SDK adapter。
- Data Plane：SQLAlchemy 领域表，SQLite 默认，PostgreSQL 连接字符串可切换；Local/S3-compatible Artifact Storage 共享同一 put contract。
- Observability：RunEvent 账本、Attempt/ExternalCall/ToolCall 记录、基础 metrics facade。

## 可靠性原则

1. 任何成功步骤都必须有 Artifact 和 Checkpoint。
2. Attempt 只新增不覆盖；成功重用必须留下 `step.reused` 事件。
3. Unknown 外部调用只能进入 Error Inbox/`needs_recovery`，不能自动重复。
4. Review reject 只产生目标 scene 的 revision；未拒绝 scene 沿用原 Artifact。
5. 所有业务事实和 Shot 都通过 Evidence ID 回指原文范围。

## 阶段 7 扩展边界

- `SQLiteTaskQueue` 是单机可恢复队列；消息有幂等键、lease、ack/nack 状态，Worker 只调用现有 Runtime，不复制状态机。
- `S3ArtifactStore` 通过官方 boto3 client 或注入式兼容客户端写入 URI；默认仍是本地文件，不强制安装云 SDK。
- `AnthropicModelAdapter` 只通过官方 Anthropic SDK 的 `messages.create`，JSON 和 Pydantic 校验失败会进入结构化错误路径。
- `ScriptToShotlistAdapter` 证明新业务工作流可复用 Runtime 的 Attempt、Artifact、Checkpoint 和 Evidence 边界。
