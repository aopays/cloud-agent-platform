# 项目治理、风险与变更控制

- 文档版本：1.0
- 状态：`DRAFT`

## 1. 治理节奏

- 每周 Product/Engineering refinement：需求、假设、优先级和验收。
- 每日 15 分钟执行同步：进度、风险、阻塞和当天集成点。
- 每周架构/安全门诊：ADR、公共契约、威胁和例外。
- 每 Sprint 计划、演示、回顾和质量报告。
- 每月 Steering Committee：价值、成本、SLO、风险和范围决策。
- 每次发布 Go/No-Go：Product、Tech Lead、QA、Security、SRE 共同提供意见，Release Owner 决策。

Agent 可以自动准备材料和证据，但不能代替责任人的批准。

## 2. 决策管理

可逆、局部、低风险决策由模块 owner 处理；跨模块公共契约由 Tech Lead；范围和优先级由 Product Owner；安全例外
由 Security Owner + Sponsor；生产发布由 Release Owner。重大技术决策写 ADR，业务决策写 Decision Log，二者都
记录背景、备选、决定、理由、影响、owner 和复审条件。

## 3. 变更请求

基线后新增或修改范围必须提交 Change Request，包含：动机、需求 ID、业务价值、紧迫性、影响模块、数据/API/
安全/测试/运维影响、估算、风险、替代方案和回滚。Product Owner 评估范围，Tech Lead 评估技术，QA/Security/SRE
评估质量和运营；批准后更新版本、追踪矩阵、backlog 和发布计划。

紧急修复允许缩短评审，但不能跳过审计、回滚和事后补文档。

## 4. 初始风险登记

### R-01 Demo 被误认为生产能力

概率高、影响高。控制：文档明确 As-Is/Next/Target；生产启动时拒绝 Demo Provider、开发 Token、本地 Sandbox 和
内存存储。Owner：Tech Lead。

### R-02 报告生成成功但业务质量不足

概率高、影响高。证据为 15 场景只有 1 份质量通过。控制：结构化快照、专业 Agent、独立 QA/Eval、质量门和领域
专家抽检。Owner：Product + QA。

### R-03 Sandbox 逃逸或宿主破坏

概率中、影响极高。控制：强隔离、默认禁网、最小权限、恶意工作负载测试、隔离等级路由和紧急 kill switch。
Owner：Security。

### R-04 Prompt Injection 数据外传

概率高、影响高。控制：数据/指令分层、工具服务器授权、出口代理、凭证不进上下文、红队评测。Owner：Security。

### R-05 跨租户访问

概率中、影响极高。控制：tenant-first 数据模型、服务端授权、RLS、防 IDOR 测试和审计。Owner：Backend/Security。

### R-06 至少一次消息产生重复副作用

概率高、影响高。控制：幂等键、operation ID、状态条件更新、outbox、去重和故障注入。Owner：Backend。

### R-07 模型质量或供应商变化

概率高、影响中高。控制：Provider 抽象、版本 pin、离线评测、canary、独立 Reviewer 和回退模型。Owner：AI Lead。

### R-08 成本失控

概率中高、影响高。控制：任务/租户硬预算、模型路由、并发配额、成本告警和 kill switch。Owner：Platform/Product。

### R-09 私有仓库凭证泄漏

概率中、影响极高。控制：短期最小凭证、secret broker、日志/产物 scan、任务后撤销。Owner：Security/Platform。

### R-10 进程内状态导致重启丢失

概率高、影响高。控制：Beta 前完成 PostgreSQL、持久工作流、恢复扫描和灾备。Owner：Backend/SRE。

### R-11 数据驻留和模型合规不满足

概率中、影响高。控制：地区路由、供应商 DPA、数据分类、租户策略和人工批准。Owner：Privacy/Security。

### R-12 团队过度并行导致集成冲突

概率中、影响中。控制：先冻结契约、目录所有权、有限并行、每日集成和主 Agent/Tech Lead 统一裁决。Owner：Tech Lead。

### R-13 测试只覆盖快乐路径

概率中、影响高。控制：失败、取消、超时、重复、恢复、安全和混沌作为发布门；QA 独立审查。Owner：QA。

### R-14 数据迁移不可回滚

概率中、影响高。控制：expand/contract、备份、回填校验、canary、前滚修复和恢复演练。Owner：Backend/SRE。

### R-15 关键人员或单一 Agent 知识集中

概率中、影响中。控制：文档即代码、结构化交接、Reviewer 轮换、Runbook 和演练。Owner：Engineering Manager。

## 5. 风险评分和复审

概率和影响各 1–5，评分为乘积：15–25 为红色需 Sponsor 关注，8–14 为黄色需明确缓解计划，1–7 为正常跟踪。
风险每周更新概率、影响、触发信号、缓解状态和残余风险；关闭必须有证据，不能因为“暂未发生”关闭。

## 6. 范围控制

对所有新增能力先判断是否支持首发用户旅程、降低最高风险或满足门禁。不能因为项目体量看起来小就盲目拆微服务；
补充应集中在持久化、隔离、质量、运维和合规这些真实生产缺口。插件市场、多区域和自动生产部署保留为后续路线，
除非有明确客户和容量证据。
