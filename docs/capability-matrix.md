# 能力吸收矩阵与完善路线

本文档基于当前仓库代码、测试门禁和已完成演示整理，用来回答三个问题：

1. 四个参考项目的哪些通用能力已经被本项目重新实现；
2. 哪些能力只有接口或离线 Contract，不能宣称为生产能力；
3. 下一步应该按什么顺序继续完善。

本文档中的“吸收”指提炼设计思想、行为契约并用本项目自己的代码重写，不指复制参考项目源码、Prompt、业务数据、账号或内部配置。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| A 已实现 | 当前仓库有代码，并有单元测试、集成测试、门禁测试或可运行演示证据 |
| B 已抽象 | 已有接口、Adapter 或离线 Contract，但缺少真实外部环境、并发或生产级验证 |
| C 待实现 | 当前只有设计结论、扩展点或延期说明，不能作为已支持能力对外承诺 |

## 一、四个参考项目的能力吸收矩阵

### 1. Agent Workflow

| 能力 | 本项目实现 | 代码与测试证据 | 状态 | 尚未覆盖 |
| --- | --- | --- | --- | --- |
| Workflow/Skill 分层 | `WorkflowAdapter` 将业务编排和持久化 Runtime 分离 | `agent_platform/workflows/base.py`、`legacy.py`、`tests/gates/test_stage1_gate.py` | A | 尚未达到原项目全部业务 Skill 的功能覆盖 |
| 生命周期委托 | 支持 `register`、`validate`、`start`、`resume`、`execute_step`、`recover` | `WorkflowAdapter` Contract、Adapter fail-fast 测试 | A | 旧 Workflow 的真实实现需要由部署方注入，仓库不携带参考源码 |
| 稳定 ID 和幂等生成 | `stable_id`、输入哈希、Attempt idempotency key、Artifact hash | `agent_platform/domain.py`、`runtime.py`、阶段 3 门禁 | A | 高并发条件下的数据库唯一约束和跨 Worker 抢占仍需强化 |
| ReviewGate | ReviewTask 持久化、场景级拒绝、局部修订和通过场景复用 | `runtime.py`、`script_to_storyboard.py`、阶段 4/5 门禁 | A | 审核角色、权限、多人会签、审核 Diff 尚未实现 |
| Tool Bridge 思想 | ToolDefinition、输入/输出 Schema、超时/重试/幂等元数据、结构化错误 | `agent_platform/tools.py`、`tests/unit/test_tools.py` | B | 会话/nonce 绑定、stale callback 防护、外部回执 reconciliation 尚未实现 |
| 注入式模型 | `ModelProvider`、FakeModel、Anthropic Adapter | `agent_platform/providers.py`、阶段 7 Contract 测试 | B | 真实模型端到端、Token/成本统计、限流和生产提示词版本管理尚未完成 |

### 2. Context

| 能力 | 本项目实现 | 代码与测试证据 | 状态 | 尚未覆盖 |
| --- | --- | --- | --- | --- |
| 证据优先 | Evidence 保存 source range、source text、hash，并被事实/分镜引用 | `agent_platform/schemas.py`、`script_to_storyboard.py`、阶段 4 门禁 | A | 尚未形成更通用的跨业务 Evidence 规则包 |
| 数据契约 | ScriptInput、Scene、Fact、Shot、Storyboard、ShotList 使用 Pydantic 严格 Schema | `agent_platform/schemas.py` | A | 尚未建立独立的版本化 Contract Registry 和兼容性策略 |
| 原文索引 | 确定性场景切分，生成稳定 scene ID 和 source offset | `ScriptToStoryboardAdapter._split_script`、阶段 4 门禁 | A | 当前解析规则仍是第一版，复杂剧本格式、导入预览和人工确认尚未覆盖 |
| 事件与可追溯写回 | RunEvent、Artifact lineage、Attempt、ExternalCall 可查询 | `repository.py`、`exporter.py`、阶段 2/3/5 门禁 | A | 事件 Schema 版本、跨服务 trace、长期归档策略尚未完成 |
| 规则和证据覆盖 | 校验事实/分镜 Evidence 存在性及场景覆盖率 | `script_to_storyboard.py`、阶段 4 门禁 | A | 复杂业务规则、规则解释和规则配置化尚未完成 |
| 专有上下文 | 未引入参考项目中的组织、云资源、身份和业务数据 | `docs/reference-analysis.md`、阶段 0 门禁 | A | 如未来需要，只能以脱敏、独立 Contract 和独立 Adapter 重新设计 |

