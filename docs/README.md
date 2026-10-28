# 文档导航

本目录是项目的设计、验收和扩展文档入口。文档按“参考分析 → 架构决策 → 运行时契约 → 验收门禁”的顺序组织。

## 参考项目只读分析

以下文档保留四个参考文件夹的分析结论，只提炼契约、边界和工程思想，不复制源码、Prompt、业务数据、账号或内部配置：

- [reference-analysis.md](reference-analysis.md)：四个参考项目的入口、数据契约、Workflow、CLI 和隔离边界。
- [architecture-decisions.md](architecture-decisions.md)：复用已有 Workflow 思想、Runtime 解耦、模块化单体和非 RAG 核心决策。
- [stage-gates.md](stage-gates.md)：阶段 0～7 的交付证据、测试命令、验收结果和延期范围。

参考目录始终只读；任何新增实现必须落在本仓库，并通过独立测试证明行为。

## 平台架构与运行时

- [architecture.md](architecture.md)：Control Plane、Workflow Runtime、Execution Plane、Data Plane 和 Observability 边界。
- [state-machine.md](state-machine.md)：Run/Step 状态、合法转换和非法转换审计。
- [recovery.md](recovery.md)：Checkpoint、恢复、幂等、局部重试和 unknown 安全策略。
- [extension-guide.md](extension-guide.md)：WorkflowAdapter、ModelProvider、ToolRegistry、队列和 Artifact Storage 扩展方法。

## 工程交付

- [security-scanning.md](security-scanning.md)：脱敏、`.env`、secret scanning 和 Git 提交检查。

文档中的“已支持”必须对应代码、测试或可运行验收；“延期”不作为当前版本能力对外承诺。
