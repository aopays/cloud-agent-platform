# 多 Agent 任务看板

## CAP-SDLC-001：企业级软件开发生命周期文档

- 状态：`DONE`
- 所有者：主 Agent
- 范围：`docs/sdlc/**`、README 文档入口和文档完整性测试
- 交付：PRD、SRS、系统/数据/API、多 Agent 编排、开发、测试、安全、发布、SRE、风险、验收和移交基线
- 验收：文档区分 As-Is/Next/Target，P0 需求具有稳定 ID，生命周期阶段有门禁，所有本地链接通过自动检查

## 当前扩展任务

### CAP-GROWTH-001：面向面试官的开源产品包装与增长基线

- 状态：`DONE`
- 所有者：主 Agent
- 范围：README 首屏与信息架构、对标仓库客观分析、FDE 面试演示材料、文档导航、GitHub 搜索元数据
- 验收：产品承诺与已实现能力一致；新用户可在首屏理解用户、痛点、输入、输出和演示路径；所有本地链接与质量门通过；不复制对标仓库原文，不使用虚构指标
- 验证：Ruff format/lint、strict mypy、全量 pytest、安全标记测试、compileall 与全仓库 Markdown 本地链接检查全部通过

### CAP-FDE-001：FDE 客户需求发现前置工作流

- 状态：`DONE`
- 所有者：主 Agent
- 范围：Discovery Prompt、离线访谈流程、技术方案报告、Web UI、中英文产品定位、测试与 GitHub 元数据
- 验收：访谈围绕证据和实施阻塞推进；三轮仅代表可生成草案；报告包含范围、责任人、数据集成、验收、
  Go/No-Go 与研发移交；本地及 GitHub 质量门通过

### CAP-OSS-001：GitHub 开源发现与仓库治理

- 状态：`DONE`
- 所有者：主 Agent
- 范围：GitHub 仓库设置、README 双语入口、项目视觉、社区模板、标签、发布与验证
- 验收：搜索元数据准确；新用户可在首屏理解价值并离线启动；main、Actions 与安全策略回读通过；
  变更通过本地质量门并以独立 PR 交付

### CAP-DISC-001：多轮需求发现与软件设计报告

- 状态：`DONE`
- 所有者：主 Agent
- 范围：需求发现服务、HTTP API、聊天页面、报告产物、测试和文档
- 验收：模糊需求可完成至少三轮对话；用户可提前或在 READY 后生成并下载报告；
  报告区分已确认信息、默认假设和待确认问题；租户隔离和输入上限有测试

## 使用规则

- 主 Agent 是本文件唯一维护者。
- 分发前填写任务 ID、依赖、所有者、允许修改范围和验收条件。
- 同一波次中不得出现重叠文件所有权。
- 任务状态只使用：`BACKLOG`、`READY`、`RUNNING`、`REVIEW`、`DONE`、`BLOCKED`。
- 子 Agent 的完成报告通过主 Agent验收后，状态才能进入 `DONE`。

## 当前里程碑

目标：完成 Cloud Agent Platform P0 纵向闭环。

进入开发的前置条件：

- [x] 人工确认 `docs/requirements.md` 中的关键假设（用户授权按现有假设推进）。
- [x] 确认 API 与 Agent 事件契约。
- [x] 确认实际技术栈：Python 3.10+、FastAPI、本地适配器默认运行，PostgreSQL/Redis 为演进接口。
- [x] 确认第一轮任务没有目录重叠。

## 第一波：并行实现

### CAP-BE-001：API、数据模型与任务调度

- 状态：`DONE`
- 所有者：`backend-engineer`
- 依赖：公共契约确认
- 允许修改：`src/api/**`、`src/models/**`、`src/scheduler/**`、`tests/api/**`、`tests/scheduler/**`
- 禁止修改：共享依赖、迁移、公共契约、沙箱和 Runtime 目录
- 交付：创建/查询/取消 API，任务状态机，队列接口，幂等和租约语义
- 验收：API 契约测试、状态机测试、重复消费和取消测试通过

### CAP-RT-001：Agent Runtime 与工具系统