### 3. Main

| 能力 | 本项目实现 | 代码与测试证据 | 状态 | 尚未覆盖 |
| --- | --- | --- | --- | --- |
| 剧本拆解 | 先按确定性规则拆分场景，再生成事实和分镜 | `workflows/script_to_storyboard.py` | A | 目前是可控最小实现，不等于完整剧本解析引擎 |
| 结构化校验 | Pydantic `extra=forbid`、字段约束、Evidence 覆盖和全场景覆盖校验 | `schemas.py`、阶段 4 门禁 | A | 尚未覆盖更多剧本格式、版本迁移和兼容输入 |
| Checkpoint | 每个安全边界保存上下文、下一步和 Artifact 引用 | `runtime.py`、`repository.py`、阶段 3 门禁 | A | 尚未实现生产级 Worker lease、心跳和可见性超时 |
| 进程恢复 | `recover()` 将遗留运行状态恢复到可继续执行的边界 | `runtime.py`、`tests/unit/test_runtime.py` | A | 外部调用未知结果仍需要人工确认或 provider reconciliation |
| 局部重试 | 只对 rejected scene 创建新 Attempt，其他场景复用旧结果 | `runtime.py`、阶段 3/4 门禁 | A | 更复杂的步骤依赖图、批量场景重试和冲突合并尚未实现 |
| Preview/Confirm | 当前有校验和审核暂停，但没有独立导入预览确认工作流 | `api.py`、`script_to_storyboard.py` | B | 增加导入预览、修改后确认、版本比较和回滚 |
| 数据库事务 | SQLAlchemy、SQLite、PostgreSQL URL、Alembic 初始迁移 | `db.py`、`migrations/`、阶段 2/6 验收 | A | 索引、备份、在线迁移、数据保留和并发压测尚未完成 |

### 4. CLI

| 能力 | 本项目实现 | 代码与测试证据 | 状态 | 尚未覆盖 |
| --- | --- | --- | --- | --- |
| 命令分层 | Run、Review、Workflow、Export 四组命令 | `agent_platform/cli.py`、阶段 5 门禁 | A | 尚未覆盖更丰富的项目/资产/批处理管理命令 |
| 稳定 JSON 输出 | `--json` 输出 Run、Review 和导出结果 | `cli.py`、阶段 5 门禁 | A | 错误响应尚未统一为完整的 code/retryable/details envelope |
| 错误分类 | Runtime 使用结构化 ErrorCode，CLI 返回失败状态和错误文本 | `domain.py`、`cli.py` | B | 需要把错误码、退出码、可重试性和结果未知统一公开给脚本客户端 |
| 幂等与重复提交 | Runtime 根据输入和成功结果复用既有 Run | `runtime.py`、阶段 3 门禁 | A | CLI 尚未提供显式幂等键、请求追踪和远程服务配置 |
| 导出 | JSON、CSV、HTML 包含 Run、步骤、审核、审计和工件信息 | `exporter.py`、阶段 5 门禁 | A | 尚未提供脱敏策略、分页导出、增量导出和大文件流式导出 |
| 服务端边界 | 当前 CLI 直接操作本地 Control Plane 和数据库 | `cli.py`、`config.py` | B | 未来远程 CLI 需要认证、TLS、版本协商和服务端错误映射 |

## 二、平台当前完整度

| 平台层 | 已有能力 | 当前真实边界 |
| --- | --- | --- |
| Control Plane | REST API、CLI、管理台、Review、Error Inbox、导出 | 默认同步、本地单进程、无认证和多租户 |
| Workflow Runtime | 11 步 storyboard 流程、状态机、Attempt、Checkpoint、恢复和局部重试 | 生产级并发调度和跨 Worker 抢占尚未完成 |
| Execution Plane | FakeModel、Anthropic Contract、ToolRegistry、SQLite LocalWorker | 默认离线；真实模型和外部调用尚未做生产 E2E |
| Data Plane | SQLite 默认、PostgreSQL 配置、Alembic、Local/S3 ArtifactStore | S3 只有 Contract/注入测试，未做真实云端演练 |
| Observability | RunEvent、Attempt、ExternalCall、时间线和基础错误收件箱 | OpenTelemetry、指标后端、告警和长期日志归档延期 |
| Workflow Extension | `script-to-shotlist` 复用同一 Runtime | 更多工作流、统一 Contract Registry 和版本迁移待实现 |

因此，当前项目可以称为“可运行的模块化单体 v1”和“企业级 Runtime 基础版”，不能称为已经完成生产级企业平台。

