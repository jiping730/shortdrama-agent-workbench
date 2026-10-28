# Extension Guide

## 新工作流

实现 `WorkflowAdapter`：

```python
class MyAdapter:
    definition = WorkflowDefinition(...)

    def register(self): ...
    def validate(self, step_name, value): ...
    def execute_step(self, step_name, context): ...
    def recover(self, context): ...
```

步骤应返回 JSON-safe value，并在边界内使用 Pydantic schema。不要在 Adapter 中直接提交数据库写入、改变 Run 状态或吞掉 provider 异常。

## 新模型

实现 `ModelProvider.generate_facts`、`generate_storyboard`、`revise_storyboard`。生产 provider 应将请求/响应映射到结构化 ExternalCall，不能把错误字符串伪装成成功 JSON。Claude 扩展使用官方 Anthropic SDK；默认 FakeModel 保证离线可测。

## 新工具

用 `ToolDefinition` 注册输入/输出模型、版本、超时、重试和幂等策略。ToolRegistry 会执行 schema 校验、审计并对成功幂等键去重。

## 队列与 Worker

使用 `TaskQueue` 的 `enqueue/lease/ack/nack` contract。`SQLiteTaskQueue` 适合本地单 Worker，`LocalWorker` 只负责取出 `run.execute` 消息并调用 `WorkflowRuntime.execute_run`；不要在 Worker 中复制状态转换或审核逻辑。生产多 Worker、可见性超时和外部队列仍需独立验收。

## 新 Artifact 存储

实现 `ArtifactStore.put(artifact_id, content)` 的对象存储版本即可替换本地文件版本。当前 `LocalArtifactStore` 和 `S3ArtifactStore` 共用该 contract；数据库仍保存 content hash、schema version、parent artifact IDs 和 URI，保证可追溯。
