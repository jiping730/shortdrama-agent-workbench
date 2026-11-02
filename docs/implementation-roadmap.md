# 能力矩阵完整实现路线图

## 1. 使用说明

本文档把 capability-matrix.md 中的 A、B、C 状态转换为可执行的开发步骤。

- A：当前已经实现，本路线图只做增强和生产化；
- B：当前已有接口、Adapter 或离线 Contract，本路线图负责补齐真实边界；
- C：当前是规划或延期能力，本路线图定义首次实现顺序。

每个步骤都包含：

1. 实现目标；
2. 需要修改或新增的模块；
3. 实现完成后新增的功能；
4. 必须补充的测试；
5. 进入下一步的门槛。

当前阶段 0～7 已完成的是核心 Runtime v1 验收。本路线图从“能力矩阵完整实现”开始，不把已有的离线 Contract 直接等同于生产能力。

## 2. 总体依赖关系

~~~text
R0 能力基线与 Contract Registry
  ↓
R1 Context Contract 与 Evidence 体系
  ↓
R2 Script Processing 与 Preview/Confirm
  ↓
R3 Agent Tool Bridge 与 ExternalCall Reconciliation
  ↓
R4 统一 API/CLI/Error Contract
  ↓
R5 PostgreSQL、生产队列、对象存储和观测
  ↓
R6 身份、权限、Workspace 隔离和安全
  ↓
R7 真实模型、评测和质量闭环
  ↓
R8 更多工作流和管理台产品化
~~~

不能跳过 R0～R4 直接扩展更多业务工作流。否则新增工作流会继续建立在不完整的 Context、错误和外部调用语义上。

## 3. R0 能力基线与 Contract Registry

### 3.1 实现目标

将当前能力矩阵变成可被代码、测试和 CI 消费的能力登记表。

### 3.2 主要实现

建议新增：

~~~text
agent_platform/contracts/
├── registry.py
├── versions.py
├── errors.py
├── events.py
└── compatibility.py
~~~

具体工作：

- 给 Script、Scene、Evidence、Fact、Shot、Storyboard、Review、Artifact 建立 Schema 版本；
- 为每个 Contract 登记名称、版本、兼容范围、生产状态和测试入口；
- 为 RunEvent、ExternalCall、Error Envelope 建立稳定事件类型；
- 将 capability-matrix 中每一行映射到 implementation path、test path 和 demo command；
- 增加 Contract 兼容性检查，阻止未知版本进入 Runtime；
- 将当前硬编码的 workflow version、prompt version、schema version 统一纳入版本对象。

### 3.3 实现后新增功能

- 可以查询某个对象当前使用的 Schema 版本；
- 旧 Artifact 可以按照版本策略读取；
- 新版本发布前可以发现不兼容字段；
- 任何能力都能从文档追踪到代码、测试和演示；
- CI 可以检查“文档标记为 A 但没有测试”的情况。

### 3.4 测试和验收

- Schema version registry 测试；
- 向后兼容和拒绝不兼容版本测试；
- Event type registry 测试；
- Contract 到代码/测试路径完整性测试；
- 重复注册和未知版本失败测试。

### 3.5 完成门槛

- 所有当前 A 状态能力有登记记录；
- 所有当前 B/C 状态能力有缺口和目标版本；
- Runtime 不再接受未登记的 workflow/schema/event version。

## 4. R1 Context Contract 与 Evidence 体系

### 4.1 对应能力矩阵

主要补齐 Context 的 B/C 能力：

- 通用 SourceIndex；
- EvidenceRange 和 EvidenceCoverage；
- RuleResult；
- confidence、evidence_level、sensitivity、status；
- 跨业务 lineage；
- Schema 版本兼容。

### 4.2 主要实现

建议新增：

~~~text
agent_platform/context/
├── source_index.py
├── evidence.py
├── rules.py
├── coverage.py
├── lineage.py
└── contracts.py
~~~

实现内容：

- 将当前 storyboard 中的场景切分和 Evidence 生成抽象为通用服务；
- Evidence 增加 rule_version、evidence_level、confidence、sensitivity 和 validation_status；
- SourceIndex 同时保存字符范围、行范围和原文 hash；
- RuleEngine 返回结构化 RuleResult，不直接抛出不可解释文本；
- 建立跨 Run、跨 Artifact、跨 Scene 的 lineage 查询；
- 支持 Evidence 的脱敏视图和审计视图；
- 将无依据事实、越界范围、跨 Run 引用统一收敛为 Context 错误。

### 4.3 实现后新增功能

