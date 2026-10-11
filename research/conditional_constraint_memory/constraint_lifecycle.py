"""
Constraint Lifecycle Management Module.
Implements decoupled Rule Validity, Current Applicability, and Gate Decisions.

Core Invariants:
1. Validity states: CANDIDATE, SUPPORTED, CONTRADICTED, RETIRED.
2. Applicability states: APPLICABLE, NOT_APPLICABLE, UNKNOWN.
3. Gate decisions: BLOCK, ALLOW, PROBE.
4. Conjunction evaluation:
   - Any fresh predicate explicitly False -> NOT_APPLICABLE (order-independent)
   - All fresh predicates explicitly True -> APPLICABLE
   - Otherwise -> UNKNOWN
5. CANDIDATE rules do NOT hard-block actions (allows limited probationary trial).
6. Success when premise is NOT_APPLICABLE is expected causal behavior, NOT counter-evidence.
   Counter-evidence ONLY occurs when action succeeds while applicability is confirmed APPLICABLE.
7. Injectable time provider with distinction between observation timestamp and rule support timestamp.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Tuple
import time
import hashlib
import copy
import json


class ValidityState(str, Enum):
    CANDIDATE = "CANDIDATE"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    RETIRED = "RETIRED"


class ApplicabilityState(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class GateDecision(str, Enum):
    BLOCK = "BLOCK"
    ALLOW = "ALLOW"
    PROBE = "PROBE"


@dataclass
class PredicateObservation:
    """Represents a concrete environment observation for a predicate key."""
    key: str
    value: Any
    timestamp: float  # When the observation was sampled from the environment
    call_id: str = ""  # Tool call provenance ID


@dataclass
class PreconditionPredicate:
    """
    Structured Precondition Predicate for a constraint rule.
    Structured fields: resource_type, resource_path, property, expected_value, ttl, key.
    """
    key: str = ""
    expected_value: Any = None
    ttl: float = 5.0  # Freshness window in seconds
    resource_type: str = ""  # e.g. "port", "directory", "file"
    resource_path: str = ""  # e.g. "18080", "/etc/service_demo", "/etc/service_demo/app.conf"
    property: str = ""       # e.g. "occupied", "writable"

    def __post_init__(self):
        if self.key and (not self.resource_type or not self.resource_path or not self.property):
            parts = self.key.split(":")
            if len(parts) >= 3:
                self.resource_type = parts[0]
                self.property = parts[-1]
                self.resource_path = ":".join(parts[1:-1])
        elif not self.key and self.resource_type and self.resource_path and self.property:
            self.key = f"{self.resource_type}:{self.resource_path}:{self.property}"


@dataclass
class ConstraintRule:
    """A conditional failure constraint rule."""
    rule_id: str
    action_signature: str  # e.g. "start_service:port=18080" or "write_config:filepath=..."
    predicates: List[PreconditionPredicate]
    failure_evidence: Dict[str, Any]  # e.g. {"error_code": 98, "stderr": "Address already in use", "evidence_id": ...}
    validity_state: ValidityState = ValidityState.CANDIDATE
    support_threshold: int = 2
    support_count: int = 1
    contradict_count: int = 0
    evidence_ids: List[str] = field(default_factory=list)
    contradiction_evidence_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_supported_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        ev_id = self.failure_evidence.get("evidence_id")
        if ev_id and ev_id not in self.evidence_ids:
            self.evidence_ids.append(ev_id)
        if self.evidence_ids:
            self.support_count = len(set(self.evidence_ids))


@dataclass(frozen=True)
class FrozenMemorySnapshot:
    """
    Immutable, integrity-verified snapshot of learned memory (rules and facts).
    Enforces isolation across evaluation episodes.
    """
    canonical_json: str
    snapshot_hash: str

    @staticmethod
    def create(
        rules: List[ConstraintRule],
        facts: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "FrozenMemorySnapshot":
        canonical_rules = []
        for r in sorted(rules, key=lambda x: x.rule_id):
            preds_serialized = [
                {
                    "key": p.key,
                    "expected_value": p.expected_value,
                    "ttl": p.ttl,
                    "resource_type": p.resource_type,
                    "resource_path": p.resource_path,
                    "property": p.property,
                }
                for p in r.predicates
            ]
            canonical_rules.append({
                "rule_id": r.rule_id,
                "action_signature": r.action_signature,
                "predicates": preds_serialized,
                "failure_evidence": r.failure_evidence,
                "validity_state": r.validity_state.value,
                "support_threshold": r.support_threshold,
                "support_count": r.support_count,
                "contradict_count": r.contradict_count,
                "evidence_ids": sorted(list(set(r.evidence_ids))),
                "contradiction_evidence_ids": sorted(list(set(r.contradiction_evidence_ids))),
                "created_at": r.created_at,
                "last_supported_at": r.last_supported_at,
                "metadata": r.metadata,
            })

        canonical_facts = []
        if facts:
            for f in sorted(facts, key=lambda x: getattr(x, "fact_id", str(x))):
                canonical_facts.append({
                    "fact_id": f.fact_id,
                    "resource": f.resource,
                    "state_description": f.state_description,
                    "error_signature": f.error_signature,
                    "evidence_id": f.evidence_id,
                    "run_id": f.run_id,
                    "step": f.step,
                    "timestamp": f.timestamp,
                    "ttl": getattr(f, "ttl", 60.0),
                })

        meta_dict = metadata or {}
        payload = {
            "rules": canonical_rules,
            "facts": canonical_facts,
            "metadata": meta_dict,
        }
        serialized = json.dumps(payload, sort_keys=True)
        h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return FrozenMemorySnapshot(canonical_json=serialized, snapshot_hash=h)

    def verify_integrity(self) -> bool:
        """Verifies that the immutable snapshot matches its SHA256 digest."""
        h = hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()
        return h == self.snapshot_hash

    def instantiate_manager(self, time_provider: Optional[Callable[[], float]] = None) -> "ConstraintLifecycleManager":
        """Instantiates an isolated, deep-copied ConstraintLifecycleManager for an episode."""
        data = json.loads(self.canonical_json)
        mgr = ConstraintLifecycleManager(time_provider=time_provider)
        for d in data["rules"]:
            preds = [PreconditionPredicate(**p) for p in d["predicates"]]
            rule = ConstraintRule(
                rule_id=d["rule_id"],
                action_signature=d["action_signature"],
                predicates=preds,
                failure_evidence=copy.deepcopy(d["failure_evidence"]),
                validity_state=ValidityState(d["validity_state"]),
                support_threshold=d["support_threshold"],
                support_count=d["support_count"],
                contradict_count=d["contradict_count"],
                evidence_ids=list(d["evidence_ids"]),
                contradiction_evidence_ids=list(d["contradiction_evidence_ids"]),
                created_at=d["created_at"],
                last_supported_at=d["last_supported_at"],
                metadata=copy.deepcopy(d["metadata"]),
            )
            mgr.add_rule(rule)
        return mgr

    def instantiate_facts(self) -> List[Any]:
        """Returns isolated, deep-copied list of StructuredFacts."""
        from .memory_pipeline import StructuredFact
        data = json.loads(self.canonical_json)
        facts = []
        for d in data["facts"]:
            facts.append(StructuredFact(**d))
        return facts


class ConstraintLifecycleManager:
    """Manages rule validity, current applicability, and execution gating."""
    def __init__(self, time_provider: Optional[Callable[[], float]] = None):
        self.time_provider = time_provider or time.time
        self.rules: Dict[str, ConstraintRule] = {}
        self.observations: Dict[str, PredicateObservation] = {}

    def compute_hash(self) -> str:
        """Computes deterministic SHA256 digest of current rules, evidence, and observations."""
        canonical_rules = []
        for r in sorted(self.rules.values(), key=lambda x: x.rule_id):
            canonical_rules.append({
                "rule_id": r.rule_id,
                "action_signature": r.action_signature,
                "validity_state": r.validity_state.value,
                "support_count": r.support_count,
                "contradict_count": r.contradict_count,
                "evidence_ids": sorted(list(set(r.evidence_ids))),
                "contradiction_evidence_ids": sorted(list(set(r.contradiction_evidence_ids))),
            })
        canonical_obs = []
        for k in sorted(self.observations.keys()):
            obs = self.observations[k]
            canonical_obs.append({"key": obs.key, "value": obs.value, "call_id": obs.call_id})
        payload = {"rules": canonical_rules, "observations": canonical_obs}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def clone(self) -> "ConstraintLifecycleManager":
        """Deep copy for episode isolation."""
        new_mgr = ConstraintLifecycleManager(time_provider=self.time_provider)
        new_mgr.rules = copy.deepcopy(self.rules)
        new_mgr.observations = copy.deepcopy(self.observations)
        return new_mgr

    def create_snapshot(self, facts: Optional[List[Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> FrozenMemorySnapshot:
        """Freezes current manager rules into an immutable FrozenMemorySnapshot."""
        return FrozenMemorySnapshot.create(
            rules=list(self.rules.values()),
            facts=facts,
            metadata=metadata,
        )

    def register_observation(self, key: str, value: Any, timestamp: Optional[float] = None, call_id: Optional[str] = None):
        """Register or update an environment observation."""
        obs_time = timestamp if timestamp is not None else self.time_provider()
        self.observations[key] = PredicateObservation(key=key, value=value, timestamp=obs_time, call_id=call_id or "")

    def add_rule(self, rule: ConstraintRule):
        """Add a constraint rule to the manager."""
        self.rules[rule.rule_id] = rule

    def evaluate_applicability(
        self,
        rule: ConstraintRule,
        snapshot: Optional[Dict[str, PredicateObservation]] = None,
    ) -> ApplicabilityState:
        """
        Evaluates the current applicability of a rule's precondition predicates.
        Conjunction semantics:
        - If ANY fresh predicate is explicitly False -> NOT_APPLICABLE (independent of iteration order)
        - If ALL predicates are fresh and True -> APPLICABLE
        - Otherwise -> UNKNOWN
        """
        now = self.time_provider()
        obs_source = snapshot if snapshot is not None else self.observations
        any_false = False
        any_unknown = False

        for pred in rule.predicates:
            obs = obs_source.get(pred.key)
            if obs is None:
                any_unknown = True
            elif (now - obs.timestamp) > pred.ttl:
                # Observation has expired
                any_unknown = True
            else:
                # Fresh observation available
                if obs.value != pred.expected_value:
                    any_false = True
                # If obs.value == pred.expected_value, predicate is satisfied

        # Invariant 2: Order-independent conjunction
        if any_false:
            return ApplicabilityState.NOT_APPLICABLE
        elif any_unknown:
            return ApplicabilityState.UNKNOWN
        else:
            return ApplicabilityState.APPLICABLE

    def make_gate_decision(
        self,
        action_signature: str,
        observations_snapshot: Optional[Dict[str, PredicateObservation]] = None,
    ) -> Dict[str, Any]:
        """
        Computes the gating decision for a proposed action signature with multi-rule order-invariant aggregation.
        Returns: {
            "decision": GateDecision,
            "matching_rule_id": Optional[str],
            "validity": Optional[ValidityState],
            "applicability": Optional[ApplicabilityState],
            "reason": str
        }
        """
        matching_rules = [r for r in self.rules.values() if r.action_signature == action_signature]
        
        if not matching_rules:
            return {
                "decision": GateDecision.ALLOW,
                "matching_rule_id": None,
                "validity": None,
                "applicability": None,
                "reason": "No constraint rule matches proposed action."
            }

        blocking_rule: Optional[Tuple[ConstraintRule, ApplicabilityState]] = None
        probing_rule: Optional[Tuple[ConstraintRule, ApplicabilityState]] = None
        candidate_allow_rule: Optional[Tuple[ConstraintRule, ApplicabilityState]] = None

        # Check each matching rule and aggregate without order sensitivity
        for rule in matching_rules:
            # Invariant 1: RETIRED / CONTRADICTED cannot block or require probe
            if rule.validity_state in [ValidityState.RETIRED, ValidityState.CONTRADICTED]:
                continue

            app_state = self.evaluate_applicability(rule, snapshot=observations_snapshot)

            if rule.validity_state == ValidityState.SUPPORTED:
                if app_state == ApplicabilityState.APPLICABLE:
                    # SUPPORTED and APPLICABLE takes highest priority: MUST BLOCK
                    blocking_rule = (rule, app_state)
                    break  # Hard block cannot be overridden
                elif app_state == ApplicabilityState.UNKNOWN:
                    if probing_rule is None:
                        probing_rule = (rule, app_state)
            elif rule.validity_state == ValidityState.CANDIDATE:
                if app_state == ApplicabilityState.UNKNOWN:
                    if probing_rule is None:
                        probing_rule = (rule, app_state)
                elif app_state == ApplicabilityState.APPLICABLE:
                    if candidate_allow_rule is None:
                        candidate_allow_rule = (rule, app_state)

        # 1. Highest priority: BLOCK
        if blocking_rule:
            rule, app_state = blocking_rule
            return {
                "decision": GateDecision.BLOCK,
                "matching_rule_id": rule.rule_id,
                "validity": rule.validity_state,
                "applicability": app_state,
                "reason": f"Action blocked: Rule {rule.rule_id} is SUPPORTED and APPLICABLE."
            }

        # 2. Next priority: PROBE (if any active rule premise is UNKNOWN)
        if probing_rule:
            rule, app_state = probing_rule
            return {
                "decision": GateDecision.PROBE,
                "matching_rule_id": rule.rule_id,
                "validity": rule.validity_state,
                "applicability": app_state,
                "reason": f"Action deferred: Rule {rule.rule_id} premise is UNKNOWN; probe required."
            }

        # 3. Candidate allowed under probation
        if candidate_allow_rule:
            rule, app_state = candidate_allow_rule
            return {
                "decision": GateDecision.ALLOW,
                "matching_rule_id": rule.rule_id,
                "validity": rule.validity_state,
                "applicability": app_state,
                "probationary": True,
                "reason": f"Rule {rule.rule_id} is in CANDIDATE state; allowed under probationary trial."
            }

        # 4. All active rules evaluated to NOT_APPLICABLE
        return {
            "decision": GateDecision.ALLOW,
            "matching_rule_id": None,
            "validity": None,
            "applicability": ApplicabilityState.NOT_APPLICABLE,
            "reason": "All matching rules are NOT_APPLICABLE, RETIRED, or CONTRADICTED."
        }

    def record_action_outcome(
        self,
        action_signature: str,
        success: bool,
        error_details: Optional[Dict[str, Any]] = None,
        pre_action_applicability: Optional[Dict[str, ApplicabilityState]] = None,
        pre_action_snapshot: Optional[Dict[str, PredicateObservation]] = None,
        evidence_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Updates rule validity based on actual action execution outcome.
        Uses pre-action applicability or pre-action snapshot to prevent post-action observation skew.
        """
        updates = []
        matching_rules = [r for r in self.rules.values() if r.action_signature == action_signature]

        for rule in matching_rules:
            if pre_action_applicability and rule.rule_id in pre_action_applicability:
                prior_app = pre_action_applicability[rule.rule_id]
            elif pre_action_snapshot is not None:
                prior_app = self.evaluate_applicability(rule, snapshot=pre_action_snapshot)
            else:
                prior_app = self.evaluate_applicability(rule)

            prior_val = rule.validity_state
            transition = "NO_CHANGE"
            ev_id = evidence_id or (error_details.get("evidence_id") if error_details else None)

            if prior_app == ApplicabilityState.APPLICABLE:
                if success:
                    # TRUE COUNTER-EVIDENCE: The premise confirmed present, but action SUCCEEDED!
                    if ev_id:
                        if ev_id not in rule.contradiction_evidence_ids:
                            rule.contradiction_evidence_ids.append(ev_id)
                        rule.contradict_count = len(set(rule.contradiction_evidence_ids))
                        if rule.contradict_count >= 2:
                            rule.validity_state = ValidityState.RETIRED
                        elif rule.contradict_count >= 1:
                            rule.validity_state = ValidityState.CONTRADICTED
                        transition = f"{prior_val} -> {rule.validity_state} (CONTRADICTED_BY_SUCCESS, count={rule.contradict_count})"
                    else:
                        transition = f"MISSING_EVIDENCE_ID_IGNORED (validity retained: {rule.validity_state})"
                else:
                    # Failure under matching premise reinforces rule ONLY IF:
                    # 1) ev_id is provided (no ghost increments without evidence ID)
                    # 2) error type or code matches a known failure pattern
                    if not ev_id:
                        transition = f"MISSING_EVIDENCE_ID_IGNORED (validity retained: {rule.validity_state})"
                    else:
                        err_code = error_details.get("error_code") if error_details else None
                        if err_code is None and error_details:
                            err_code = error_details.get("exit_code")
                        rule_err_code = rule.failure_evidence.get("error_code")
                        if rule_err_code is None:
                            rule_err_code = rule.failure_evidence.get("exit_code")

                        err_type = error_details.get("error_type") if error_details else None
                        rule_err_type = rule.failure_evidence.get("error_type")

                        has_known_error = bool(err_type and err_type not in ("Unknown", "CommandExecutionError")) or (err_code is not None and err_code != 0)
                        code_match = (err_code is not None and rule_err_code is not None and err_code == rule_err_code)
                        type_match = (err_type is not None and rule_err_type is not None and err_type == rule_err_type)

                        is_matching_error = has_known_error and (code_match or type_match or (rule_err_code is not None and err_code == rule_err_code))

                        if is_matching_error:
                            if ev_id not in rule.evidence_ids:
                                rule.evidence_ids.append(ev_id)
                                rule.support_count = len(set(rule.evidence_ids))
                                rule.last_supported_at = self.time_provider()

                                if rule.validity_state == ValidityState.CANDIDATE and rule.support_count >= rule.support_threshold:
                                    rule.validity_state = ValidityState.SUPPORTED
                                    transition = f"CANDIDATE -> SUPPORTED (PROBATION_PASSED, count={rule.support_count})"
                                else:
                                    transition = f"SUPPORTED_REINFORCED (count={rule.support_count})"
                            else:
                                transition = f"DUPLICATE_EVIDENCE_IGNORED (count={rule.support_count})"
                        else:
                            transition = f"NON_MATCHING_OR_MISSING_EVIDENCE_IGNORED (validity retained: {rule.validity_state})"

            elif prior_app == ApplicabilityState.NOT_APPLICABLE:
                if success:
                    # Premise was cleared, action succeeded -> Normal causal behavior!
                    # Rule remains valid and supported; DO NOT penalize rule!
                    transition = f"PREMISE_CLEARED_SUCCESS (validity retained: {rule.validity_state})"
                else:
                    # Failure occurred when precondition was not met -> Unrelated issue
                    transition = f"UNRELATED_FAILURE (validity retained: {rule.validity_state})"

            elif prior_app == ApplicabilityState.UNKNOWN:
                # State was unknown; do not definitively contradict or upgrade
                transition = f"UNKNOWN_OUTCOME (validity retained: {rule.validity_state})"

            updates.append({
                "rule_id": rule.rule_id,
                "prior_applicability": prior_app,
                "prior_validity": prior_val,
                "new_validity": rule.validity_state,
                "transition": transition
            })

        return updates

    # Alias for API compatibility
    register_action_outcome = record_action_outcome


