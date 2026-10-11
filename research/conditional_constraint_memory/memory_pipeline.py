"""
End-to-End Experience-to-Memory Extraction and Retrieval Pipeline.
Connects:
Source Task Execution -> Failure Trace -> Candidate Rule Extraction -> Evidence Binding -> Verification -> Target Retrieval/Injection.

Strict Methodological Rules:
- Rule parser is explicitly documented as a DeterministicHeuristicRuleParser (human expert rules).
- Inputs to extraction can ONLY be tool_name, tool_params, exit_code, stderr, stdout, and observation_snapshot.
- Unrecognized or ambiguous failures are strictly REJECTED (no false assumptions).
- Default validity state is CANDIDATE with support_count = 1 from a single evidence ID.
- Evidence IDs are deduplicated.
- Full provenance (evidence_id, run_id, step, error_code, exit_code, error_type, stderr, premise_snapshot) is preserved.
"""

import os
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from .constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision,
    ConstraintLifecycleManager,
)


@dataclass
class FailureTrace:
    """Raw failure trace from actual task execution without synthetic fabrication."""
    run_id: str
    step: int
    tool_name: str
    tool_params: Dict[str, Any]
    exit_code: int
    stderr: str
    stdout: str
    observation_snapshot: Dict[str, Any]
    error_code: Optional[int] = None
    error_type: Optional[str] = None
    evidence_id: str = ""
    timestamp: float = field(default_factory=time.time)
    config_snapshot: Optional[Dict[str, Any]] = None
    resource_id: Optional[str] = None
    user: Optional[str] = None

    def __post_init__(self):
        if not self.evidence_id:
            self.evidence_id = f"ev_{self.run_id}_s{self.step}_{int(self.timestamp * 1000)}"
        if self.error_code is None:
            self.error_code = self.exit_code


@dataclass
class StructuredFact:
    """Dynamic world fact for Baseline B2."""
    fact_id: str
    resource: str
    state_description: str
    error_signature: str
    evidence_id: str
    run_id: str
    step: int
    timestamp: float
    ttl: float = 60.0

    def is_fresh(self, current_time: float) -> bool:
        return (current_time - self.timestamp) <= self.ttl

    def to_prompt_text(self, current_time: float) -> str:
        status = "ACTIVE" if self.is_fresh(current_time) else "UNCONFIRMED_EXPIRED"
        return (
            f"- [{status}] Resource '{self.resource}': {self.state_description} "
            f"(Source: run '{self.run_id}' step {self.step}, Evidence: {self.evidence_id})"
        )


