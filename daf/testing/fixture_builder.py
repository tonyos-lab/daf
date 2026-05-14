"""
FixturePlanBuilder — fluent builder for valid PlanProposal dicts.

Constructs the exact JSON structure that PlanningOrchestrator
returns from the LLM — the same structure MockLLMClient returns.

Without this helper, developers would need to know the exact
schema fields, types, and required keys. This makes it discoverable.

USAGE:

  from daf.testing import FixturePlanBuilder

  # Single task
  plan = FixturePlanBuilder()\\
      .with_task("ST-01", agent="analyst", tools=["read_db"])\\
      .build()

  # Multiple tasks with dependencies
  plan = FixturePlanBuilder()\\
      .with_task("ST-01", agent="reader", tools=["read_db"])\\
      .with_task("ST-02", agent="analyst", tools=["llm_extraction"],
                 depends_on=["ST-01"])\\
      .with_task("ST-03", agent="writer", tools=["llm_generation"],
                 depends_on=["ST-02"], task_type="llm_generation",
                 reversible=False)\\
      .with_rationale("Read documents, extract features, generate report")\\
      .with_confidence(0.92)\\
      .build()

  # Use with MockLLMClient
  client = MockLLMClient(responses=[plan])

VALID task_type values:
  "deterministic"       — no LLM calls, pure computation
  "llm_classification"  — classify input into categories
  "llm_extraction"      — extract structured data from text
  "llm_summarization"   — summarise content
  "llm_transformation"  — transform content format
  "llm_generation"      — generate new content
  "llm_evaluation"      — evaluate or score content
"""
from __future__ import annotations

from typing import Any


# Valid task types — matches PlanningOrchestrator schema
VALID_TASK_TYPES = frozenset({
    "deterministic",
    "llm_classification",
    "llm_extraction",
    "llm_summarization",
    "llm_transformation",
    "llm_generation",
    "llm_evaluation",
})


class _TaskSpec:
    """Internal representation of one sub-task."""

    def __init__(
        self,
        task_id:        str,
        agent:          str,
        tools:          list[str],
        task_type:      str         = "llm_extraction",
        data_sources:   list[str]   = None,
        depends_on:     list[str]   = None,
        estimated_cost: float       = 0.02,
        reversible:     bool        = True,
        rationale:      str         = "",
        name:           str         = "",
    ) -> None:
        self.task_id        = task_id
        self.agent          = agent
        self.tools          = tools
        self.task_type      = task_type
        self.data_sources   = data_sources or []
        self.depends_on     = depends_on or []
        self.estimated_cost = estimated_cost
        self.reversible     = reversible
        self.rationale      = rationale or f"Execute {task_type} using {', '.join(tools) or 'no tools'}"
        self.name           = name or task_id.lower().replace("-", "_")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id":        self.task_id,
            "name":           self.name,
            "task_type":      self.task_type,
            "agent_required": self.agent,
            "tools_required": self.tools,
            "data_required":  self.data_sources,
            "depends_on":     self.depends_on,
            "estimated_cost": self.estimated_cost,
            "reversible":     self.reversible,
            "rationale":      self.rationale,
        }


