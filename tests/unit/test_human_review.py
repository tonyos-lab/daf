"""
Unit tests for HumanReview models.

Coverage:
  - GatedTaskDetail construction
  - HumanReviewRequest.create() with expiry
  - HumanReviewRequest properties (is_expired, gated_task_ids, task_count)
  - TaskDecision is_approved / is_rejected
  - HumanReviewResponse convenience constructors
  - HumanReviewResponse convenience methods
  - HumanReviewResponse immutability
  - Timeout auto-reject response
  - Mixed approval/rejection scenarios
"""
from __future__ import annotations

import uuid
import time
import pytest
from datetime import datetime, timezone

from daf.models.human_review import (
    GatedTaskDetail,
    HumanReviewRequest,
    HumanReviewResponse,
    TaskDecision,
)


# ── Fixtures ─────────────────────────────────────────────────

def make_gated_task(
    task_id:   str = "ST-03",
    action:    str = "send_email",
    reversible: bool = False,
) -> GatedTaskDetail:
    return GatedTaskDetail(
        task_id=task_id,
        task_name=f"Task {task_id}",
        action_class=action,
        gate_reason="Action class in always_gate_action_classes",
        risk_rationale="Irreversible action with external effect",
        reversible=reversible,
        estimated_impact=f"Will send email to client — cannot be undone",
        estimated_cost=0.01,
    )


def make_review_request(
    task_ids:        list[str] | None = None,
    timeout_seconds: float = 3600.0,
) -> HumanReviewRequest:
    tasks = [make_gated_task(tid) for tid in (task_ids or ["ST-03"])]
    return HumanReviewRequest.create(
        grant_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        tenant_id="test-tenant",
        user_id="test-user",
        gated_tasks=tasks,
        timeout_seconds=timeout_seconds,
        workflow_task="Analyse contracts and send report",
    )


# ── GatedTaskDetail ──────────────────────────────────────────

class TestGatedTaskDetail:

    def test_construction(self):
        """GatedTaskDetail constructs with required fields."""
        task = make_gated_task("ST-03", "send_email", reversible=False)
        assert task.task_id == "ST-03"
        assert task.action_class == "send_email"
        assert task.reversible is False

    def test_default_estimated_cost_is_zero(self):
        """estimated_cost defaults to 0.0."""
        task = GatedTaskDetail(
            task_id="ST-01",
            task_name="Read file",
            action_class="read_file",
            gate_reason="manual gate",
            risk_rationale="sensitive data",
            reversible=True,
            estimated_impact="Reads the file",
        )
        assert task.estimated_cost == 0.0

    def test_reversible_true(self):
        """Reversible task is marked correctly."""
        task = make_gated_task(reversible=True)
        assert task.reversible is True


# ── HumanReviewRequest ───────────────────────────────────────

class TestHumanReviewRequest:

    def test_create_sets_review_id(self):
        """create() generates a unique review_id."""
        req_a = make_review_request()
        req_b = make_review_request()
        assert req_a.review_id != req_b.review_id

    def test_create_sets_requested_at(self):
        """create() sets requested_at to current UTC time."""
        before = datetime.now(timezone.utc)
        req    = make_review_request()
        after  = datetime.now(timezone.utc)
        assert before <= req.requested_at <= after

    def test_create_sets_expires_at(self):
        """create() sets expires_at = requested_at + timeout_seconds."""
        req = make_review_request(timeout_seconds=1800)
        delta = (req.expires_at - req.requested_at).total_seconds()
        assert abs(delta - 1800) < 1.0  # within 1 second

    def test_create_stores_all_gated_tasks(self):
        """All gated tasks are stored in the request."""
        req = make_review_request(task_ids=["ST-03", "ST-05", "ST-07"])
        assert len(req.gated_tasks) == 3
        ids = [t.task_id for t in req.gated_tasks]
        assert "ST-03" in ids
        assert "ST-05" in ids
        assert "ST-07" in ids

    def test_gated_task_ids_property(self):
        """gated_task_ids returns list of task_id strings."""
        req = make_review_request(task_ids=["ST-03", "ST-05"])
        ids = req.gated_task_ids
        assert ids == ["ST-03", "ST-05"]

    def test_task_count_property(self):
        """task_count returns number of gated tasks."""
        req = make_review_request(task_ids=["ST-03", "ST-05", "ST-07"])
        assert req.task_count == 3

    def test_is_expired_false_for_future_expiry(self):
        """is_expired is False when expires_at is in the future."""
        req = make_review_request(timeout_seconds=3600)
        assert req.is_expired is False

    def test_is_expired_true_for_past_expiry(self):
        """is_expired is True when expires_at is in the past."""
        req = make_review_request(timeout_seconds=0.001)
        time.sleep(0.01)  # wait for expiry
        assert req.is_expired is True

    def test_workflow_task_stored(self):
        """workflow_task is accessible on the request."""
        req = make_review_request()
        assert req.workflow_task == "Analyse contracts and send report"

    def test_tenant_and_user_ids_stored(self):
        """tenant_id and user_id are stored on the request."""
        assert make_review_request().tenant_id == "test-tenant"
        assert make_review_request().user_id == "test-user"