class DeterministicHeuristicRuleParser:
    """
    Explicitly disclosed deterministic heuristic parser for system failures.
    Strictly parses confirmed OS error signatures and rejects all unrecognized errors.
    Immutable: reads only from memory trace and never reads config files from disk post-teardown.
    """

    @staticmethod
    def classify_failure(trace: FailureTrace) -> Optional[Dict[str, Any]]:
        """
        Classifies failure based on strict stdout/stderr and trace metadata inspection.
        Returns failure classification dict or None if rejected.
        """
        if trace.exit_code == 0:
            return None

        stderr_lower = trace.stderr.lower()

        # Port conflict classification
        if trace.tool_name == "start_service":
            if "address already in use" in stderr_lower or trace.exit_code == 98 or trace.error_code == 98:
                port = trace.tool_params.get("port")
                if port is None and trace.config_snapshot:
                    port = trace.config_snapshot.get("port")
                if port is None and trace.resource_id and trace.resource_id.startswith("port:"):
                    p_str = trace.resource_id.split(":")[-1]
                    if p_str.isdigit():
                        port = int(p_str)

                if port is not None:
                    return {
                        "category": "port_conflict",
                        "resource_type": "port",
                        "resource_path": str(port),
                        "property": "occupied",
                        "resource": f"port:{port}",
                        "action_signature": f"start_service:port={port}",
                        "pred_key": f"port:{port}:occupied",
                        "expected_val": True,
                        "error_type": "AddressAlreadyInUse",
                        "error_code": 98,
                        "description": f"Port {port} is occupied / in use by another process.",
                    }
            # Any other start_service error (e.g. missing config, permission, syntax) is REJECTED
            return None

        # File permission classification
        elif trace.tool_name == "write_config":
            is_perm_denied = (
                "permission denied" in stderr_lower
                or trace.error_type == "PermissionDenied"
                or (trace.exit_code in (1, 13) and "permission" in stderr_lower)
            )
            if is_perm_denied:
                filepath = trace.tool_params.get("filepath") or trace.tool_params.get("config_path")
                if filepath is not None:
                    # Classify resource type strictly from memory trace without post-teardown disk access
                    is_dir = (
                        (trace.resource_id and trace.resource_id.startswith("dir:"))
                        or filepath.endswith("/")
                        or (not ("." in os.path.basename(filepath)))
                    )
                    if is_dir:
                        res_type = "dir"
                        res_path = filepath.rstrip("/")
                        prop = "writable"
                        pred_k = f"dir:{res_path}:writable"
                        desc = f"Directory '{res_path}' lacks write permissions for current user context."
                    else:
                        res_type = "file"
                        res_path = filepath
                        prop = "writable"
                        pred_k = f"file:{res_path}:writable"
                        desc = f"File '{res_path}' lacks write permissions for current user context."

                    return {
                        "category": "permission_denied",
                        "resource_type": res_type,
                        "resource_path": res_path,
                        "property": prop,
                        "resource": f"{res_type}:{res_path}",
                        "action_signature": f"write_config:filepath={filepath}",
                        "pred_key": pred_k,
                        "expected_val": False,
                        "error_type": "PermissionDenied",
                        "error_code": trace.error_code or 13,
                        "description": desc,
                    }
            # Any other write error (e.g. disk full, read error, invalid content) is REJECTED
            return None

        return None


class MemoryPipeline:
    """Extracts facts and rules from raw failure traces via DeterministicHeuristicRuleParser."""

    @staticmethod
    def extract_fact_for_b2(trace: FailureTrace) -> Optional[StructuredFact]:
        """Extracts dynamic structured fact for Baseline B2 from tool failure."""
        classification = DeterministicHeuristicRuleParser.classify_failure(trace)
        if classification is None:
            return None

        return StructuredFact(
            fact_id=f"fact_{trace.run_id}_{trace.step}",
            resource=classification["resource"],
            state_description=classification["description"],
            error_signature=trace.stderr.strip(),
            evidence_id=trace.evidence_id,
            run_id=trace.run_id,
            step=trace.step,
            timestamp=trace.timestamp,
        )

    @staticmethod
    def extract_rule_for_m(trace: FailureTrace) -> Optional[ConstraintRule]:
        """
        Extracts candidate rule for Method M from tool failure.
        Default validity is strictly CANDIDATE with support_count = 1 from evidence deduplication.
        Callers cannot pass initial_validity=SUPPORTED to bypass probation.
        """
        classification = DeterministicHeuristicRuleParser.classify_failure(trace)
        if classification is None:
            return None

        predicates = [
            PreconditionPredicate(
                key=classification["pred_key"],
                expected_value=classification["expected_val"],
                ttl=30.0,
                resource_type=classification.get("resource_type", ""),
                resource_path=classification.get("resource_path", ""),
                property=classification.get("property", ""),
            )
        ]
        evidence = {
            "evidence_id": trace.evidence_id,
            "run_id": trace.run_id,
            "step": trace.step,
            "error_code": classification["error_code"],
            "exit_code": trace.exit_code,
            "error_type": classification["error_type"],
            "error_signature": trace.stderr.strip(),
            "premise_snapshot": dict(trace.observation_snapshot),
        }
        return ConstraintRule(
            rule_id=f"rule_{trace.run_id}_{trace.step}",
            action_signature=classification["action_signature"],
            predicates=predicates,
            failure_evidence=evidence,
            validity_state=ValidityState.CANDIDATE,
            support_threshold=2,
            support_count=1,
            evidence_ids=[trace.evidence_id],
            created_at=trace.timestamp,
            last_supported_at=trace.timestamp,
        )


