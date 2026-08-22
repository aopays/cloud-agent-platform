"""Multi-turn requirement discovery and software design report generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

from src.agent_runtime.provider import LLMProvider, Message
from src.shared.contracts import Artifact
from src.shared.interfaces import ArtifactStore


class DiscoveryStatus(str, Enum):
    DISCOVERY = "DISCOVERY"
    READY = "READY"
    FINALIZED = "FINALIZED"


class DiscoveryNotFound(LookupError):
    pass


class DiscoveryConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DiscoveryMessage:
    sequence: int
    role: str
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class DiscoverySession:
    session_id: str
    tenant_id: str
    initial_requirement: str
    context: str | None
    status: DiscoveryStatus
    created_at: datetime
    updated_at: datetime
    messages: list[DiscoveryMessage]
    user_rounds: int = 0
    report: str | None = None
    report_artifact: Artifact | None = None


class DiscoveryAssistant(Protocol):
    async def initial_questions(self, requirement: str, context: str | None) -> str: ...

    async def follow_up(self, session: DiscoverySession) -> str: ...

    async def build_report(self, session: DiscoverySession) -> str: ...


class DemoDiscoveryAssistant:
    """Deterministic offline FDE discovery flow for a usable local demo."""

    async def initial_questions(self, requirement: str, context: str | None) -> str:
        del context
        if self._is_logistics_scheduling(requirement):
            return (
                "我会按 FDE 客户发现流程先确认业务结果和需求证据。请回答下面 5 个问题；"
                "不知道的可以写‘按合理默认值’：\n\n"
                "1. 谁是客户侧负责人和最终决策人？主要使用者是调度员、司机还是车队管理员？\n"
                "2. 现在如何排班，哪个环节最浪费时间或最容易出错？请给一个最近发生的例子。\n"
                "3. 属于城市配送、长途货运还是其他场景？司机、车辆、区域和日任务量是多少？\n"
                "4. 客户最想改善哪个可量化指标：准时率、成本、排班耗时、公平性还是投诉率？\n"
                "5. 第一版必须解决什么、明确不解决什么，谁负责验收？"
            )
        return (
            "我会按 FDE 客户发现流程，把这句话转成可执行技术方案。第一轮请回答：\n\n"
            "1. 谁提出了需求、谁最终决策、谁实际使用？三者是否是同一个人？\n"
            "2. 客户现在怎么完成这件事？最痛的步骤是什么？请提供一个最近的真实例子。\n"
            "3. 问题发生频率、用户量、数据量和损失或耗时大约是多少？\n"
            "4. 第一版必须改变哪个业务结果？用什么数字或现场行为证明成功？\n"
            "5. 明确的范围外事项、交付时间、预算或合规红线是什么？"
        )

    async def follow_up(self, session: DiscoverySession) -> str:
        logistics = self._is_logistics_scheduling(session.initial_requirement)
        if session.user_rounds == 1 and logistics:
            return (
                "收到。第二轮重点确认排班规则和异常处理：\n\n"
                "1. 是否需要遵守连续驾驶、强制休息、工时和加班上限？\n"
                "2. 是否要匹配驾照类型、司机技能、车辆类型、线路熟悉度？\n"
                "3. 如何处理请假、迟到、车辆故障、临时加单和紧急替班？\n"
                "4. 是否允许调度员手动调整，调整后是否需要保留原因和审计记录？\n"
                "5. 司机能否拒绝或申请换班，谁负责最终审批？"
            )
        if session.user_rounds == 1:
            return (
                "收到。第二轮只追问会阻塞工程实施的业务规则和证据：\n\n"
                "1. 请按顺序描述当前主流程，并指出每一步的输入、负责人和完成条件。\n"
                "2. 哪些规则绝不能违反？最常见的三个例外和人工兜底方式是什么？\n"
                "3. 需要哪些角色、权限和审批节点？谁有权覆盖系统建议？\n"
                "4. 需要哪些数据，分别来自哪个系统，由客户侧谁负责提供和解释？\n"
                "5. 哪些关键说法仍是猜测？需要访谈谁或查看什么数据才能确认？"
            )
        if session.user_rounds == 2 and logistics:
            return (
                "很好。最后一轮确认交付与系统边界：\n\n"
                "1. 是否需要连接订单系统、TMS、GPS、考勤或地图服务？\n"
                "2. 调度员使用电脑网页即可吗？司机是否需要手机端和消息通知？\n"
                "3. 排班需要提前多久生成，临时变化要求几秒或几分钟内重新计算？\n"
                "4. 是否有数据保留、隐私、等保或地域合规要求？\n"
                "5. 期望上线时间、预算和已有技术栈是什么？"
            )
        if session.user_rounds == 2:
            return (
                "第三轮确认技术可行性、验收和决策边界：\n\n"
                "1. 需要连接哪些现有系统？接口、样例数据、测试环境和系统负责人是否可获得？\n"
                "2. 哪些数据敏感，涉及哪些权限、安全、审计、地域或行业合规要求？\n"
                "3. 性能、可用性、并发、数据保留和故障恢复的最低可接受标准是什么？\n"
                "4. 请给出 3 到 5 条可现场验收的 Given/When/Then 标准和 PoC 成功阈值。\n"
                "5. 上线时间、预算、客户配合人、技术栈和最终 Go/No-Go 决策流程是什么？"
            )
        return (
            "已经达到生成技术方案草案的最少轮次，但这不等于需求完整。请检查业务结果与决策人、"
            "现状证据、范围和非目标、规则与异常、数据和集成负责人、安全约束、验收阈值、预算与时间。"
            "任何一项仍不明确，都可以继续补充；也可以生成 FDE 技术发现报告，"
            "并把缺口列为下一步行动。"
        )

    async def build_report(self, session: DiscoverySession) -> str:
        if self._is_logistics_scheduling(session.initial_requirement):
            return self._logistics_report(session)
        return self._generic_report(session)

    @staticmethod
    def _is_logistics_scheduling(requirement: str) -> bool:
        normalized = requirement.lower()
        logistics_words = ("物流", "司机", "车队", "配送", "货运", "排班")
        return sum(word in normalized for word in logistics_words) >= 2

    @staticmethod
    def _confirmed_information(session: DiscoverySession) -> str:
        answers = [message.content for message in session.messages if message.role == "user"][1:]
        if not answers:
            return "用户尚未回答澄清问题；以下设计全部使用显式默认假设。"
        return "\n\n".join(
            f"### 第 {index} 轮用户回答\n\n{answer}"
            for index, answer in enumerate(answers, start=1)
        )

    def _logistics_report(self, session: DiscoverySession) -> str:
        context = session.context or "未提供；采用下文默认假设。"
        confirmed = self._confirmed_information(session)
        return f"""# FDE 客户需求发现与物流司机排班技术方案