# ── TaskDecision ─────────────────────────────────────────────

class TestTaskDecision:

    def test_approved_decision(self):
        """is_approved and is_rejected work correctly for approved."""
        d = TaskDecision(task_id="ST-03", decision="approved")
        assert d.is_approved is True
        assert d.is_rejected is False

    def test_rejected_decision(self):
        """is_approved and is_rejected work correctly for rejected."""
        d = TaskDecision(task_id="ST-03", decision="rejected")
        assert d.is_approved is False
        assert d.is_rejected is True

    def test_reason_optional(self):
        """reason defaults to empty string."""
        d = TaskDecision(task_id="ST-03", decision="approved")
        assert d.reason == ""

    def test_reason_stored(self):
        """reason is stored when provided."""
        d = TaskDecision(
            task_id="ST-03",
            decision="rejected",
            reason="Recipient not in approved list"
        )
        assert d.reason == "Recipient not in approved list"


# ── HumanReviewResponse ──────────────────────────────────────

class TestHumanReviewResponse:

    def test_approved_all_constructor(self):
        """approved_all() creates response with all tasks approved."""
        review_id = uuid.uuid4()
        grant_id  = uuid.uuid4()
        resp = HumanReviewResponse.approved_all(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id="alice@company.com",
            task_ids=["ST-03", "ST-05"],
        )
        assert resp.is_fully_approved() is True
        assert resp.has_rejections() is False
        assert resp.approved_task_ids() == ["ST-03", "ST-05"]
        assert resp.rejected_task_ids() == []

    def test_rejected_all_constructor(self):
        """rejected_all() creates response with all tasks rejected."""
        review_id = uuid.uuid4()
        grant_id  = uuid.uuid4()
        resp = HumanReviewResponse.rejected_all(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id="alice@company.com",
            task_ids=["ST-03", "ST-05"],
            reason="Data not verified",
        )
        assert resp.is_fully_approved() is False
        assert resp.has_rejections() is True
        assert resp.rejected_task_ids() == ["ST-03", "ST-05"]
        assert resp.approved_task_ids() == []

        # Verify reason is stored on each decision
        for d in resp.task_decisions:
            assert d.reason == "Data not verified"

    def test_timeout_response_constructor(self):
        """timeout_response() creates auto-reject with timed_out=True."""
        review_id = uuid.uuid4()
        grant_id  = uuid.uuid4()
        resp = HumanReviewResponse.timeout_response(
            review_id=review_id,
            grant_id=grant_id,
            task_ids=["ST-03"],
        )
        assert resp.timed_out is True
        assert resp.reviewer_id == "system:timeout"
        assert resp.is_fully_approved() is False
        assert resp.has_rejections() is True
        assert "timed out" in resp.task_decisions[0].reason.lower()

    def test_mixed_decisions(self):
        """Response can have mixed approved/rejected decisions."""
        review_id = uuid.uuid4()
        grant_id  = uuid.uuid4()
        resp = HumanReviewResponse(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id="alice@company.com",
            task_decisions=[
                TaskDecision(task_id="ST-03", decision="approved"),
                TaskDecision(task_id="ST-05", decision="rejected",
                             reason="Not authorised for this recipient"),
            ],
        )
        assert resp.is_fully_approved() is False
        assert resp.has_rejections() is True
        assert resp.approved_task_ids() == ["ST-03"]
        assert resp.rejected_task_ids() == ["ST-05"]

    def test_decision_for_returns_correct_decision(self):
        """decision_for() returns the decision for a specific task_id."""
        review_id = uuid.uuid4()
        grant_id  = uuid.uuid4()
        resp = HumanReviewResponse.approved_all(
            review_id=review_id,
            grant_id=grant_id,
            reviewer_id="alice",
            task_ids=["ST-03", "ST-05"],
        )
        d = resp.decision_for("ST-03")
        assert d is not None
        assert d.task_id == "ST-03"
        assert d.is_approved is True

    def test_decision_for_returns_none_for_unknown_task(self):
        """decision_for() returns None for task not in response."""
        resp = HumanReviewResponse.approved_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
        )
        assert resp.decision_for("ST-99") is None

    def test_response_is_immutable(self):
        """HumanReviewResponse is frozen — cannot be modified."""
        resp = HumanReviewResponse.approved_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
        )
        with pytest.raises(Exception):
            resp.reviewer_id = "bob"  # type: ignore

    def test_responded_at_set_to_now(self):
        """responded_at is set to current UTC time."""
        before = datetime.now(timezone.utc)
        resp   = HumanReviewResponse.approved_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
        )
        after = datetime.now(timezone.utc)
        assert before <= resp.responded_at <= after

    def test_notes_default_empty(self):
        """notes defaults to empty string."""
        resp = HumanReviewResponse.approved_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
        )
        assert resp.notes == ""

    def test_notes_stored(self):
        """notes is stored when provided."""
        resp = HumanReviewResponse.approved_all(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_ids=["ST-03"],
            notes="Verified with compliance team",
        )
        assert resp.notes == "Verified with compliance team"

    def test_empty_task_decisions_is_fully_approved(self):
        """is_fully_approved is True when task_decisions is empty (vacuous truth)."""
        resp = HumanReviewResponse(
            review_id=uuid.uuid4(),
            grant_id=uuid.uuid4(),
            reviewer_id="alice",
            task_decisions=[],
        )
        assert resp.is_fully_approved() is True
        assert resp.has_rejections() is False


