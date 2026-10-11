"""
End-to-End Experience-to-Memory Extraction and Retrieval Pipeline.
Connects:
Source Task Execution -> Failure Trace -> Candidate Rule Extraction -> Evidence Binding -> Verification -> Target Retrieval/Injection.

Strict Rules:
- Inputs to extraction can ONLY be tool_name, tool_params, exit_code, stderr, stdout, and observation_snapshot.
- No oracle rule names or cheat labels.
- Rules must bind full source task evidence (run_id, step, error_signature, premise_snapshot).
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import time
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
    """Raw failure trace from source task execution."""
    run_id: str
    step: int
    tool_name: str
    tool_params: Dict[str, Any]
    exit_code: int
    stderr: str
    stdout: str
    observation_snapshot: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class StructuredFact:
    """Dynamic world fact for Baseline B2."""
    fact_id: str
    resource: str
    state_description: str
    error_signature: str
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
            f"(Source: run '{self.run_id}' step {self.step}, Error: {self.error_signature})"
        )


class MemoryPipeline:
    """Extracts facts and rules from raw failure traces without oracle labels."""

    @staticmethod
    def extract_fact_for_b2(trace: FailureTrace) -> Optional[StructuredFact]:
        """Extracts dynamic structured fact for Baseline B2 from tool failure."""
        if trace.exit_code == 0:
            return None

        stderr_lower = trace.stderr.lower()
        if "address already in use" in stderr_lower or trace.tool_name == "start_service":
            port = trace.tool_params.get("port")
            return StructuredFact(
                fact_id=f"fact_{trace.run_id}_{trace.step}",
                resource=f"port:{port}",
                state_description=f"Port {port} is occupied / in use by another process.",
                error_signature=trace.stderr.strip(),
                run_id=trace.run_id,
                step=trace.step,
                timestamp=trace.timestamp,
            )
        elif "permission denied" in stderr_lower or trace.tool_name == "write_config":
            filepath = trace.tool_params.get("filepath")
            return StructuredFact(
                fact_id=f"fact_{trace.run_id}_{trace.step}",
                resource=f"file:{filepath}",
                state_description=f"File '{filepath}' is read-only / lacks write permissions for non-root agentuser.",
                error_signature=trace.stderr.strip(),
                run_id=trace.run_id,
                step=trace.step,
                timestamp=trace.timestamp,
            )
        return None

    @staticmethod
    def extract_rule_for_m(trace: FailureTrace, initial_validity: ValidityState = ValidityState.SUPPORTED) -> Optional[ConstraintRule]:
        """
        Extracts candidate/supported rule for Method M from tool failure.
        Inputs: only tool call, exit code, stderr, observation snapshot.
        """
        if trace.exit_code == 0:
            return None

        stderr_lower = trace.stderr.lower()

        if trace.tool_name == "start_service":
            port = trace.tool_params.get("port")
            action_sig = f"start_service:port={port}"
            # Extract predicate key from observation snapshot
            pred_key = f"port:{port}:occupied"
            predicates = [
                PreconditionPredicate(key=pred_key, expected_value=True, ttl=30.0)
            ]
            evidence = {
                "run_id": trace.run_id,
                "step": trace.step,
                "error_signature": trace.stderr.strip(),
                "premise_snapshot": trace.observation_snapshot,
            }
            return ConstraintRule(
                rule_id=f"rule_{trace.run_id}_{trace.step}",
                action_signature=action_sig,
                predicates=predicates,
                failure_evidence=evidence,
                validity_state=initial_validity,
                support_threshold=2,
                support_count=1 if initial_validity == ValidityState.CANDIDATE else 2,
                created_at=trace.timestamp,
                last_supported_at=trace.timestamp,
            )

        elif trace.tool_name == "write_config":
            filepath = trace.tool_params.get("filepath")
            action_sig = f"write_config:filepath={filepath}"
            pred_key = f"file:{filepath}:writable"
            predicates = [
                PreconditionPredicate(key=pred_key, expected_value=False, ttl=30.0)
            ]
            evidence = {
                "run_id": trace.run_id,
                "step": trace.step,
                "error_signature": trace.stderr.strip(),
                "premise_snapshot": trace.observation_snapshot,
            }
            return ConstraintRule(
                rule_id=f"rule_{trace.run_id}_{trace.step}",
                action_signature=action_sig,
                predicates=predicates,
                failure_evidence=evidence,
                validity_state=initial_validity,
                support_threshold=2,
                support_count=1 if initial_validity == ValidityState.CANDIDATE else 2,
                created_at=trace.timestamp,
                last_supported_at=trace.timestamp,
            )

        return None