- 新工作流可以复用同一套 Evidence 和 SourceIndex；
- 用户能看到“这条事实为什么被接受或拒绝”；
- 可以区分原始证据、模型推断和人工确认；
- 证据缺失会显示具体规则、字段和来源范围；
- 允许对历史 Evidence 做版本化比较；
- 未来人物表、镜头表和制作计划可以共享同一证据链。

### 4.4 测试和验收

- Evidence range 字符/行坐标一致性测试；
- 越界、空文本、跨 Run、跨 Script 引用测试；
- evidence_level/confidence/sensitivity 校验测试；
- RuleResult 可解释错误测试；
- Artifact lineage 跨修订、跨步骤查询测试；
- 同一输入在同一规则版本下生成稳定 Evidence ID 测试。

### 4.5 完成门槛

- script-to-storyboard 改用通用 Context Contract；
- script-to-shotlist 不再维护自己的 Evidence 逻辑；
- 所有事实和分镜输出都能查询来源、规则版本和校验结果。

## 5. R2 Script Processing 与 Preview/Confirm

### 5.1 对应能力矩阵

主要补齐 Main 的 B/C 能力：

- Parser Strategy；
- 多格式剧本解析；
- 导入 Preview；
- 人工 Confirm；
- Validation Report；
- 解析规则版本化；
- 局部修改和回滚。

### 5.2 主要实现

建议新增：

~~~text
agent_platform/script_processing/
├── parser.py
├── strategies/
│   ├── scene_heading.py
│   ├── plain_text.py
│   └── structured_script.py
├── preview.py
├── validation.py
├── revisions.py
└── import_service.py
~~~

实现内容：

- 将当前 _split_script 从业务 Adapter 中抽出；
- 定义 ParserStrategy 接口和解析规则版本；
- 支持场景标题、角色、对白、动作、地点和道具的基础识别；
- 生成 ImportPreview，不直接进入模型生成；
- 允许用户修改场景边界、标题和标签；
- Confirm 后才创建正式 ScriptVersion 和 Evidence；
- 修改一个场景时保持无关 scene_id、Evidence 和 Artifact 不变；
- 输出结构化 ValidationReport；
- 允许保存 rejected import、修订版本和回滚版本。

### 5.3 实现后新增功能

- 用户可以在生成分镜前预览和修正剧本拆解；
- 同一剧本可以使用不同 Parser 版本重新解析；
- 复杂剧本格式可以通过新增 Strategy 扩展；
- 错误不再只显示“解析失败”，而是显示具体行、字段和建议；
- 重新解析不会无条件破坏历史 Run；
- 人工确认后的 ScriptVersion 可重复使用。

### 5.4 测试和验收

- 多种剧本格式解析测试；
- Unicode、空行、长行和混合换行测试；
- Preview 不落正式 Artifact 测试；
- Confirm 后稳定 ID 测试；
- 修改一个场景不影响其他场景测试；
- ValidationReport 错误定位测试；
- 解析规则版本回放和回滚测试。

### 5.5 完成门槛

- script-to-storyboard 只能消费 Confirmed ScriptVersion；
- Preview 和 Confirm 的 API/CLI 有稳定 Contract；
- 解析规则升级有迁移或兼容策略；
- 现有离线 E2E 全部保持通过。

## 6. R3 Agent Tool Bridge 与 ExternalCall Reconciliation

### 6.1 对应能力矩阵

主要补齐 Agent Workflow 的 B 能力：

- nonce/session；
- correlation ID；
- stale callback；
- 结果未知；
- provider reconciliation；
- 工具权限和版本；
- 请求/响应脱敏。

### 6.2 主要实现

扩展：

~~~text
agent_platform/tools.py
agent_platform/providers.py
agent_platform/runtime.py
agent_platform/repository.py
agent_platform/execution/
├── calls.py
├── reconciliation.py
├── callbacks.py
└── permissions.py
~~~

实现内容：

- ToolCall 增加 session_id、nonce、correlation_id、started_at、finished_at；
- ExternalCall 增加 provider_request_id、reconciliation_status 和 callback_generation；
- 迟到回执必须根据 nonce、session 和 generation 拒绝；
- 同一幂等键的重复回执只能产生一个成功结果；
- provider 超时后进入 reconciliation queue；
- 增加人工确认和 provider 查询接口；
- 请求、响应和错误日志做字段级脱敏；
- ToolRegistry 增加工具权限、版本兼容和调用主体校验；
- 将成功但持久化失败划分为可恢复状态，不重复调用 provider。

### 6.3 实现后新增功能