## 1. 文档信息

- 原始需求：{session.initial_requirement}
- 已知前置条件：{context}
- 需求发现轮数：{session.user_rounds}
- 会话编号：{session.session_id}
- 文档性质：客户访谈后的技术方案草案，待客户业务负责人和技术负责人共同确认

## 2. 客户需求证据

{confirmed}

## 3. 默认假设与待确认项

在用户没有明确回答的部分，MVP 暂按以下假设设计，正式开发前需要业务负责人确认：

- 面向一个城市配送车队，约 100 名司机、80 辆车、10 个配送区域。
- 调度员使用 Web 管理端，司机使用移动端 H5 或企业微信入口。
- 每日生成次日班表，同时支持当日请假、故障和临时订单触发的局部重排。
- 优先保证法规与订单时间窗，其次降低空驶里程和加班，最后提高班次公平性。
- 第一版只给出排班建议，由调度员确认后发布，不自动控制车辆或向外部系统写入。

## 4. 用户角色

1. 调度员：维护约束、生成和调整班表、处理冲突、发布班次。
2. 车队管理员：维护司机、车辆、资质、规则，查看成本和履约报表。
3. 司机：查看班次、确认接班、请假、申请换班、接收变更通知。
4. 审计/运营人员：只读查看排班变更、人工覆盖原因和关键指标。

## 5. MVP 功能范围

### 5.1 基础资料