# ── Integration: Request + Response ──────────────────────────

class TestHumanReviewRequestResponseIntegration:
    """
    Test the full request → response flow.
    Simulates what EvaluateStage will do in Step 13.
    """

    def test_response_review_id_matches_request(self):
        """Response review_id matches the request it responds to."""
        req  = make_review_request(task_ids=["ST-03", "ST-05"])
        resp = HumanReviewResponse.approved_all(
            review_id=req.review_id,
            grant_id=req.grant_id,
            reviewer_id="alice@company.com",
            task_ids=req.gated_task_ids,
        )
        assert resp.review_id == req.review_id
        assert resp.grant_id  == req.grant_id

    def test_all_requested_tasks_have_decisions(self):
        """Every gated task in the request has a decision in the response."""
        req  = make_review_request(task_ids=["ST-03", "ST-05", "ST-07"])
        resp = HumanReviewResponse.approved_all(
            review_id=req.review_id,
            grant_id=req.grant_id,
            reviewer_id="alice",
            task_ids=req.gated_task_ids,
        )
        for task_id in req.gated_task_ids:
            assert resp.decision_for(task_id) is not None

    def test_timeout_scenario(self):
        """
        Simulate the timeout scenario:
        Request expires → auto-reject response generated.
        """
        req = make_review_request(timeout_seconds=0.001)
        time.sleep(0.01)  # ensure expiry

        assert req.is_expired is True

        # EvaluateStage generates auto-reject on timeout
        resp = HumanReviewResponse.timeout_response(
            review_id=req.review_id,
            grant_id=req.grant_id,
            task_ids=req.gated_task_ids,
        )

        assert resp.timed_out is True
        assert resp.has_rejections() is True
        assert resp.is_fully_approved() is False
