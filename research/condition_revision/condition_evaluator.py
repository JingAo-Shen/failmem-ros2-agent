"""
Condition Evaluator Module for Counterexample-Driven Condition Revision.
Provides:
1. Grounded predicate evaluation returning ConditionResult (TRUE, FALSE, UNKNOWN).
2. Explicit subject binding: distinguishes rule's specified subject from task's target object.
3. Dynamic observation precedence: physical state (solid/liquid/gas) in observation overrides static prior knowledge.
4. Attribution tracking: distinguishes current_observation, historical_observation, prior_knowledge, and prior_inference_untested.
5. Step-level re-evaluation to dynamically retract invalid rules.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set
import re


class ConditionResult(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class EvidenceSource(str, Enum):
    CURRENT_OBSERVATION = "current_observation"
    HISTORICAL_OBSERVATION = "historical_observation"
    PRIOR_KNOWLEDGE = "prior_knowledge"
    PRIOR_INFERENCE_UNTESTED = "prior_inference_untested"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


# Known material categories grounded in ScienceWorld semantics
METAL_MATERIALS = {
    "aluminum", "copper", "iron", "steel", "gold", "silver", "brass", "metal",
    "foil", "aluminum foil", "metal fork", "copper wire", "key", "metal spoon", "penny", "wire"
}

NON_METAL_MATERIALS = {
    "wood", "plastic", "rubber", "glass", "paper", "cloth", "ceramic", "cotton",
    "apricot", "apple", "banana", "fruit", "book", "glass jar", "rubber band",
    "plastic cup", "wood block", "chalk", "soap", "sponge"
}

LIQUID_DEFAULT_SUBSTANCES = {
    "water", "orange juice", "juice", "milk", "oil", "vinegar", "soapy water", "salt water"
}

SOLID_DEFAULT_SUBSTANCES = {
    "ice", "chocolate", "marshmallow", "wood", "metal", "stone", "rock", "glass",
    "foil", "fork", "apricot", "apple", "book", "salt", "sugar", "baking soda"
}

LIVING_THINGS = {
    "plant", "tree", "flower", "grass", "mouse", "cat", "dog", "insect", "bee", "bird", "frog"
}

NON_LIVING_THINGS = {
    "rock", "chair", "table", "cup", "box", "door", "bed", "sink", "stove", "counter",
    "fork", "foil", "book", "wire", "battery", "light bulb", "water", "ice", "glass"
}

KNOWN_ROOMS = {"workshop", "kitchen", "bathroom", "bedroom", "living room", "hallway", "greenhouse", "outside"}
KNOWN_CONTAINERS = {"red box", "green box", "stove", "freezer", "refrigerator", "cupboard", "sink"}


def extract_target_entity(task_desc: str) -> str:
    """
    Extract the primary target object name from a ScienceWorld task description.
    e.g. 'determine if aluminum foil is electrically conductive' -> 'aluminum foil'
         'melt ice' -> 'ice'
         'power red light bulb' -> 'red light bulb'
    """
    desc_lower = task_desc.lower()
    
    # Pattern 1: determine if X is ...
    m = re.search(r"determine if ([a-z0-9\s\-]+?) is (?:electrically|conductive|living)", desc_lower)
    if m:
        return m.group(1).strip()
        
    # Pattern 2: focus on the X
    m = re.search(r"first, focus on the ([a-z0-9\s\-]+?)\.", desc_lower)
    if m:
        return m.group(1).strip()
        
    # Pattern 3: melt / boil / freeze X
    m = re.search(r"\b(?:melt|boil|freeze|change the state of matter of)\s+([a-z0-9\s\-]+?)(?:\s+in|\s+to|\.|$)", desc_lower)
    if m:
        return m.group(1).strip()

    # Pattern 4: power X
    m = re.search(r"\bpower\s+([a-z0-9\s\-]+?)(?:\.|$)", desc_lower)
    if m:
        return m.group(1).strip()

    # Fallback: find living / non-living thing
    if "living thing" in desc_lower:
        return "living thing"

    return "unknown_target"


class ConditionEvaluator:
    """
    Evaluates condition predicates against target entity and observable state.
    Distinguishes:
    - Entity attributes (is_metal) vs physical properties (is_conductive)
    - Dynamic observation state vs default prior knowledge
    - Specified rule subject vs current task target
    """

    @staticmethod
    def is_target_metal(target: str, obs_text: str = "") -> Tuple[ConditionResult, EvidenceSource, str]:
        target_lower = target.lower().strip()
        obs_lower = obs_text.lower()
        
        # 1. Direct perceptual observation in current/recent text
        if f"{target_lower} made of metal" in obs_lower or f"metallic {target_lower}" in obs_lower:
            return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly states '{target}' is metallic"
        if f"{target_lower} made of plastic" in obs_lower or f"{target_lower} made of glass" in obs_lower or f"{target_lower} made of wood" in obs_lower:
            return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly states '{target}' is non-metallic"

        # 2. Prior knowledge dictionary (explicitly documented as prior, not perceptual)
        for m in METAL_MATERIALS:
            if m in target_lower:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred from prior material knowledge dictionary (material: metal), unverified by sensor"
        for non_m in NON_METAL_MATERIALS:
            if non_m in target_lower:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred from prior material knowledge dictionary (material: non-metal), unverified by sensor"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"Cannot determine if '{target}' is metal from observation or prior knowledge"

    @staticmethod
    def is_target_conductive(
        target: str,
        obs_text: str = "",
        history_obs: List[str] = None,
        allow_prior_inference: bool = True
    ) -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Physical property: electrical conductivity.
        Distinguishes empirical test observation from prior inference.
        """
        combined_obs = " ".join([obs_text] + (history_obs or [])).lower()
        target_lower = target.lower().strip()

        # 1. Empirical electrical observation in current or history
        test_indicators = [
            "light bulb turns on", "light turns on", "bulb is on",
            "current flows", "is conductive", "conducts electricity"
        ]
        non_test_indicators = [
            "light bulb remains off", "light stays off", "bulb does not turn on",
            "no current", "is non-conductive", "does not conduct electricity"
        ]

        if any(ind in combined_obs for ind in test_indicators):
            return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Empirical observation confirms electrical conductivity (circuit closed/light turned on)"
        if any(ind in combined_obs for ind in non_test_indicators):
            return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Empirical observation confirms non-conductivity (circuit open/light off)"

        # 2. Prior knowledge inference (if allowed, stamped as prior_inference_untested)
        if allow_prior_inference:
            is_m, src, expl = ConditionEvaluator.is_target_metal(target, obs_text)
            if is_m == ConditionResult.TRUE:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_INFERENCE_UNTESTED, f"Inferred electrical conductivity from metal material prior without empirical circuit test"
            elif is_m == ConditionResult.FALSE:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_INFERENCE_UNTESTED, f"Inferred non-conductivity from non-metal material prior without empirical circuit test"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"No empirical conductivity test recorded for '{target}'"

    @staticmethod
    def is_target_liquid(target: str, obs_text: str = "") -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Evaluates whether target is currently in liquid state.
        CRITICAL: Dynamic observation (frozen, ice, solid, boiling) MUST override static noun prior!
        """
        target_lower = target.lower().strip()
        obs_lower = obs_text.lower()

        # 1. Dynamic Observation Precedence
        # Check for freezing / solid indicators
        frozen_clues = ["frozen", "freezes", "froze", "ice", "solidified", "turned to solid", "temperature -", "degrees celsius (below freezing)"]
        if any(clue in obs_lower for clue in frozen_clues):
            return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly indicates target is frozen/solid (ice), not liquid"

        # Check for gaseous / boiling indicators
        gas_clues = ["steam", "gas", "vapor", "boiled away", "evaporated"]
        if any(clue in obs_lower for clue in gas_clues):
            return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly indicates target is gaseous/steam, not liquid"

        # Check for explicit liquid indicators
        liquid_clues = ["liquid", "melted", "water is liquid", "fluid"]
        if any(clue in obs_lower for clue in liquid_clues):
            return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly confirms target is liquid"

        # 2. Static Default Prior (Only when observation has no dynamic thermal/phase clues)
        for l in LIQUID_DEFAULT_SUBSTANCES:
            if l in target_lower:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default liquid state for '{target}' from prior knowledge (unverified dynamically)"
        for s in SOLID_DEFAULT_SUBSTANCES:
            if s in target_lower:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default solid state for '{target}' from prior knowledge (unverified dynamically)"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"State of matter for '{target}' cannot be determined from observation or prior knowledge"

    @staticmethod
    def is_target_solid(target: str, obs_text: str = "") -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Evaluates whether target is currently in solid state.
        Dynamic observation takes strict precedence over static priors.
        """
        obs_lower = obs_text.lower()
        target_lower = target.lower().strip()

        # 1. Dynamic Observation Precedence
        solid_clues = ["frozen", "ice", "solid", "solidified", "ice cube"]
        if any(clue in obs_lower for clue in solid_clues):
            return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly indicates target is solid (frozen/ice)"

        liquid_clues = ["melted", "liquid", "fluid"]
        if any(clue in obs_lower for clue in liquid_clues):
            return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly indicates target is liquid (melted), not solid"

        # 2. Static Default Prior
        for s in SOLID_DEFAULT_SUBSTANCES:
            if s in target_lower:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default solid state for '{target}' from prior knowledge"
        for l in LIQUID_DEFAULT_SUBSTANCES:
            if l in target_lower:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default liquid state for '{target}' from prior knowledge"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"Cannot determine if '{target}' is solid"

    @staticmethod
    def is_target_living(target: str, obs_text: str = "") -> Tuple[ConditionResult, EvidenceSource, str]:
        target_lower = target.lower().strip()
        obs_lower = obs_text.lower()

        if "living" in obs_lower and target_lower in obs_lower:
            return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Observation states '{target}' is living"
        if "non-living" in obs_lower and target_lower in obs_lower:
            return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Observation states '{target}' is non-living"

        for lt in LIVING_THINGS:
            if lt in target_lower:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred living organism from prior knowledge"
        for nlt in NON_LIVING_THINGS:
            if nlt in target_lower:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred non-living object from prior knowledge"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"Cannot determine if '{target}' is living"

    @staticmethod
    def evaluate_subject_location(
        condition_str: str,
        current_target: str,
        task_desc: str,
        current_obs: str,
        history_obs: List[str] = None
    ) -> Optional[Tuple[ConditionResult, EvidenceSource, str]]:
        """
        Handles subject-location semantics, preventing false matches.
        e.g., 'aluminum foil in workshop' MUST NOT evaluate to TRUE if current target is apricot,
        even if apricot or the agent is in the workshop!
        """
        cond_lower = condition_str.lower().strip()
        combined_obs = " ".join([current_obs] + (history_obs or [])).lower()
        desc_lower = task_desc.lower()

        # Find location mentioned in condition
        found_loc = None
        for room in KNOWN_ROOMS:
            if room in cond_lower:
                found_loc = room
                break
        if not found_loc:
            for container in KNOWN_CONTAINERS:
                if container in cond_lower:
                    found_loc = container
                    break

        if not found_loc:
            return None

        # Determine subject specified in condition
        subject = None
        # Check if condition specifies an explicit named entity other than generic "target/object/item"
        for m in (METAL_MATERIALS | NON_METAL_MATERIALS | LIQUID_DEFAULT_SUBSTANCES | SOLID_DEFAULT_SUBSTANCES):
            if m in cond_lower and m not in found_loc:
                subject = m
                break

        if subject is None:
            # Condition uses generic subject e.g. "target in workshop" or "item in workshop"
            subject = current_target.lower()

        # If condition explicitly named a subject that differs from current_target
        # and subject is NOT observed in the environment:
        subject_in_obs = subject in combined_obs
        loc_in_obs = found_loc in combined_obs or found_loc in desc_lower

        if subject != current_target.lower():
            # Explicit subject mismatch
            if not subject_in_obs:
                return (
                    ConditionResult.FALSE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Condition subject '{subject}' is not observed in '{found_loc}' (current target is '{current_target}')"
                )
            elif loc_in_obs:
                return (
                    ConditionResult.TRUE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Condition subject '{subject}' is observed in '{found_loc}'"
                )
            else:
                return (
                    ConditionResult.UNKNOWN,
                    EvidenceSource.INSUFFICIENT_EVIDENCE,
                    f"Condition subject '{subject}' found in obs, but location '{found_loc}' not confirmed"
                )
        else:
            # Subject matches current_target
            if subject_in_obs and loc_in_obs:
                return (
                    ConditionResult.TRUE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Target '{subject}' and location '{found_loc}' both verified in observation"
                )
            elif not subject_in_obs:
                return (
                    ConditionResult.FALSE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Target '{subject}' is not present in observed location '{found_loc}'"
                )
            else:
                return (
                    ConditionResult.UNKNOWN,
                    EvidenceSource.INSUFFICIENT_EVIDENCE,
                    f"Target '{subject}' present, but location '{found_loc}' not yet confirmed in observation"
                )

    @staticmethod
    def evaluate_condition_detailed(
        condition_str: str,
        target: str,
        task_desc: str,
        current_obs: str,
        history_obs: List[str] = None
    ) -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Parses and evaluates a condition string bound to the target entity.
        Returns (ConditionResult, EvidenceSource, explanation).
        """
        cond_lower = condition_str.lower().strip()
        combined_obs = " ".join([current_obs] + (history_obs or []))

        # 1. Check Subject-Location / Presence first
        loc_res = ConditionEvaluator.evaluate_subject_location(condition_str, target, task_desc, current_obs, history_obs)
        if loc_res is not None:
            return loc_res

        # 2. Material Constraints (Metal / Non-Metal)
        if any(w in cond_lower for w in ["metal", "metallic"]):
            is_neg = ("not" in cond_lower or "non" in cond_lower)
            res, src, expl = ConditionEvaluator.is_target_metal(target, combined_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is metal, violating negative condition '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is verified non-metal (satisfies negative condition)"
                return ConditionResult.UNKNOWN, src, expl
            else:
                return res, src, expl

        # 3. Physical Property: Electrical Conductivity
        if any(w in cond_lower for w in ["conductive", "conductor"]):
            is_neg = ("not" in cond_lower or "non" in cond_lower)
            res, src, expl = ConditionEvaluator.is_target_conductive(target, current_obs, history_obs, allow_prior_inference=True)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is conductive, violating '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is non-conductive"
                return ConditionResult.UNKNOWN, src, expl
            else:
                return res, src, expl

        # 4. State of Matter Constraints (Liquid / Solid / Gas)
        if "liquid" in cond_lower:
            is_neg = ("not" in cond_lower or "non" in cond_lower)
            res, src, expl = ConditionEvaluator.is_target_liquid(target, combined_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is liquid, violating '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is not liquid"
                return ConditionResult.UNKNOWN, src, expl
            else:
                return res, src, expl

        if "solid" in cond_lower or "ice" in cond_lower:
            is_neg = ("not" in cond_lower or "non" in cond_lower)
            res, src, expl = ConditionEvaluator.is_target_solid(target, combined_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is solid, violating '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is not solid"
                return ConditionResult.UNKNOWN, src, expl
            else:
                return res, src, expl

        # 5. Living organism constraints
        if "living" in cond_lower:
            is_neg = ("not" in cond_lower or "non" in cond_lower)
            res, src, expl = ConditionEvaluator.is_target_living(target, combined_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is living, violating '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is non-living"
                return ConditionResult.UNKNOWN, src, expl
            else:
                return res, src, expl

        # Fallback: cannot ground condition in verifiable physics or state
        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"Condition '{condition_str}' cannot be grounded in observable state or physics"

    @staticmethod
    def evaluate_condition_string(
        condition_str: str,
        target: str,
        task_desc: str,
        current_obs: str,
        history_obs: List[str] = None
    ) -> Tuple[ConditionResult, str]:
        """
        Backward-compatible interface returning (ConditionResult, explanation_with_source).
        """
        res, src, expl = ConditionEvaluator.evaluate_condition_detailed(
            condition_str=condition_str,
            target=target,
            task_desc=task_desc,
            current_obs=current_obs,
            history_obs=history_obs
        )
        full_expl = f"{expl} [evidence_source: {src.value}]"
        return res, full_expl
