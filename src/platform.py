"""Dependency composition for the runnable modular-monolith MVP."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.agent_runtime.loop import AgentRuntime
from src.agent_runtime.openai_provider import OpenAIResponsesProvider
from src.agent_runtime.provider import DemoProvider, LLMProvider
from src.discovery import (
    DemoDiscoveryAssistant,
    DiscoveryAssistant,
    DiscoveryService,
    ProviderDiscoveryAssistant,
)
from src.models.repository import InMemoryTaskRepository
from src.repository_preparation import LocalRepositoryPreparer
from src.sandbox import DockerSandboxProvider, LocalSandboxProvider
from src.scheduler.cancellation import CancellationBroker
from src.scheduler.leases import InMemoryLeaseManager
from src.scheduler.queue import InMemoryTaskQueue
from src.scheduler.service import TaskLifecycleService
from src.shared.interfaces import SandboxProvider
from src.shared.settings import Settings
from src.storage import InMemoryEventStore, LocalArtifactStore
from src.tools.builtin import create_default_registry
from src.worker import TaskWorker


@dataclass(slots=True)
class Platform:
    settings: Settings
    service: TaskLifecycleService
    queue: InMemoryTaskQueue
    events: InMemoryEventStore
    artifacts: LocalArtifactStore
    discovery: DiscoveryService
    worker: TaskWorker


def create_platform(settings: Settings | None = None) -> Platform:
    settings = settings or Settings.from_environment()
    if settings.app_env not in {"development", "test"} and (
        settings.bearer_token == "local-demo-token" or len(settings.bearer_token) < 32
    ):
        raise ValueError("production requires a non-default bearer token of at least 32 chars")
    repository = InMemoryTaskRepository()
    queue = InMemoryTaskQueue()
    leases = InMemoryLeaseManager()
    cancellations = CancellationBroker()
    events = InMemoryEventStore()
    service = TaskLifecycleService(
        repository=repository,
        queue=queue,
        leases=leases,
        cancellations=cancellations,
        event_sink=events,
    )
    artifacts = LocalArtifactStore(settings.artifact_root)
    sandbox_backend = settings.sandbox_backend
    sandbox: SandboxProvider
    if sandbox_backend == "docker":
        sandbox = DockerSandboxProvider(settings.run_root)
    elif sandbox_backend == "local":
        if settings.app_env not in {"development", "test"}:
            raise ValueError("the trusted local sandbox is forbidden outside development/test")
        sandbox = LocalSandboxProvider(
            settings.run_root,
            allow_trusted_execution=True,
        )
    else:
        raise ValueError("SANDBOX_BACKEND must be 'local' or 'docker'")
    llm_provider: LLMProvider
    discovery_assistant: DiscoveryAssistant
    if settings.llm_provider == "demo":
        llm_provider = DemoProvider()
        discovery_assistant = DemoDiscoveryAssistant()
    elif settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        llm_provider = OpenAIResponsesProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )
        discovery_assistant = ProviderDiscoveryAssistant(llm_provider)
    else:
        raise ValueError("LLM_PROVIDER must be 'demo' or 'openai'")
    runtime = AgentRuntime(
        llm_provider,
        create_default_registry(allow_execute=sandbox_backend != "local"),
    )
    worker = TaskWorker(
        worker_id=f"local-worker-{uuid4().hex}",
        service=service,
        queue=queue,
        sandbox_provider=sandbox,
        repository_preparer=LocalRepositoryPreparer(
            allowed_root=settings.repository_import_root,
            allowed_git_hosts=settings.repository_allowed_hosts,
        ),
        runtime=runtime,
        event_sink=events,
        artifact_store=artifacts,
    )
    discovery = DiscoveryService(discovery_assistant, artifacts)
    return Platform(settings, service, queue, events, artifacts, discovery, worker)
