# 分阶段开发门禁记录

本文件是本项目的交付门禁。任何阶段只有在其交付物、自动化测试和人工验收命令全部通过后，才允许开始下一阶段；“有接口/骨架”不等于“已支持”。

## 门禁规则

| 阶段 | 必须通过的证据 | 状态 |
|---|---|---|
| 0 只读盘点与架构决策 | `docs/reference-analysis.md`、`docs/architecture-decisions.md`、只读边界测试、依赖边界扫描 | 已通过（2026-10-28） |
| 1 Workflow Adapter 与 Runtime 接口 | Adapter contract tests、已有 workflow 接入/隔离测试、Fake provider contract | 已通过（2026-10-28） |
| 2 领域模型、数据库、迁移、事件 | SQLite transaction tests、migration smoke test、PostgreSQL integration evidence | 已通过（2026-10-28） |
| 3 Checkpoint、恢复、幂等、局部重试、Error Inbox | process interruption/restart test、unknown safety test、idempotency and retry matrix | 已通过（2026-10-28） |
| 4 script-to-storyboard | 每个业务步骤的 schema/evidence/review tests 和 offline e2e | 已通过（2026-10-28） |
| 5 API、CLI、管理台 | REST contract、CLI contract、export contract、UI smoke | 已通过（2026-10-28） |
| 6 FakeModel、测试、Docker、CI、文档 | clean environment tests、Docker startup、CI checks、secret scan | 已通过（2026-10-28） |
| 7 可选扩展 | real provider/queue/object storage/additional workflow 各自独立验收 | 已通过（2026-10-28） |

## 阶段 0 当前验收

验收对象：四个只读参考目录、个人 RAG 项目边界、目标仓库当前代码。

已形成的证据：

- [reference-analysis.md](reference-analysis.md)：包含参考模块、可复用思想、重写/隔离内容和明确不引入内容四张表。
- [architecture-decisions.md](architecture-decisions.md)：记录 workflow 复用边界、Runtime 解耦、非 RAG 核心和模块化单体决策。
- `tests/gates/test_stage0_gate.py`：自动检查阶段 0 文档存在、平台代码不引用参考绝对路径/个人 RAG 项目/禁止技术路线。
- 参考目录只读访问；本项目 Git 工作区为独立仓库。

阶段 0 通过标准：

```bash
py -3.9 -m pytest tests/gates/test_stage0_gate.py -q --basetemp=.pytest-tmp
```

只有该命令通过后，才进入阶段 1。此前已有的业务实现不自动视为后续阶段已通过。

阶段 0 门禁结果（2026-10-28）：`3 passed`。阶段 0 的文档、只读参考边界和禁止依赖扫描均已通过；现允许开始阶段 1。

## 阶段 1 当前验收

已形成的证据：

- `agent_platform/workflows/base.py`：明确 `register`、`validate`、`start`、`resume`、`execute_step`、`recover` 六项 Adapter contract，并在 Runtime 初始化时 fail fast 校验。
- `agent_platform/workflows/legacy.py`：通过注入式 `LegacyWorkflowAdapter` 委托已有 workflow 的业务方法和生命周期，不导入参考仓库源码；Runtime 继续持有 Attempt、Checkpoint、事务和事件。
- `tests/gates/test_stage1_gate.py`：验证契约完整性、注入式 workflow 的持久化执行、`start/resume/recover` 生命周期委托和不完整 Adapter 拒绝。
- `tests/unit`、`tests/integration`、`tests/e2e`：既有基线回归通过。

阶段 1 验收命令及结果：

```text
py -3.9 -m pytest tests/gates/test_stage1_gate.py -q --basetemp=.pytest-tmp
4 passed

py -3.9 -m pytest -q --basetemp=.pytest-tmp-stage1-all
19 passed
```

阶段 1 已通过，现允许进入阶段 2。阶段 2 的数据库扩展和迁移验收仍未开始，不能以本阶段结果代替。

## 阶段 2 当前验收

已形成的证据：

- `agent_platform/db.py`：15 个核心领域表通过 SQLAlchemy 统一建模，包含 Run、Task、StepExecution、Attempt、Checkpoint、Artifact、Evidence、ReviewTask、ToolCall、ExternalCall 和 RunEvent 等持久化边界。
- `migrations/versions/0001_initial.py`：Alembic 初始 revision；SQLite 空库 upgrade smoke test 通过且重复 upgrade 幂等。
- `tests/gates/test_stage2_gate.py`：验证 SQLite 表/列契约、事务回滚、结构化事件顺序、Alembic upgrade 和 PostgreSQL schema/事务。
- `Dockerfile`、`docker-compose.yml`：镜像包含 Alembic 配置/迁移目录，PostgreSQL 测试端口仅绑定本机回环地址。