## 三、完善方向和验收标准

### P0 建立自己的能力基线

目标是把“参考项目观察”转换成可执行的本项目 Contract：

- 为 Script、Scene、Evidence、Fact、Shot、Review 和 Artifact 建立版本化 Schema；
- 为每个能力维护本矩阵中的代码入口、测试入口和演示命令；
- 对每个 B 状态项明确负责人、依赖、风险和完成门槛；
- 任何 A 状态都必须有代码和自动化测试，不能只依赖文档描述。

验收结果应能回答：给定一项能力，能否在 5 分钟内找到实现、测试和运行证据。

### P1 完成四个参考项目的通用能力吸收

#### Context 方向

建立自己的 `context_contracts` 层，包含：

- 可复用的 SourceIndex、EvidenceRange、EvidenceCoverage；
- 规则结果、规则版本和失败原因；
- Schema 版本兼容和迁移；
- 事实、场景、分镜之间的 lineage 查询。

验收：构造跨 Run、缺 Evidence、越界 offset、Schema 版本不兼容等测试，所有错误都能定位到具体规则和来源。

#### Main 方向

把当前最小 `_split_script` 演进为独立的 Script Processing 模块：

- Parser Strategy：支持多种剧本格式；
- Import Preview：先展示场景和 Evidence，再确认导入；
- Validation Report：输出可解释的结构化问题；
- Revision/Confirm：允许人工修改后重新校验；
- 解析规则版本化，保证同一输入可以复现历史结果。

验收：同一剧本在相同规则版本下得到稳定 scene ID；修改一个场景不会改变无关场景的 ID 和 Artifact。

#### Agent Workflow 方向

把当前 ToolRegistry 和 ExternalCall Contract 完善为可靠的外部调用边界：

- 调用 nonce、session 和 correlation ID；
- 超时、重复回执、stale callback 的处理；
- provider reconciliation 和人工确认；
- 请求/响应脱敏和调用级审计；
- 工具权限、版本和兼容性检查。

验收：模拟“请求已发出但响应丢失”“旧回执晚到”“同一幂等键重复回调”，系统不得产生重复成功结果。

#### CLI 方向

统一所有控制面输出：

- `code`、`message`、`retryable`、`details`、`correlation_id`；
- 稳定退出码；
- 本地模式和远程 API 模式使用同一命令语义；
- 默认脱敏，显式参数才能显示调试详情；
- 支持幂等键和结果未知查询。

验收：脚本客户端只根据 JSON 和退出码就能区分成功、可重试失败、不可重试失败和结果未知。

### P2 生产可靠性和安全

完成后才适合把平台交给多人或长期运行：

- PostgreSQL 正式索引、备份、迁移和连接池；
- Worker lease、心跳、可见性超时和优雅取消；
- 真实队列 Adapter 和故障恢复；
- Workspace/Project 权限、RBAC、审计主体和租户隔离；
- Secret Manager、限流、TLS、输入大小限制和数据保留；
- S3/MinIO 真实端到端测试；
- OpenTelemetry trace、指标和告警。

验收：杀掉 Worker、断开模型连接、重复提交请求或切换实例后，不能重复产生成功 Artifact，也不能丢失人工审核状态。

### P3 真实模型和质量评测

真实模型接入不应只验证“能返回 JSON”，还应验证质量和成本：

- Prompt/Model/Schema 版本关联；
- 固定剧本评测集和回归基线；
- Evidence 引用准确率、场景覆盖率和结构化错误率；
- Token、耗时、成本、重试率和人工修改率；
- 模型降级、限流和超时策略。

验收：每次模型或 Prompt 变更都能比较质量指标，并能回滚到上一版本。

### P4 产品化和更多工作流

最后再扩展业务范围：

- 管理台增加 Evidence 高亮、Attempt Diff、审核 Diff 和错误收件箱操作；
- 增加 `script-to-character-sheet`；
- 增加 `storyboard-to-production-plan`；
- 建立 Workflow Definition/Version 的注册和发布流程；
- 为每条工作流分别建立输入、输出、证据、审核和恢复门禁。

## 四、推荐实施顺序

```text
P0 能力基线
  → P1 Context / Main / Agent / CLI 通用能力吸收
  → P2 生产可靠性与安全
  → P3 真实模型评测
  → P4 更多工作流和管理台产品化
```

在 P2 完成前，项目适合作为个人作品库、离线演示和架构验证平台；在 P2 和 P3 完成后，才适合对外描述为可控的生产级 Agent Workflow Platform。
