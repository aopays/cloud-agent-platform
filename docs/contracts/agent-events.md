# Agent 事件协议

## 1. 事件信封

所有事件采用追加式记录：

```json
{
  "taskId": "task_123",
  "attemptId": "attempt_001",
  "sequence": 17,
  "type": "tool.completed",
  "timestamp": "2026-08-19T10:00:00Z",
  "payload": {}
}
```

约束：

- `sequence` 在单个 attempt 内严格递增。
- 同一 `attemptId + sequence` 幂等。
- `payload` 必须符合对应事件类型，不得包含秘密和模型私有思维链。
- 大输出写入对象存储，事件只保存摘要、大小、哈希和 artifact ID。

## 2. P0 事件类型

### `task.status_changed`

```json
{
  "from": "QUEUED",
  "to": "PREPARING",
  "reason": "worker_lease_acquired"
}
```

### `agent.action_summary`

保存面向用户的简短行动说明，不保存隐式推理：

```json
{
  "summary": "正在搜索仓库中的 TODO 和 FIXME 标记。"
}
```

### `model.request_completed`

```json
{
  "provider": "configured-provider",
  "model": "configured-model",
  "durationMs": 820,
  "inputTokens": 1200,
  "outputTokens": 180
}
```

### `tool.started`

```json
{
  "callId": "call_abc",
  "tool": "search_text",
  "argumentsSummary": {
    "pattern": "TODO|FIXME"
  }
}
```

### `tool.completed`

```json
{
  "callId": "call_abc",
  "tool": "search_text",
  "durationMs": 124,
  "outcome": "success",
  "exitCode": 0,
  "truncated": false,
  "outputBytes": 920
}
```

### `artifact.created`

```json
{
  "artifactId": "artifact_report",
  "name": "todo-report.md",
  "mediaType": "text/markdown",
  "sizeBytes": 4096,
  "sha256": "hex-digest"
}
```

### `budget.updated`

```json
{
  "agentTurns": 4,
  "inputTokens": 6000,
  "outputTokens": 900,
  "wallTimeSeconds": 32
}
```

### `task.error`

```json
{
  "code": "TOOL_TIMEOUT",
  "message": "命令执行超过允许时间。",
  "retryable": false
}
```

## 3. 兼容性

- 新增可选字段属于向后兼容。
- 删除字段、改变字段类型或事件语义需要提升协议版本。
- 消费者必须忽略未知事件类型，但记录可观测告警。
