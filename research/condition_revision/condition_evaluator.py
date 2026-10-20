"""
Condition Evaluator Module for Counterexample-Driven Condition Revision.
Provides:
1. Grounded predicate evaluation returning ConditionResult (TRUE, FALSE, UNKNOWN).
2. Entity binding: binds conditions specifically to the task's target object.
3. Decoupling of retrieval/recall from applicability condition verification.
4. Step-level re-evaluation to dynamically retract invalid rules.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set
import re


class ConditionResult(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


# Known material categories grounded in ScienceWorld semantics
CONDUCTIVE_MATERIALS = {
    "aluminum", "copper", "iron", "steel", "gold", "silver", "brass", "metal",
    "foil", "aluminum foil", "metal fork", "copper wire", "key", "metal spoon", "penny", "wire"
}

NON_CONDUCTIVE_MATERIALS = {
    "wood", "plastic", "rubber", "glass", "paper", "cloth", "ceramic", "cotton",
    "apricot", "apple", "banana", "fruit", "book", "glass jar", "rubber band",
    "plastic cup", "wood block", "chalk", "soap", "sponge"
}

LIQUID_SUBSTANCES = {
    "water", "orange juice", "juice", "milk", "oil", "vinegar", "soapy water", "salt water"
}

SOLID_SUBSTANCES = {
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
    Returns ConditionResult.TRUE, ConditionResult.FALSE, or ConditionResult.UNKNOWN.
    """

    @staticmethod
    def is_target_metal(target: str, obs_text: str = "") -> ConditionResult:
        target_lower = target.lower().strip()
        obs_lower = obs_text.lower()
        
        # Check target name directly
        for m in CONDUCTIVE_MATERIALS:
            if m in target_lower:
                return ConditionResult.TRUE
        for non_m in NON_CONDUCTIVE_MATERIALS:
            if non_m in target_lower:
                return ConditionResult.FALSE
                
        # Check observation context if target description gives evidence
        if f"{target_lower} made of metal" in obs_lower or f"metallic {target_lower}" in obs_lower:
            return ConditionResult.TRUE
        if f"{target_lower} made of plastic" in obs_lower or f"{target_lower} made of glass" in obs_lower:
            return ConditionResult.FALSE

        return ConditionResult.UNKNOWN

    @staticmethod
    def is_target_liquid(target: str, obs_text: str = "") -> ConditionResult:
        target_lower = target.lower().strip()
        obs_lower = obs_text.lower()
        
        for l in LIQUID_SUBSTANCES:
            if l in target_lower:
                return ConditionResult.TRUE
        for s in SOLID_SUBSTANCES:
            if s in target_lower:
                return ConditionResult.FALSE
                
        if "liquid" in obs_lower and target_lower in obs_lower:
            return ConditionResult.TRUE
        if "solid" in obs_lower and target_lower in obs_lower:
            return ConditionResult.FALSE

        return ConditionResult.UNKNOWN

    @staticmethod
    def is_target_solid(target: str, obs_text: str = "") -> ConditionResult:
        res = ConditionEvaluator.is_target_liquid(target, obs_text)
        if res == ConditionResult.TRUE:
            return ConditionResult.FALSE
        elif res == ConditionResult.FALSE:
            return ConditionResult.TRUE
        return ConditionResult.UNKNOWN

    @staticmethod
    def is_target_living(target: str, obs_text: str = "") -> ConditionResult:
        target_lower = target.lower().strip()
        for lt in LIVING_THINGS:
            if lt in target_lower:
                return ConditionResult.TRUE
        for nlt in NON_LIVING_THINGS:
            if nlt in target_lower:
                return ConditionResult.FALSE
        return ConditionResult.UNKNOWN

    @staticmethod
    def is_target_present(target: str, obs_text: str) -> ConditionResult:
        if not target or target == "unknown_target":
            return ConditionResult.UNKNOWN
        target_lower = target.lower().strip()
        obs_lower = obs_text.lower()
        if target_lower in obs_lower:
            return ConditionResult.TRUE
        return ConditionResult.FALSE

    @staticmethod
    def evaluate_condition_string(
        condition_str: str,
        target: str,
        task_desc: str,
        current_obs: str,
        history_obs: List[str] = None
    ) -> Tuple[ConditionResult, str]:
        """
        Parses and evaluates a condition string bound to the target entity.
        Returns (ConditionResult, explanation).
        """
        cond_lower = condition_str.lower().strip()
        combined_obs = " ".join([current_obs] + (history_obs or []))
        
        # 1. Material / Conductivity Constraints
        if any(w in cond_lower for w in ["metal", "metallic", "conductive", "conductor"]):
            if "not" in cond_lower or "non" in cond_lower:
                # Target must not be metal
                res = ConditionEvaluator.is_target_metal(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, f"Target '{target}' is metal, violating condition '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, f"Target '{target}' is verified non-metallic"
                return ConditionResult.UNKNOWN, f"Cannot verify if '{target}' is non-metallic from observation"
            else:
                # Target must be metal
                res = ConditionEvaluator.is_target_metal(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.TRUE, f"Target '{target}' is confirmed metal"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.FALSE, f"Target '{target}' is non-metallic, violating condition '{condition_str}'"
                return ConditionResult.UNKNOWN, f"Cannot verify if '{target}' is metal from observation"

        # 2. State of Matter Constraints (Liquid / Solid / Gas)
        if "liquid" in cond_lower:
            if "not" in cond_lower:
                res = ConditionEvaluator.is_target_liquid(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, f"Target '{target}' is liquid, violating condition '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, f"Target '{target}' is not liquid"
                return ConditionResult.UNKNOWN, f"State of matter for '{target}' is unknown"
            else:
                res = ConditionEvaluator.is_target_liquid(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.TRUE, f"Target '{target}' is confirmed liquid"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.FALSE, f"Target '{target}' is not liquid, violating condition '{condition_str}'"
                return ConditionResult.UNKNOWN, f"State of matter for '{target}' is unknown"

        if "solid" in cond_lower or "ice" in cond_lower:
            if "not" in cond_lower:
                res = ConditionEvaluator.is_target_solid(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, f"Target '{target}' is solid, violating condition '{condition_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, f"Target '{target}' is not solid"
                return ConditionResult.UNKNOWN, f"Cannot determine if '{target}' is solid"
            else:
                res = ConditionEvaluator.is_target_solid(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.TRUE, f"Target '{target}' is confirmed solid"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.FALSE, f"Target '{target}' is not solid, violating condition '{condition_str}'"
                return ConditionResult.UNKNOWN, f"Cannot determine if '{target}' is solid"

        # 3. Target Presence Constraint
        if "present" in cond_lower or "available" in cond_lower or "located" in cond_lower:
            # Check target presence
            if target.lower() in cond_lower or "target" in cond_lower or "object" in cond_lower or "item" in cond_lower:
                res = ConditionEvaluator.is_target_present(target, combined_obs)
                if res == ConditionResult.TRUE:
                    return ConditionResult.TRUE, f"Target '{target}' is present in observed environment"
                else:
                    return ConditionResult.FALSE, f"Target '{target}' is not present in observed environment"
            # Generic container presence (e.g. red box, stove)
            for container in ["red box", "green box", "stove", "freezer", "kitchen", "workshop"]:
                if container in cond_lower:
                    if container in combined_obs.lower() or container in task_desc.lower():
                        return ConditionResult.TRUE, f"Required container/location '{container}' is present"
                    else:
                        return ConditionResult.UNKNOWN, f"Container/location '{container}' not yet observed"

        # 4. Fallback: If condition cannot be grounded in observable facts
        return ConditionResult.UNKNOWN, f"Condition '{condition_str}' cannot be grounded in current observable state"
