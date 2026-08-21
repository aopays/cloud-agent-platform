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
    """Deterministic offline product-manager flow for a usable local demo."""

    async def initial_questions(self, requirement: str, context: str | None) -> str:
        del context
        if self._is_logistics_scheduling(requirement):
            return (
                "这个需求目前比较模糊，我先确认业务背景。请尽量回答下面 5 个问题；"
                "不知道的可以写‘按合理默认值’：\n\n"
                "1. 主要使用者是谁：调度员、车队管理员、司机，还是都需要？\n"
                "2. 业务属于城市配送、长途货运、快递末端，还是其他场景？\n"
                "3. 大约有多少司机、车辆和配送区域？按天还是按周排班？\n"
                "4. 排班最重要的目标是什么：准时率、最低成本、公平性还是司机满意度？\n"
                "5. 第一版必须解决的三个问题是什么？"
            )
        return (
            "我会先做需求挖掘，再生成软件设计报告。请回答：\n\n"
            "1. 谁会使用这个软件，他们现在最痛苦的问题是什么？\n"
            "2. 软件在哪些业务场景下使用，频率和大致规模是多少？\n"
            "3. 第一版必须完成哪些核心流程？\n"
            "4. 用什么指标判断软件上线成功？\n"
            "5. 有哪些明确不能做或必须遵守的前置条件？"
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
                "收到。第二轮确认业务规则：\n\n"
                "1. 核心流程有哪些必须满足的规则和例外？\n"
                "2. 需要哪些角色、权限和审批节点？\n"
                "3. 需要保存哪些数据，数据从哪里来？\n"
                "4. 发生冲突或失败时应由系统还是人工处理？\n"
                "5. 哪些操作必须保留审计记录？"
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
                "最后一轮确认交付条件：\n\n"
                "1. 使用网页、手机、桌面端，还是需要多端？\n"
                "2. 需要连接哪些已有系统或第三方服务？\n"
                "3. 对性能、可用性、安全和合规有什么要求？\n"
                "4. 预计用户量、数据量和并发量是多少？\n"
                "5. 上线时间、预算、团队和技术栈有哪些限制？"
            )
        return (
            "需求信息已经达到第一版设计所需的基本完整度。你可以继续补充，"
            "也可以点击“生成软件设计报告”。报告会区分已确认需求和默认假设。"
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
        return f"""# 物流司机排班软件设计报告

## 1. 文档信息

- 原始需求：{session.initial_requirement}
- 已知前置条件：{context}
- 需求发现轮数：{session.user_rounds}
- 会话编号：{session.session_id}

## 2. 已确认需求

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
"""

    def _generic_report(self, session: DiscoverySession) -> str:
        context = session.context or "未提供；未确认部分按默认假设处理。"
        confirmed = self._confirmed_information(session)
        return f"""# 软件设计报告

## 1. 原始需求

{session.initial_requirement}

## 2. 已知前置条件

{context}

## 3. 多轮需求发现记录

{confirmed}

## 4. 产品目标与成功指标

- 解决原始需求描述中的核心业务问题。
- 先交付覆盖主流程的可验证 MVP，再基于真实使用数据扩展。
- 上线前由业务负责人确认角色、规则、数据、集成和合规假设。

## 5. MVP 功能框架

1. 身份认证、用户角色和权限。
2. 核心业务对象的创建、查询、修改和状态流转。
3. 主业务流程、异常处理和人工审批。
4. 操作审计、基础报表和通知。
5. 可配置业务规则以及导入、导出能力。

## 6. 建议架构

采用模块化单体作为第一版：Web/移动端调用 API 服务，业务模块使用 PostgreSQL，
耗时任务进入 Redis 队列和异步 Worker。外部集成通过适配器隔离，日志、指标和审计分开保存。

## 7. 安全与质量

- 最小权限、租户隔离、输入校验、敏感数据加密和审计。
- 核心状态机、幂等写入、超时、重试和故障恢复必须自动测试。
- 先验证业务正确性，再根据实际数据决定是否拆分微服务。

## 8. MVP 验收标准

1. 目标用户可以完整完成主业务流程。
2. 非法状态、越权访问和重复提交被明确拒绝。
3. 关键操作可追踪，错误对用户可解释。
4. 性能、安全和可恢复性满足已确认的前置条件。

## 9. 仍需确认

- 用户角色、业务规模、核心规则、异常流程和成功指标。
- 外部系统、部署环境、安全合规、预算和时间限制。
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
                        "判断信息是否足够形成 MVP 设计。简要总结已确认内容和关键假设，"
                        "然后提示用户可以生成软件设计报告；不要直接输出报告。"
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
                    "你是资深产品经理和软件架构师。根据完整对话输出中文 Markdown 软件设计报告。"
                    "必须区分已确认需求、默认假设和待确认问题，并包含角色、流程、功能范围、"
                    "数据模型、架构、API、安全、非功能要求、MVP 验收标准、风险和迭代计划。"
                    "不要声称用户确认了对话中没有出现的信息。"
                ),
            )
        ]
        messages.extend(Message(role=item.role, content=item.content) for item in session.messages)
        messages.append(Message(role="user", content="现在生成完整的软件设计报告。"))
        response = await self._provider.complete(messages, [])
        return self._answer(response.final_answer)

    @staticmethod
    def _discovery_prompt() -> str:
        return (
            "你是需求发现 Agent。目标是通过多轮对话把模糊的软件需求变为可验收的 MVP。"
            "优先询问用户角色、业务场景、规模、规则、异常、数据、集成、成功指标和交付约束。"
            "每轮只问 3 到 5 个问题，问题要具体、容易回答；不要泄露内部推理。"
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
                "software-design-report.md",
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
