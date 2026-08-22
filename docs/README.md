# Cloud Agent Platform 文档中心

这里不是一组“为了显得完整”的文档，而是把可运行代码、架构决策、测试证据和生产演进边界连接起来的导航页。

## 第一次了解项目

1. [项目首页](../README.md)：价值、能力、启动和演示路径。
2. [FDE / AI Agent 面试展示包](fde-interview-kit.md)：三分钟讲稿、现场 Demo、常见追问和简历写法。
3. [产品定位与需求](product-positioning.md)：目标用户、核心场景、MVP 范围和指标。
4. [系统架构](system-architecture.md)：从系统上下文到组件、时序和部署。
5. [代码导览](code-tour.md)：从 `src/main.py` 开始逐层读懂代码。

## 想运行或二次开发

- [FDE 客户需求发现工作手册](fde-discovery-playbook.md)
- [FDE 多轮需求发现功能](requirement-discovery.md)
- [MVP 需求基线](requirements.md)
- [MVP 架构基线](architecture.md)
- [验收标准](acceptance-criteria.md)
- [OpenAPI 契约](contracts/openapi.yaml)
- [Agent 事件契约](contracts/agent-events.md)
- [发布前检查](release-checklist.md)
- [贡献指南](../CONTRIBUTING.md)

## 想评估工程与安全

- [沙箱与安全边界](security-boundary.md)
- [公开安全策略](../SECURITY.md)
- [需求场景评测](reviews/discovery-scenario-evaluation.md)
- [任务看板与决策记录](task-board.md)

## 想了解开源传播与项目包装

- [对标仓库增长分析](open-source-growth-analysis.md)：用公开数据拆解搜索入口、首屏转化、面试资料和 Star 路径。
- [FDE / AI Agent 面试展示包](fde-interview-kit.md)：把可运行能力转成有证据的项目讲解，不虚构业务和性能指标。

## 想看真实软件生命周期

[SDLC 文档中心](sdlc/README.md)覆盖产品、SRS、数据/API、多 Agent 编排、开发、测试、安全、发布、SRE、
治理和移交，并用 `As-Is / Next / Target` 区分事实与路线图。

## 想扩展为多 Agent 平台

- [多 Agent 目标架构](multi-agent-platform-architecture.md)
- [多 Agent 开发流程](workflows/multi-agent-development.md)
- [Tech Lead Prompt](prompts/tech-lead.md)

当前运行时代码是单 Agent 工具循环；上述多 Agent 文档描述的是扩展路径和团队协作方法，不应作为已实现功能宣传。
