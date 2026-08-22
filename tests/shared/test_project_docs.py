from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_all_project_markdown_local_links_resolve() -> None:
    documents = [ROOT / "README.md", ROOT / "README.zh-CN.md"]
    documents.extend((ROOT / "docs").rglob("*.md"))
    broken: list[str] = []

    for document in documents:
        text = document.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            relative_target = target.split("#", maxsplit=1)[0]
            if relative_target and not (document.parent / relative_target).resolve().exists():
                broken.append(f"{document.relative_to(ROOT)} -> {target}")

    assert not broken, "broken local links:\n" + "\n".join(broken)


def test_default_readme_exposes_runnable_and_honest_product_story() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "FDE" in readme
    assert "本地运行" in readme
    assert "docs/fde-interview-kit.md" in readme
    assert "docs/security-boundary.md" in readme
    assert "产品运行时只有一个 Agent" in readme
