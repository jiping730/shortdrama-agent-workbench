# Agent Workflow Platform 完整实现文档

## 1. 文档目的

本文档定义 Agent Workflow Platform 从当前可运行 v1 到能力矩阵完整落地后的实现规范。它回答四个问题：

- 平台应该如何实现，而不仅是有哪些模块；
- 四个参考项目的通用能力如何转换为本项目自己的接口；
- 当前代码、离线 Contract 和目标能力分别处于什么状态；
- 每个阶段应该交付什么，以及用什么证据验收。

本文档不要求复制参考项目源码。参考项目只提供经过只读分析的行为、契约和工程思想；所有落地代码、Prompt、配置、数据和测试样例都必须属于本项目自己的实现。

## 2. 完成定义

### 2.1 当前基线

当前仓库已经具备：

- 模块化单体 Runtime；
- script-to-storyboard 完整离线闭环；
- SQLite、本地 Artifact Store、PostgreSQL 配置模式和 Alembic 初始迁移；
- Run、StepExecution、Attempt、Checkpoint、Artifact、Evidence、ReviewTask、ExternalCall、ToolCall、RunEvent；
- 状态转换、Checkpoint、恢复、幂等、局部重试、审核暂停和 unknown 安全语义；
- FakeModel、Anthropic 离线 Contract、LocalWorker、SQLite 队列和 S3-compatible ArtifactStore Contract；
- REST API、CLI、管理页、JSON/CSV/HTML 导出；
- script-to-shotlist 扩展示例。

当前状态是“可运行的模块化单体 v1”，不是完整的生产级多租户平台。

### 2.2 目标完成态

当能力矩阵完整实现后，平台应满足：

1. Context 有版本化、可解释、可复现的 Evidence、Rule 和 Schema Contract；
2. Main 有可扩展的剧本解析、Preview/Confirm、版本化规则和恢复语义；
3. Agent Workflow 有完整的 Tool Bridge、nonce/session、stale callback 和 reconciliation；
4. CLI 在本地模式和远程 API 模式下使用同一套稳定 JSON/Error Contract；
5. Worker、PostgreSQL、对象存储、权限、观测和真实模型适配器具备生产级验收证据；
6. 新工作流只需实现业务 Adapter，不复制 Runtime、状态机、审核和恢复逻辑；
7. 每个“已支持”能力都能指向实现代码、自动化测试和可运行演示。

## 3. 设计原则

### 3.1 业务编排和可靠性运行时分离

Workflow Adapter 只负责业务步骤、输入输出和业务校验；Workflow Runtime 负责数据库事务、状态转换、Attempt、Checkpoint、审核、恢复和事件。

~~~text
业务 Adapter
    ↓ JSON-safe context / Schema
Workflow Runtime
    ↓ persistence / checkpoint / event / retry
Control Plane + Data Plane + Observability
~~~

Adapter 不得直接修改 Run 状态、提交数据库事务、吞掉模型异常或自行实现第二套重试状态机。

### 3.2 Contract-first

每一个跨模块边界先定义：

- 输入 Schema；
- 输出 Schema；
- 错误码和错误可重试性；
- 幂等键；
- 超时和取消语义；
- 审计字段；
- 版本兼容策略。

### 3.3 Evidence-first

业务事实、场景和分镜必须能回指原文。Evidence 优先使用稳定 source range、source text 和 content hash；向量检索不能替代精确来源。

### 3.4 事件和 Artifact 追加式保留

成功 Attempt、Artifact、Review 决策和 RunEvent 不被覆盖。新的修订通过新的 Attempt 和带父引用的 Artifact 表达，历史结果只读保留。

### 3.5 离线优先，真实外部服务可插拔

默认 FakeModel 保证 CI、作品演示和恢复测试确定性。真实模型、外部工具和云对象存储必须通过 Adapter 注入，不能成为默认安装和默认测试依赖。

### 3.6 模块化单体优先

Control Plane、Runtime、Execution、Data、Observability 通过包和接口隔离，但第一版保持一个进程和一个数据库。只有在队列、权限、部署和运维证据成熟后，才评估拆分服务。

## 4. 目标代码结构

当前代码已经有大部分基础目录；以下结构描述能力矩阵完整落地后的组织方式：

