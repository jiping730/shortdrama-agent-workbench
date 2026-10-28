# Agent Workflow Platform 平台详细介绍

## 1. 产品定位

Agent Workflow Platform 是一个面向个人 Git 作品库和受控 AI 生产流程的模块化 Agent 平台。

它不把重点放在聊天，而是把 Agent 执行过程组织成一条可持久化、可审核、可恢复、可追踪的业务链路：

~~~text
Workflow Definition
        ↓
Run
        ↓
Task / Step
        ↓
Attempt
        ↓
Artifact + Evidence
        ↓
Human Review
        ↓
Recovery / Selective Retry
        ↓
Audit
~~~

当前第一条业务工作流是 script-to-storyboard。能力矩阵完整落地后，平台将继续承载 script-to-shotlist、script-to-character-sheet 和 storyboard-to-production-plan 等受控工作流。

## 2. 它解决什么问题

直接调用大模型通常只有：

~~~text
输入 → 输出
~~~

这种方式难以回答：

- 这次输出由哪个模型、哪个版本和哪个 Prompt 生成；
- 输出中的事实是否有原文依据；
- 中途失败后是否可以从上一个成功步骤继续；
- 审核只拒绝了一个场景时，为什么要重新生成全部内容；
- 外部调用超时后，provider 到底有没有执行成功；
- 同一输入重复提交是否会产生重复结果；
- 谁在什么时间批准或拒绝了什么内容。

本平台把这些问题变成明确的领域对象、状态、事件和审计记录。

## 3. 当前版本和目标完成态

| 维度 | 当前版本 | 能力矩阵完整落地后 |
| --- | --- | --- |
| 运行方式 | 本地单体、SQLite 默认、同步 API | PostgreSQL、队列 Worker、可水平扩展的执行边界 |
| 模型 | FakeModel 默认，Anthropic 为可选 Adapter | 真实模型、版本管理、评测、成本和降级策略 |
| 工作流 | script-to-storyboard 完整离线闭环，script-to-shotlist 扩展验证 | 多个受控工作流统一发布、版本和权限管理 |
| 证据 | source range、source text、hash、evidence_ids | confidence、evidence_level、sensitivity、规则版本和跨对象 lineage |
| 审核 | ReviewTask、场景拒绝、局部重试 | Evidence 高亮、Attempt Diff、多人审核和审批策略 |
| 队列 | SQLite Queue、LocalWorker | lease、心跳、可见性超时、外部队列和故障转移 |
| 存储 | LocalArtifactStore，S3 Contract | S3/MinIO 生产端到端、保留、加密和访问审计 |
| 安全 | .env 脱敏、secret scan、独立仓库 | Auth、RBAC、Workspace 隔离、Secret Manager 和 TLS |
| 可观测性 | RunEvent、Attempt、ExternalCall、基础时间线 | OpenTelemetry、指标、告警、成本和质量看板 |

因此，当前项目已经是可运行的 Runtime 基础版；“完整企业平台”是能力矩阵完成后的目标状态，不是当前默认运行模式。

## 4. 平台组成

### 4.1 Control Plane

Control Plane 是平台的管理入口，负责：

- 创建和查询 Run；
- 查看步骤、Attempt、Artifact、Evidence 和事件；
- 暂停、恢复、取消和重试；
- 创建、批准和拒绝 ReviewTask；
- 查询 Error Inbox；
- 导出 JSON、CSV 和 HTML；
- 提供 REST API、CLI 和轻量管理台。

Control Plane 不直接执行模型业务逻辑，而是调用 Runtime。

### 4.2 Workflow Runtime

Runtime 是平台核心。它不负责“聊天”，而负责执行可靠性：

- 将 WorkflowAdapter 注册为版本化 WorkflowDefinition；
- 按步骤顺序调度业务逻辑；
- 保存 Attempt 和 Checkpoint；
- 约束 Run/Step 状态转换；
- 管理审核暂停和局部重试；
- 处理恢复、幂等和结果未知；
- 写入 RunEvent、ExternalCall 和 Artifact lineage。

### 4.3 Execution Plane

Execution Plane 将模型和工具作为可替换执行能力：

- FakeModel：离线、确定性、可注入错误模式；
- Anthropic Adapter：可选真实模型边界；
- ToolRegistry：统一工具契约和审计；
- LocalWorker：验证异步执行；
- TaskQueue：本地队列和未来生产队列边界。

### 4.4 Data Plane

Data Plane 保存平台事实：

- Run 和 Step 生命周期；
- Attempt 历史；
- Checkpoint 快照；
- Artifact 内容和 lineage；
- Evidence 原文范围；
- Review 决策；
- Tool/External 调用；
- RunEvent 时间线。

### 4.5 Observability

Observability 让一次运行可以被解释：

~~~text
Run
 ├── Step timeline
 ├── Attempt history
 ├── Artifact lineage
 ├── Evidence references
 ├── Review decisions
 ├── Tool/Model/External calls
 └── Error and recovery events
~~~

## 5. 第一条工作流详解

### 5.1 script-to-storyboard

~~~text
prepare_input
→ split_script
→ build_source_index
→ extract_facts
→ validate_facts
→ generate_storyboard
→ validate_storyboard
→ wait_for_human_review
→ revise_rejected_scenes
→ adopt_result
→ export_artifacts
~~~

### 5.2 输入

- 剧本标题；
- script ID；
- UTF-8 剧本文本；
- project/workspace 标识；
- 可选模型模式和幂等键。

### 5.3 输出

每条分镜至少包含：

- scene_id；
- shot_id；
- shot_type；
- duration_hint；
- location；
- characters；
- action；
- camera；
- dialogue_or_voiceover；
- visual_intent；
- evidence_ids。

