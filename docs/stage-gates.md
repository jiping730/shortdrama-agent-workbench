# 分阶段开发门禁记录

本文件是本项目的交付门禁。任何阶段只有在其交付物、自动化测试和人工验收命令全部通过后，才允许开始下一阶段；“有接口/骨架”不等于“已支持”。

## 门禁规则

| 阶段 | 必须通过的证据 | 状态 |
|---|---|---|
| 0 只读盘点与架构决策 | `docs/reference-analysis.md`、`docs/architecture-decisions.md`、只读边界测试、依赖边界扫描 | 已通过（2026-10-28） |
| 1 Workflow Adapter 与 Runtime 接口 | Adapter contract tests、已有 workflow 接入/隔离测试、Fake provider contract | 已通过（2026-10-28） |
| 2 领域模型、数据库、迁移、事件 | SQLite transaction tests、migration smoke test、PostgreSQL integration evidence | 待阶段 1 通过 |
| 3 Checkpoint、恢复、幂等、局部重试、Error Inbox | process interruption/restart test、unknown safety test、idempotency and retry matrix | 待阶段 2 通过 |
| 4 script-to-storyboard | 每个业务步骤的 schema/evidence/review tests 和 offline e2e | 待阶段 3 通过 |
| 5 API、CLI、管理台 | REST contract、CLI contract、export contract、UI smoke | 待阶段 4 通过 |
| 6 FakeModel、测试、Docker、CI、文档 | clean environment tests、Docker startup、CI checks、secret scan | 待阶段 5 通过 |
| 7 可选扩展 | real provider/queue/object storage/additional workflow 各自独立验收 | 明确延期，不阻塞 v1 |

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
