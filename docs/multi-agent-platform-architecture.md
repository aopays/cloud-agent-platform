# 多 Agent 需求发现、软件设计与开发平台架构

## 1. 产品定位

目标不是“多开几个聊天窗口”，而是构建一个有控制面、共享契约、状态机、预算、审计和质量门的 Agent 团队。

平台接收模糊需求，先通过多轮会话形成结构化需求；再由多个专业 Agent 并行完成领域分析、
架构、安全、数据/API 和测试设计；质量通过后拆分开发 DAG，在隔离环境里完成代码、测试和审查。

核心原则：

- 用户对业务决策负责，Agent 对分析、实现和证据负责。
- Agent 之间通过结构化共享状态和版本化产物协作，不依赖不可审计的自由聊天。
- 只有输入、输出和验收条件清楚的子任务才并行。
- `执行成功`、`报告生成`、`业务质量通过`、`用户批准` 是不同状态。
- 所有模型输出都不可信，必须经过 Schema、策略、权限和质量校验。

## 2. 总体架构

```text
Web / Mobile / API Client
          │
          ▼
API Gateway + Auth + Rate Limit + Idempotency
          │
          ▼
Conversation Service ───── Requirement Snapshot Store
          │                           │
          ▼                           ▼
Multi-Agent Orchestrator ───── Shared Blackboard
          │                           │
          ├── Intake Agent            ├── facts
          ├── Interview Agent         ├── assumptions
          ├── Domain Agent            ├── decisions
          ├── Product Agent           ├── open questions
          ├── Architect Agent         ├── artifacts
          ├── Data/API Agent          └── provenance
          ├── Security Agent
          ├── QA/Eval Agent
          └── Synthesis Agent
          │
          ▼
Workflow Engine + Scheduler + Budget + Approval Gates
          │
          ▼
Worker Pool ── Agent Runtime ── Tool Policy ── Isolated Sandbox
          │
          ├── Backend Agent
          ├── Frontend Agent
          ├── Runtime Agent
          ├── Sandbox/Security Agent
          ├── Test Agent
          └── Integration Agent
          │
          ▼
PostgreSQL / Redis / Object Store / Event Bus / Observability
```

## 3. 控制面与执行面分离

### 3.1 控制面

负责可信决策和状态，不执行用户代码：

- 认证、租户、配额、限流和幂等。
- 会话、结构化需求、决策、审批和版本。
- Agent 注册、能力声明、模型路由和工具授权。
- DAG 调度、租约、重试、取消、预算和质量门。
- 审计事件、产物元数据和可观测性。

### 3.2 执行面

负责不可信模型工具调用和代码执行：

- 每个 Agent Run 使用独立工作区和最小权限工具集。
- 代码、脚本和命令只进入 Sandbox，不在 API/Orchestrator 宿主机执行。
- 默认禁网、非 root、只读根文件系统、无 Docker socket、资源有界。
- 运行结束、取消或超时后终止进程树并销毁环境。

### 3.3 数据面

- PostgreSQL：会话、消息索引、需求快照、决策、DAG、Run、审批、质量分和审计。
- Redis：短期队列、租约、心跳、取消、限流和热点缓存。
- S3/MinIO：报告、图、代码补丁、日志归档、测试结果和构建产物。
- Event Bus：状态变化、Agent 事件、审批和通知；小规模可用 Redis Streams，
  大规模可用 Kafka/NATS JetStream。

## 4. Agent 角色

### 4.1 Intake / Ambiguity Agent

输入原始需求和前置条件，输出：

- 领域和风险等级。
- 需求清晰度评分。
- 已知事实、推测、矛盾和缺失维度。
- 推荐流程模板和需要启用的专业 Agent。

它不生成最终方案，只做路由和最小分类。

### 4.2 Requirement Interview Agent

- 每轮只问 3–5 个最高信息增益问题。
- 优先补充用户、流程、规模、规则、异常、数据、集成、指标和交付限制。
- 检测回答中的冲突和模糊量词。
- 任何默认值写入 `assumptions`，不得进入 `confirmedFacts`。
- 遇到必须由用户决定的问题，进入 `WAITING_FOR_USER`，而不是自行选择。