- 司机档案、驾照与技能、可工作时间、偏好、请假和历史工时。
- 车辆档案、车型、载重、状态、所属站点和维保计划。
- 配送任务、线路、区域、时间窗、所需技能和车辆约束。

### 5.2 排班工作台

- 选择日期与站点，一键生成建议班表。
- 展示未分配任务、冲突、超时风险和规则违反原因。
- 拖拽调整司机、车辆和任务，保存人工调整理由。
- 比较调整前后的成本、准时率、加班和公平性指标。
- 确认并发布班表，保留版本和审计记录。

### 5.3 司机端

- 查看和确认班次。
- 提交请假、换班和不可用时段。
- 接收发布、变更、取消和紧急替班通知。

### 5.4 异常处理

- 司机临时缺勤、车辆故障、订单加急或取消时触发局部重排。
- 系统给出候选替代方案，不覆盖调度员尚未确认的人工调整。

## 6. 核心业务规则

- 硬约束：驾照/技能匹配、车辆可用、任务时间窗、强制休息、最大工时、班次不重叠。
- 软约束：司机偏好、线路熟悉度、公平性、连续工作天数、空驶里程和加班成本。
- 冲突处理顺序：法规安全 > 订单履约 > 车辆匹配 > 成本 > 公平与偏好。
- 任何违反硬约束的方案不能发布；人工覆盖软约束必须填写原因。

## 7. 关键业务流程

```text
同步司机/车辆/订单
  → 校验数据完整性
  → 生成候选排班
  → 计算冲突与评分
  → 调度员人工调整
  → 复核硬约束
  → 发布班表
  → 司机确认
  → 异常触发局部重排
```

## 8. 技术架构

```text
Web 调度端 / 司机移动端
        ↓
API Gateway + 身份认证
        ↓
排班业务服务 ── 规则引擎
        ↓              ↓
排班优化器        通知与审批服务
        ↓              ↓
PostgreSQL        Redis + 任务队列
        ↓
审计日志 / 指标 / 报表
```

建议技术栈：React 或 Vue 管理端、FastAPI 服务、PostgreSQL、Redis、异步 Worker；
排班优化器第一版使用 Google OR-Tools 的 CP-SAT/车辆路径能力，复杂模型与业务服务隔离部署。

## 9. 核心数据模型

- `Driver`：司机、资质、技能、状态、所属站点。
- `DriverAvailability`：可用时间、请假、偏好和最大工时。
- `Vehicle`：车辆、车型、载重、状态和站点。
- `DeliveryTask`：订单任务、时间窗、区域、技能和车辆要求。
- `Shift`：班次开始/结束时间、站点和状态。
- `Assignment`：班次、司机、车辆和配送任务的关联。
- `ScheduleVersion`：排班版本、评分、发布状态和创建来源。
- `ConstraintViolation`：约束类型、严重程度、对象和说明。
- `AuditLog`：操作人、变更前后内容、原因和时间。

## 10. 主要 API

- `POST /v1/schedules/generate`：生成候选排班。
- `GET /v1/schedules/{{id}}`：查看班表、评分和冲突。
- `PATCH /v1/schedules/{{id}}/assignments`：人工调整安排。
- `POST /v1/schedules/{{id}}/validate`：重新校验硬约束。
- `POST /v1/schedules/{{id}}/publish`：发布班表。
- `POST /v1/incidents`：报告请假、故障或临时订单。
- `POST /v1/schedules/{{id}}/reoptimize`：局部重新排班。
- `POST /v1/shifts/{{id}}/confirm`：司机确认班次。

## 11. 排班算法策略

第一阶段先过滤不满足硬约束的司机/车辆组合；第二阶段用加权目标函数优化：

```text
总评分 = 准时风险 × W1
       + 空驶里程 × W2
       + 加班成本 × W3
       + 工作量不公平度 × W4
       + 偏好违反数 × W5
```

所有权重必须可配置，并保存每次求解的规则版本、输入摘要和评分，保证结果可解释、可回放。

## 12. 安全与合规