### 5.4 审核机制

Run 首次生成后进入 waiting_review：

1. 审核员查看场景、分镜和 Evidence；
2. 可以批准场景；
3. 可以拒绝指定场景并写入意见；
4. Runtime 只修订被拒绝场景；
5. 原 Attempt 和 Artifact 保留；
6. 新修订生成新的 Attempt 和子 Artifact；
7. 全部通过后进入 completed。

### 5.5 恢复机制

如果进程在安全边界中断：

- 已成功步骤不会重新执行；
- Runtime 读取最新 Checkpoint；
- 遗留 running Step 被恢复为可处理状态；
- 外部调用未知时进入人工确认或 reconciliation；
- 从最近有效边界继续执行。

## 6. 一次典型运行

~~~text
1. 用户提交剧本
2. Runtime 创建 Run
3. prepare_input 保存输入 Artifact
4. split_script 生成稳定 scene_id
5. build_source_index 保存 Evidence
6. ModelProvider 提取 Facts
7. Schema 校验 Facts 和 Storyboard
8. Run 进入 waiting_review
9. 审核员拒绝场景 1
10. Runtime 只修订场景 1
11. 场景 2 复用原 Artifact
12. 审核员批准全部场景
13. Runtime 采用最终 Artifact
14. 导出 JSON/CSV/HTML
15. Run 进入 completed
~~~

## 7. 用户角色

### 7.1 Workflow Operator

负责创建 Run、查看状态、暂停、恢复、取消和导出。

### 7.2 Reviewer

负责查看 Evidence、批准结果、拒绝具体场景和填写修订意见。

### 7.3 Platform Developer

负责实现 WorkflowAdapter、Provider、Tool 和 ArtifactStore，不直接修改运行历史。

### 7.4 Auditor

负责查看 RunEvent、Attempt、Artifact lineage、ExternalCall 和审核记录。

目标完成态下，这些角色通过 Workspace/Project 权限和 RBAC 隔离。

## 8. 使用方式

### 8.1 本地离线模式

~~~bash
python -m pip install -e ".[dev]"
python -m uvicorn agent_platform.api:app --reload
~~~

使用 FakeModel 创建 Run：

~~~bash
python -m agent_platform.cli --json run create \
  --project-id demo \
  --script-file examples/sample_script.txt
~~~

### 8.2 Docker/PostgreSQL 模式

~~~bash
docker compose up --build
~~~

该模式用于验证 PostgreSQL、容器启动、健康检查和持久化边界，不等于已经具备生产部署所需的权限、备份和高可用。

### 8.3 真实模型模式

目标使用方式：

~~~bash
python -m pip install -e ".[anthropic]"
~~~

通过环境变量注入 Provider 和凭据。密钥不能写入代码、.env 提交内容或导出文件。

### 8.4 管理台和 API

启动服务后：

- 管理台：http://localhost:8000/；
- OpenAPI：http://localhost:8000/docs；
- Run 查询：GET /api/v1/runs；
- 审核：POST /api/v1/reviews/{review_id}/approve 或 reject；
- 事件：GET /api/v1/runs/{run_id}/events；
- 导出：CLI 的 export json/csv/html。

## 9. 四个参考项目如何转化为自己的平台

平台不是把四个项目拼在一起，而是提炼四类能力：

| 能力来源 | 被转化成的平台能力 |
| --- | --- |
| Agent Workflow | WorkflowAdapter、ReviewGate 思想、ModelProvider、ToolRegistry、业务编排和生命周期边界 |
| Context | Evidence、SourceIndex、规则、Schema 版本和可追溯 Contract |
| Main | 脚本解析、Preview/Confirm、Checkpoint、Worker Recovery、数据库事务 |
| CLI | 稳定 JSON、错误码、可重试性、结果未知、导出和远程控制面边界 |

参考实现中的公司 Prompt、内部服务、账号、数据、组织权限和云配置不进入本项目。所有能力重新用本项目自己的 Python、Pydantic、SQLAlchemy、FastAPI 和测试实现。

## 10. 目标完成态的产品价值

### 对内容生产

- 剧本到结构化分镜的流程可重复；
- 每个事实和镜头都有原文依据；
- 审核员可以按场景局部修改；
- 生成历史、审核意见和最终版本可追溯。

### 对平台工程

- Agent 工作流不再是一次性脚本；
- 模型和工具可以替换；
- 外部不确定性不会静默造成重复执行；
- 中断、重试和恢复有明确语义；
- 新工作流共享同一运行时。

### 对个人作品库

- 展示 Workflow Runtime 和领域建模能力；
- 展示 Agent 与传统后端工程的结合；
- 展示人工审核、可观测性和可靠性设计；
- 展示从参考项目抽象能力并独立重写的工程边界。

## 11. 明确不属于平台核心的内容

- 聊天首页和长期对话记忆；
- FAISS、Chroma、Milvus、Embedding、GraphRAG、Tavily、MCP；
- 真实视频、图片和音频生成；
- 一开始拆分微服务或部署 Kubernetes；
- 复杂计费和大规模商业多租户；
- 未经确认的公司 Prompt、账号、内部接口和业务数据。

## 12. 后续路线

~~~text
能力基线和 Contract Registry
        ↓
Context / Main / Agent / CLI 能力补齐
        ↓
生产队列、权限、PostgreSQL、对象存储和观测
        ↓
真实模型评测和质量闭环
        ↓
更多工作流和管理台产品化
~~~

在生产可靠性、安全和模型评测完成前，平台最适合用于个人作品库、离线演示、架构验证和受控内部流程；完成后才适合对外称为生产级 Agent Workflow Platform。
