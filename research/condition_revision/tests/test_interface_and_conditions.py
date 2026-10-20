"""
Comprehensive Unit Test Suite for Interface Unification and Condition Semantics:
1. Trajectory Interface Round-Trip (ensures non-empty task description and executed actions reach extractor).
2. Subject-Location Semantics ('aluminum foil in workshop' does not match apricot).
3. Dynamic Physical State Precedence (water frozen in freezer evaluates to solid, not liquid).
4. Entity Attribute vs Physical Property Distinction (material prior vs empirical circuit observation).
5. Group B Memory Exposure & Demonstration Extraction.
6. Target-specific isolation: Other objects' state (e.g. ice in freezer) does NOT alter target's state (water on table).
7. Negation and word boundary: 'non-living' is never preempted by 'living'.
8. Grounded electrical test: Light bulb on does not prove arbitrary target conductive unless bound to circuit.
9. Unobserved location returns UNKNOWN rather than FALSE.
10. Compound condition conjunction: All clauses evaluated, failing if any clause fails.
11. Current observation overrides older historical observation.
12. Target extraction for multi-step tasks (melt ice, boil water) correctly identifies specific substances.
"""

import sys
import os
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from condition_evaluator import ConditionEvaluator, ConditionResult, EvidenceSource, extract_target_entity
from experience_extractor import NaturalExperienceExtractor
from agents.trajectory_retrieval_agent import TrajectoryRetrievalAgent