- 按角色授权，司机只能看到自己的班次和必要任务信息。
- 对手机号、位置、考勤等个人信息进行最小化收集、传输加密和访问审计。
- 排班发布、人工覆盖、规则修改必须记录不可抵赖的审计日志。
- 地图/GPS/TMS 凭证存放在密钥服务中，不能进入日志或模型上下文。
- 自动排班仅作为建议；涉及劳动法规和安全的硬约束由规则引擎确定性校验。

## 13. 非功能要求

- 100 名司机、一天任务量不超过 5,000 时，首次排班建议在 60 秒内生成。
- 单个异常的局部重排在 10 秒内返回候选方案。
- 排班发布接口幂等；版本不可原地覆盖；关键操作具备审计记录。
- 核心服务目标可用性 99.9%，数据库每日备份并定期验证恢复。

## 14. MVP 验收标准

1. 导入司机、车辆和配送任务后可以生成无硬约束冲突的候选班表。
2. 调度员可以查看冲突原因、手动调整并重新校验。
3. 发布后的班表具有唯一版本，司机能够查看并确认。
4. 司机请假或车辆故障后，系统能生成不影响无关班次的替代建议。
5. 每次人工覆盖都记录操作人、时间、原因和前后差异。
6. 未授权用户不能查看其他司机的个人信息和班次。

## 15. 迭代计划

- 第 1 周：需求确认、原型、数据模型和规则清单。
- 第 2–3 周：基础资料、班表工作台和确定性规则校验。
- 第 4 周：优化器、冲突解释和人工调整。
- 第 5 周：司机端、通知、异常重排和审计。
- 第 6 周：业务试运行、指标校准、安全测试和上线准备。

## 16. 仍需业务方决定

- 真实车队规模、排班周期、业务类型和优化目标优先级。
- 适用地区的驾驶工时、休息和劳动法规具体条款。
- TMS、订单、GPS、考勤和通知系统的接口条件。
- 司机是否有拒绝、换班和偏好配置权，以及审批流程。
- 上线时间、预算、部署环境、数据地域和保留期限。

## 17. FDE 下一步行动与研发移交

1. 与客户负责人逐项确认默认假设、非目标、决策权限和验收指标，并形成会议决策记录。
2. 获取脱敏样例数据、现有排班表、规则清单和 TMS/GPS 接口文档，验证技术可行性。
3. 用一周完成规则建模与低保真原型评审；未通过的数据和接口前置条件不得进入开发承诺。
4. 将已确认项转成需求 ID、验收测试和迭代任务；待确认项保留责任人和截止时间。
5. 在 PoC 结束时依据准时率、排班耗时、硬约束违规数和人工调整量做 Go/No-Go 决策。
"""

    def _generic_report(self, session: DiscoverySession) -> str:
        context = session.context or "未提供；未确认部分按默认假设处理。"
        confirmed = self._confirmed_information(session)
        return f"""# FDE 客户需求发现与可执行技术方案

## 1. 执行摘要

- 客户原始表达：{session.initial_requirement}
- 已知前置条件：{context}
- 访谈轮数：{session.user_rounds}
- 当前成熟度：技术方案草案；未被客户明确表达的信息不得视为承诺

## 2. 客户需求证据

{confirmed}

## 3. 事实、假设和待确认决策

- **已确认事实**：仅包括上方客户原始表达和逐轮回答。
- **默认假设**：第一版采用模块化单体、人工审批高风险动作、先覆盖一个可验证主流程。
- **待确认决策**：决策人、现状基线、范围外事项、数据负责人、集成条件、验收阈值、预算和上线窗口。
- **证据要求**：重要结论应关联会议纪要、样例数据、流程截图、接口文档或客户负责人确认。

## 4. 客户角色与决策地图

1. 业务负责人：确认业务目标、范围、优先级和成功指标。
2. 一线用户：验证现状流程、异常场景和实际可用性。
3. 客户技术负责人：确认数据、接口、环境、安全与运维责任。
4. FDE：维护需求证据、技术方案、风险和跨团队移交。
5. 最终决策人：依据 PoC 结果、成本和风险做 Go/No-Go 决策。

## 5. As-Is 问题与 To-Be 目标

