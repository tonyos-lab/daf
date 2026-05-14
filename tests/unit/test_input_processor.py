"""
Unit tests for InputProcessor.

Coverage:
  - Happy path: valid request returns WorkflowRequest
  - Task validation: empty, non-string, too long
  - User/tenant ID sanitization: defaults, stripping, truncation
  - Constraints validation: max_cost_usd, max_duration_s
  - Intent classification: deterministic, llm, mixed
  - Context sanitization: valid values, non-serialisable dropped
  - Request ID uniqueness
  - Timestamp set to UTC now
"""
from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone

from daf.components.input_processor import (
    InputProcessor,
    InputValidationError,
    MAX_TASK_LENGTH,
    MAX_ID_LENGTH,
)
from daf.models.workflow_request import WorkflowRequest


# ── Fixture ───────────────────────────────────────────────────

def make_processor() -> InputProcessor:
    return InputProcessor(policy_engine=None)


# ── Happy Path ────────────────────────────────────────────────

class TestInputProcessorHappyPath:

    def test_minimal_valid_request(self):
        """Minimal request with only task field succeeds."""
        proc   = make_processor()
        result = proc.process({"task": "Analyse the contracts"})
        assert isinstance(result, WorkflowRequest)
        assert result.task_description == "Analyse the contracts"

    def test_returns_workflow_request(self):
        """process() returns a WorkflowRequest instance."""
        proc   = make_processor()
        result = proc.process({"task": "Test task"})
        assert isinstance(result, WorkflowRequest)

    def test_request_id_is_uuid(self):
        """Generated request_id is a valid UUID."""
        proc   = make_processor()
        result = proc.process({"task": "Test"})
        assert isinstance(result.request_id, uuid.UUID)

    def test_unique_request_ids(self):
        """Each call generates a unique request_id."""
        proc = make_processor()
        a    = proc.process({"task": "Test"})
        b    = proc.process({"task": "Test"})
        assert a.request_id != b.request_id

    def test_timestamp_is_utc_now(self):
        """Timestamp is set to current UTC time."""
        before = datetime.now(timezone.utc)
        proc   = make_processor()
        result = proc.process({"task": "Test"})
        after  = datetime.now(timezone.utc)
        assert before <= result.timestamp <= after

    def test_full_valid_request(self):
        """Full request with all optional fields."""
        proc   = make_processor()
        result = proc.process({
            "task":       "Summarise the Q3 reports",
            "user_id":    "alice@company.com",
            "tenant_id":  "acme-corp",
            "context":    {"project": "Q3 analysis", "year": 2026},
            "constraints": {"max_cost_usd": 0.50, "max_duration_s": 120},
        })
        assert result.task_description == "Summarise the Q3 reports"
        assert result.user_id          == "alice@company.com"
        assert result.tenant_id        == "acme-corp"
        assert result.context["project"] == "Q3 analysis"
        assert result.constraints["max_cost_usd"] == 0.50


# ── Task Validation ───────────────────────────────────────────

class TestInputProcessorTaskValidation:

    def test_empty_task_raises(self):
        """Empty task string raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": ""})
        assert exc.value.field == "task"
        assert "empty" in exc.value.reason.lower()

    def test_whitespace_only_task_raises(self):
        """Whitespace-only task raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "   \n\t  "})
        assert exc.value.field == "task"

    def test_missing_task_raises(self):
        """Missing task key raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({})
        assert exc.value.field == "task"

    def test_non_string_task_raises(self):
        """Non-string task raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": 42})
        assert exc.value.field == "task"
        assert "string" in exc.value.reason.lower()

    def test_task_too_long_raises(self):
        """Task exceeding MAX_TASK_LENGTH raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "x" * (MAX_TASK_LENGTH + 1)})
        assert exc.value.field == "task"
        assert "maximum" in exc.value.reason.lower()

    def test_task_at_max_length_accepted(self):
        """Task exactly at MAX_TASK_LENGTH is accepted."""
        proc   = make_processor()
        result = proc.process({"task": "x" * MAX_TASK_LENGTH})
        assert len(result.task_description) == MAX_TASK_LENGTH

    def test_task_is_stripped(self):
        """Leading/trailing whitespace is stripped from task."""
        proc   = make_processor()
        result = proc.process({"task": "  Analyse the contracts  "})
        assert result.task_description == "Analyse the contracts"

    def test_none_task_raises(self):
        """None task raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": None})
        assert exc.value.field == "task"


