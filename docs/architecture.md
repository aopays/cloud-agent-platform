# Cloud Agent Platform 架构基线

## 1. 设计目标

- 七天内形成可演示的端到端 MVP。
- 编排层与执行层明确分离。
- LLM、队列、沙箱和对象存储可以替换。
- 默认安全、资源有界、运行可取消、过程可审计。
- 保持模块化单体加独立 Worker，避免 MVP 阶段过度微服务化。

## 2. 建议技术栈

- API：FastAPI
- Worker：Python 异步 Worker；队列实现可选 Redis + Dramatiq/ARQ/Celery
- 数据库：PostgreSQL
- 缓存和队列：Redis
- 沙箱：Docker MVP，生产演进到 gVisor/Kata/Firecracker
- 对象存储：本地适配器起步，接口兼容 S3
- 实时事件：SSE
- LLM：自定义 Provider 接口，隔离厂商 SDK
- 前端：P0 可用简单 Web UI 或 CLI；需要展示时使用 Next.js

以上选型为假设，最终以实际环境、团队能力和时间限制为准。

## 3. 模块边界

### API Service

- 身份认证、请求校验、限流和幂等键。
- 创建、查询和取消任务。
- 提供事件流和产物元数据。
- 不直接执行 Agent Loop 或用户命令。

### Scheduler

- 持久化任务状态和 attempt。
- 将可运行任务投递到队列。
- 管理优先级、租户并发、重试策略和取消信号。
- 使用 at-least-once 投递，依靠 task ID 与 attempt ID 保证业务幂等。

### Agent Worker

- 获取执行租约并定期发送心跳。
- 创建沙箱，准备工作区和运行上下文。
- 调用 Agent Runtime，持续写入事件和预算。
- 收集产物、清理沙箱并提交终态。

### Agent Runtime

- 管理模型消息、公开行动摘要和上下文压缩。
- 校验模型产生的结构化工具调用。
- 执行预算、最大轮次、重复调用和停止策略。
- 不直接绕过 Sandbox Runtime 执行用户命令。

### Tool Registry 与 Policy Engine

- 定义工具名称、JSON Schema、权限等级、超时和输出上限。
- 对路径、命令、网络和敏感信息进行策略判断。
- 高风险操作预留人工审批状态。

### Sandbox Runtime

- 创建、执行、取消和销毁任务隔离环境。
- 提供文件和命令执行原语。
- 实现 CPU、内存、磁盘、PID、时间和网络限制。

### Persistence

- PostgreSQL：任务、attempt、事件索引、工具调用、配额和产物元数据。
- Redis：队列、短期租约、心跳、取消信号和限流。
- Object Store：报告、压缩日志、patch 和大文件产物。

## 4. 主执行流程

```text
Client
  -> API: create task
  -> Database: persist CREATED
  -> Queue: enqueue task
  -> Worker: acquire lease
  -> Sandbox: prepare isolated workspace
  -> Runtime: model/tool loop
  -> Event Store: append events
  -> Artifact Store: persist outputs
  -> Database: commit terminal status
  -> Sandbox: destroy
  -> Client: query result/events
```

## 5. 状态机

```text
CREATED
  -> QUEUED
  -> PREPARING
  -> RUNNING
  -> SUCCEEDED

任意非终态可根据原因进入：
FAILED / CANCELLING / CANCELLED / TIMED_OUT
```

终态不可逆。状态更新使用版本号或条件更新，避免重复 Worker 覆盖结果。

## 6. Agent Loop

每轮执行：

1. 检查取消信号和总预算。
2. 构造最小必要上下文。
3. 调用 LLM Provider。
4. 如果模型返回最终结果，验证后结束。
5. 如果模型返回工具调用，执行 Schema 校验和策略授权。
6. 在沙箱中执行工具，截断并清理输出。
7. 持久化事件和使用量，将 observation 加回上下文。
8. 检查重复调用、无进展和最大轮次。

## 7. 关键取舍

- MVP 使用模块化单体和独立 Worker，降低部署与调试成本。
- 队列采用 at-least-once，避免追求难以保证的 exactly-once。
- Docker 仅作为 MVP 隔离；处理高风险不可信代码需要更强隔离层。
- SSE 比 WebSocket 更适合单向事件流和快速演示。
- 公共契约优先，允许 API、Runtime 和 Sandbox 并行实现。

## 8. 可扩展性路径

- 把 Worker 迁移到 Kubernetes Job，并按资源规格建立队列。
- 增加模型路由、熔断、配额和租户公平调度。
- 引入沙箱预热池减少冷启动。
- 将事件流演进为独立事件总线，但保持事件 Schema 兼容。
- 使用评测集持续衡量任务成功率、成本、延迟和安全违规率。