- As-Is 必须补齐当前步骤、负责人、输入输出、等待时间、错误率和人工兜底。
- To-Be 只承诺改变已确认的业务结果，不以“上线一个系统”代替价值目标。
- 建议先建立现状基线，再定义目标值和测量周期，避免上线后无法判断是否成功。

## 6. MVP 范围与非目标

### 范围内

1. 身份认证、角色权限和一个端到端核心业务流程。
2. 核心对象的状态流转、异常处理、人工审批和审计。
3. 必要的数据导入、外部集成适配器、通知和基础指标。

### 范围外

- 未确认的全量历史数据迁移、自动化高风险决策和一次性替换所有旧系统。
- 没有接口、数据样例或客户责任人的外部系统集成。
- 未形成验收标准的“智能化”“高性能”“体验好”等模糊目标。

## 7. 可追踪功能需求

- `FR-001`：目标用户能够完成已确认的端到端主流程。
- `FR-002`：关键业务对象具有合法、可审计且不可跳过的状态转换。
- `FR-003`：规则冲突、外部系统失败和人工覆盖具有显式处理路径。
- `FR-004`：关键写操作支持身份校验、幂等、防重复和操作审计。
- `FR-005`：系统输出能够关联输入数据、规则版本和处理结果。

## 8. 数据与集成清单

每个数据源和外部系统必须记录业务用途、系统负责人、接口方式、字段样例、数据量、更新频率、
敏感等级、测试环境、失败策略和交付日期。没有负责人或样例数据的集成标记为阻塞项。

## 9. 建议技术方案

### 9.1 技术架构

采用模块化单体作为第一版：Web/移动端调用 API 服务，业务模块使用 PostgreSQL，
耗时任务进入 Redis 队列和异步 Worker。外部集成通过适配器隔离，日志、指标和审计分开保存。

只有在独立扩缩容、隔离或团队所有权有真实证据时才拆分微服务。所有 AI 推断必须与确定性业务规则、
人工审批和可追踪证据分层。

### 9.2 核心数据模型

- `Actor`：用户、角色、组织、权限和决策责任。
- `BusinessEntity`：客户领域中的核心业务对象及其生命周期。
- `WorkflowState`：主流程状态、合法转换、完成条件和失败原因。
- `DecisionRule`：业务规则、优先级、版本、适用范围和人工覆盖条件。
- `IntegrationRecord`：外部系统、幂等键、同步状态和失败重试信息。
- `AuditEvent`：操作者、输入、变更前后内容、原因、结果和时间。

### 9.3 API 基线

- `POST /v1/entities`：幂等创建核心业务对象。
- `GET /v1/entities/{id}`：按权限查看对象、状态和处理证据。
- `POST /v1/entities/{id}/actions`：执行经过校验的状态动作。
- `GET /v1/entities/{id}/events`：查看公开业务与审计事件。
- `POST /v1/integrations/{{system}}/sync`：触发可追踪的外部系统同步。

具体实体名、字段、状态和 API 必须在客户确认领域模型后替换，不能把通用占位符当成最终契约。

## 10. 安全、可靠性与非功能要求

- 最小权限、租户隔离、输入校验、敏感数据加密和审计。
- 核心状态机、幂等写入、超时、重试和故障恢复必须自动测试。
- 性能、并发、可用性、RTO/RPO、保留期限和合规要求在客户确认数值前均为开放项。

## 11. PoC 与 MVP 验收标准

1. `Given` 已确认角色、样例数据和测试环境，`When` 执行主流程，`Then` 可完成并生成可核验结果。
2. 规则、异常、越权、重复提交和外部依赖失败都有客户认可的处理结果。
3. 关键操作可追踪到用户、输入、规则版本、结果和时间。
4. PoC 指标必须包含现状基线、目标阈值、测量窗口、数据来源和验收负责人。
5. 未通过数据质量、安全或集成前置条件时，不得以功能演示替代正式验收。

## 12. 交付计划与工程门禁

1. Discovery：确认问题、证据、范围、负责人和决策机制。
2. Feasibility：用样例数据和接口验证关键技术风险。
3. PoC：只实现能证明核心价值的最小闭环。
4. MVP：补齐安全、可靠性、运维、数据治理和验收自动化。
5. Handoff：输出需求 ID、架构决策、接口契约、验收用例、风险和责任矩阵。

