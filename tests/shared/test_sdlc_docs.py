from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDLC_ROOT = ROOT / "docs" / "sdlc"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

REQUIRED_DOCUMENTS = {
    "README.md",
    "01-product-and-business-requirements.md",
    "02-software-requirements-specification.md",
    "03-system-data-api-design.md",
    "04-multi-agent-orchestration-design.md",
    "05-development-plan.md",
    "06-test-and-quality-plan.md",
    "07-security-privacy-compliance.md",
    "08-release-deployment-runbook.md",
    "09-operations-sre.md",
    "10-project-governance-and-risk.md",
    "11-acceptance-handover-traceability.md",
    "templates/adr.md",
    "templates/change-request.md",
    "templates/test-report.md",
}


def test_sdlc_document_set_is_complete() -> None:
    missing = [name for name in sorted(REQUIRED_DOCUMENTS) if not (SDLC_ROOT / name).is_file()]
    assert not missing, f"missing SDLC documents: {missing}"


def test_sdlc_local_markdown_links_resolve() -> None:
    broken: list[str] = []
    for document in SDLC_ROOT.rglob("*.md"):
        text = document.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            relative_target = target.split("#", maxsplit=1)[0]
            if relative_target and not (document.parent / relative_target).resolve().exists():
                broken.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not broken, "broken local links:\n" + "\n".join(broken)


def test_srs_contains_traceable_functional_and_nonfunctional_requirements() -> None:
    srs = (SDLC_ROOT / "02-software-requirements-specification.md").read_text(encoding="utf-8")
    assert len(set(re.findall(r"CAP-FR-\d{3}", srs))) >= 30
    assert len(set(re.findall(r"CAP-NFR-\d{3}", srs))) >= 10
    assert "未决业务决策" in srs