### 4.3 Domain Analyst Agent

- 建立领域词汇表、实体、生命周期、规则和常见失败模式。
- 对电商库存分析预占/扣减/释放/盘点/调拨和一致性。
- 对结算分析分录、账期、批次、冲正、付款幂等和审计。
- 对医疗、劳动法规、金融等高风险领域只列出待专家确认项，不替代专业判断。

### 4.4 Product Manager Agent

- 定义目标、非目标、角色、场景、MVP 边界和成功指标。
- 将事实转成 Epic、用户故事和业务验收标准。
- 管理优先级和范围，防止架构 Agent 静默扩大需求。

### 4.5 Solution Architect Agent

- 输出上下文图、模块边界、同步/异步流程、状态机和部署拓扑。
- 根据规模和一致性要求选择模块化单体、服务拆分或工作流引擎。
- 记录 ADR：背景、备选方案、取舍、后果和回滚条件。
- 不用“微服务”“高可用”等空泛词，必须关联真实规模和 SLO。

### 4.6 Data & API Agent

- 输出实体、字段分类、主外键、唯一约束、索引、生命周期和数据所有者。
- 输出 OpenAPI/AsyncAPI、幂等、分页、错误码、版本和兼容策略。
- 对关键写流程定义事务边界、Outbox、去重和重放行为。

### 4.7 Security & Compliance Agent

- 进行数据分类、信任边界、STRIDE 威胁建模和权限矩阵。
- 检查凭证、日志、模型上下文、租户隔离、越权、Prompt Injection 和供应链风险。
- 标出需要人工审批或专业合规确认的动作。
- Critical/High 未关闭时阻止进入开发或部署。

### 4.8 QA / Eval Agent

- 将需求转为 Given/When/Then、状态机、边界、故障和安全测试。
- 检查报告是否覆盖所有确认需求，是否把假设伪装成事实。
- 使用确定性规则、领域词表、黄金样例和 LLM Judge 组合评分。
- Reviewer 与生成报告的 Agent 分离，降低自我确认偏差。

### 4.9 Synthesis Agent

- 合并专业产物，解决重复和非冲突表述。
- 发现冲突时回到相应 Agent 或用户，不自行“取平均”。
- 生成最终软件设计报告、追踪矩阵、ADR、OpenAPI、数据模型和开发计划。

### 4.10 开发阶段 Agent

- Tech Lead：任务 DAG、公共契约、集成和最终验收。
- Backend：领域服务、API、数据库和队列。
- Frontend：交互、状态管理、可访问性和前端测试。
- Agent Runtime：模型循环、工具协议、预算、上下文和事件。
- Sandbox/Security：隔离、策略、资源、网络和攻击测试。
- QA：验收、回归、端到端和质量报告。
- Integration：合并、契约兼容、迁移、打包和发布候选。

## 5. 多 Agent 工作流

### 5.1 需求和设计状态机

```text
DRAFT
  → DISCOVERY
  → WAITING_FOR_USER ──回答──┐
  └───────────────────────────┘
  → READY_FOR_DESIGN
  → DESIGNING
  → REVIEWING
  → NEEDS_CLARIFICATION / NEEDS_APPROVAL
  → QUALITY_PASSED
  → USER_APPROVED
  → PLANNED
```

### 5.2 开发状态机

```text
PLANNED
  → QUEUED
  → PREPARING
  → RUNNING
  → INTEGRATING
  → VALIDATING
  → SUCCEEDED

任意非终态：CANCELLING / CANCELLED / FAILED / TIMED_OUT / BLOCKED
```

`BLOCKED` 只用于真正需要用户、权限或外部状态变化的情况；普通失败进入可重试或失败终态。

### 5.3 DAG 规则

典型设计 DAG：