阶段 2 验收命令及结果：

```text
py -3.9 -m pytest tests/gates/test_stage2_gate.py -q --basetemp=.pytest-tmp-stage2-postgres
5 passed

py -3.9 -c "... command.upgrade(c, 'head') ..."
postgres alembic upgrade head: ok
```

PostgreSQL 证据使用隔离的 `stage2gate` compose project 和新 volume，未修改原有数据库卷；验证后该临时 project 会停止。阶段 2 已通过，现允许进入阶段 3。阶段 3 的恢复、幂等、局部重试和 Error Inbox 仍需单独门禁。

## 阶段 3 当前验收

已形成的证据：

- `agent_platform/runtime.py`：每个成功安全边界保存 Checkpoint；重启后可从最新快照恢复；成功 Attempt 保留且不重复执行；超时外部调用落为 `unknown`；unknown 在 reconciliation 前禁止 retry；场景 retry 只调整目标 revision；取消终态可重复调用；非法 step 转换写入事件。
- `agent_platform/repository.py`、`agent_platform/api.py`：Error Inbox 聚合 failed/needs_recovery Run、unknown ExternalCall 和 pending ReviewTask，保持只读投影，不自动重试。
- `agent_platform/workflows/script_to_storyboard.py`：Evidence ID 在同一 Run 内稳定，同时避免相同脚本跨 Run 的全局主键冲突；选择性修订先 revise、再 validate，再重新打开审核闸门。
- `tests/gates/test_stage3_gate.py`：覆盖进程中断恢复、成功步骤不重复、局部场景重试、timeout/unknown 安全、Error Inbox、pause/resume/cancel 和非法转换审计。

阶段 3 验收命令及结果：

```text
py -3.9 -m pytest tests/gates/test_stage3_gate.py -q --basetemp=.pytest-tmp-stage3-gate2
7 passed

py -3.9 -m pytest -q --basetemp=.pytest-tmp-stage3-all2
30 passed, 1 skipped
```

全量测试中的 1 个 skip 是阶段 2 PostgreSQL 测试未设置连接串；阶段 2 已在隔离 PostgreSQL 环境单独取得 `5 passed`，不影响阶段 3 专项门禁。阶段 3 已通过，现允许进入阶段 4；阶段 4 只验证 script-to-storyboard 业务契约和证据覆盖，不把本阶段可靠性测试当作业务验收。

## 阶段 4 当前验收

已形成的证据：

- `agent_platform/workflows/script_to_storyboard.py`、`agent_platform/schemas.py`：11 个声明步骤；确定性 scene/evidence 范围；Fact、Shot、Storyboard 的结构化校验；事实和分镜的 Evidence 覆盖约束；审核后只修订目标 scene。
- `tests/gates/test_stage4_gate.py`：验证步骤顺序、稳定 scene ID、原文 offset、跨 Run Evidence 隔离、Schema 拒绝、无依据事实拒绝、分镜字段契约和 FakeModel 离线全流程。
- 离线流程实际从 `waiting_review` 经审核批准到 `completed`，并产生 JSON/CSV/HTML 导出 Artifact。

阶段 4 验收命令及结果：

```text
py -3.9 -m pytest tests/gates/test_stage4_gate.py -q --basetemp=.pytest-tmp-stage4-gate
5 passed

py -3.9 -m pytest -q --basetemp=.pytest-tmp-stage4-all
35 passed, 1 skipped
```

阶段 4 已通过，现允许进入阶段 5。阶段 5 的 REST、CLI、导出契约和管理台 smoke test 尚未开始；本阶段只证明业务插件，不证明控制面完整。

## 阶段 5 当前验收

已形成的证据：

- `agent_platform/api.py`：版本化 REST 路由覆盖 Run 创建/查询/暂停/恢复/取消/重试、事件、Artifact、Review、审核决策、Workflow 描述和 Error Inbox。
- `agent_platform/cli.py`：`run create/show/list/pause/resume/cancel/retry`、`review list/approve/reject`、`workflow list/describe` 和 `export json/csv/html` 均通过真实 SQLite 控制面调用。
- `agent_platform/exporter.py`：JSON、CSV、HTML 三种导出均写入文件并包含 Run/步骤/审核/审计信息。
- `agent_platform/api.py` 根路由：运行管理台 smoke 页面展示 Run 控制面入口、状态和时间线，不以聊天窗口为首页。
- `tests/gates/test_stage5_gate.py`：验证 OpenAPI 路径契约、API 审核/局部重试闭环、CLI 全部命令族和三种导出。

