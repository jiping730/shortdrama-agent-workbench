# State Machine

## Run 状态

| 当前 | 合法下一步 |
|---|---|
| created | queued, cancelled |
| queued | running, paused, cancelled |
| running | paused, waiting_review, failed, completed, cancelled, needs_recovery |
| paused | queued, running, cancelled, needs_recovery |
| waiting_review | queued, paused, cancelled, needs_recovery |
| failed | queued, cancelled, needs_recovery |
| needs_recovery | queued, paused, cancelled, failed |
| completed/cancelled | terminal |

非法转换会抛出 `InvalidTransition`，同时写入 `run.illegal_transition` 事件。

## Step 状态

`pending → running → succeeded|failed|waiting_review|unknown`。

`succeeded → pending` 只允许显式 selective retry；`unknown → queued` 需要外部确认/恢复流程，Runtime 不会隐式重放。审核循环允许 `succeeded → waiting_review`，但只由新的 selective revision 触发。

## script-to-storyboard steps

```text
prepare_input
  -> split_script
  -> build_source_index
  -> extract_facts
  -> validate_facts
  -> generate_storyboard
  -> validate_storyboard
  -> wait_for_human_review
  -> revise_rejected_scenes
  -> adopt_result
  -> export_artifacts
```

`wait_for_human_review` 是安全边界。审核通过后继续；拒绝后必须由 `run retry --scene-id ...` 选择性修订。