```text
Intake
  → Interview / Requirement Snapshot
  → [Domain Analysis, Product Scope]
  → [Architecture, Data/API, Security]
  → QA/Eval
  → Synthesis
  → User Approval
```

只有输入和输出契约稳定后才能并行。例如 Architecture 与 Data/API 可以在领域实体未确认前做草案，
但不能冻结契约；Security 可以提前威胁建模，但最终复核必须等待部署和数据流确定。

## 6. 共享黑板与消息契约

Agent 不直接修改同一份自由文本。共享黑板按资源版本写入：

```json
{
  "resourceId": "req_123",
  "resourceType": "requirement_snapshot",
  "version": 7,
  "tenantId": "tenant_a",
  "ownerAgent": "requirement-agent",
  "status": "PROPOSED",
  "payload": {},
  "provenance": ["message_17", "decision_4"],
  "createdAt": "..."
}
```

Agent Run 输入：

```json
{
  "runId": "run_123",
  "role": "data-api-agent",
  "objective": "为已确认的库存领域设计数据模型和API",
  "inputArtifacts": ["req_snapshot:v7", "domain_model:v3"],
  "allowedTools": ["read_artifact", "write_artifact", "validate_openapi"],
  "budget": {"maxTurns": 12, "maxInputTokens": 60000, "wallTimeSeconds": 300},
  "acceptance": ["所有P0写流程有幂等语义", "OpenAPI校验通过"]
}
```

Run 输出必须是结构化状态和版本化产物，不返回私有思维链：

```json
{
  "status": "SUCCEEDED",
  "summary": "完成库存账户、预占和流水模型",
  "artifacts": ["data_model:v1", "openapi:v1"],
  "openQuestions": ["盘点差异是否需要双人审批"],
  "evidence": ["openapi-lint:pass", "schema-tests:pass"]
}
```

## 7. 推荐技术栈

### 7.1 前端

- Next.js/React + TypeScript：多轮对话、决策确认、报告、任务看板和事件时间线。
- TanStack Query：服务端状态、轮询和缓存失效。
- SSE：任务和 Agent 单向事件；需要双向低延迟协作时再用 WebSocket。
- Monaco Editor：查看和批准 OpenAPI、JSON Schema、补丁和代码。
- Playwright：真实用户路径、审批和下载端到端测试。

### 7.2 API 与领域服务

- Python 3.12+、FastAPI、Pydantic v2。
- SQLAlchemy 2 + Alembic；边界清晰的 Repository/Unit of Work。
- OpenAPI 3.1 和 AsyncAPI；Schemathesis/Dredd 做契约测试。
- 当前面试 MVP 可保持模块化单体；会话、编排和执行队列稳定后再拆服务。

### 7.3 工作流和调度

- 面试 MVP：现有 asyncio Worker + 内存/Redis 队列，保留可替换端口。
- 生产长流程：Temporal，适合等待用户数小时、重试、补偿、定时器和进程重启恢复。
- 高吞吐事件：Kafka 或 NATS JetStream；不要用消息总线代替业务状态机。

### 7.4 LLM 与 Agent Runtime

- OpenAI Responses API：推理、工具调用和多轮工作流。
- 会话短期可手动重放消息；生产可选择 Conversations 或 `previous_response_id`，
  但必须按数据保留和零保留要求决定，不能默认把敏感需求持久化到外部。
- 模型路由建议：低成本模型做分类/抽取，中高能力模型做架构和综合，独立模型做 Reviewer；
  具体模型和 reasoning 档位必须用本项目评测集验证，不能仅按“最新”选择。
- Structured Outputs/JSON Schema 生成 `RequirementSnapshot` 和 Agent 交付，不依赖 Markdown 解析。
- Prompt 版本、模型快照、工具版本和评测结果一起记录，支持回放和回归。

官方 OpenAI 文档当前建议使用 Responses API 处理推理、工具和多轮工作流，
并明确要求在代表性任务上比较质量、token、延迟和成本；多 Agent 属于 beta，
因此平台自己的 DAG、审计、回退和质量门不能省略。