## 13. 风险、依赖与仍需确认

- 用户角色、决策人、业务规模、现状基线、规则、异常流程和成功指标。
- 外部系统负责人、数据样例、接口权限、部署环境、安全合规、预算和时间限制。
- 客户未按期提供数据、接口或评审人员时，交付时间和范围必须走变更控制。

## 14. FDE 下一步访谈清单

- 对每个开放项指定客户责任人和确认日期。
- 用真实业务案例走查主流程和前三类异常，拒绝只讨论抽象功能名。
- 获取样例数据、接口文档和安全要求，安排技术可行性验证。
- 让业务负责人签字确认范围、非目标、验收指标与变更流程。
- 将本报告转成开发任务前，由架构、开发、QA 和安全共同完成可实施性评审。
"""


class ProviderDiscoveryAssistant:
    """Use the configured LLM provider for adaptive discovery and reporting."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def initial_questions(self, requirement: str, context: str | None) -> str:
        response = await self._provider.complete(
            [
                Message(role="system", content=self._discovery_prompt()),
                Message(
                    role="user",
                    content=(
                        f"原始需求：{requirement}\n"
                        f"已知前置条件：{context or '没有提供'}\n"
                        "这是第一轮。只提出最有价值的 3 到 5 个澄清问题。"
                    ),
                ),
            ],
            [],
        )
        return self._answer(response.final_answer)

    async def follow_up(self, session: DiscoverySession) -> str:
        messages = [Message(role="system", content=self._discovery_prompt())]
        messages.extend(Message(role=item.role, content=item.content) for item in session.messages)
        if session.user_rounds >= 3:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "按 FDE 技术发现就绪清单判断信息是否足够：业务结果和决策人、"
                        "现状流程与量化证据、"
                        "用户和规模、MVP 范围与非目标、规则与异常、数据和集成负责人、安全约束、"
                        "验收阈值、预算时间与 Go/No-Go 流程。若有阻塞缺口，"
                        "继续追问最关键的 3 到 5 个；"
                        "全部覆盖后才说明可以生成技术方案。不要直接输出报告。"
                    ),
                )
            )
        else:
            messages.append(
                Message(
                    role="user",
                    content="继续下一轮，只追问当前信息中最关键的 3 到 5 个缺口。",
                )
            )
        response = await self._provider.complete(messages, [])
        return self._answer(response.final_answer)

    async def build_report(self, session: DiscoverySession) -> str:
        messages = [
            Message(
                role="system",
                content=(
                    "你是资深 Forward Deployed Engineer、解决方案架构师和交付负责人。"
                    "根据完整对话输出中文 Markdown《FDE 客户需求发现与可执行技术方案》。"
                    "必须区分已确认事实、客户原话证据、默认假设、开放问题和已做决策。"
                    "报告必须包含执行摘要、决策人与用户、As-Is 流程和量化痛点、To-Be 目标、"
                    "MVP 范围与非目标、可追踪需求 ID、规则与异常、数据和集成责任矩阵、"
                    "技术架构与 API、安全和非功能要求、PoC/MVP 验收阈值、交付计划、风险依赖、"
                    "Go/No-Go 条件以及给开发与 QA 的移交清单。不要把模型推测写成客户承诺。"
                ),
            )
        ]
        messages.extend(Message(role=item.role, content=item.content) for item in session.messages)
        messages.append(Message(role="user", content="现在生成完整的 FDE 技术发现与方案报告。"))
        response = await self._provider.complete(messages, [])
        return self._answer(response.final_answer)

    @staticmethod
    def _discovery_prompt() -> str:
        return (
            "你是资深 Forward Deployed Engineer 的客户需求发现助手。目标不是陪聊或急于给方案，"
            "而是把企业负责人的模糊表达变成有证据、可实施、可验收的技术方案。"
            "优先确认业务结果与决策人、As-Is 流程和真实案例、量化规模与痛点、用户与权限、"
            "MVP 范围和非目标、规则与异常、数据来源和系统负责人、集成条件、安全合规、"
            "PoC 验收阈值、预算时间和决策流程。严格区分事实、假设、决策、风险和开放问题。"
            "不得重复已经回答的问题；遇到‘快、智能、好用’等模糊词必须追问数字、样例或可观察行为。"
            "每轮只问 3 到 5 个最阻塞工程实施的问题，并说明问题所处的访谈阶段；不要泄露内部推理。"
        )

    @staticmethod
    def _answer(value: str | None) -> str:
        if value is None or not value.strip():
            raise DiscoveryConflict("configured model returned no conversational text")
        return value.strip()