# ── ID Sanitization ───────────────────────────────────────────

class TestInputProcessorIDSanitization:

    def test_missing_user_id_defaults(self):
        """Missing user_id defaults to 'anonymous'."""
        proc   = make_processor()
        result = proc.process({"task": "Test"})
        assert result.user_id == "anonymous"

    def test_missing_tenant_id_defaults(self):
        """Missing tenant_id defaults to 'default'."""
        proc   = make_processor()
        result = proc.process({"task": "Test"})
        assert result.tenant_id == "default"

    def test_empty_user_id_defaults(self):
        """Empty user_id defaults to 'anonymous'."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "user_id": ""})
        assert result.user_id == "anonymous"

    def test_whitespace_user_id_defaults(self):
        """Whitespace-only user_id defaults to 'anonymous'."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "user_id": "   "})
        assert result.user_id == "anonymous"

    def test_user_id_stripped(self):
        """Leading/trailing whitespace stripped from user_id."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "user_id": "  alice  "})
        assert result.user_id == "alice"

    def test_user_id_truncated_if_too_long(self):
        """user_id longer than MAX_ID_LENGTH is truncated."""
        proc      = make_processor()
        long_id   = "a" * (MAX_ID_LENGTH + 50)
        result    = proc.process({"task": "Test", "user_id": long_id})
        assert len(result.user_id) == MAX_ID_LENGTH

    def test_non_string_user_id_defaults(self):
        """Non-string user_id defaults to 'anonymous'."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "user_id": 12345})
        assert result.user_id == "anonymous"

    def test_tenant_id_preserved(self):
        """Valid tenant_id is preserved."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "tenant_id": "acme-corp"})
        assert result.tenant_id == "acme-corp"


# ── Constraints Validation ────────────────────────────────────

class TestInputProcessorConstraints:

    def test_valid_constraints_passed_through(self):
        """Valid constraints are passed to WorkflowRequest."""
        proc   = make_processor()
        result = proc.process({
            "task": "Test",
            "constraints": {"max_cost_usd": 1.0, "max_duration_s": 300},
        })
        assert result.constraints["max_cost_usd"]  == 1.0
        assert result.constraints["max_duration_s"] == 300

    def test_missing_constraints_defaults_to_empty(self):
        """Missing constraints defaults to empty dict."""
        proc   = make_processor()
        result = proc.process({"task": "Test"})
        assert result.constraints == {}

    def test_zero_max_cost_raises(self):
        """max_cost_usd of 0 raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "Test", "constraints": {"max_cost_usd": 0}})
        assert "max_cost_usd" in exc.value.field

    def test_negative_max_cost_raises(self):
        """Negative max_cost_usd raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "Test", "constraints": {"max_cost_usd": -1.0}})
        assert "max_cost_usd" in exc.value.field

    def test_non_number_max_cost_raises(self):
        """Non-numeric max_cost_usd raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "Test",
                          "constraints": {"max_cost_usd": "expensive"}})
        assert "max_cost_usd" in exc.value.field

    def test_zero_max_duration_raises(self):
        """max_duration_s of 0 raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "Test", "constraints": {"max_duration_s": 0}})
        assert "max_duration_s" in exc.value.field

    def test_positive_max_duration_accepted(self):
        """Positive max_duration_s is accepted."""
        proc   = make_processor()
        result = proc.process({
            "task": "Test",
            "constraints": {"max_duration_s": 60},
        })
        assert result.constraints["max_duration_s"] == 60

    def test_non_dict_constraints_raises(self):
        """Non-dict constraints raises InputValidationError."""
        proc = make_processor()
        with pytest.raises(InputValidationError) as exc:
            proc.process({"task": "Test", "constraints": "expensive"})
        assert exc.value.field == "constraints"

    def test_extra_constraint_keys_passed_through(self):
        """Unknown constraint keys are passed through unchanged."""
        proc   = make_processor()
        result = proc.process({
            "task": "Test",
            "constraints": {"max_cost_usd": 0.50, "output_format": "json"},
        })
        assert result.constraints["output_format"] == "json"


# ── Intent Classification ─────────────────────────────────────

class TestInputProcessorIntentClassification:

    def test_explicit_intent_class_respected(self):
        """Explicitly provided intent_class is used without classification."""
        proc   = make_processor()
        result = proc.process({
            "task": "Analyse the data",
            "intent_class": "deterministic",
        })
        assert result.intent_class == "deterministic"

    def test_llm_keywords_classify_as_llm(self):
        """Task with LLM keywords is classified as 'llm'."""
        proc = make_processor()
        for task in [
            "Summarise the quarterly reports",
            "Analyse the contract and identify risks",
            "Write a report on the findings",
            "Generate a summary of the documents",
        ]:
            result = proc.process({"task": task})
            assert result.intent_class == "llm", \
                f"Expected 'llm' for task: {task!r}, got {result.intent_class!r}"

    def test_deterministic_keywords_classify_as_deterministic(self):
        """Task with deterministic keywords is classified as 'deterministic'."""
        proc = make_processor()
        for task in [
            "Count the number of records in the database",
            "List all contracts from 2025",
            "Get the total revenue for Q3",
            "Find all documents tagged as urgent",
        ]:
            result = proc.process({"task": task})
            assert result.intent_class == "deterministic", \
                f"Expected 'deterministic' for task: {task!r}"

    def test_ambiguous_task_classified_as_mixed(self):
        """Task with both or neither keyword types is 'mixed'."""
        proc   = make_processor()
        result = proc.process({"task": "Process the workflow efficiently"})
        assert result.intent_class == "mixed"

    def test_default_intent_is_mixed(self):
        """Default intent class when no keywords match is 'mixed'."""
        proc   = make_processor()
        result = proc.process({"task": "Do the thing"})
        assert result.intent_class == "mixed"


# ── Context Sanitization ──────────────────────────────────────

class TestInputProcessorContextSanitization:

    def test_valid_context_preserved(self):
        """Valid context values are preserved."""
        proc   = make_processor()
        result = proc.process({
            "task": "Test",
            "context": {
                "project": "Q3",
                "year":    2026,
                "active":  True,
                "tags":    ["urgent", "finance"],
            },
        })
        assert result.context["project"] == "Q3"
        assert result.context["year"]    == 2026
        assert result.context["active"]  is True
        assert result.context["tags"]    == ["urgent", "finance"]

    def test_non_serialisable_context_values_dropped(self):
        """Non-serialisable values (functions, objects) are dropped."""
        proc   = make_processor()
        result = proc.process({
            "task": "Test",
            "context": {
                "valid":   "kept",
                "invalid": lambda x: x,   # function — not serialisable
            },
        })
        assert "valid"   in result.context
        assert "invalid" not in result.context

    def test_non_dict_context_defaults_to_empty(self):
        """Non-dict context defaults to empty dict."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "context": "not a dict"})
        assert result.context == {}

    def test_missing_context_defaults_to_empty(self):
        """Missing context defaults to empty dict."""
        proc   = make_processor()
        result = proc.process({"task": "Test"})
        assert result.context == {}

    def test_none_context_defaults_to_empty(self):
        """None context defaults to empty dict."""
        proc   = make_processor()
        result = proc.process({"task": "Test", "context": None})
        assert result.context == {}


# ── InputValidationError ──────────────────────────────────────

class TestInputValidationError:

    def test_error_stores_field_and_reason(self):
        err = InputValidationError("task", "must not be empty")
        assert err.field  == "task"
        assert err.reason == "must not be empty"

    def test_error_message_includes_field_and_reason(self):
        err = InputValidationError("task", "must not be empty")
        assert "task"  in str(err)
        assert "empty" in str(err)

    def test_error_is_exception(self):
        assert issubclass(InputValidationError, Exception)