### 7.5 存储

- PostgreSQL 16：事务真相源、JSONB 快照、唯一约束和条件更新。
- Redis 7：缓存、租约、取消、限流和短期事件。
- S3/MinIO：版本化 Artifact、对象锁、生命周期和签名下载。
- pgvector 可用于相似需求检索，但不是 P0；不能用向量相似度替代结构化事实。

### 7.6 沙箱

- 开发：Docker，非 root、cap-drop、no-new-privileges、只读 rootfs、默认禁网。
- 生产高风险代码：gVisor/Kata/Firecracker，独立节点池，镜像签名和 SBOM。
- 工具参数 JSON Schema、argv-only、路径规范化、符号链接检查、输出截断、进程树取消。
- 代理出网采用域名允许列表、凭证注入隔离和完整审计。

### 7.7 安全

- OIDC/OAuth2、短期访问令牌、RBAC/ABAC；策略可用 OPA 或 Cedar。
- Vault/KMS 管理模型、Git、数据库和对象存储凭证。
- 租户 ID 进入每个主键/索引/授权检查；数据库可增加 Row Level Security 防御纵深。
- 日志和事件先脱敏；凭证、个人信息、支付和健康数据不进入普通模型上下文。
- 高风险工具、外部写入、付费、部署和生产数据访问必须人工批准。

### 7.8 可观测性

- OpenTelemetry Trace 贯穿 conversation → workflow → agent run → model → tool → sandbox。
- Prometheus/Grafana：延迟、队列、成功率、token、费用、质量分、重试和沙箱资源。
- Loki/ELK：结构化日志；Tempo/Jaeger：Trace；Sentry：应用错误。
- 业务指标：澄清轮数、用户放弃率、假设确认率、一次质量通过率和返工率。

## 8. 数据模型建议

核心表：

- `conversation_session`：租户、状态、领域、风险、模型和版本。
- `conversation_message`：序号、角色、公开内容、token 和时间。
- `requirement_snapshot`：版本化结构化需求和来源。
- `requirement_fact`：字段、值、状态、置信度、消息来源和确认人。
- `decision`：选择、备选、理由、决策人和影响。
- `open_question`：严重级别、负责人、截止时间和阻塞状态。
- `agent_definition`：角色、提示词版本、模型路由、工具和权限。
- `workflow_run` / `workflow_node`：DAG、依赖、状态、重试和租约。
- `agent_run`：输入、输出、预算、模型、使用量和终态。
- `artifact` / `artifact_version`：类型、哈希、存储、来源和审批状态。
- `approval`：请求、风险、批准人、范围、过期和结果。
- `evaluation_run`：数据集、grader、各维度分数、证据和回归基线。
- `audit_event`：不可变公开行为事件。

关键约束：

- `(tenant_id, session_id, sequence)` 唯一。
- `(workflow_run_id, node_key, attempt)` 唯一。
- Artifact 内容哈希去重，但逻辑版本不可覆盖。
- 状态更新带版本号，避免并发 Agent 覆盖用户新决定。
- 所有外部副作用带幂等键和审批引用。

## 9. API 建议

需求发现：

- `POST /v1/discovery-sessions`
- `POST /v1/discovery-sessions/{id}/messages`
- `GET /v1/discovery-sessions/{id}`
- `GET /v1/discovery-sessions/{id}/requirements`
- `PATCH /v1/discovery-sessions/{id}/facts/{factId}`：用户确认或纠正。
- `POST /v1/discovery-sessions/{id}/decisions`
- `POST /v1/discovery-sessions/{id}/design-runs`

编排：

- `GET /v1/workflows/{id}`
- `GET /v1/workflows/{id}/events`：SSE。
- `POST /v1/workflows/{id}/cancel`
- `POST /v1/workflows/{id}/approvals/{approvalId}`
- `GET /v1/workflows/{id}/artifacts`

开发：

