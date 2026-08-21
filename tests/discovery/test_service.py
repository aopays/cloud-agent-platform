from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.discovery import (
    DemoDiscoveryAssistant,
    DiscoveryConflict,
    DiscoveryNotFound,
    DiscoveryService,
    DiscoveryStatus,
)
from src.storage import LocalArtifactStore


def service(tmp_path: Path) -> DiscoveryService:
    return DiscoveryService(DemoDiscoveryAssistant(), LocalArtifactStore(tmp_path / "artifacts"))


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
    assert "按天还是按周排班" in session.messages[-1].content


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
    assert "生成软件设计报告" in session.messages[-1].content


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
    assert "物流司机排班软件设计报告" in finalized.report
    assert "约 100 名司机" in finalized.report
    assert "默认假设与待确认项" in finalized.report
    assert "MVP 验收标准" in finalized.report
    artifact = await discovery.report_artifact(session.session_id, tenant_id="tenant-a")
    assert artifact.name == "software-design-report.md"
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