- 外部调用断线后可以查询，而不是盲目重试；
- 旧 Worker 或旧回调不会污染新 Run；
- 真实模型和工具调用有完整请求链路；
- 管理台可以显示调用正在确认、已确认或需要人工处理；
- 工具权限可以按 Workspace、Project 和 Workflow 限制；
- 模型和工具调用日志可以安全导出。

### 6.4 测试和验收

- 请求发出但响应丢失测试；
- 迟到回执测试；
- 重复 callback 测试；
- 同一幂等键并发调用测试；
- provider reconciliation 成功/失败测试；
- 工具权限拒绝测试；
- 敏感字段脱敏测试；
- provider 成功但数据库提交失败的恢复测试。

### 6.5 完成门槛

- unknown 不会被默认 resume 盲目重放；
- 所有外部调用均可通过 correlation_id 查询；
- 同一外部结果最多产生一个成功 Artifact；
- 真实 Anthropic Adapter 通过隔离集成测试。

## 7. R4 统一 API、CLI 和 Error Contract

### 7.1 对应能力矩阵

主要补齐 CLI 的 B 能力和 Control Plane 的远程边界：

- Error Envelope；
- 稳定退出码；
- retryable/result_unknown；
- correlation_id；
- 幂等键；
- 本地/远程模式统一；
- 分页、版本协商和脱敏。

### 7.2 主要实现

建议新增：

~~~text
agent_platform/controlplane/
├── envelopes.py
├── pagination.py
├── auth_context.py
├── versioning.py
└── client.py
~~~

扩展 CLI：

- 增加 endpoint、token、workspace、timeout 和 idempotency-key；
- 本地模式继续直接使用 Runtime；
- 远程模式调用 REST API；
- 统一成功、业务失败、可重试失败和结果未知输出；
- 稳定退出码不随异常文本变化；
- 默认隐藏内部 traceback 和敏感响应；
- 大列表支持分页和过滤；
- 所有请求携带 correlation_id。

### 7.3 实现后新增功能

- 同一条 CLI 命令可以切换本地模式和远程模式；
- 自动化脚本可以可靠判断是否重试；
- 用户可以查询“请求是否真正执行”的未知结果；
- 远程 API 和本地 Runtime 的错误语义一致；
- 大量 Run、Review 和 Artifact 可以分页查询；
- 作品库外部用户可以通过稳定 API 使用平台。

### 7.4 测试和验收

- Error Envelope 全部错误类型测试；
- CLI 退出码矩阵测试；
- 本地/远程命令一致性测试；
- retryable/result_unknown 映射测试；
- 幂等键透传测试；
- 分页、过滤和版本协商测试；
- 默认脱敏和显式 debug 模式测试。

### 7.5 完成门槛

- CLI 不再依赖异常文本判断失败类型；
- REST、CLI、Runtime 共用错误码；
- API 文档、CLI help 和 README 完全一致；
- 旧客户端的兼容策略有测试。

## 8. R5 生产数据、队列、对象存储和观测

### 8.1 对应能力矩阵

主要补齐平台生产边界：

- PostgreSQL 正式索引和连接池；
- Worker lease、心跳、visibility timeout；
- 外部队列；
- S3/MinIO 真实端到端；
- OpenTelemetry、指标和告警。

### 8.2 主要实现

数据库：

- 补充唯一约束、复合索引和查询索引；
- 增加 migration lock 和在线迁移策略；
- 配置连接池、事务隔离和重试；
- 增加备份、恢复和数据保留策略。

Worker：

- 增加 lease_owner、lease_expiry、heartbeat_at；
- 使用 fencing token 防止旧 Worker 写回；
- 支持优雅取消和 visibility timeout；
- ack/nack 与 Runtime 状态保持一致；
- 生产队列 Adapter 保持 TaskQueue Contract。

Artifact：

- 真实 S3/MinIO 上传、读取、校验和删除标记；
- 失败重试和 URI 可用性检查；
- 数据库 metadata 与对象内容的一致性修复任务。

Observability：

- Run/Step/Attempt/ExternalCall trace；
- 成功率、失败率、重试率、耗时、队列积压和模型成本；
- Error Inbox 告警；
- 日志脱敏和长期归档。

### 8.3 实现后新增功能

- 多个 Worker 可以安全并行处理 Run；
- Worker 崩溃后任务会自动恢复；
- 大型 Artifact 不再依赖本地磁盘；
- 运维人员可以看到队列、模型、数据库和 Artifact 的健康状态；
- 可以通过指标发现慢步骤、异常重试和成本异常；
- 生产数据有备份和恢复路径。

### 8.4 测试和验收

