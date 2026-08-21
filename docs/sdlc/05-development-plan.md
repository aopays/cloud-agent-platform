# 开发计划与工程规范

- 文档版本：1.0
- 状态：`DRAFT`
- 规划对象：从当前 MVP 到 Internal Beta，再到 Production v1

## 1. 团队建议

基础团队 8–10 人：1 Product Owner、1 Tech Lead、2 Backend、1 Frontend、1 Agent/ML Engineer、1 Platform/SRE、
1 QA Automation、0.5 Security 和 0.5 UX。小团队可以兼任，但 Product、最终技术责任、安全批准和 QA 结论不能
全部由同一人承担。

## 2. 14 周参考计划

### 第 0–1 周：立项与需求基线

- 真实用户访谈、任务样本、数据分类和成功指标。
- 冻结 P0/非目标、API、状态机、SLO 草案和安全边界。
- 建立 backlog、风险登记、ADR、评测集和 Definition of Ready。
- Gate：G1 需求基线通过。

### 第 2–3 周：生产基础骨架

- PostgreSQL/Alembic、tenant 模型、OIDC、幂等事务和 outbox。
- Redis/Temporal 开发环境、S3/MinIO、OpenTelemetry 和 CI。
- 基础设施即代码、Secret 管理、环境配置和镜像流水线。
- Gate：公共契约、迁移、健康检查和本地集成环境通过。

### 第 4–5 周：可靠任务执行

- 持久队列、租约、心跳、恢复扫描、死信、取消和重试。
- 产物两阶段提交、签名下载、内容扫描和保留。
- Worker 崩溃、重复投递、数据库故障和对象存储故障测试。

### 第 6–7 周：多 Agent 需求发现

- RequirementSnapshot、访谈策略、专业 Agent DAG 和质量门。
- Prompt registry、结构化输出、模型路由、成本和离线评测。
- Web 会话、差异确认、未决问题和报告追踪矩阵。

### 第 8–9 周：沙箱与私有仓库

- 真实 Docker 隔离验证、网络出口代理、磁盘配额和镜像签名。
- GitHub/GitLab App 短期凭证、ref 固定、仓库大小和子模块策略。
- Prompt Injection、恶意仓库、fork bomb、路径逃逸和清理攻击测试。

### 第 10–11 周：管理、可观测与成本

- 租户策略、RBAC、配额、审批、审计查询和管理员页面。
- SLI/SLO、告警、dashboard、成本归因、限流和容量测试。
- Beta 使用手册、支持流程、Runbook 和灾备恢复。

### 第 12 周：系统测试和安全评审

- 功能、契约、E2E、性能、耐久、渗透、隐私和可访问性测试。
- 缺陷清零、模型/Prompt 冻结、运维演练和 UAT 候选。
- Gate：G3 代码冻结。

### 第 13 周：UAT 与灰度

- 5 个内部团队、代表性仓库、人工对照和反馈闭环。
- 5% → 25% → 50% → 100% 灰度；每阶段观察一个任务高峰周期。
- Gate：G4 发布批准和 G5 稳定性确认。

## 3. Epic 分解

- E1 身份与租户：OIDC、RBAC、配额、审计。
- E2 持久化控制面：PostgreSQL、迁移、幂等、outbox。
- E3 工作流与调度：Temporal/队列、租约、恢复、取消。
- E4 Agent Runtime：Provider、预算、上下文、工具和事件。
- E5 Sandbox：隔离、资源、网络、仓库和生命周期。
- E6 Requirement Discovery：快照、访谈、专业 Agent 和质量门。
- E7 Artifact：对象存储、扫描、签名下载和保留。
- E8 Web/SDK：操作界面、实时事件、错误恢复和可访问性。
- E9 Observability/SRE：telemetry、SLO、告警、灾备和成本。
- E10 Security/Compliance：威胁模型、隐私、渗透和例外流程。

每个 Story 必须包含 requirement IDs、用户价值、范围、异常路径、验收条件、观测要求、安全影响、测试策略和回滚。

## 4. Definition of Ready

- 用户、问题、目标结果和非目标明确。
- 依赖、API、数据、权限和迁移影响已识别。
- Given/When/Then 验收条件可自动化。
- 设计和安全问题没有未解决的 P0。
- 任务大小不超过一个 Sprint；更大任务先拆分。
- 文件/模块所有权明确，适合并行的任务没有写入冲突。

## 5. Definition of Done

- 实现符合基线需求，没有静默扩展。
- 单元、集成、契约、E2E 和安全回归按风险通过。
- Ruff format/check、mypy strict、依赖和镜像扫描通过。
- 指标、日志、trace、错误码、Runbook 和文档已更新。
- 数据迁移可前滚，回滚或兼容策略经过演练。
- Reviewer 批准；Critical/High 缺陷为零；验收证据已链接。

## 6. 分支、评审与集成

- 主干保持可发布，功能使用短生命周期分支和 feature flag。
- PR 聚焦一个 Story，包含风险、测试命令、截图/契约差异和回滚说明。
- 公共 Schema、迁移、安全边界和依赖变更要求 Tech Lead + 对应领域 Reviewer。
- Agent 产出的代码与人工代码使用相同质量门，不因生成速度降低审查标准。
- 合并前执行增量测试；每日执行完整回归；发布候选执行独立安全和可靠性审查。

## 7. 工程命令

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q src tests
```

CI 还应增加 OpenAPI diff、数据库迁移测试、依赖漏洞、secret scan、SBOM、镜像签名、容器策略和 IaC 扫描。

## 8. 技术债管理

技术债条目必须记录影响、风险、证据、临时措施、负责人和目标 Sprint。以下属于进入 Beta 前必须关闭的架构债：
进程内存储、Demo 报告生成、开发 Token、快照式 SSE、本地产物目录、无真实私有仓库凭证、无生产隔离验证、
无多实例一致性和无灾备演练。