- `POST /v1/projects/{id}/plans`
- `POST /v1/projects/{id}/development-runs`
- `GET /v1/development-runs/{id}/tasks`
- `POST /v1/development-runs/{id}/tasks/{taskId}/retry`
- `GET /v1/development-runs/{id}/reviews`

错误响应统一包含 `code`、安全消息、`retryable`、`traceId` 和可选 `details`，
但不能返回上游模型正文、密钥、主机路径或内部堆栈。

## 10. 质量门与评测

### 10.1 确定性门

- JSON Schema、OpenAPI、SQL migration、状态机和目录所有权校验。
- 所有确认需求都有 `provenance` 和至少一条验收标准。
- 未确认假设不能进入 P0 无条件实现任务。
- Critical/High 安全风险不能开放发布。

### 10.2 模型评测

- 需求覆盖：确认事实是否完整进入设计。
- 事实忠实：是否创造用户未确认的业务结论。
- 领域深度：实体、状态、规则和失败路径是否具体。
- 可实施性：数据/API/架构/测试能否拆任务和估时。
- 一致性：重复运行的关键契约稳定度。
- 成本效率：质量通过前提下的 token、延迟和费用。

LLM Judge 不能是唯一质量门；关键场景需要规则、黄金答案、人工专家和真实代码验证。

## 11. 可靠性设计

- API 创建使用 Idempotency-Key；消息使用 clientMessageId 去重。
- Workflow 使用 at-least-once 投递，节点终态和 Artifact 提交幂等。
- 模型 429/5xx/网络错误指数退避并有限重试；业务/Schema 错误不盲目重试。
- Worker 心跳和租约过期后可接管，但同一 attempt 只有一个终态提交者。
- 用户取消传播到模型调用、工具协程和沙箱进程树。
- 每个工作流有总时间、总 token、单 Agent 轮次和工具输出上限。
- 恢复扫描器处理 Worker 崩溃、Outbox 未发送和孤儿沙箱。

## 12. 部署拓扑

面试 MVP：

```text
FastAPI 模块化单体 + 单 Worker + Docker + 本地 Artifact
```

生产第一阶段：

```text
Kubernetes
├── api deployment
├── orchestrator deployment
├── worker deployment（按工具/风险分池）
├── temporal workers
├── sandbox nodes
├── PostgreSQL HA
├── Redis HA
└── S3/MinIO + Observability
```

Worker 按负载分池：只读分析、代码执行、浏览器、重型构建和高风险审批任务不能混用同一资源策略。

## 13. 演进路线

### 阶段 0：当前可演示版本

- 多轮页面、三轮会话、Demo 物流报告、OpenAI Provider 接口、任务和沙箱链路。
- 限制：内存状态，跨领域 Demo 报告不可直接开发。

### 阶段 1：跨领域需求设计闭环

- PostgreSQL 会话、RequirementSnapshot、OpenAI 结构化抽取。
- Domain/Product/Architect/Security/QA 五 Agent DAG。
- 质量门、用户决策页面、报告与追踪矩阵。

### 阶段 2：多 Agent 开发闭环

- 设计报告拆 Epic/Story/Task DAG。
- 独立工作区并行编码，Integration/QA/Security 审查。
- PR 仍需人工批准，不自动部署生产。

### 阶段 3：生产化

- Temporal、Kubernetes、强沙箱、对象存储、配额、成本路由、灾备和合规。
- 使用持续评测决定模型、Prompt、Agent 数量和并行度。

## 14. 最重要的架构取舍

1. 不要为了“多 Agent”而让所有角色每次都运行；根据领域、风险和缺口动态路由。
2. 不要让 Agent 直接共享无限聊天历史；共享结构化事实和版本化 Artifact。
3. 不要把报告成功写盘当成业务成功；必须有独立质量状态和用户批准。
4. 不要在 MVP 过早拆微服务；先保证契约、状态机、幂等、评测和安全边界。
5. 不要用 LLM 替代确定性规则；金额、权限、状态、法规硬约束和发布门由代码执行。
6. 并行只优化墙钟时间，不天然提高正确率；最终综合和审查仍是串行质量门。