阶段 5 验收命令及结果：

```text
py -3.9 -m pytest tests/gates/test_stage5_gate.py -q --basetemp=.pytest-tmp-stage5-gate2
2 passed

py -3.9 -m pytest -q --basetemp=.pytest-tmp-stage5-all
37 passed, 1 skipped
```

阶段 5 已通过，现允许进入阶段 6。阶段 6 的 clean environment、FakeModel 全模式、Docker startup、CI 和 secret scan 仍需单独验证。

## 阶段 6 当前验收

已形成的证据：

- `tests/gates/test_stage6_gate.py`：验证 FakeModel 的 `success`、`invalid_output`、`timeout`、`model_error`、`unknown` 五种确定性模式，工程交付文件、文档契约、CI 检查项和高置信度敏感信息/参考路径扫描。
- `Dockerfile`：包含 `alembic.ini` 和 `migrations`，并通过 PostgreSQL extra 安装正式数据库驱动。
- `docker-compose.yml`：PostgreSQL 健康检查、`service_healthy` 启动依赖、本机回环端口绑定和隔离数据卷。
- `agent_platform/runtime.py`：修复 PostgreSQL 外键顺序问题；先写 Run，再写输入 Artifact，最后回填 `input_artifact_id`，SQLite 与 PostgreSQL 行为一致。
- `.github/workflows/ci.yml`：配置 pytest、compileall 和 gitleaks CI 检查；本机未安装 gitleaks，因此不把本地检查冒充为已执行。

阶段 6 验收命令及结果：

```text
py -3.9 -m pytest tests/gates/test_stage6_gate.py -q --basetemp=.pytest-tmp-stage6-gate4
4 passed

py -3.9 -m pytest -q --basetemp=.pytest-tmp-stage6-all2
41 passed, 1 skipped
```

Docker 隔离验收使用 Compose project `stage6gate2`，未删除既有 Docker volume：

```text
docker compose -p stage6gate2 ps
platform: Up; postgres: Up (healthy)

容器内 GET /health: 200
容器内 POST /api/v1/runs: 200, status=waiting_review
PostgreSQL: 该 Run 存在，9 个 artifacts，23 条 run_events，input_artifact_id 已正确回填
```

阶段 6 已通过，现允许进入阶段 7。阶段 7 必须分别证明真实模型边界、队列 Worker、对象存储适配器和第二条工作流；未通过前不能标记整体目标完成。

## 阶段 7 当前验收条件

- 官方 Anthropic SDK：注入式 SDK client 的离线 contract test；有效 JSON、非法 JSON、Pydantic schema 错误均进入结构化错误路径；默认 provider 仍为 FakeModel。
- 队列：SQLite 队列跨实例重开后保留消息；幂等 enqueue 不复制消息；LocalWorker 能执行 deferred Run，并正确 ack/nack。
- 对象存储：Local 和 S3-compatible `put` contract；Runtime 注入 S3 adapter 后数据库仍保存 URI、hash、schema version 和父工件关系；不上传真实业务数据。
- 更多工作流：`script-to-shotlist` 使用同一 Runtime，产生自己的结构化 Artifact、Checkpoint 和 Evidence，不复制状态机。
- 安全边界：阶段 7 测试不需要真实密钥、外网模型请求或云端对象存储；生产级多 worker lease、可见性超时和云端演练继续明确延期。

阶段 7 专项门禁命令：

```text
py -3.9 -m pytest tests/gates/test_stage7_gate.py -q --basetemp=.pytest-tmp-stage7-gate
```

阶段 7 验收结果：

```text
py -3.9 -m pytest tests/gates/test_stage7_gate.py -q --basetemp=.pytest-tmp-stage7-gate2
9 passed

py -3.9 -m pytest -q --basetemp=.pytest-tmp-stage7-all3
50 passed, 1 skipped
```

Docker/PostgreSQL 验收使用隔离 Compose project `stage6gate2`，未删除既有 volume：

```text
容器内 GET /health: 200
script-to-shotlist Run: completed
PostgreSQL: 6 artifacts, 5 checkpoints, 2 evidence
```

阶段 7 已通过，允许将整体 v1 目标标记为完成。明确延期项仍为生产级多 worker lease/可见性超时、真实云对象存储端到端演练、OpenTelemetry exporter、完整鉴权/多租户、复杂计费、真实媒体生成和更多业务工作流；这些不被当前代码宣称为已支持。
