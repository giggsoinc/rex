"""Coordinator factory — picks backend based on config / mode."""

from __future__ import annotations

from rex.coordinator.base import Coordinator, WorkerMode


def get_coordinator(mode: str = "asyncio") -> Coordinator:
    """Construct the configured coordinator.

    Args:
        mode: One of: asyncio, mp, sqs (cloud), prefect (cloud), k8s (cloud).
              Cloud backends are stubs — only local works today.

    Returns:
        Coordinator instance.
    """
    if mode in {"asyncio", "async", "local"}:
        from rex.coordinator.local_async import LocalAsyncCoordinator
        return LocalAsyncCoordinator()

    if mode in {"mp", "multiprocess", "multiprocessing"}:
        from rex.coordinator.local_mp import LocalMultiprocessCoordinator
        return LocalMultiprocessCoordinator()

    if mode == "sqs":
        from rex.coordinator.cloud_sqs import SqsCoordinator
        return SqsCoordinator()

    if mode == "prefect":
        from rex.coordinator.cloud_prefect import PrefectCoordinator
        return PrefectCoordinator()

    if mode == "k8s":
        from rex.coordinator.cloud_k8s import K8sCoordinator
        return K8sCoordinator()

    raise ValueError(f"Unsupported coordinator mode: {mode}")
