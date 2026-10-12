"""
Test suite validating KnowledgeView symmetry across B2, B2-G, and M.
Asserts that initial visible knowledge prompts are character-for-character identical.
Exports the actual rendered initial prompts to results/prompt_knowledge_snapshot.json.
"""

import json
import time
from pathlib import Path
from research.conditional_constraint_memory.constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ConstraintLifecycleManager,
    FrozenMemorySnapshot,
)
from research.conditional_constraint_memory.memory_pipeline import StructuredFact
from research.conditional_constraint_memory.knowledge_view import UnifiedKnowledgeView
from research.conditional_constraint_memory.multistep_agent_runner import MultiStepAgentRunner


class DummyBackend:
    def generate(self, messages):
        return {"content": "{}", "prompt_tokens": 10, "generated_tokens": 5, "latency_s": 0.001}


def test_knowledge_view_symmetry_across_arms():
    """Validates that B2, B2-G, and M receive identical visible prompts from the same snapshot."""
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_sym_1",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_sym"},
        validity_state=ValidityState.CANDIDATE,
        support_count=1,
        evidence_ids=["ev_sym"],
    )
    fact = StructuredFact(
        fact_id="fact_sym_1",
        resource="port:18080",
        state_description="occupied",
        error_signature="Address already in use",
        evidence_id="ev_sym",
        run_id="run_sym_0",
        step=1,
        timestamp=1000.0,
        ttl=30.0,
    )

    snapshot = FrozenMemorySnapshot.create(rules=[rule], facts=[fact])

    # Instantiate for B2, B2-G, and M
    mgr_b2 = snapshot.instantiate_manager()
    facts_b2 = snapshot.instantiate_facts()

    mgr_b2g = snapshot.instantiate_manager()
    facts_b2g = snapshot.instantiate_facts()

    mgr_m = snapshot.instantiate_manager()
    facts_m = snapshot.instantiate_facts()

    runner = MultiStepAgentRunner(DummyBackend())

    fixed_time = 1010.0  # age = 10s <= 30s TTL -> ACTIVE
    view_b2 = UnifiedKnowledgeView.from_manager_and_facts(lifecycle_manager=mgr_b2, facts=facts_b2)
    view_b2g = UnifiedKnowledgeView.from_manager_and_facts(lifecycle_manager=mgr_b2g, facts=facts_b2g)
    view_m = UnifiedKnowledgeView.from_manager_and_facts(lifecycle_manager=mgr_m, facts=facts_m)

    text_b2 = view_b2.render_knowledge_text(current_time=fixed_time, lifecycle_manager=mgr_b2)
    text_b2g = view_b2g.render_knowledge_text(current_time=fixed_time, lifecycle_manager=mgr_b2g)
    text_m = view_m.render_knowledge_text(current_time=fixed_time, lifecycle_manager=mgr_m)

    # Strict string equality
    assert text_b2 == text_b2g, "B2 and B2-G rendered knowledge must be identical!"
    assert text_b2g == text_m, "B2-G and M rendered knowledge must be identical!"

    # Test full system prompts built by runner
    sys_b2 = runner.build_system_prompt(text_b2)
    sys_b2g = runner.build_system_prompt(text_b2g)
    sys_m = runner.build_system_prompt(text_m)

    assert sys_b2 == sys_b2g == sys_m, "Full system prompts must be character-for-character identical!"

    # Export rendered snapshot to JSON
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "prompt_knowledge_snapshot.json"

    export_payload = {
        "timestamp": time.time(),
        "source_snapshot_hash": snapshot.snapshot_hash,
        "fixed_render_time": fixed_time,
        "rendered_knowledge_text": text_m,
        "full_system_prompt": sys_m,
        "initial_conversation": [
            {"role": "system", "content": sys_m},
            {"role": "user", "content": "Begin task: Discover the environment, choose valid placement, write config, start service, and verify health."}
        ],
        "parity_check": {
            "b2_equals_b2g": (text_b2 == text_b2g),
            "b2g_equals_m": (text_b2g == text_m),
            "system_prompt_parity": (sys_b2 == sys_m),
        }
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export_payload, f, indent=2)

    assert export_payload["parity_check"]["b2_equals_b2g"] is True
    assert export_payload["parity_check"]["b2g_equals_m"] is True
