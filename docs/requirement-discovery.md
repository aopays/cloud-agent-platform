# 多轮需求发现与软件设计报告

## 产品目标

在仓库执行任务之前增加一个对话式控制面。用户可以只提交十几个字的模糊需求，
需求发现 Agent 通过多轮问题确认用户、场景、规模、规则、异常、数据、集成、成功指标和交付约束，
最后生成 Markdown 软件设计报告。

需求发现不会直接执行用户代码，也不需要仓库地址。它与 `/v1/tasks` 的仓库执行流程相互独立；
未来可以把已确认的报告作为执行 Agent 的任务输入。

## 使用入口

- 对话页面：`http://127.0.0.1:8001/discovery`
- Swagger：`http://127.0.0.1:8001/docs`
- 开发环境 Bearer Token：`local-demo-token`

## API 流程

1. `POST /v1/discovery-sessions`：提交模糊需求和可选前置条件。
2. `POST /v1/discovery-sessions/{sessionId}/messages`：回答 Agent 的问题。
3. `GET /v1/discovery-sessions/{sessionId}`：获取完整对话和状态。
4. `POST /v1/discovery-sessions/{sessionId}/finalize`：生成软件设计报告。
5. `GET /v1/discovery-sessions/{sessionId}/report`：下载 Markdown 报告。

状态含义：

- `DISCOVERY`：仍在进行需求澄清。
- `READY`：已完成建议的三轮澄清，可以生成第一版报告。
- `FINALIZED`：报告已经生成，会话只读。

用户可在三轮前提前生成报告。系统必须把未确认信息标记为默认假设或待确认项，
不得把模型推测伪装为用户确认。

## Demo 与 OpenAI 模式

Demo 模式使用确定性产品经理流程，能够离线演示物流司机排班等需求的三轮澄清，
并生成结构完整的软件设计报告。OpenAI 模式使用配置的 Responses Provider，根据已有对话动态追问和生成报告。

OpenAI 模式采用手动重放最小消息历史的方式维持会话上下文，`store` 保持为 `false`。
生产环境可进一步评估 Responses API Conversations 或 `previous_response_id`，并结合数据保留要求选择状态管理方式。

## 安全与边界

- 所有会话 API 使用与任务 API 相同的 Bearer 和租户隔离。
- 单条需求、前置条件和回答最多 20,000 字符；每个会话最多 12 个用户轮次。
- 报告产物受认证下载，并限制为 Artifact Store 的安全文件名和大小。
- 模型错误只返回通用错误，不把 API Key、上游响应正文或内部异常写给用户。
- 对话中只保存用户可见的问答，不保存模型私有思维链。

## 当前限制

- 会话状态使用进程内存，服务重启后丢失；报告文件仍在本地 `.artifacts`，但元数据不会自动恢复。
- Demo 模式的问题模板对物流排班做了优化，其他领域使用通用问题和通用报告框架。
- 尚未把最终报告自动转换成开发任务 DAG，也没有自动启动多 Agent 编码团队。
