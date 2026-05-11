"""Executor base class and the PlanRunner that drives them.

A CustomizationExecutor pairs an `apply` with a matching `revert`. The
PlanRunner instantiates one executor per plan entry, applies them in order,
and reverts them in reverse order on process termination. Per-executor
exceptions are caught — one failure must not abort the rest of the plan, and
must not abort revert.

Revert is idempotent at the runner level. SIGINT/SIGTERM and atexit both
funnel through `PlanRunner.revert_all`, which no-ops on a second call.

Note: SIGKILL (kill -9) and hard crashes will not run revert. That's the
"runtime overlay = approximate revert on crash" property documented in
ADR-0005.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


class CustomizationExecutor(abc.ABC):
    """Pair of apply/revert for one vocabulary entry.

    Subclasses must be safe to construct without side effects. All system
    mutation belongs in `apply`. `revert` must restore the pre-apply state
    as closely as possible; it MUST tolerate being called even when apply
    failed partway, so subclasses should guard with internal state flags
    (e.g. `self._installed = False` until apply has fully committed).
    """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abc.abstractmethod
    def apply(self, parameters: dict[str, Any]) -> None: ...

    @abc.abstractmethod
    def revert(self) -> None: ...


@dataclass
class _AppliedEntry:
    plan_entry_id: str
    executor: CustomizationExecutor
    parameters: dict[str, Any] = field(default_factory=dict)


class PlanRunner:
    """Apply a list of plan entries, then hold them for process lifetime."""

    def __init__(self, vocabulary: list[Any]) -> None:
        # vocabulary is list[VocabularyEntry] but we avoid the import here to
        # keep this module free of any executor-specific dependency.
        self._by_id = {e.id: e for e in vocabulary}
        self._applied: list[_AppliedEntry] = []
        self._reverted = False

    @property
    def applied(self) -> list[_AppliedEntry]:
        return list(self._applied)

    def apply_plan(self, plan: list[Any]) -> None:
        """Apply each entry in order. Failures are logged and skipped."""
        for entry in plan:
            vocab = self._by_id.get(entry.id)
            if vocab is None:
                logger.error("plan entry id not in vocabulary, skipping", id=entry.id)
                continue
            try:
                executor = vocab.executor_class()
            except Exception:
                logger.exception("executor construction failed", id=entry.id)
                continue
            try:
                executor.apply(entry.parameters)
            except Exception:
                logger.exception("apply failed", id=entry.id, params=entry.parameters)
                # Do not record an unrequited apply. The executor may have
                # partially mutated state; we still call revert as a best
                # effort to clean up.
                try:
                    executor.revert()
                except Exception:
                    logger.exception("partial revert after failed apply also failed", id=entry.id)
                continue
            self._applied.append(
                _AppliedEntry(plan_entry_id=entry.id, executor=executor, parameters=entry.parameters)
            )
            logger.info("applied", id=entry.id, params=entry.parameters)

    def revert_all(self) -> None:
        """Revert every applied executor in reverse order. Idempotent."""
        if self._reverted:
            return
        self._reverted = True
        logger.info("reverting all", count=len(self._applied))
        for entry in reversed(self._applied):
            try:
                entry.executor.revert()
                logger.info("reverted", id=entry.plan_entry_id)
            except Exception:
                logger.exception("revert failed", id=entry.plan_entry_id)
        self._applied.clear()