~~~text
agent_platform/
├── api.py                         # REST Control Plane
├── cli.py                         # 本地/远程 CLI 入口
├── config.py                      # 显式环境配置和安全默认值
├── domain.py                      # ID、状态、错误、哈希和领域原语
├── schemas.py                     # 稳定输入输出 Schema
├── db.py                          # SQLAlchemy Engine、Session、模型注册
├── repository.py                  # 事务边界和领域查询
├── runtime.py                     # Run/Step/Attempt/Checkpoint 执行内核
├── observability.py               # 日志、事件、指标和 trace adapter
├── controlplane/                  # 版本化 API、查询投影、错误 Envelope
├── context/                       # SourceIndex、Evidence、Rules、Schema registry
├── execution/                     # Provider、Tool、ExternalCall、Worker
├── storage/                       # ArtifactStore、保留策略、URI 和 hash
├── workflows/
│   ├── base.py                    # WorkflowAdapter Contract
│   ├── legacy.py                  # 外部自有 Workflow 注入边界
│   ├── script_to_storyboard.py    # 第一条业务工作流
│   ├── script_to_shotlist.py      # 第二条扩展工作流
│   └── ...                        # 后续受控工作流
└── evaluation/                    # Golden script、质量指标和回归评测
~~~

context、execution 和 evaluation 属于目标演进目录，不代表当前已经全部存在。

## 5. 平台分层

### 5.1 Control Plane

职责：

- Workspace、Project 和 WorkflowDefinition 管理；
- WorkflowVersion 注册和发布；
- Run 创建、查询、暂停、恢复、取消和重试；
- ReviewTask、Artifact、Evidence、Error Inbox 查询；
- REST API、CLI 和管理页；
- 稳定 JSON Envelope、Correlation ID 和权限检查。

Control Plane 不直接执行模型业务逻辑，而是调用 Runtime。

### 5.2 Workflow Runtime

职责：

- 根据 WorkflowVersion 装载 Adapter；
- 调度步骤并生成 Attempt；
- 执行状态转换表；
- 在安全边界写 Checkpoint 和 Artifact；
- 处理人工审核、局部重试和恢复；
- 记录 RunEvent、ToolCall、ExternalCall；
- 保证幂等和历史保留。

### 5.3 Execution Plane

职责：

- ModelProvider：FakeModel、Anthropic 和未来其他 Provider；
- ToolRegistry：输入/输出 Schema、版本、超时、重试、幂等和审计；
- TaskQueue：本地 SQLite 队列和未来外部队列；
- Worker：lease、心跳、ack/nack、取消和故障恢复；
- ExternalCall：请求、响应、结果未知和 reconciliation。

### 5.4 Data Plane

职责：

- SQLAlchemy 领域模型和事务；
- SQLite 本地模式；
- PostgreSQL 正式模式；
- Alembic 迁移；
- Local/S3/MinIO ArtifactStore；
- Artifact hash、父子关系、Schema 版本和 URI。

### 5.5 Observability

职责：

- 结构化日志；
- Run/Step/Attempt 时间线；
- ToolCall、ModelCall、ExternalCall；
- 错误码、重试率、成功率、耗时和队列积压；
- 可选 OpenTelemetry trace/metric exporter；
- 脱敏后的运行审计。

## 6. 核心领域模型

| 对象 | 作用 | 目标关键字段 |
| --- | --- | --- |
| Workspace | 资源隔离边界 | workspace_id、名称、状态、权限策略 |
| Project | 业务项目 | project_id、workspace、名称、配置版本 |
| WorkflowDefinition | 工作流逻辑定义 | 名称、描述、步骤列表、能力版本 |
| WorkflowVersion | 可复现发布版本 | 版本号、Schema 版本、Prompt/Provider 策略、发布时间 |
| Run | 一次完整执行 | run_id、project、workflow_version、status、current_step、correlation_id、input_hash、时间戳 |
| Task | 可调度任务 | 任务类型、状态、优先级、lease、重试策略 |
| StepExecution | Run 内的步骤实例 | step_id、步骤名、status、input_hash、current_attempt、output_artifact_id、error_code |
| Attempt | 一次不可覆盖的执行尝试 | attempt_id、attempt_no、input_snapshot、output_artifact_id、model_version、prompt_version、idempotency_key |
| Checkpoint | 安全边界快照 | Run context、下一步骤、Artifact 引用、序号 |
| Artifact | 结构化结果或文件 | 类型、hash、Schema 版本、URI/content、父 Artifact |
| Evidence | 原文证据 | evidence_id、script_id、scene_id、source_start/end、source_text、hash、置信/敏感级别 |
| ReviewTask | 人工审核任务 | 目标 Artifact/scene、状态、审核人、意见、版本 |
| ToolCall | 工具审计记录 | 工具名、版本、输入/输出 hash、nonce、状态、错误 |
| ExternalCall | 外部调用状态 | provider、operation、request/response、idempotency、状态 |
| RunEvent | 不可变时间线事件 | 类型、步骤、payload、correlation_id、actor、创建时间 |