- 多 Worker 同一消息抢占测试；
- lease 过期和 fencing 测试；
- Worker 被杀后的恢复测试；
- PostgreSQL 并发事务测试；
- S3/MinIO 上传、读取、断网和重试测试；
- 备份恢复演练；
- OTel trace 与 correlation_id 对齐测试；
- 指标和告警阈值测试。

### 8.5 完成门槛

- 不能重复产生成功 Artifact；
- 不能丢失 ReviewTask 和 Checkpoint；
- PostgreSQL 和对象存储均有独立演练记录；
- 生产 Worker 的并发和故障测试通过。

## 9. R6 身份、权限和安全

### 9.1 对应能力矩阵

补齐当前明确延期的：

- Auth；
- RBAC；
- Workspace/Project 隔离；
- 审计主体；
- Secret Manager；
- TLS、限流和输入保护。

### 9.2 主要实现

领域对象：

- User；
- WorkspaceMember；
- Role；
- Permission；
- APIKey/Session；
- AuditActor。

权限点：

- Workspace 读取和管理；
- Project 读取、运行和导出；
- Review 批准/拒绝；
- Workflow 发布；
- Artifact 读取；
- Error Inbox 处理；
- Tool/Model 调用权限。

安全能力：

- Token 不进入日志；
- Secret Manager 注入模型凭据；
- 请求大小和文件大小限制；
- API 限流；
- TLS；
- 脱敏导出；
- 管理操作写 AuditEvent。

### 9.3 实现后新增功能

- 多个用户可以安全共享一个平台；
- 不同 Workspace 之间无法读取数据；
- 只有授权 Reviewer 可以批准结果；
- 只有授权 Developer 可以发布 Workflow；
- 所有重要操作可追溯到具体用户；
- 密钥轮换不需要修改代码或提交配置。

### 9.4 测试和验收

- 未授权读取/修改测试；
- 跨 Workspace 访问测试；
- RBAC 角色矩阵测试；
- Token 泄漏扫描；
- 限流和大输入测试；
- Secret rotation 测试；
- 审计完整性测试。

### 9.5 完成门槛

- 所有 API、CLI、Artifact 和 Tool 路径都执行权限校验；
- 权限拒绝不泄露资源是否存在；
- 安全扫描、依赖扫描和审计测试通过。

## 10. R7 真实模型和质量评测

### 10.1 对应能力矩阵

补齐真实模型能力：

- Prompt/Model/Schema 版本关联；
- Golden script 评测；
- Evidence 准确率；
- 质量、成本、延迟和人工修改指标；
- 降级、限流和模型回滚。

### 10.2 主要实现

新增：

~~~text
agent_platform/evaluation/
├── datasets.py
├── runners.py
├── metrics.py
├── baselines.py
└── reports.py
~~~

实现内容：

- 建立脱敏 Golden Script 数据集；
- 为每条样本保存期望结构、Evidence 规则和人工评分；
- 固定模型、Prompt、Schema 和规则版本；
- 统计结构化成功率、Evidence 覆盖率、场景完整率、人工修改率；
- 记录 Token、耗时、成本和重试；
- 允许模型 Provider 降级和版本回滚；
- 真实模型测试只在隔离环境运行，不进入默认 CI。

### 10.3 实现后新增功能

- 可以判断模型版本是否真的变好；
- Prompt 修改有回归对比；
- 可以定位是模型、规则还是 Evidence 导致失败；
- 可以按成本、延迟和质量选择 Provider；
- 真实模型异常时可以降级到备用 Provider；
- 模型变更有可审计的版本记录。

### 10.4 测试和验收

- Golden dataset 回归；
- 有效 JSON、非法 JSON、Schema 错误测试；
- Evidence 错误检测；
- 成本和延迟统计测试；
- 降级和回滚测试；
- 模型版本不可变记录测试。

### 10.5 完成门槛

- 每次模型变更都有评测报告；
- 质量指标达到预设阈值；
- 真实模型失败不会破坏 Runtime 的 Attempt、Artifact 和审计语义。

## 11. R8 更多工作流和管理台产品化

### 11.1 对应能力矩阵

补齐：

- character-sheet；
- production-plan；
- Workflow 发布；
- WorkflowVersion 迁移；
- Evidence/Attempt Diff；
- 多人审核和审批策略。

### 11.2 主要实现

新工作流必须分别定义：

- 输入 Schema；
- 输出 Schema；
- Evidence Contract；
- 步骤图；
- Review Gate；
- Recovery 规则；
- Provider/Tool 依赖；
- API、CLI 和导出；
- 独立 Gate Tests。

管理台增加：

