# 验收、移交与需求追踪矩阵

- 文档版本：1.0
- 状态：`DRAFT`
- 目标：证明每个 P0 需求已设计、实现、测试、运营并由正确责任人批准

## 1. 验收层次

- 技术验收：代码、契约、迁移、测试、安全和性能符合工程门禁。
- 产品验收：用户旅程、范围、体验和业务指标符合 PRD。
- 运营验收：SLO、监控、告警、备份、恢复、Runbook 和值班就绪。
- 安全/隐私验收：威胁、数据、供应商、例外和事件响应通过。
- UAT：真实用户在 Staging/Canary 完成代表性任务并签字。

## 2. MVP 追踪矩阵

- `CAP-FR-010/011/016` → `src/discovery.py`、`src/api/discovery_routes.py`、`src/discovery_ui.py` →
  `tests/discovery`、`tests/integration/test_discovery_api.py`、15 场景批量脚本。
- `CAP-FR-020/021/022/023/024` → `src/scheduler`、`src/models`、`src/worker.py` →
  `tests/scheduler`、`tests/api`、`tests/e2e/test_platform_e2e.py`。
- `CAP-FR-030/031/032/033/034/035` → `src/agent_runtime`、`src/tools` →
  `tests/agent_runtime`、`tests/tools`。
- `CAP-FR-040/042/044/045` → `src/repository_preparation.py`、`src/sandbox` →
  `tests/security`、`tests/sandbox`。
- `CAP-FR-050/051/052/053` → `src/storage.py`、`src/agent_runtime/events.py`、API artifact 路由 →
  `tests/shared`、`tests/integration`、`tests/e2e`。

此矩阵证明 MVP 覆盖，不表示生产 NFR 已满足。`CAP-FR-001–004` 的企业身份/权限、`CAP-FR-012–015` 的结构化多 Agent
需求质量、`CAP-FR-041` 私有仓库短期凭证以及持久化/灾备仍属于 Next。

## 3. UAT 场景

### UAT-01 FDE 客户需求发现

FDE 输入客户模糊需求，经过至少三轮形成草案；系统标记事实、假设、决策、风险和开放项；生成报告包含决策人、
As-Is 证据、范围与非目标、数据集成、架构、API、NFR、PoC 验收和研发移交。通过标准：业务与技术负责人认为
可估时、可拆任务、可现场验收，无 P0 阻塞项被隐藏。

### UAT-02 只读仓库分析

工程师选择允许仓库并提交 TODO/安全/依赖分析。用户能观察排队、准备、模型、工具和产物事件；报告可下载；重复请求
不产生重复任务。通过标准：结果与人工基线一致，错误不泄密，资源在完成后销毁。

### UAT-03 取消和故障恢复

运行长命令时取消；随后模拟 Worker 重启和模型暂时失败。通过标准：取消时延达标，无进程/目录残留；恢复后状态和
事件一致，没有重复副作用。

### UAT-04 租户隔离

两个租户创建会话、任务和产物，并尝试互相枚举、查询、取消和下载。通过标准：全部越权访问被拒绝且审计完整。

### UAT-05 管理和成本

管理员配置模型、并发和预算；任务接近/超过预算。通过标准：策略在新任务生效，运行中按版本保持一致，成本可归因，
超限产生明确终态和事件。

## 4. Go/No-Go 清单

- PRD/SRS、API、数据、事件、安全边界和 ADR 已 `BASELINED`。
- P0 requirement→design→code→test→evidence 追踪率 100%。
- Critical/High 缺陷和风险例外为零，或有合法、限时、批准的例外。
- 完整回归、AI Eval、性能、安全、恢复、迁移和 UAT 通过。
- Dashboard、告警、Runbook、备份恢复、值班和支持准备完成。
- 灰度、回滚、kill switch、模型/Prompt 回退经过演练。
- 发布说明、已知限制、用户指南、管理员指南和数据政策已交付。

任何一项安全边界、数据完整性、回滚或值守未就绪，应为 No-Go。

## 5. 移交包

- 源码、签名镜像、SBOM、版本和构建 provenance。
- 基线需求、架构、ADR、OpenAPI、事件和数据字典。
- 测试计划、测试报告、AI Eval、性能和安全报告。
- IaC、环境配置说明、迁移、回滚和灾备证据。
- SLO、Dashboard、告警、Runbook、值班和升级矩阵。
- 用户/管理员手册、已知限制、数据保留和支持流程。
- 未完成 backlog、技术债、风险、例外、owner 和截止时间。

Tech Lead 向 SRE/支持进行架构和故障演练；Security 进行事件和凭证演练；Product 进行用户和范围培训。接收方需要
实际执行 smoke、回滚和恢复，而不是只阅读文档。

## 6. 当前验收证据

当前仓库最近一次本地验证为 pytest 96 passed、15 subtests passed、1 skipped；Ruff lint/format 和 mypy 通过。
跳过项与 Windows 符号链接权限相关，生产 Linux 环境仍需动态验证。15 个需求发现场景全部能够生成并下载报告，
但只有物流司机排班达到开发质量阈值，因此多 Agent 需求质量仍为 G1/G2 阻塞项。

## 7. 正式签字

正式发布需要 Product Owner、Tech Lead、QA Lead、Security Owner、SRE/Release Owner 签署版本、日期、结论、例外和
有效期。签字记录存审批系统并链接发布版本；Markdown 中的姓名文本不能替代身份验证后的批准记录。