### 6.1 状态

Run 状态至少包括：

~~~text
created → queued → running → waiting_review → completed
                         ↓              ↓
                      paused         queued
                         ↓
                  needs_recovery → queued

running → failed
running → cancelled
~~~

Step 状态至少包括：

~~~text
pending → queued → running → succeeded
                         ├── failed
                         ├── unknown
                         ├── waiting_review
                         └── skipped
~~~

每一次合法转换都必须写事件；非法转换必须抛出领域错误并写入拒绝原因。

## 7. WorkflowAdapter Contract

Adapter 的最小接口：

~~~python
class WorkflowAdapter(Protocol):
    definition: WorkflowDefinition

    def register(self) -> WorkflowDefinition: ...
    def validate(self, step_name: str, value: Any) -> Any: ...
    def start(self, context: dict[str, Any]) -> dict[str, Any]: ...
    def resume(self, context: dict[str, Any]) -> dict[str, Any]: ...
    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any: ...
    def recover(self, context: dict[str, Any]) -> dict[str, Any]: ...
~~~

约束：

- Adapter 必须声明名称、版本和步骤顺序；
- Adapter 返回 JSON-safe 结果；
- 业务输出先经过 Schema 校验，再由 Runtime 写 Artifact；
- Adapter 不直接访问 Runtime 数据库；
- Provider 异常必须保留结构化错误，不得伪装成成功结果；
- 新工作流必须有独立 Schema、Evidence、Review 和门禁测试。

## 8. script-to-storyboard 执行流程

### 8.1 正常路径

~~~text
prepare_input
→ split_script
→ build_source_index
→ extract_facts
→ validate_facts
→ generate_storyboard
→ validate_storyboard
→ wait_for_human_review
→ adopt_result
→ export_artifacts
~~~

每个步骤执行时：

1. 读取当前 Run context 和上游 Artifact；
2. 计算 input hash 和 idempotency key；
3. 创建 Attempt；
4. 调用 Adapter 或 Provider；
5. 进行 Schema 和业务规则校验；
6. 写 Artifact 和父子关系；
7. 保存 Checkpoint；
8. 写入 step.succeeded 和相关调用事件；
9. 更新下一安全边界。

### 8.2 Evidence 规则

- 场景必须保存 source start/end/text；
- Fact 必须引用至少一个 Evidence；
- Shot 必须引用至少一个 Evidence；
- Evidence 必须属于当前 Run 和当前 Script；
- 越界、缺失、跨 Run 引用和无依据输出必须失败；
- 后续完整 Context Contract 可增加 confidence、evidence_level、sensitivity 和 rule_version。

### 8.3 审核拒绝路径

~~~text
Review rejected
→ 标记原 Review rejected
→ 记录 rejected_scene_ids
→ 只调用 revise_storyboard(scene_ids)
→ 创建新 Attempt 和子 Artifact
→ Schema/Evidence 校验
→ 创建新 ReviewTask
→ 审核通过
→ adopt_result
→ export_artifacts
~~~

未被拒绝的场景不得重新调用模型，必须复用已有结果。

## 9. 可靠性实现

### 9.1 幂等

建议使用以下输入组成幂等键：

~~~text
workflow_version
+ step_name
+ input_hash
+ normalized_parameters
+ scene_revision
~~~

数据库层同时建立唯一约束；内存字典不能作为生产级唯一防线。

### 9.2 Checkpoint 和恢复

Checkpoint 至少保存：

- Run context snapshot；
- 已完成步骤和 Artifact 引用；
- 下一步骤；
- workflow/version/schema 版本；
- 序号和 correlation ID。

恢复时：

1. 读取最新有效 Checkpoint；
2. 将遗留 running Step 标记为 pending 或 unknown，不能静默删除；
3. 对未知外部调用先进入 reconciliation 或人工确认；
4. 已成功 Attempt 直接复用；
5. 从下一安全边界继续。

