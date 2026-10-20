"""
Condition Evaluator Module for Counterexample-Driven Condition Revision.
Provides:
1. Grounded predicate evaluation returning ConditionResult (TRUE, FALSE, UNKNOWN).
2. Explicit subject binding: distinguishes rule's specified subject from task's target object.
3. Target-specific observation binding: other objects' state (e.g. ice in freezer) does NOT alter target's state (water).
4. Strict precedence of current observation over historical observation.
5. Strict word boundary matching: 'non-living' is never preempted by 'living'.
6. Empirical conductivity binding: electrical test results only apply to objects bound to the circuit.
7. Unobserved state returns UNKNOWN rather than FALSE.
8. Compound conditions are evaluated conjunctively.
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
    "foil", "aluminum foil", "metal fork", "copper wire", "key", "metal spoon", "penny", "wire", "pot"
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
    "fork", "foil", "book", "wire", "battery", "light bulb", "water", "ice", "glass", "substance",
    "apricot", "apple", "banana", "fruit", "wood block", "glass jar", "rubber band"
}

KNOWN_ROOMS = {"workshop", "kitchen", "bathroom", "bedroom", "living room", "hallway", "greenhouse", "outside", "art studio", "foundry"}
KNOWN_CONTAINERS = {"red box", "green box", "stove", "freezer", "refrigerator", "cupboard", "sink", "pot", "counter", "table"}


def extract_target_entity(task_desc: str) -> str:
    """
    Extract the primary target object name from a ScienceWorld task description.
    e.g. 'determine if aluminum foil is electrically conductive' -> 'aluminum foil'
         'melt ice' -> 'ice'
         'boil water' -> 'water'
         'power red light bulb' -> 'red light bulb'
    """
    desc_lower = task_desc.lower()

    # Pattern 1: melt / boil / freeze / change the state of matter of X
    m = re.search(r"\b(?:melt|boil|freeze|change the state of matter of)\s+([a-z0-9\s\-]+?)(?:\s+in|\s+to|\.|$)", desc_lower)
    if m:
        t = m.group(1).strip()
        if t not in ["substance", "item", "object", "target", "something"]:
            return t

    # Pattern 2: determine if X is ...
    m = re.search(r"determine if ([a-z0-9\s\-]+?) is (?:electrically|conductive|living)", desc_lower)
    if m:
        return m.group(1).strip()

    # Pattern 3: focus on the X (filter out generic placeholder nouns)
    m = re.search(r"first, focus on the ([a-z0-9\s\-]+?)\.", desc_lower)
    if m:
        t = m.group(1).strip()
        if t not in ["substance", "item", "object", "target", "something"]:
            return t

    # Pattern 4: power X
    m = re.search(r"\bpower\s+([a-z0-9\s\-]+?)(?:\.|$)", desc_lower)
    if m:
        return m.group(1).strip()

    # Fallback: check if known targets appear in task_desc
    for cand in ["aluminum foil", "metal fork", "glass jar", "apricot", "apple", "ice", "water", "chocolate", "orange juice"]:
        if cand in desc_lower:
            return cand

    if "living thing" in desc_lower:
        return "living thing"

    return "unknown_target"


def extract_target_clauses(target: str, text: str) -> List[str]:
    """Extract sentences or clause fragments that specifically mention the target entity."""
    if not text:
        return []
    target_lower = target.lower().strip()
    # Split text into sentences, semicolons, and coordinate clause boundaries
    sentences = re.split(r"[.\n;]|\b,\s*(?:and|while|but|whereas)\b", text, flags=re.IGNORECASE)
    matched = []
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        if target_lower in s_clean.lower():
            matched.append(s_clean.lower())
    return matched


class ConditionEvaluator:
    """
    Evaluates condition predicates against target entity and observable state.
    Strictly adheres to:
    - Target-specific clause binding (no bleeding from other objects)
    - Dynamic observation precedence over static prior
    - Strict word boundary parsing for negation
    - Target-bound empirical conductivity checking
    - Grounded 3-valued logic (TRUE, FALSE, UNKNOWN)
    """

    @staticmethod
    def is_target_metal(target: str, obs_text: str = "", history_obs: List[str] = None) -> Tuple[ConditionResult, EvidenceSource, str]:
        target_lower = target.lower().strip()
        target_clauses = extract_target_clauses(target, obs_text)

        # 1. Perceptual observation on target in current observation
        for clause in target_clauses:
            # Check negative predicates first with strict regex boundaries
            if re.search(r"\b(?:non[- ]?metallic|non[- ]?metal|not metal|not metallic|made of plastic|made of glass|made of wood)\b", clause):
                return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation explicitly states '{target}' is non-metallic"
            if re.search(r"(?<!non-)(?<!non )(?<!not )\b(?:made of metal|metallic|metal)\b", clause):
                return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation explicitly states '{target}' is metallic"

        # 2. History check
        if history_obs:
            for h in reversed(history_obs):
                h_clauses = extract_target_clauses(target, h)
                for clause in h_clauses:
                    if re.search(r"\b(?:non[- ]?metallic|non[- ]?metal|not metal|not metallic|made of plastic|made of glass|made of wood)\b", clause):
                        return ConditionResult.FALSE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation states '{target}' is non-metallic"
                    if re.search(r"(?<!non-)(?<!non )(?<!not )\b(?:made of metal|metallic|metal)\b", clause):
                        return ConditionResult.TRUE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation states '{target}' is metallic"

        # 3. Prior knowledge dictionary (explicitly documented as prior, not perceptual)
        for m in METAL_MATERIALS:
            if re.search(rf"\b{re.escape(m)}\b", target_lower):
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred from prior material knowledge dictionary (material: metal), unverified by sensor"
        for non_m in NON_METAL_MATERIALS:
            if re.search(rf"\b{re.escape(non_m)}\b", target_lower):
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
        CRITICAL:
        1. Light bulb turning on only proves conductivity IF the circuit was tested with the TARGET entity!
        2. Historical wiring and light bulb states at other moments cannot be arbitrarily spliced together.
        """
        target_lower = target.lower().strip()
        target_clauses = extract_target_clauses(target, obs_text)

        # 1. Direct explicit statement in current observation
        for clause in target_clauses:
            if any(p in clause for p in ["is conductive", "conducts electricity"]):
                return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation states '{target}' is conductive"
            if any(p in clause for p in ["is non-conductive", "does not conduct electricity"]):
                return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation states '{target}' is non-conductive"

        # 2. Chronological circuit tracing across history and current observation
        all_steps = (history_obs or []) + ([obs_text] if obs_text else [])
        test_indicators = ["light bulb turns on", "light turns on", "bulb is on", "bulb turns on", "current flows"]

        target_in_circuit = False
        valid_empirical_test = False
        valid_test_source = None
        valid_test_expl = ""

        for i, step_text in enumerate(all_steps):
            step_lower = step_text.lower()
            is_current_step = (i == len(all_steps) - 1)

            # Check target connection event
            if (
                f"connected to {target_lower}" in step_lower or
                f"on {target_lower} is now connected" in step_lower or
                f"connect {target_lower}" in step_lower
            ):
                target_in_circuit = True

            # Check target disconnection event
            if (
                f"disconnecting {target_lower}" in step_lower or
                f"disconnect {target_lower}" in step_lower
            ):
                target_in_circuit = False

            # Check if circuit activated at this exact step
            bulb_active = any(ind in step_lower for ind in test_indicators)
            if bulb_active:
                if target_in_circuit:
                    valid_empirical_test = True
                    valid_test_source = EvidenceSource.CURRENT_OBSERVATION if is_current_step else EvidenceSource.HISTORICAL_OBSERVATION
                    valid_test_expl = f"Empirical circuit test bound to '{target}' produced active current/light while target was actively connected"
                else:
                    # Bulb was active, but target was NOT in the circuit!
                    # Do NOT attribute this activation to target!
                    pass

        if valid_empirical_test:
            return ConditionResult.TRUE, valid_test_source, valid_test_expl

        # 3. Prior knowledge inference (explicitly stamped as prior_inference_untested)
        if allow_prior_inference:
            is_m, src, expl = ConditionEvaluator.is_target_metal(target, obs_text, history_obs)
            if is_m == ConditionResult.TRUE:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_INFERENCE_UNTESTED, f"Inferred electrical conductivity from metal material prior without empirical circuit test"
            elif is_m == ConditionResult.FALSE:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_INFERENCE_UNTESTED, f"Inferred non-conductivity from non-metal material prior without empirical circuit test"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"No empirical conductivity test bound to '{target}' recorded"

    @staticmethod
    def is_target_liquid(target: str, obs_text: str = "", history_obs: List[str] = None) -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Evaluates whether target is currently in liquid state.
        CRITICAL:
        1. Only clauses mentioning target (or its immediate container) provide dynamic phase evidence.
        2. Current observation strictly overrides older history.
        """
        target_lower = target.lower().strip()
        target_clauses = extract_target_clauses(target, obs_text)

        # 1. Dynamic evidence from CURRENT observation on target
        if target_clauses:
            for clause in target_clauses:
                if any(clue in clause for clue in ["frozen", "freezes", "froze", "solidified", "solid ice", "ice cube", "temperature -"]):
                    return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation confirms '{target}' is frozen solid, not liquid"
                if any(clue in clause for clue in ["steam", "gas", "vapor", "boiled away", "evaporated"]):
                    return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation confirms '{target}' is gaseous, not liquid"
                if any(clue in clause for clue in ["liquid", "melted", "fluid"]):
                    return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation confirms '{target}' is in liquid state"

        # 2. Dynamic evidence from RECENT history on target (most recent first)
        if history_obs:
            for h in reversed(history_obs):
                h_clauses = extract_target_clauses(target, h)
                for clause in h_clauses:
                    if any(clue in clause for clue in ["frozen", "freezes", "froze", "solidified", "solid ice", "ice cube", "temperature -"]):
                        return ConditionResult.FALSE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation confirms '{target}' was frozen solid"
                    if any(clue in clause for clue in ["steam", "gas", "vapor", "boiled away", "evaporated"]):
                        return ConditionResult.FALSE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation confirms '{target}' was gaseous"
                    if any(clue in clause for clue in ["liquid", "melted", "fluid"]):
                        return ConditionResult.TRUE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation confirms '{target}' was liquid"

        # 3. Static Default Prior (Only when NO dynamic clues exist for target)
        for l in LIQUID_DEFAULT_SUBSTANCES:
            if l in target_lower:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default liquid state for '{target}' from prior knowledge (unverified dynamically)"
        for s in SOLID_DEFAULT_SUBSTANCES:
            if s in target_lower:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default solid state for '{target}' from prior knowledge (unverified dynamically)"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"State of matter for '{target}' cannot be determined from observation or prior knowledge"

    @staticmethod
    def is_target_solid(target: str, obs_text: str = "", history_obs: List[str] = None) -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Evaluates whether target is currently in solid state.
        Strictly bound to target clauses, with current obs taking precedence.
        """
        target_lower = target.lower().strip()
        target_clauses = extract_target_clauses(target, obs_text)

        # 1. Dynamic evidence from CURRENT observation on target
        if target_clauses:
            for clause in target_clauses:
                if any(clue in clause for clue in ["frozen", "freezes", "froze", "solidified", "solid", "ice cube", "temperature -"]):
                    return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation confirms '{target}' is solid"
                if any(clue in clause for clue in ["melted", "liquid", "fluid"]):
                    return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation confirms '{target}' is liquid, not solid"
                if any(clue in clause for clue in ["steam", "gas", "vapor"]):
                    return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Current observation confirms '{target}' is gas, not solid"

        # 2. Dynamic evidence from RECENT history on target
        if history_obs:
            for h in reversed(history_obs):
                h_clauses = extract_target_clauses(target, h)
                for clause in h_clauses:
                    if any(clue in clause for clue in ["frozen", "freezes", "froze", "solidified", "solid", "ice cube", "temperature -"]):
                        return ConditionResult.TRUE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation confirms '{target}' was solid"
                    if any(clue in clause for clue in ["melted", "liquid", "fluid"]):
                        return ConditionResult.FALSE, EvidenceSource.HISTORICAL_OBSERVATION, f"Historical observation confirms '{target}' was liquid"

        # 3. Static Default Prior
        for s in SOLID_DEFAULT_SUBSTANCES:
            if s in target_lower:
                return ConditionResult.TRUE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default solid state for '{target}' from prior knowledge"
        for l in LIQUID_DEFAULT_SUBSTANCES:
            if l in target_lower:
                return ConditionResult.FALSE, EvidenceSource.PRIOR_KNOWLEDGE, f"Inferred default liquid state for '{target}' from prior knowledge"

        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"Cannot determine if '{target}' is solid"

    @staticmethod
    def is_target_living(target: str, obs_text: str = "", history_obs: List[str] = None) -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Evaluates whether target is living matter.
        CRITICAL: Checks 'non-living' FIRST before 'living' to avoid substring preemption!
        """
        target_lower = target.lower().strip()
        combined_obs = " ".join([obs_text] + (history_obs or [])).lower()

        # Check observation with strict word boundary
        target_clauses = extract_target_clauses(target, combined_obs)
        for clause in target_clauses:
            if re.search(r"\bnon[- ]?living\b", clause):
                return ConditionResult.FALSE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly states '{target}' is non-living"
            if re.search(r"\bliving\b", clause):
                return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, f"Observation explicitly states '{target}' is living"

        # Prior dictionary check
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
        Handles subject-location semantics.
        Adheres to:
        - If location has not been observed/visited, returns UNKNOWN (not FALSE).
        - If condition subject contradicts current target, returns FALSE (subject mismatch).
        - If subject is verified in location, returns TRUE.
        """
        cond_lower = condition_str.lower().strip()
        obs_lower = current_obs.lower()
        desc_lower = task_desc.lower()
        all_obs = " ".join([current_obs] + (history_obs or [])).lower()

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

        # Determine subject specified in condition, checking longer phrases first
        all_entities = sorted(
            list(METAL_MATERIALS | NON_METAL_MATERIALS | LIQUID_DEFAULT_SUBSTANCES | SOLID_DEFAULT_SUBSTANCES),
            key=len,
            reverse=True
        )
        subject = None
        for m in all_entities:
            if re.search(rf"\b{re.escape(m)}\b", cond_lower) and m != found_loc:
                subject = m
                break

        if subject is None:
            subject = current_target.lower()

        # Check if the location has been observed/visited at all
        # The agent is in found_loc if found_loc is in current_obs (e.g. "This room is called the <found_loc>")
        agent_in_loc = (
            f"called the {found_loc}" in obs_lower or
            f"you are in the {found_loc}" in obs_lower or
            f"teleport to the {found_loc}" in all_obs or
            found_loc in obs_lower
        )

        subject_in_obs = (subject in obs_lower)
        target_in_obs = (current_target.lower() in obs_lower)

        # Check if subject matches current_target (exact or substring/synonym e.g. "foil" and "aluminum foil")
        is_subject_match = (
            subject == current_target.lower() or
            subject in current_target.lower() or
            current_target.lower() in subject
        )

        # Case 1: Subject Mismatch (Condition specifies a specific object different from task target)
        if not is_subject_match:
            if not subject_in_obs:
                return (
                    ConditionResult.FALSE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Rule subject '{subject}' does not match task target '{current_target}'"
                )
            else:
                return (
                    ConditionResult.TRUE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Subject '{subject}' is observed in environment"
                )

        # Case 2: Subject matches current_target
        if not agent_in_loc:
            # Location has NOT been observed yet! Evidence is insufficient, return UNKNOWN!
            return (
                ConditionResult.UNKNOWN,
                EvidenceSource.INSUFFICIENT_EVIDENCE,
                f"Location '{found_loc}' has not been visited or observed yet (evidence insufficient)"
            )

        if subject_in_obs:
            return (
                ConditionResult.TRUE,
                EvidenceSource.CURRENT_OBSERVATION,
                f"Target '{subject}' and location '{found_loc}' both verified in current observation"
            )
        else:
            # Check if observation explicitly declares absence (e.g. empty container / nothing)
            explicit_absence_patterns = [
                r"\bcontains nothing\b",
                r"\bempty\b",
                rf"\bno {re.escape(subject)}\b",
                r"\bthere is nothing\b",
                r"\bcontaining nothing\b"
            ]
            if any(re.search(pat, obs_lower) for pat in explicit_absence_patterns):
                return (
                    ConditionResult.FALSE,
                    EvidenceSource.CURRENT_OBSERVATION,
                    f"Target '{subject}' is explicitly confirmed absent in '{found_loc}'"
                )
            # Otherwise: simply not mentioned in current observation text is NOT evidence of non-existence!
            return (
                ConditionResult.UNKNOWN,
                EvidenceSource.INSUFFICIENT_EVIDENCE,
                f"Target '{subject}' is not mentioned in current observation of '{found_loc}' (absence of mention is insufficient evidence of non-existence)"
            )

    @staticmethod
    def evaluate_atomic_condition(
        cond_str: str,
        target: str,
        task_desc: str,
        current_obs: str,
        history_obs: List[str] = None
    ) -> Tuple[ConditionResult, EvidenceSource, str]:
        """Evaluates a single atomic condition clause."""
        cond_lower = cond_str.lower().strip()

        # 1. Location / presence check
        loc_res = ConditionEvaluator.evaluate_subject_location(cond_str, target, task_desc, current_obs, history_obs)
        if loc_res is not None:
            return loc_res

        # 2. Material Constraints (Metal / Non-Metal)
        if any(w in cond_lower for w in ["metal", "metallic"]):
            is_neg = bool(re.search(r"\b(?:not|non)\b", cond_lower))
            res, src, expl = ConditionEvaluator.is_target_metal(target, current_obs, history_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is metal, violating '{cond_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is verified non-metal"
                return ConditionResult.UNKNOWN, src, expl
            return res, src, expl

        # 3. Physical Property: Electrical Conductivity
        if any(w in cond_lower for w in ["conductive", "conductor"]):
            is_neg = bool(re.search(r"\b(?:not|non)\b", cond_lower))
            res, src, expl = ConditionEvaluator.is_target_conductive(target, current_obs, history_obs, allow_prior_inference=True)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is conductive, violating '{cond_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is non-conductive"
                return ConditionResult.UNKNOWN, src, expl
            return res, src, expl

        # 4. State of Matter: Liquid
        if "liquid" in cond_lower:
            is_neg = bool(re.search(r"\b(?:not|non)\b", cond_lower))
            res, src, expl = ConditionEvaluator.is_target_liquid(target, current_obs, history_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is liquid, violating '{cond_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is not liquid"
                return ConditionResult.UNKNOWN, src, expl
            return res, src, expl

        # 5. State of Matter: Solid / Ice
        if "solid" in cond_lower or "ice" in cond_lower:
            is_neg = bool(re.search(r"\b(?:not|non)\b", cond_lower))
            res, src, expl = ConditionEvaluator.is_target_solid(target, current_obs, history_obs)
            if is_neg:
                if res == ConditionResult.TRUE:
                    return ConditionResult.FALSE, src, f"Target '{target}' is solid, violating '{cond_str}'"
                elif res == ConditionResult.FALSE:
                    return ConditionResult.TRUE, src, f"Target '{target}' is not solid"
                return ConditionResult.UNKNOWN, src, expl
            return res, src, expl

        # 6. Living Organism Constraints (Strict 'non-living' precedence)
        if re.search(r"\bnon[- ]?living\b", cond_lower):
            res, src, expl = ConditionEvaluator.is_target_living(target, current_obs, history_obs)
            if res == ConditionResult.FALSE:
                return ConditionResult.TRUE, src, f"Target '{target}' is confirmed non-living"
            elif res == ConditionResult.TRUE:
                return ConditionResult.FALSE, src, f"Target '{target}' is living, violating '{cond_str}'"
            return ConditionResult.UNKNOWN, src, expl

        if re.search(r"\bliving\b", cond_lower):
            return ConditionEvaluator.is_target_living(target, current_obs, history_obs)

        # Fallback: unsupported natural language predicate returns UNKNOWN
        return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, f"Condition '{cond_str}' is unsupported or cannot be grounded"

    @staticmethod
    def evaluate_condition_detailed(
        condition_str: str,
        target: str,
        task_desc: str,
        current_obs: str,
        history_obs: List[str] = None
    ) -> Tuple[ConditionResult, EvidenceSource, str]:
        """
        Compound-aware evaluator.
        Splits composite conditions on ' and ' or ';' and evaluates conjunctively.
        """
        # Split on conjunctions
        clauses = re.split(r"\s+and\s+|;\s*", condition_str, flags=re.IGNORECASE)
        if len(clauses) > 1:
            results = []
            explanations = []
            has_unknown = False
            for cl in clauses:
                cl_clean = cl.strip()
                if not cl_clean:
                    continue
                r, s, e = ConditionEvaluator.evaluate_atomic_condition(cl_clean, target, task_desc, current_obs, history_obs)
                results.append((r, s))
                explanations.append(f"[{cl_clean}: {r.value} ({e})]")
                if r == ConditionResult.FALSE:
                    # Conjunction fails immediately
                    return ConditionResult.FALSE, s, "; ".join(explanations)
                if r == ConditionResult.UNKNOWN:
                    has_unknown = True

            if has_unknown:
                return ConditionResult.UNKNOWN, EvidenceSource.INSUFFICIENT_EVIDENCE, "; ".join(explanations)
            return ConditionResult.TRUE, EvidenceSource.CURRENT_OBSERVATION, "; ".join(explanations)

        # Single atomic condition
        return ConditionEvaluator.evaluate_atomic_condition(condition_str, target, task_desc, current_obs, history_obs)

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
