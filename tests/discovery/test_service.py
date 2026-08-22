from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.agent_runtime.provider import Message, ModelResponse
from src.discovery import (
    DemoDiscoveryAssistant,
    DiscoveryConflict,
    DiscoveryMessage,
    DiscoveryNotFound,
    DiscoveryService,
    DiscoverySession,
    DiscoveryStatus,
    ProviderDiscoveryAssistant,
)
from src.storage import LocalArtifactStore


def service(tmp_path: Path) -> DiscoveryService:
    return DiscoveryService(DemoDiscoveryAssistant(), LocalArtifactStore(tmp_path / "artifacts"))


class RecordingProvider:
    name = "recording"
    model = "recording-model"

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse:
        del tools
        self.messages = list(messages)
        return ModelResponse(final_answer="请继续补充关键实施信息。")


@pytest.mark.asyncio
async def test_logistics_requirement_starts_with_business_questions(tmp_path: Path) -> None:
    session = await service(tmp_path).create(
        "设计一个物流司机排班用的软件",
        context="六周内交付 Web MVP",
        tenant_id="tenant-a",
    )

    assert session.status is DiscoveryStatus.DISCOVERY
    assert session.user_rounds == 0
    assert "调度员" in session.messages[-1].content
    assert "最终决策人" in session.messages[-1].content
    assert "最近发生的例子" in session.messages[-1].content


@pytest.mark.asyncio
async def test_generic_discovery_starts_with_fde_evidence_questions(tmp_path: Path) -> None:
    session = await service(tmp_path).create(
        "给企业做一个智能客服系统",
        context="负责人希望两个月上线",
        tenant_id="tenant-a",
    )

    question = session.messages[-1].content
    assert "FDE 客户发现流程" in question
    assert "谁最终决策" in question
    assert "真实例子" in question
    assert "范围外事项" in question


@pytest.mark.asyncio
async def test_three_rounds_make_session_ready(tmp_path: Path) -> None:
    discovery = service(tmp_path)
    session = await discovery.create(
        "设计一个物流司机排班用的软件",
        context=None,
        tenant_id="tenant-a",
    )

    for answer in (
        "调度员和司机使用，城市配送，100 名司机，按天排班。",
        "必须遵守工时和休息规则，允许调度员人工调整。",
        "需要对接 TMS，调度员用 Web，司机用手机。",
    ):
        session = await discovery.add_user_message(
            session.session_id,
            answer,
            tenant_id="tenant-a",
        )

    assert session.status is DiscoveryStatus.READY
    assert session.user_rounds == 3
    assert "生成 FDE 技术发现报告" in session.messages[-1].content


@pytest.mark.asyncio
async def test_finalize_generates_downloadable_logistics_report(tmp_path: Path) -> None:
    discovery = service(tmp_path)
    session = await discovery.create(
        "设计一个物流司机排班用的软件",
        context="六周交付，优先做管理端",
        tenant_id="tenant-a",
    )
    session = await discovery.add_user_message(
        session.session_id,
        "约 100 名司机，城市配送，目标是准时率和公平性。",
        tenant_id="tenant-a",
    )

    finalized = await discovery.finalize(session.session_id, tenant_id="tenant-a")
    assert finalized.status is DiscoveryStatus.FINALIZED
    assert finalized.report is not None
    assert "FDE 客户需求发现与物流司机排班技术方案" in finalized.report
    assert "约 100 名司机" in finalized.report
    assert "默认假设与待确认项" in finalized.report
    assert "MVP 验收标准" in finalized.report
    assert "FDE 下一步行动与研发移交" in finalized.report
    artifact = await discovery.report_artifact(session.session_id, tenant_id="tenant-a")
    assert artifact.name == "fde-technical-solution.md"
    content = await asyncio.to_thread(Path(artifact.storage_path).read_text, encoding="utf-8")
    assert content == finalized.report

    same = await discovery.finalize(session.session_id, tenant_id="tenant-a")
    assert same.report_artifact == finalized.report_artifact
    with pytest.raises(DiscoveryConflict):
        await discovery.add_user_message(
            session.session_id,
            "继续修改",
            tenant_id="tenant-a",
        )


@pytest.mark.asyncio
async def test_discovery_sessions_are_tenant_scoped(tmp_path: Path) -> None:
    discovery = service(tmp_path)
    session = await discovery.create("设计库存系统", context=None, tenant_id="tenant-a")

    with pytest.raises(DiscoveryNotFound):
        await discovery.get(session.session_id, tenant_id="tenant-b")


@pytest.mark.asyncio
async def test_generic_report_is_an_engineering_handoff_not_a_chat_summary(
    tmp_path: Path,
) -> None:
    discovery = service(tmp_path)
    session = await discovery.create(
        "给企业做一个智能客服系统",
        context="客户业务负责人希望先做内部 PoC",
        tenant_id="tenant-a",
    )
    session = await discovery.add_user_message(
        session.session_id,
        "客服主管决策，每天五万工单，当前人工分流约十分钟，PoC 目标三十秒内给出建议。",
        tenant_id="tenant-a",
    )

    finalized = await discovery.finalize(session.session_id, tenant_id="tenant-a")
    assert finalized.report is not None
    for section in (
        "事实、假设和待确认决策",
        "客户角色与决策地图",
        "MVP 范围与非目标",
        "数据与集成清单",
        "PoC 与 MVP 验收标准",
        "FDE 下一步访谈清单",
    ):
        assert section in finalized.report
    assert "每天五万工单" in finalized.report


def test_provider_prompt_enforces_fde_discovery_gates() -> None:
    prompt = ProviderDiscoveryAssistant._discovery_prompt()
    assert "Forward Deployed Engineer" in prompt
    assert "事实、假设、决策、风险和开放问题" in prompt
    assert "不得重复已经回答的问题" in prompt
    assert "数字、样例或可观察行为" in prompt


@pytest.mark.asyncio
async def test_provider_keeps_probing_blockers_after_minimum_rounds() -> None:
    provider = RecordingProvider()
    assistant = ProviderDiscoveryAssistant(provider)
    now = datetime.now(timezone.utc)
    session = DiscoverySession(
        session_id="discovery_test",
        tenant_id="tenant-a",
        initial_requirement="做一个智能客服系统",
        context=None,
        status=DiscoveryStatus.READY,
        created_at=now,
        updated_at=now,
        messages=[
            DiscoveryMessage(index, "user", f"第 {index} 轮回答", now) for index in range(1, 4)
        ],
        user_rounds=3,
    )

    await assistant.follow_up(session)

    readiness_instruction = provider.messages[-1].content
    assert "FDE 技术发现就绪清单" in readiness_instruction
    assert "若有阻塞缺口，继续追问" in readiness_instruction
    assert "Go/No-Go" in readiness_instruction
