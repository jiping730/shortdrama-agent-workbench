# 参考项目只读盘点

盘点日期：2026-10-28。四个参考目录只读访问；本仓库没有对它们建立 Python import、路径依赖或复制源码。以下结论只提炼边界、契约和工程思想，未带入公司 Prompt、账号、内部地址、业务数据或云配置。

## 1. 参考模块

| 参考模块 | 真实入口/证据 | 观察到的能力 | 对本项目的结论 |
|---|---|---|---|
| `zhongwen-shortdrama-agent` | `production-chain-agent/production_chain/workflow.py`、`models.py`、`tests/test_workflow.py` | `ProductionChainAgent` 协调 `ScriptSkill`、`AssetSkill`、`SceneSkill`、`GenerationSkill`；`stable_id`；注入式 LLM；`ReviewGate`；测试中的 Mock/Broken LLM | 作为 WorkflowAdapter 的行为参考。原实现状态和任务存储以内存为主，外层补 Runtime State、Attempt、Checkpoint、事件与恢复。 |
| `zhongwen-shortdrama-agent` | `pi-http-wrapper/src/pi_http_wrapper/tool_bridge.py`、`engine.py`、`tests/test_tool_bridge.py` | 工具调用 nonce/会话绑定、超时、unknown、精确回执、并发与 stale callback 防护 | 提炼 ToolRegistry 和 ExternalCall 的审计/unknown 语义；不引入 Pi、Codex、内部服务或其运行配置。 |
| `zhongwen-shortdrama-main` | `src/modules/script-breakdown/{types.ts,validators.ts,worker.ts,test-doubles.ts}`、`src/modules/storyboard/{preview.ts,service.ts,repository.ts}` | 证据范围校验、结构化输出、worker claim/recovery、阶段 checkpoint、局部 retry、数据库事务、导入 preview/confirm | 重写为 Python/Pydantic/SQLAlchemy 的证据与恢复契约；不复制 TypeScript 业务实现。 |
| `zhongwen-shortdrama-cli` | `ARCHITECTURE.md`、`src/shortdrama_cli/cli/runtime.py`、`api/errors.py` | CLI 只调用服务端、稳定 JSON envelope、错误码/可重试性/结果未知分层、幂等键、输出脱敏 | 本项目 CLI 直接服务本地 Control Plane，保留结构化错误、幂等键和 JSON/CSV/HTML 导出，不连接参考服务端。 |
| `zhongwen-shortdrama-context` | `docs/40-ADR-agent-runtime-v1.md`、`docs/contracts/zhongwen-shortdrama-data-contract-v1.md` | 规格先行、证据纪律、事件契约、运行层/能力层分离、写回可追溯 | 采用本项目自己的通用领域模型；公司云、组织、身份和专有数据只作为不可带入的边界。 |

## 2. 可复用设计思想

| 设计思想 | 来源 | 本项目落点 |
|---|---|---|
| 稳定业务 ID 和输入哈希 | Agent `stable_id`、main 的恢复/引用模型 | `domain.stable_id`、`content_hash`、稳定 `scene_id`、Attempt idempotency key |
| 技能/工作流与状态存储解耦 | Agent 的 Skill 分层和 main 的 repository/worker 分层 | `WorkflowAdapter` 只执行步骤；`WorkflowRuntime` 负责状态、事务和恢复 |
| 结构化输出必须验证 | Agent 的 `_validate_*`、main 的 schema/validator | 所有事实、场景、分镜经 Pydantic 校验，失败归类为 `schema_validation_failed` |
| 人审是独立闸门 | Agent `ReviewGate` | ReviewTask 持久化；拒绝只进入指定 scene 的新 Attempt；通过场景复用 Artifact |
| 工具回执不是异常文本 | Agent Tool Bridge、CLI error projection | ToolRegistry 返回结构化错误；ExternalCall unknown 禁止盲重试 |
| worker 具备断点恢复 | main `worker.ts`、stage checkpoints | 每个安全边界生成 Checkpoint；`recover()` 从最新有效快照接续 |
| CLI/API 结果可机器消费 | cli JSON envelope 与错误映射 | 版本化 REST、argparse CLI、稳定 JSON/CSV/HTML 导出 |

## 3. 需要重写或隔离的内容

| 内容 | 原因 | 处置 |
|---|---|---|
| Agent 的 LLM prompt 和 provider 实现 | 可能包含公司业务、模型路由或内部配置，许可证/归属不能由本项目假设 | FakeModel 默认；`ModelProvider` 接口；Anthropic 适配器是可选官方 SDK 边界 |
| Agent 的资产/生成链 | 本项目不生成真实图片、视频、音频，第一条工作流只做 script-to-storyboard | 保留“候选→审核→采用”的思想，不接入媒体 provider |
| main 的 PostgreSQL 业务表、TypeScript repository | 业务范围和部署边界不同 | SQLAlchemy 独立模型；SQLite 默认，PostgreSQL 通过 `DATABASE_URL` |
| cli 的服务端环境、token/session、trusted endpoints | 属于原服务的账号与网络边界 | 本 CLI 只操作本地数据库和 Artifact Repository，不读取参考凭证 |
| context 的公司身份、云资源、组织角色和专有契约 | 不属于个人作品库平台的可提交代码 | 仅吸收“证据、事件、模块边界”原则 |

## 4. 明确不引入的内容

| 不引入 | 原因 |
|---|---|
| FAISS、Chroma、Milvus、Embedding、GraphRAG、Tavily、长期对话记忆、MCP | 不是本平台可靠工作流的核心；证据来自原文范围，不依赖向量检索 |
| 公司内部 Prompt、账号、密钥、接口地址、数据库配置、业务数据 | 绝对边界与安全/许可证要求 |
| 真实媒体生成和付费 provider | 第一版不做图片/视频/音频生成，FakeModel 足够支撑 Runtime 验收 |
| 微服务、Kubernetes、复杂计费、多租户 | 个人作品库第一版采用模块化单体 |
| 参考仓库作为安装依赖 | 目标项目必须独立安装、独立配置、独立测试、独立运行 |

## 盘点结论

已有 Agent Workflow 不是玩具：它有稳定 ID、注入式模型、分层 Skill、ReviewGate、Mock/错误测试和工具桥接边界。但它不是持久化执行引擎，缺少本项目要求的统一 Run/Task/Step/Attempt/Checkpoint 生命周期。因此本项目复用其“业务编排边界和审核不可越权”思想，并通过 `WorkflowAdapter` 注入，而不是把它变成第二套内存状态机或直接绑定参考仓库。