- 状态：`DONE`
- 所有者：`agent-runtime-engineer`
- 依赖：事件契约确认、Sandbox 接口 stub
- 允许修改：`src/agent_runtime/**`、`src/tools/**`、`tests/agent_runtime/**`、`tests/tools/**`
- 禁止修改：共享依赖、公共契约、API 和 Sandbox 实现目录
- 交付：LLM Provider 接口、Agent Loop、工具 Schema、预算、终止和重复调用检测
- 验收：最终结果、工具调用、取消、超时、预算耗尽和无进展测试通过

### CAP-SB-001：沙箱与安全策略

- 状态：`DONE`
- 所有者：`sandbox-security-engineer`
- 依赖：Sandbox 接口确认
- 允许修改：`src/sandbox/**`、`sandbox/**`、`tests/sandbox/**`
- 禁止修改：共享依赖、公共契约、API 和 Runtime 目录
- 交付：沙箱生命周期、文件和命令原语、资源限制、默认禁网、取消与清理
- 验收：路径穿越、符号链接、资源耗尽、网络访问和进程残留测试通过

## 主 Agent 集成任务

### CAP-LEAD-001：项目骨架和共享接口

- 状态：`DONE`
- 所有者：主 Agent
- 依赖：需求与架构确认
- 允许修改：全项目共享文件
- 交付：依赖配置、公共接口、基础目录、容器编排、数据库迁移和测试命令
- 验收：三个专业 Agent 可以在不修改共享文件的情况下独立工作

### CAP-LEAD-002：端到端集成

- 状态：`DONE`
- 所有者：主 Agent
- 依赖：CAP-BE-001、CAP-RT-001、CAP-SB-001
- 交付：连接 API、Worker、Runtime、Sandbox、事件和产物
- 验收：成功、取消、超时和策略拒绝的端到端场景通过

### CAP-REL-002：GitHub 发布准备

- 状态：`DONE`
- 所有者：主 Agent
- 依赖：CAP-LEAD-002、CAP-QA-001、CAP-SEC-001、CAP-REL-001
- 交付：项目根配置、`.env` 加载、跨平台启动、Docker/Compose 闭环、许可证、社区文件、CI、安全扫描和发布清单
- 验收：任意工作目录导入通过；本地质量门通过；应用与 Sandbox 镜像构建通过；Compose `/readyz` 和首页冒烟通过；Sandbox 非 root 与禁网动态验证通过

## 第二波：并行审查

### CAP-QA-001：需求覆盖与测试审查

- 状态：`DONE`
- 所有者：`qa-reviewer`
- 依赖：CAP-LEAD-002
- 模式：默认只读
- 交付：按严重级别排列的问题、证据、复现命令和测试缺口

### CAP-SEC-001：攻击视角安全审查

- 状态：`DONE`
- 所有者：`sandbox-security-engineer`
- 依赖：CAP-LEAD-002
- 模式：只读审查
- 交付：路径、容器、资源、网络、凭证、Prompt Injection 和清理风险

### CAP-REL-001：可靠性与一致性审查

- 状态：`DONE`
- 所有者：`backend-engineer`
- 依赖：CAP-LEAD-002
- 模式：只读审查
- 交付：幂等、重试、租约、取消、并发、终态一致性和故障恢复问题

## 决策和阻塞记录

```text
日期：2026-08-19
任务 ID：CAP-LEAD-001
类型：DECISION
背景：当前开发机未安装 FastAPI，Docker 服务未启动；仍需形成可测试的纵向 MVP。
证据：Python 3.10.2 可用；FastAPI import 失败；Docker daemon 连接失败。
决定或需要的输入：默认使用本地可替换适配器运行测试；声明 FastAPI 依赖并保留 Docker/PostgreSQL/Redis 演进配置。Docker 安全控制仅在服务可用后才能做运行时验证。
影响范围：公共骨架、测试策略、README 已知限制。
负责人：主 Agent
```

使用以下模板追加：

```text
日期：
任务 ID：
类型：DECISION / BLOCKER
背景：
证据：
决定或需要的输入：
影响范围：
负责人：
```