### 9.3 Unknown

网络超时或连接中断不能证明 provider 没有执行。系统必须：

- ExternalCall 标记 unknown；
- Attempt 使用 external_result_unknown；
- Run 进入 needs_recovery；
- 默认禁止自动重放；
- 等待 provider reconciliation、幂等查询或人工确认。

### 9.4 错误分类

至少使用：

~~~text
invalid_input
schema_validation_failed
evidence_missing
model_error
tool_error
timeout
external_result_unknown
review_rejected
persistence_error
unexpected_error
~~~

错误响应还应包含 code、message、retryable、result_unknown、correlation_id 和 details。

## 10. 外部调用和工具实现

### 10.1 ModelProvider

~~~python
class ModelProvider(Protocol):
    def generate_facts(self, script_text: str, scenes: list[Scene]) -> list[Fact]: ...
    def generate_storyboard(
        self, script_text: str, scenes: list[Scene], facts: list[Fact]
    ) -> list[Shot]: ...
    def revise_storyboard(
        self,
        script_text: str,
        scenes: list[Scene],
        facts: list[Fact],
        rejected_scene_ids: list[str],
    ) -> list[Shot]: ...
~~~

真实 Provider 必须：

- 使用官方 SDK；
- 支持 timeout、取消和重试策略；
- 记录 model_version、prompt_version 和 schema_version；
- 对返回内容做结构化解析和 Schema 校验；
- 脱敏记录请求和响应；
- 对结果未知提供查询或人工确认路径。

### 10.2 ToolRegistry

工具定义至少包括：

- 名称和版本；
- 输入/输出 Pydantic Schema；
- handler；
- timeout；
- retryable；
- idempotent；
- 权限和审计策略；
- correlation ID、session 和 nonce。

完整实现还要处理重复回执、旧 session 的迟到回执、worker 取消后的回执、工具版本不兼容，以及工具成功但持久化失败。

## 11. 队列和 Worker

本地模式：

~~~text
enqueue → lease → execute_run → ack
                         ↓
                       nack
~~~

生产 Worker 必须增加：

- lease owner；
- lease expiry；
- heartbeat；
- visibility timeout；
- 取消信号；
- 任务版本和 fencing token；
- worker 崩溃后的恢复；
- ack 前后数据库事务一致性。

队列只能负责调度消息，不能复制 Runtime 的状态转换逻辑。

## 12. Artifact Storage

Artifact 元数据和对象内容要保持可追溯：

~~~text
Artifact metadata
  ├── artifact_id
  ├── content_hash
  ├── schema_version
  ├── parent_artifact_ids
  └── content_uri

ArtifactStore.put(artifact_id, content) → URI
~~~

目标实现：

- 本地文件系统用于开发和离线测试；
- S3/MinIO 用于生产；
- content hash 用于完整性和幂等；
- 父 Artifact 用于修订 lineage；
- 保留策略、删除标记和访问审计由 Data Plane 管理。

## 13. API、CLI 和管理台

### 13.1 REST API

核心资源：

~~~text
/api/v1/workspaces
/api/v1/projects
/api/v1/workflows
/api/v1/runs
/api/v1/runs/{run_id}/events
/api/v1/runs/{run_id}/artifacts
/api/v1/runs/{run_id}/reviews
/api/v1/error-inbox
/api/v1/reviews/{review_id}/approve
/api/v1/reviews/{review_id}/reject
~~~

目标 API 需要统一请求幂等键、Correlation ID、pagination、版本协商、认证权限、稳定 Error Envelope 和结果未知查询。

### 13.2 CLI

目标命令组：

~~~text
workspace / project
workflow list / describe / publish
run create / show / list / pause / resume / cancel / retry
review list / approve / reject
artifact show / export
error-inbox list / inspect / reconcile
~~~

本地模式和远程模式必须共享命令语义，不能因为传输方式不同而改变错误含义。

### 13.3 管理台

管理台应优先展示：

- Run 状态和当前步骤；
- Step/Attempt 时间线；
- 输入和输出 Artifact；
- Evidence 原文高亮；
- 审核意见和修订 Diff；
- Error Inbox；
- ExternalCall 的未知状态和确认入口；
- 运行耗时、重试次数和失败原因。

不把聊天窗口作为首页。

## 14. 安全实现

必须遵守：