- Evidence 原文高亮；
- Attempt Diff；
- Artifact lineage 图；
- Review 批量操作；
- Error Inbox 处理；
- 运行比较；
- 规则和模型版本筛选；
- 成本、质量和延迟看板。

### 11.3 实现后新增功能

- 同一平台可以处理多种短剧生产任务；
- 用户可以从人物表继续生成镜头表和制作计划；
- 不同工作流版本可并行运行；
- 审核员可以比较修订前后差异；
- 运营人员可以按项目、模型、规则和结果质量分析运行；
- 新业务不需要重新开发状态机和恢复系统。

### 11.4 测试和验收

- 每个工作流独立 E2E；
- 工作流版本迁移测试；
- 跨工作流 Artifact lineage 测试；
- 多人审核和权限测试；
- 管理台关键操作 smoke；
- 批量运行和导出测试。

### 11.5 完成门槛

- 新工作流不修改核心 Runtime；
- 所有工作流共享错误、审核、恢复和审计语义；
- 每个工作流都有独立验收报告；
- 管理台不依赖聊天交互才能完成核心操作。

## 12. 每一步完成后的功能增量

| 步骤 | 用户直接获得的新增功能 | 平台新增基础能力 |
| --- | --- | --- |
| R0 | 能查看每项能力是否真正完成 | Contract Registry、状态可追踪 |
| R1 | 查看证据级别、置信度、规则结果和来源链 | 通用 Context/Evidence 层 |
| R2 | 生成前预览、修改和确认剧本拆分 | Parser Strategy、Preview/Confirm、规则版本 |
| R3 | 外部调用超时后可确认，不会盲目重复生成 | nonce/session、stale callback、reconciliation |
| R4 | 本地和远程 CLI 行为一致，可自动判断是否重试 | 统一 Error Envelope、退出码、分页和幂等 |
| R5 | 多 Worker、云存储、断点恢复和运行指标 | lease、心跳、S3、PostgreSQL、OTel |
| R6 | 多用户、多 Workspace 和权限控制 | Auth、RBAC、Secret Manager、审计主体 |
| R7 | 真实模型质量可比较，成本和效果可量化 | Golden dataset、评测、降级和回滚 |
| R8 | 人物表、制作计划、多版本工作流和可视化 Diff | Workflow 发布、版本迁移、产品化管理台 |

## 13. 推荐交付节奏

### 第一个交付批次：R0 + R1

结果：从“当前单条工作流有 Evidence”升级为“平台有通用、版本化、可解释的 Context Contract”。

### 第二个交付批次：R2

结果：从“输入文本直接进入流程”升级为“用户可以预览、修订、确认和回滚剧本拆解”。

### 第三个交付批次：R3 + R4

结果：从“本地可靠运行”升级为“外部调用可确认，API 和 CLI 可被自动化系统稳定使用”。

### 第四个交付批次：R5 + R6

结果：从“个人单机作品库”升级为“可供多人和长期运行的受控平台”。

### 第五个交付批次：R7

结果：从“模型能返回结构化结果”升级为“模型质量、成本、延迟和回归风险可量化”。

### 第六个交付批次：R8

结果：从“一个工作流的 Runtime”升级为“可承载多条业务工作流的平台产品”。

## 14. 阶段门禁模板

每个步骤结束时必须提交以下证据：

~~~text
阶段名称：
能力矩阵条目：
新增代码：
新增 API/CLI：
新增数据表或迁移：
新增测试：
新增演示命令：
失败和恢复场景：
安全检查：
性能或成本证据：
延期事项：
下一阶段入口条件：
~~~

只有当代码、测试、演示和文档四类证据同时存在，才可以把该步骤标记为已完成。

## 15. 最终完成标准

能力矩阵完整实现后，平台应能够：

1. 接收一个带版本的 WorkflowDefinition；
2. 创建可幂等的 Run；
3. 按步骤执行并持久化每个 Attempt；
4. 为每个结果保存 Artifact 和 Evidence；
5. 在人工审核节点暂停；
6. 只修订被拒绝的对象；
7. 在进程、Worker、模型或网络故障后安全恢复；
8. 对未知外部结果进行确认而非盲目重试；
9. 通过本地或远程 API/CLI 操作；
10. 支持多用户权限和多 Workspace 隔离；
11. 记录模型、工具、成本、质量和审计信息；
12. 在不修改核心 Runtime 的情况下增加新工作流。

在这些条件全部满足之前，项目应继续使用“企业级 Runtime 基础版”或“可运行的模块化单体 v1”表述，而不宣称已经完成生产级企业平台。
