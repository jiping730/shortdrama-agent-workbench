# Recovery and Idempotency

## Checkpoint

每步成功后保存：Run 上下文快照、下一步名称、Artifact 引用和递增序号。进程在安全边界停止时，最新成功步骤仍可复用，未完成步骤保持 pending/running 事实，不静默清理。

## Resume

`WorkflowRuntime.recover(run_id)` 读取最新 Checkpoint，将遗留的 running step 恢复为 pending，Run 进入 `needs_recovery → queued → running`，然后从 checkpoint 的下一步继续。已成功步骤不会再次调用模型。

## Selective retry

审核拒绝时，ReviewTask 保留 rejected 状态。`run retry --scene-id SCENE_ID`：

1. 校验该 scene 确有 rejected review；
2. 只调用 `revise_storyboard(..., rejected_scene_ids=[...])`；
3. 产生新 Attempt 和带父引用的 Artifact；
4. 通过 Pydantic 校验；
5. 只为修订 scene 创建新 Review；
6. 通过后采用修订结果，其他 scene 继续复用旧结果。

## Unknown 外部调用

传输超时/连接中断不能证明 provider 未执行。ExternalCall 标记 `unknown`，Attempt 使用 `external_result_unknown`，Run 进入 `needs_recovery`。默认 resume 不重放，直到加入明确的 provider reconciliation/人工确认策略。

## Idempotency

输入哈希、工作流版本、step、参数和 revision 组合生成 Attempt idempotency key。相同成功输入返回已有 Run；同一 Run 内成功 Attempt 被重用并留下 `step.reused` 事件。历史 Attempt 和 Artifact 永不覆盖。