- 所有密钥只通过环境或 Secret Manager 注入；
- .env、数据库、Artifact、日志不提交 Git；
- 日志和导出默认脱敏；
- Prompt 和模型请求不能带入不必要的业务原文；
- Workspace/Project 权限在 API、CLI、Artifact 和工具层同时校验；
- 所有管理操作记录 actor、时间、目标和结果；
- 参考项目只读，不建立 import、路径或运行时依赖；
- 不引入向量数据库、长期记忆或 MCP 作为平台核心。

## 15. 分阶段实现计划

### P0 能力基线

交付能力矩阵、代码入口和测试入口索引、Schema/错误/状态 Contract，以及每项能力的完成标准。

门禁：每个 A 状态项都有代码和测试；每个 B/C 状态项都有明确缺口。

### P1 Context/Main/Agent/CLI 吸收

交付 Context Contract Registry、Script Parser Strategy、Import Preview/Confirm、Tool Bridge nonce/session/reconciliation、统一 CLI/API Error Envelope、Golden test 和跨 Run lineage 测试。

门禁：四个方向分别有实现、测试、演示和边界说明。

### P2 生产可靠性和安全

交付 PostgreSQL 正式 schema、索引、迁移、备份；生产队列；Worker lease、心跳和取消；Auth/RBAC/Workspace 隔离；S3/MinIO 端到端；OTel/metrics/alerts。

门禁：杀 Worker、断模型、重复请求、断网、旧回执和实例切换测试全部通过。

### P3 真实模型和评测

交付官方 Provider 真实集成、Prompt/Model/Schema 版本、Golden script 评测集、质量/成本/延迟/错误/人工修改指标。

门禁：模型变更可比较、可回归、可回滚；真实凭据只在隔离环境使用。

### P4 产品化和更多工作流

交付 Evidence/Attempt Diff 管理台、character-sheet、production-plan 等工作流、Workflow 发布和版本迁移、工作流级权限和审批。

门禁：每个新工作流独立通过 Schema、Evidence、Review、Recovery、API/CLI 和导出测试。

## 16. 测试策略

### 单元测试

- stable ID 和 hash；
- Schema、规则和错误分类；
- 状态转换；
- ToolRegistry 和 Provider Contract；
- CLI Envelope 和导出格式。

### 集成测试

- SQLite transaction；
- PostgreSQL migration/schema；
- Repository/Runtime/ArtifactStore；
- API/CLI/Review；
- Queue/Worker。

### E2E 测试

至少覆盖：

1. 创建 Run；
2. 进入审核；
3. 拒绝一个场景；
4. 只重试该场景；
5. 通过审核；
6. 导出 JSON/CSV/HTML；
7. 杀进程后恢复；
8. 重复提交不重复产生成功结果；
9. unknown 不自动重放；
10. 权限不足无法读取或修改其他 Workspace。

## 17. 交付检查清单

### 代码和数据

- [ ] 所有 Schema 有版本；
- [ ] 所有状态转换有测试；
- [ ] 所有外部调用有 ExternalCall；
- [ ] 所有成功步骤有 Checkpoint；
- [ ] 所有重试保留 Attempt；
- [ ] 所有 Artifact 有 hash 和 lineage；
- [ ] 所有事实和分镜有 Evidence；
- [ ] 所有错误有 code 和 retryability。

### 安全和运行

- [ ] 没有密钥、内部地址、账号和业务数据；
- [ ] Secret scan 通过；
- [ ] SQLite 和 PostgreSQL 都有测试；
- [ ] Worker 中断可恢复；
- [ ] unknown 不自动重复；
- [ ] 权限和审计通过；
- [ ] 日志和导出已脱敏。

### 文档和演示

- [ ] README 与代码一致；
- [ ] 能力矩阵状态准确；
- [ ] 四个参考项目的只读分析保留；
- [ ] 有一次完整 Run 演示；
- [ ] 有审核拒绝、局部重试、恢复和导出演示；
- [ ] 延期能力没有被写成已支持。

## 18. 最终判断标准

只有当 P0～P4 的实现和门禁全部完成后，才可以将平台描述为“能力矩阵完整实现后的生产级 Agent Workflow Platform”。在此之前，准确表述应为：

> 一个已经完成核心 Runtime、持久化、审核、恢复、离线模型和扩展边界验证的模块化单体平台，正在向生产级可靠性、安全和多工作流平台演进。