class DiscoveryService:
    MAX_USER_ROUNDS = 12
    READY_AFTER_ROUNDS = 3

    def __init__(self, assistant: DiscoveryAssistant, artifact_store: ArtifactStore) -> None:
        self._assistant = assistant
        self._artifact_store = artifact_store
        self._sessions: dict[str, DiscoverySession] = {}
        self._sessions_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def create(
        self,
        requirement: str,
        *,
        context: str | None,
        tenant_id: str,
    ) -> DiscoverySession:
        now = datetime.now(timezone.utc)
        session_id = f"discovery_{uuid4().hex}"
        assistant_message = await self._assistant.initial_questions(requirement, context)
        session = DiscoverySession(
            session_id=session_id,
            tenant_id=tenant_id,
            initial_requirement=requirement,
            context=context,
            status=DiscoveryStatus.DISCOVERY,
            created_at=now,
            updated_at=now,
            messages=[
                DiscoveryMessage(sequence=1, role="user", content=requirement, created_at=now),
                DiscoveryMessage(
                    sequence=2,
                    role="assistant",
                    content=assistant_message,
                    created_at=now,
                ),
            ],
        )
        async with self._sessions_lock:
            self._sessions[session_id] = session
            self._session_locks[session_id] = asyncio.Lock()
        return session

    async def get(self, session_id: str, *, tenant_id: str) -> DiscoverySession:
        async with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None or session.tenant_id != tenant_id:
            raise DiscoveryNotFound("discovery session not found")
        return session

    async def add_user_message(
        self,
        session_id: str,
        content: str,
        *,
        tenant_id: str,
    ) -> DiscoverySession:
        session = await self.get(session_id, tenant_id=tenant_id)
        lock = self._session_locks[session_id]
        async with lock:
            if session.status is DiscoveryStatus.FINALIZED:
                raise DiscoveryConflict("finalized discovery session is read-only")
            if session.user_rounds >= self.MAX_USER_ROUNDS:
                raise DiscoveryConflict("discovery session reached the maximum number of rounds")
            now = datetime.now(timezone.utc)
            session.messages.append(
                DiscoveryMessage(
                    sequence=len(session.messages) + 1,
                    role="user",
                    content=content,
                    created_at=now,
                )
            )
            session.user_rounds += 1
            if session.user_rounds >= self.READY_AFTER_ROUNDS:
                session.status = DiscoveryStatus.READY
            reply = await self._assistant.follow_up(session)
            session.messages.append(
                DiscoveryMessage(
                    sequence=len(session.messages) + 1,
                    role="assistant",
                    content=reply,
                )
            )
            session.updated_at = datetime.now(timezone.utc)
            return session

    async def finalize(self, session_id: str, *, tenant_id: str) -> DiscoverySession:
        session = await self.get(session_id, tenant_id=tenant_id)
        lock = self._session_locks[session_id]
        async with lock:
            if session.status is DiscoveryStatus.FINALIZED:
                return session
            report = await self._assistant.build_report(session)
            artifact = await self._artifact_store.put_text(
                session.session_id,
                "fde-technical-solution.md",
                report,
                "text/markdown",
            )
            session.report = report
            session.report_artifact = artifact
            session.status = DiscoveryStatus.FINALIZED
            session.updated_at = datetime.now(timezone.utc)
            return session

    async def report_artifact(self, session_id: str, *, tenant_id: str) -> Artifact:
        session = await self.get(session_id, tenant_id=tenant_id)
        if session.report_artifact is None:
            raise DiscoveryConflict("software design report has not been generated")
        return session.report_artifact
