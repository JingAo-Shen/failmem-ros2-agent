"""
Unified Knowledge View Architecture for Fair Knowledge Input Across All Agent Arms.

Ensures strict parity:
- Symmetrical facts visible to B2, B2-G, and M.
- Symmetrical conditional rules visible to B2, B2-G, and M.
- Identical evidence provenance, support counts, and uncertainty disclaimers.
- Identical observation freshness threshold (TTL = 30.0s).

Execution Semantics:
- B2: Visible knowledge rendered in prompt; NO gate interception (autonomous LLM reasoning).
- B2-G: Visible knowledge rendered in prompt; generic predicate gating on rules (BLOCK if APPLICABLE, PROBE if UNKNOWN).
- M: Visible knowledge rendered in prompt; candidate lifecycle gating (probationary trial if CANDIDATE, updates state on outcome).
"""

import time
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path

from .constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    ConstraintLifecycleManager,
    FrozenMemorySnapshot,
)
from .memory_pipeline import StructuredFact


@dataclass
class UnifiedKnowledgeView:
    facts: List[StructuredFact] = field(default_factory=list)
    rules: List[ConstraintRule] = field(default_factory=list)
    freshness_ttl_s: float = 30.0

    @classmethod
    def from_manager_and_facts(
        cls,
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
        facts: Optional[List[StructuredFact]] = None,
        freshness_ttl_s: float = 30.0,
    ) -> "UnifiedKnowledgeView":
        """Builds a UnifiedKnowledgeView from lifecycle manager and facts."""
        rule_list = list(lifecycle_manager.rules.values()) if lifecycle_manager else []
        fact_list = list(facts) if facts else []
        return cls(facts=fact_list, rules=rule_list, freshness_ttl_s=freshness_ttl_s)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: FrozenMemorySnapshot,
        freshness_ttl_s: float = 30.0,
    ) -> "UnifiedKnowledgeView":
        """Builds a UnifiedKnowledgeView directly from FrozenMemorySnapshot."""
        mgr = snapshot.instantiate_manager()
        facts = snapshot.instantiate_facts()
        return cls.from_manager_and_facts(lifecycle_manager=mgr, facts=facts, freshness_ttl_s=freshness_ttl_s)

    def render_knowledge_text(
        self,
        current_time: Optional[float] = None,
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
    ) -> str:
        """
        Renders the canonical, deterministic knowledge string.
        Output is guaranteed character-for-character identical across B2, B2-G, and M
        when given identical initial memory states.
        """
        now = current_time if current_time is not None else time.time()
        sections: List[str] = []

        # 1. Freshness & Epistemic Disclaimer
        sections.append("### Memory Freshness & Observation Policy:")
        sections.append(
            f"- Observation TTL: {self.freshness_ttl_s:.1f}s. "
            "Facts older than TTL are UNCONFIRMED_EXPIRED and must be re-probed prior to critical actions."
        )

        # 2. Known Environment Facts
        if self.facts:
            fact_lines = []
            for f in sorted(self.facts, key=lambda x: x.fact_id):
                age = max(0.0, now - f.timestamp)
                freshness = "ACTIVE" if age <= self.freshness_ttl_s else "UNCONFIRMED_EXPIRED"
                fact_lines.append(
                    f"- Fact [{f.fact_id}] ({freshness}): Resource '{f.resource}' -> {f.state_description}. "
                    f"[Evidence: {f.evidence_id}, Source: {f.run_id} step {f.step}, Age: {age:.1f}s]"
                )
            sections.append("### Known Environment Facts:\n" + "\n".join(fact_lines))
        else:
            sections.append("### Known Environment Facts:\n- No environment facts available.")

        # 3. Conditional Constraint Rules
        if self.rules:
            rule_lines = []
            for r in sorted(self.rules, key=lambda x: x.rule_id):
                if lifecycle_manager:
                    app = lifecycle_manager.evaluate_applicability(r)
                else:
                    app = ApplicabilityState.UNKNOWN

                pred_desc = " AND ".join(
                    [f"{p.key} == {p.expected_value}" for p in r.predicates]
                ) if r.predicates else "None"
                err_type = r.failure_evidence.get("error_type", "ExecutionError")
                err_code = r.failure_evidence.get("error_code", r.failure_evidence.get("exit_code", 1))

                rule_lines.append(
                    f"- Rule [{r.rule_id}]: IF [{pred_desc}] THEN action '{r.action_signature}' fails with {err_type} (code {err_code}).\n"
                    f"  Status: Validity={r.validity_state.value}, Applicability={app.value}.\n"
                    f"  Provenance: SupportCount={r.support_count}, Contradictions={r.contradict_count}, Evidence={sorted(list(set(r.evidence_ids)))}."
                )
            sections.append("### Active Conditional Constraint Rules:\n" + "\n".join(rule_lines))
        else:
            sections.append("### Active Conditional Constraint Rules:\n- No active constraint rules.")

        return "\n\n".join(sections)