class TestInterfaceAndConditions(unittest.TestCase):

    def test_trajectory_interface_prompt_formatting(self):
        """Verify that task description, executed actions, and observations enter the prompt without None."""
        extractor = NaturalExperienceExtractor(llm_client=None)

        sample_traj = {
            "episode_id": "test_ep_01",
            "task_name": "test-conductivity",
            "variation": 1,
            "task_desc": "Your task is to determine if aluminum foil is electrically conductive.",
            "success": True,
            "steps": [
                {
                    "step": 1,
                    "thought": "Need to go to workshop",
                    "model_action": "teleport to workshop",
                    "executed_action": "teleport to workshop",
                    "observation": "You teleport to the workshop."
                },
                {
                    "step": 2,
                    "thought": "Need to focus on aluminum foil",
                    "model_action": "focus on aluminum foil",
                    "executed_action": "focus on aluminum foil",
                    "observation": "You focus on the aluminum foil."
                },
                {
                    "step": 3,
                    "thought": "Move to red box",
                    "model_action": "move aluminum foil to red box",
                    "executed_action": "move aluminum foil to red box",
                    "observation": "You move aluminum foil to red box."
                }
            ]
        }

        prompt = extractor.format_extraction_prompt(sample_traj)

        self.assertIn("determine if aluminum foil is electrically conductive", prompt)
        self.assertNotIn("Action: 'None'", prompt)
        self.assertIn("Action: 'teleport to workshop'", prompt)
        self.assertIn("Action: 'focus on aluminum foil'", prompt)
        self.assertIn("Action: 'move aluminum foil to red box'", prompt)
        self.assertIn("Final Task Success: True", prompt)

    def test_aluminum_foil_in_workshop_not_matched_by_apricot(self):
        """Subject mismatch: condition specifying aluminum foil evaluates to FALSE when target is apricot."""
        task_desc = "Your task is to determine if apricot is electrically conductive. The apricot is located around the workshop."
        target = "apricot"
        current_obs = "You are in the workshop. You see an apricot, a red box, a green box."

        res, expl = ConditionEvaluator.evaluate_condition_string(
            condition_str="aluminum foil located in workshop",
            target=target,
            task_desc=task_desc,
            current_obs=current_obs
        )

        self.assertEqual(res, ConditionResult.FALSE)
        self.assertIn("does not match", expl.lower())

    def test_other_object_freezing_does_not_affect_water_liquid_state(self):
        """CRITICAL FIX 1: An ice cube in freezer does NOT alter liquid state of water on table."""
        target = "water"
        obs = "In the freezer, you see an ice cube that is frozen solid. On the kitchen counter, you see a cup of water."

        res_liquid, src_liquid, _ = ConditionEvaluator.is_target_liquid(target, obs)
        self.assertEqual(res_liquid, ConditionResult.TRUE, "Water on table must remain liquid even if ice cube is in freezer")

        res_solid, src_solid, _ = ConditionEvaluator.is_target_solid(target, obs)
        self.assertEqual(res_solid, ConditionResult.FALSE)

    def test_non_living_not_preempted_by_living(self):
        """CRITICAL FIX 2: 'non-living' must never be preempted by 'living' substring."""
        target = "apricot"
        obs = "You examine the apricot. The apricot is non-living matter."

        res_living, src_living, _ = ConditionEvaluator.is_target_living(target, obs)
        self.assertEqual(res_living, ConditionResult.FALSE, "apricot must evaluate as non-living (FALSE for is_target_living)")
        self.assertEqual(src_living, EvidenceSource.CURRENT_OBSERVATION)

        # Evaluator condition string check
        res_cond, expl = ConditionEvaluator.evaluate_condition_string("target is non-living", target, "", obs)
        self.assertEqual(res_cond, ConditionResult.TRUE, f"Condition 'target is non-living' should be TRUE: {expl}")

        res_cond_living, expl_l = ConditionEvaluator.evaluate_condition_string("target is living", target, "", obs)
        self.assertEqual(res_cond_living, ConditionResult.FALSE, f"Condition 'target is living' should be FALSE: {expl_l}")

    def test_bulb_on_does_not_prove_arbitrary_target_conductive(self):
        """CRITICAL FIX 3: Light bulb turning on only proves conductivity IF bound to target in circuit."""
        # Unrelated ceiling bulb
        target = "wood block"
        obs_unrelated = "In the ceiling, the light bulb is on. On the table, you see a wood block."
        res_unrel, src_unrel, _ = ConditionEvaluator.is_target_conductive(target, obs_unrelated, allow_prior_inference=False)
        self.assertEqual(res_unrel, ConditionResult.UNKNOWN, "Ceiling light should not prove wood block conductive")

        # Target properly bound to circuit
        target_metal = "aluminum foil"
        obs_connected = "terminal 1 on aluminum foil is now connected to battery. The light bulb turns on."
        res_conn, src_conn, _ = ConditionEvaluator.is_target_conductive(target_metal, obs_connected, allow_prior_inference=False)
        self.assertEqual(res_conn, ConditionResult.TRUE, "Target bound to circuit with active light should be TRUE")
        self.assertEqual(src_conn, EvidenceSource.CURRENT_OBSERVATION)

    def test_unobserved_object_location_returns_unknown_not_false(self):
        """CRITICAL FIX 4: If location has not been visited/observed yet, return UNKNOWN, not FALSE."""
        target = "aluminum foil"
        current_obs = "This room is called the hallway. In it you see a picture."

        res, expl = ConditionEvaluator.evaluate_condition_string(
            condition_str="aluminum foil located in workshop",
            target=target,
            task_desc="find aluminum foil",
            current_obs=current_obs
        )

        self.assertEqual(res, ConditionResult.UNKNOWN, f"Unvisited workshop must return UNKNOWN, got: {res} ({expl})")
        self.assertIn("insufficient", expl.lower())

    def test_compound_conditions_all_evaluated(self):
        """CRITICAL FIX 5: Compound conditions must evaluate all clauses conjunctively."""
        target = "aluminum foil"
        current_obs = "You are in the workshop. This room is called the workshop. You see a piece of aluminum foil."

        # Case A: Location TRUE and Material TRUE -> TRUE
        res_a, expl_a = ConditionEvaluator.evaluate_condition_string(
            condition_str="aluminum foil located in workshop and aluminum foil is metal",
            target=target,
            task_desc="test aluminum foil",
            current_obs=current_obs
        )
        self.assertEqual(res_a, ConditionResult.TRUE, f"Expected TRUE, got: {res_a} ({expl_a})")

        # Case B: Location TRUE but Material FALSE -> FALSE
        res_b, expl_b = ConditionEvaluator.evaluate_condition_string(
            condition_str="aluminum foil located in workshop and aluminum foil is non-metal",
            target=target,
            task_desc="test aluminum foil",
            current_obs=current_obs
        )
        self.assertEqual(res_b, ConditionResult.FALSE, f"Expected FALSE, got: {res_b} ({expl_b})")

    def test_current_state_overrides_older_history_state(self):
        """CRITICAL FIX 6: Current observation of freezing strictly overrides older liquid history."""
        target = "water"
        history_obs = ["You see liquid water in the pot."]
        current_obs = "In the freezer, the water in the pot is frozen into solid ice."

        res_solid, src_solid, _ = ConditionEvaluator.is_target_solid(target, current_obs, history_obs)
        self.assertEqual(res_solid, ConditionResult.TRUE)
        self.assertEqual(src_solid, EvidenceSource.CURRENT_OBSERVATION)

        res_liquid, src_liquid, _ = ConditionEvaluator.is_target_liquid(target, current_obs, history_obs)
        self.assertEqual(res_liquid, ConditionResult.FALSE)
        self.assertEqual(src_liquid, EvidenceSource.CURRENT_OBSERVATION)

    def test_extract_target_entity_melt_and_boil(self):
        """Verify target entity extraction for multi-step tasks without being confused by 'substance'."""
        t_melt = extract_target_entity("Your task is to melt ice. First, focus on the substance. Then change its state.")
        self.assertEqual(t_melt, "ice")

        t_boil = extract_target_entity("Your task is to boil water. First, focus on the substance. Then heat it.")
        self.assertEqual(t_boil, "water")

        t_cond = extract_target_entity("Your task is to determine if aluminum foil is electrically conductive.")
        self.assertEqual(t_cond, "aluminum foil")

    def test_group_b_trajectory_retrieval_memory_exposure(self):
        """Verify Group B sets active_memory and non-null actions."""
        past_trajs = [
            {
                "task_name": "test-conductivity",
                "variation": 1,
                "task_desc": "Your task is to determine if aluminum foil is electrically conductive.",
                "success": True,
                "steps": [
                    {"step": 1, "executed_action": "teleport to workshop", "observation": "You teleport."},
                    {"step": 2, "executed_action": "focus on aluminum foil", "observation": "You focus."},
                    {"step": 3, "executed_action": "move aluminum foil to red box", "observation": "Done."}
                ]
            }
        ]

        agent = TrajectoryRetrievalAgent(llm_client=None, trajectory_store=past_trajs)
        ref_text, mem_info = agent.retrieve_relevant_trajectory("determine if apricot is electrically conductive")

        self.assertIsNotNone(mem_info)
        self.assertEqual(mem_info["type"], "raw_trajectory")
        self.assertEqual(mem_info["retrieved_task"], "test-conductivity")
        self.assertIn("Action: teleport to workshop", mem_info["exposure_text"])
        self.assertNotIn("Action: None", mem_info["exposure_text"])


if __name__ == "__main__":
    unittest.main()
