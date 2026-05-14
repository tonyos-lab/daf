"""
HumanReviewGateway — pluggable mechanism for HITL notifications.

EvaluateStage calls BaseHumanReviewGateway.request_and_wait().
The gateway handles how the review request reaches the human
and how the response returns to DAF.

IMPLEMENTATIONS:
  StubHumanReviewGateway:  unit tests — returns configurable response
  CLIHumanReviewGateway:   development — prints to terminal, waits for input
  WebhookHumanReviewGateway: production (Phase 3) — HTTP POST + polling

PLUGGABILITY:
  Organizations provide their own gateway by inheriting from
  BaseHumanReviewGateway. The gateway knows how to reach the
  reviewer (email, Slack, admin dashboard, etc.).
  EvaluateStage does not care how — it just calls request_and_wait().
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from daf.models.human_review import (
    HumanReviewRequest,
    HumanReviewResponse,
    TaskDecision,
)

logger = logging.getLogger(__name__)


# ── Abstract interface ───────────────────────────────────────

class BaseHumanReviewGateway(ABC):
    """
    Abstract interface for HITL review delivery and collection.

    EvaluateStage calls request_and_wait() with a HumanReviewRequest
    and receives a HumanReviewResponse.

    The gateway is responsible for:
    - Delivering the request to the reviewer
    - Waiting for their response (up to timeout)
    - Returning HumanReviewResponse.timeout_response() on timeout
    """

    @abstractmethod
    async def request_and_wait(
        self,
        request: HumanReviewRequest,
    ) -> HumanReviewResponse:
        """
        Send a review request and wait for a human response.

        On timeout: return HumanReviewResponse.timeout_response()
        Never raise — always return a HumanReviewResponse.

        Args:
            request: The HumanReviewRequest to send

        Returns:
            HumanReviewResponse with decisions for all gated tasks
        """
        ...


# ── StubHumanReviewGateway ───────────────────────────────────

class StubHumanReviewGateway(BaseHumanReviewGateway):
    """
    Stub gateway for unit tests.

    Returns a configurable response without any I/O.
    Records all requests for test inspection.

    USAGE:
        # Always approves
        gateway = StubHumanReviewGateway(approve_all=True)

        # Always rejects
        gateway = StubHumanReviewGateway(approve_all=False)

        # Simulates timeout
        gateway = StubHumanReviewGateway(simulate_timeout=True)

        # Custom response per call
        gateway = StubHumanReviewGateway()
        gateway.set_next_response(my_response)
    """

    def __init__(
        self,
        approve_all:      bool = True,
        simulate_timeout: bool = False,
        reviewer_id:      str  = "stub:reviewer",
    ) -> None:
        self._approve_all      = approve_all
        self._simulate_timeout = simulate_timeout
        self._reviewer_id      = reviewer_id
        self._next_response:   HumanReviewResponse | None = None
        self.requests:         list[HumanReviewRequest] = []

    def set_next_response(
        self,
        response: HumanReviewResponse,
    ) -> None:
        """Set a specific response to return on the next call."""
        self._next_response = response

    async def request_and_wait(
        self,
        request: HumanReviewRequest,
    ) -> HumanReviewResponse:
        """Return configured response without any I/O."""
        self.requests.append(request)

        # Use custom response if set
        if self._next_response is not None:
            resp = self._next_response
            self._next_response = None
            return resp

        if self._simulate_timeout:
            return HumanReviewResponse.timeout_response(
                review_id=request.review_id,
                grant_id=request.grant_id,
                task_ids=request.gated_task_ids,
            )

        if self._approve_all:
            return HumanReviewResponse.approved_all(
                review_id=request.review_id,
                grant_id=request.grant_id,
                reviewer_id=self._reviewer_id,
                task_ids=request.gated_task_ids,
            )
        else:
            return HumanReviewResponse.rejected_all(
                review_id=request.review_id,
                grant_id=request.grant_id,
                reviewer_id=self._reviewer_id,
                task_ids=request.gated_task_ids,
                reason="StubGateway configured to reject",
            )

    def reset(self) -> None:
        """Clear request history."""
        self.requests.clear()
        self._next_response = None

    def __repr__(self) -> str:
        return (
            f"StubHumanReviewGateway("
            f"approve_all={self._approve_all}, "
            f"requests={len(self.requests)})"
        )


# ── CLIHumanReviewGateway ────────────────────────────────────

class CLIHumanReviewGateway(BaseHumanReviewGateway):
    """
    CLI-based gateway for development and testing.

    Prints the review request to stdout and waits for keyboard input.
    Input timeout is enforced via asyncio.

    NOT for production use — blocking I/O on the event loop.
    Use WebhookHumanReviewGateway in production (Phase 3).
    """

    async def request_and_wait(
        self,
        request: HumanReviewRequest,
    ) -> HumanReviewResponse:
        """Print request to terminal and wait for user input."""
        self._print_request(request)

        try:
            # Calculate seconds until expiry
            from datetime import datetime, timezone
            now            = datetime.now(timezone.utc)
            seconds_left   = max(
                1.0,
                (request.expires_at - now).total_seconds()
            )

            response = await asyncio.wait_for(
                self._collect_input(request),
                timeout=seconds_left,
            )
            return response

        except asyncio.TimeoutError:
            print("\n[DAF] Review request timed out. Auto-rejecting all tasks.")
            return HumanReviewResponse.timeout_response(
                review_id=request.review_id,
                grant_id=request.grant_id,
                task_ids=request.gated_task_ids,
            )

    def _print_request(self, request: HumanReviewRequest) -> None:
        """Print the review request in a readable format."""
        print("\n" + "═" * 60)
        print("  DAF — HUMAN REVIEW REQUIRED")
        print("═" * 60)
        print(f"  Workflow: {request.workflow_task[:80]}")
        print(f"  Review ID: {request.review_id}")
        print(f"  Requested by: {request.user_id}")
        print(f"  Expires: {request.expires_at.strftime('%H:%M:%S UTC')}")
        print()
        print(f"  {request.task_count} task(s) require your approval:")
        print()

        for i, task in enumerate(request.gated_tasks, 1):
            print(f"  [{i}] Task: {task.task_id} — {task.task_name}")
            print(f"      Action: {task.action_class}")
            print(f"      Impact: {task.estimated_impact}")
            print(f"      Reversible: {'Yes' if task.reversible else 'No'}")
            print(f"      Gate reason: {task.gate_reason}")
            print()

        print("═" * 60)

    async def _collect_input(
        self,
        request: HumanReviewRequest,
    ) -> HumanReviewResponse:
        """Collect approval/rejection input from the terminal."""
        decisions = []
        reviewer  = input("  Your name/ID: ").strip() or "cli:reviewer"
        print()

        for task in request.gated_tasks:
            while True:
                answer = input(
                    f"  Approve task {task.task_id} "
                    f"({task.action_class})? [y/n]: "
                ).strip().lower()
                if answer in ("y", "yes", "n", "no"):
                    break
                print("  Please enter y or n")

            is_approved = answer in ("y", "yes")
            reason      = ""
            if not is_approved:
                reason = input(
                    f"  Reason for rejecting {task.task_id}: "
                ).strip()

            decisions.append(TaskDecision(
                task_id=task.task_id,
                decision="approved" if is_approved else "rejected",
                reason=reason,
            ))

        notes = input("\n  Any overall notes? (Enter to skip): ").strip()
        print("═" * 60 + "\n")

        return HumanReviewResponse(
            review_id=request.review_id,
            grant_id=request.grant_id,
            reviewer_id=reviewer,
            task_decisions=decisions,
            notes=notes,
        )