class FixturePlanBuilder:
    """
    Fluent builder for PlanProposal dicts.

    Produces the exact dict structure that MockLLMClient
    returns to PlanningOrchestrator.

    Call .build() to get the final dict.
    Each method returns self for chaining.
    """

    def __init__(self) -> None:
        self._tasks:              list[_TaskSpec] = []
        self._orchestrator:       str   = "default_orchestrator"
        self._rationale:          str   = "Auto-generated test plan"
        self._confidence:         float = 0.90
        self._requires_human_gate: bool  = False

    def with_task(
        self,
        task_id:        str,
        agent:          str,
        tools:          list[str],
        task_type:      str         = "llm_extraction",
        data_sources:   list[str]   = None,
        depends_on:     list[str]   = None,
        estimated_cost: float       = 0.02,
        reversible:     bool        = True,
        rationale:      str         = "",
        name:           str         = "",
    ) -> FixturePlanBuilder:
        """
        Add a sub-task to the plan.

        Args:
            task_id:        Unique ID (e.g. "ST-01"). Must be unique in the plan.
            agent:          Agent role name. Must exist in your AgentRegistry.
            tools:          Tools this agent needs. Must be in PolicyMatrix permissions.
            task_type:      One of VALID_TASK_TYPES. Default: "llm_extraction".
            data_sources:   Data sources this task needs. Default: [].
            depends_on:     task_ids that must complete before this one. Default: [].
            estimated_cost: Estimated USD cost. Default: 0.02.
            reversible:     Whether this action can be undone. Default: True.
            rationale:      Why this task is needed. Auto-generated if not provided.
            name:           Display name. Derived from task_id if not provided.

        Returns:
            self (for chaining)

        Raises:
            ValueError: task_id already exists in the plan
            ValueError: task_type is not a valid value
        """
        if any(t.task_id == task_id for t in self._tasks):
            raise ValueError(
                f"task_id '{task_id}' already exists in this plan. "
                f"Each task must have a unique task_id."
            )
        if task_type not in VALID_TASK_TYPES:
            raise ValueError(
                f"task_type '{task_type}' is not valid. "
                f"Choose from: {sorted(VALID_TASK_TYPES)}"
            )

        self._tasks.append(_TaskSpec(
            task_id=task_id,
            agent=agent,
            tools=tools,
            task_type=task_type,
            data_sources=data_sources or [],
            depends_on=depends_on or [],
            estimated_cost=estimated_cost,
            reversible=reversible,
            rationale=rationale,
            name=name,
        ))
        return self

    def with_rationale(self, rationale: str) -> FixturePlanBuilder:
        """Set the overall planning rationale. Default: 'Auto-generated test plan'."""
        self._rationale = rationale
        return self

    def with_confidence(self, confidence: float) -> FixturePlanBuilder:
        """
        Set the plan confidence score (0.0–1.0). Default: 0.90.
        Affects risk evaluation for irreversible tasks.
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {confidence}"
            )
        self._confidence = confidence
        return self

    def with_orchestrator(self, orchestrator: str) -> FixturePlanBuilder:
        """Set the orchestrator name. Default: 'default_orchestrator'."""
        self._orchestrator = orchestrator
        return self

    def with_human_gate(self, required: bool = True) -> FixturePlanBuilder:
        """Mark that this plan requires a human gate. Default: False."""
        self._requires_human_gate = required
        return self

    def build(self) -> dict[str, Any]:
        """
        Build and return the PlanProposal dict.

        The returned dict matches the exact schema that
        PlanningOrchestrator parses from LLM responses.
        Pass it to MockLLMClient(responses=[plan]).

        Raises:
            ValueError: if no tasks have been added
            ValueError: if a depends_on references an unknown task_id
        """
        if not self._tasks:
            raise ValueError(
                "Plan has no tasks. "
                "Call .with_task() at least once before .build()."
            )

        # Validate depends_on references
        known_ids = {t.task_id for t in self._tasks}
        for task in self._tasks:
            for dep in task.depends_on:
                if dep not in known_ids:
                    raise ValueError(
                        f"Task '{task.task_id}' depends_on '{dep}' "
                        f"but '{dep}' is not in this plan. "
                        f"Known task IDs: {sorted(known_ids)}"
                    )

        total_cost = sum(t.estimated_cost for t in self._tasks)

        return {
            "orchestrator":       self._orchestrator,
            "planning_rationale": self._rationale,
            "sub_tasks":          [t.to_dict() for t in self._tasks],
            "total_estimated_cost": round(total_cost, 6),
            "confidence":         self._confidence,
            "requires_human_gate": self._requires_human_gate,
        }

    def __repr__(self) -> str:
        return (
            f"FixturePlanBuilder("
            f"tasks={[t.task_id for t in self._tasks]})"
        )
