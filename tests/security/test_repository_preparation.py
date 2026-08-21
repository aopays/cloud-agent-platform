from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.repository_preparation import (
    LocalRepositoryPreparer,
    RepositoryPreparationError,
)
from src.shared.contracts import RepositorySpec

pytestmark = pytest.mark.security


def test_local_repository_must_be_below_configured_import_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "destination"
    destination.mkdir()
    preparer = LocalRepositoryPreparer(allowed_root=allowed)

    with pytest.raises(RepositoryPreparationError, match="outside the import root"):
        asyncio.run(preparer.prepare(RepositorySpec(outside.as_uri()), destination))


def test_import_omits_sensitive_files_and_git_metadata(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    source = allowed / "repo"
    source.mkdir(parents=True)
    (source / "app.py").write_text("# TODO safe\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (source / "private.key").write_text("secret\n", encoding="utf-8")
    (source / "secret.txt").write_text("secret\n", encoding="utf-8")
    (source / "id_rsa").write_text("private key\n", encoding="utf-8")
    (source / ".npmrc").write_text("//registry/:_authToken=x\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("credential=secret\n", encoding="utf-8")
    destination = tmp_path / "destination"
    destination.mkdir()

    asyncio.run(
        LocalRepositoryPreparer(allowed_root=allowed).prepare(
            RepositorySpec(source.as_uri()), destination
        )
    )
    assert (destination / "app.py").is_file()
    assert not (destination / ".env").exists()
    assert not (destination / "private.key").exists()
    assert not (destination / "secret.txt").exists()
    assert not (destination / "id_rsa").exists()
    assert not (destination / ".npmrc").exists()
    assert not (destination / ".git").exists()


def test_https_repository_host_must_be_allowlisted(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    destination = tmp_path / "destination"
    destination.mkdir()
    preparer = LocalRepositoryPreparer(allowed_root=allowed, allowed_git_hosts=("github.com",))

    with pytest.raises(RepositoryPreparationError, match="host or credentials"):
        asyncio.run(
            preparer.prepare(RepositorySpec("https://internal.example/repository.git"), destination)
        )
