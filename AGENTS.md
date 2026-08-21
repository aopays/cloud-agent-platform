# Cloud Agent Platform 工程规则

## 项目目标

构建一个可运行的 Cloud Agent Platform MVP：用户提交自然语言任务和代码仓库，平台在隔离执行环境中运行自主 Agent，通过 LLM 推理和受控工具调用完成任务，并返回事件、产物和最终结果。

## 指令优先级

1. 用户当前任务中的明确要求。
2. 本文件中的项目级规则。
3. `docs/requirements.md`、`docs/architecture.md` 和公共契约。
4. 专业 Agent 自身的角色说明。

发现冲突时停止受影响部分，向主 Agent 报告证据和建议，不得自行改变产品边界。

## 开工前必读

- `docs/requirements.md`
- `docs/architecture.md`
- `docs/acceptance-criteria.md`
- `docs/security-boundary.md`
- `docs/contracts/openapi.yaml`
- `docs/contracts/agent-events.md`
- `docs/task-board.md`

开始修改前检查当前文件状态和已有变更，保留其他 Agent 或用户的工作。

## 团队和所有权

- 主 Agent：需求澄清、架构决策、共享文件、任务调度、集成和最终验收。
- `backend-engineer`：`src/api/**`、`src/models/**`、`src/scheduler/**`、对应测试。
- `agent-runtime-engineer`：`src/agent_runtime/**`、`src/tools/**`、对应测试。
- `sandbox-security-engineer`：`src/sandbox/**`、`sandbox/**`、对应测试。
- `qa-reviewer`：默认只读审查；经授权后可修改 `tests/**` 和 `docs/reviews/**`。

## 共享文件

以下文件默认只允许主 Agent 修改：

- `AGENTS.md`
- `README.md`
- `docs/contracts/**`
- 依赖和 lock 文件
- `docker-compose.yml` 及根级容器编排文件
- 数据库迁移
- 公共类型、公共 Schema 和跨模块配置
- CI/CD 与发布配置

子 Agent 如需变更共享文件，应在完成报告中提交变更请求、原因和最小补丁建议，不直接修改。

## 并行开发规则

- 只并行执行输入、输出、目录和验收条件都明确的任务。
- 同一波次中，两个 Agent 不得拥有同一文件或目录。
- 强依赖任务必须串行；先完成公共契约，再实现消费者。
- 子 Agent 不创建提交、不执行破坏性 Git 操作、不覆盖未归属自己的变更。
- 主 Agent 在分发前记录任务 ID、依赖、允许修改范围和完成标准。
- 出现公共接口不一致时，由主 Agent裁决并统一修改。

## 自主与审批边界

- 对构建、修改或修复任务，可执行范围内的本地编辑和非破坏性测试。
- 对审查、分析和诊断任务，默认只读；除非任务明确要求修复。
- 外部写入、部署、付费操作、破坏性操作、权限扩大和需求扩张必须获得用户确认。
- 不得读取、打印或写入真实密钥；示例使用占位符和 `.env.example`。

## 安全底线

- 不可信代码只能在受限沙箱内执行，禁止访问宿主机 Docker socket。
- 沙箱默认禁网、非 root、最小 capabilities、有限 CPU/内存/磁盘/PID/时间。
- 所有文件工具必须防止路径穿越和符号链接逃逸。
- 凭证不得进入 LLM 上下文、日志、工具输出或持久化产物。
- 工具参数必须结构化校验；命令和输出必须限时、限量、可取消。
- 记录公开的行动摘要、工具调用和状态变化，不持久化模型私有思维链。

## 工程质量

- 优先实现最小、清晰、可测试的纵向闭环。
- 不为尚未确认的 P1/P2 能力提前引入复杂基础设施。
- 错误必须显式处理，任务状态转换必须可追踪。
- 新行为必须有测试；修复缺陷必须有回归用例。
- 注释解释原因和约束，不重复代码表面含义。
- 日志使用结构化字段，不记录秘密或完整敏感内容。

## 验证顺序

项目命令尚未确定前，Agent 应先发现现有命令，不得虚构测试结果。建立项目后，在此处补充实际命令：

1. 格式化检查：`.venv/Scripts/python -m ruff format --check .`
2. 静态检查：`.venv/Scripts/python -m ruff check .` 和 `.venv/Scripts/python -m mypy src`
3. 单元测试：`.venv/Scripts/python -m pytest tests/shared tests/api tests/scheduler tests/agent_runtime tests/tools tests/sandbox`
4. 集成测试：`.venv/Scripts/python -m pytest tests/integration`
5. 端到端测试：`.venv/Scripts/python -m pytest tests/e2e`
6. 安全测试：`.venv/Scripts/python -m pytest tests/sandbox -m security`

## Definition of Done

任务只有满足以下条件才能标记完成：

- 实现范围与任务描述一致，没有静默扩张。
- 修改仅发生在授权目录；共享文件变更由主 Agent完成。
- 相关测试已实际运行并记录命令、退出码和关键结果。
- 错误路径、取消、超时和资源上限得到对应验证。
- 文档和契约与行为一致。
- 没有未说明的 Critical 或 High 风险。
- 完成报告列出修改文件、验证证据、遗留问题和集成要求。

## 子 Agent 完成报告

每个子 Agent 必须按以下格式返回：

```text
任务状态：完成 / 部分完成 / 阻塞
任务 ID：

修改文件：
- ...

实现内容：
- ...

验证证据：
- 命令：
- 退出码：
- 关键结果：

遗留问题：
- ...

风险：
- ...

需要主 Agent 操作：
- ...
```
