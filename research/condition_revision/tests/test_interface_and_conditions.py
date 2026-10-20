"""
Unit Test Suite for Interface Unification and Condition Semantics:
1. Trajectory Interface Round-Trip (ensures non-empty task description and executed actions reach extractor).
2. Subject-Location Semantics ('aluminum foil in workshop' does not match apricot).
3. Dynamic Physical State Precedence (water frozen in freezer evaluates to solid, not liquid).
4. Entity Attribute vs Physical Property Distinction (material prior vs empirical circuit observation).
5. Group B Memory Exposure & Demonstration Extraction.
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

        # Assertions
        self.assertIn("determine if aluminum foil is electrically conductive", prompt)
        self.assertNotIn("Action: 'None'", prompt)
        self.assertIn("Action: 'teleport to workshop'", prompt)
        self.assertIn("Action: 'focus on aluminum foil'", prompt)
        self.assertIn("Action: 'move aluminum foil to red box'", prompt)
        self.assertIn("Final Task Success: True", prompt)

    def test_aluminum_foil_in_workshop_not_matched_by_apricot(self):
        """
        Critical Semantic Test 1:
        'aluminum foil located in workshop' MUST NOT evaluate to TRUE
        when current target is apricot, even if apricot or agent is in workshop!
        """
        task_desc = "Your task is to determine if apricot is electrically conductive. The apricot is located around the workshop."
        target = "apricot"
        current_obs = "You are in the workshop. You see an apricot, a red box, a green box."

        # Condition specifying aluminum foil
        res, expl = ConditionEvaluator.evaluate_condition_string(
            condition_str="aluminum foil located in workshop",
            target=target,
            task_desc=task_desc,
            current_obs=current_obs
        )

        self.assertEqual(res, ConditionResult.FALSE, f"False positive match! expl: {expl}")
        self.assertIn("not observed", expl)

        # Condition specifying target or apricot SHOULD evaluate to TRUE
        res_target, expl_target = ConditionEvaluator.evaluate_condition_string(
            condition_str="target located in workshop",
            target=target,
            task_desc=task_desc,
            current_obs=current_obs
        )
        self.assertEqual(res_target, ConditionResult.TRUE, f"Target in workshop should be TRUE! expl: {expl_target}")

    def test_water_freezing_dynamic_observation_precedence(self):
        """
        Critical Semantic Test 2:
        When observation shows water is frozen in the freezer,
        is_target_liquid must return FALSE and is_target_solid must return TRUE!
        """
        target = "water"
        frozen_obs = "In the freezer, the water in the cup is frozen into ice at temperature -5 degrees celsius."

        res_liquid, src_liquid, expl_liquid = ConditionEvaluator.is_target_liquid(target, frozen_obs)
        self.assertEqual(res_liquid, ConditionResult.FALSE, "Frozen water should not evaluate as liquid!")
        self.assertEqual(src_liquid, EvidenceSource.CURRENT_OBSERVATION)

        res_solid, src_solid, expl_solid = ConditionEvaluator.is_target_solid(target, frozen_obs)
        self.assertEqual(res_solid, ConditionResult.TRUE, "Frozen water must evaluate as solid!")
        self.assertEqual(src_solid, EvidenceSource.CURRENT_OBSERVATION)

        # When observation has no thermal clues, default prior kicks in
        ambient_obs = "You see a cup of water on the kitchen table."
        res_amb_liq, src_amb_liq, expl_amb_liq = ConditionEvaluator.is_target_liquid(target, ambient_obs)
        self.assertEqual(res_amb_liq, ConditionResult.TRUE)
        self.assertEqual(src_amb_liq, EvidenceSource.PRIOR_KNOWLEDGE)

    def test_entity_attribute_vs_physical_property_distinction(self):
        """
        Critical Semantic Test 3:
        Distinguish entity attribute (is_metal) from physical property (is_conductive).
        Prior dictionary lookups must be recorded as prior_knowledge / prior_inference_untested,
        not current_observation!
        """
        # 1. Attribute: is_target_metal
        res_metal, src_metal, _ = ConditionEvaluator.is_target_metal("aluminum foil", "You see a piece of aluminum foil.")
        self.assertEqual(res_metal, ConditionResult.TRUE)
        self.assertEqual(src_metal, EvidenceSource.PRIOR_KNOWLEDGE)

        res_apricot_metal, src_apricot_metal, _ = ConditionEvaluator.is_target_metal("apricot", "You see an apricot.")
        self.assertEqual(res_apricot_metal, ConditionResult.FALSE)
        self.assertEqual(src_apricot_metal, EvidenceSource.PRIOR_KNOWLEDGE)

        # 2. Property: is_target_conductive without empirical test
        res_cond, src_cond, expl_cond = ConditionEvaluator.is_target_conductive("aluminum foil", "You see a piece of aluminum foil.")
        self.assertEqual(res_cond, ConditionResult.TRUE)
        self.assertEqual(src_cond, EvidenceSource.PRIOR_INFERENCE_UNTESTED)
        self.assertIn("prior", expl_cond.lower())

        # 3. Property: is_target_conductive WITH empirical test in observation
        tested_obs = "You close the circuit with the wire. The light bulb turns on."
        res_emp, src_emp, expl_emp = ConditionEvaluator.is_target_conductive("aluminum foil", tested_obs)
        self.assertEqual(res_emp, ConditionResult.TRUE)
        self.assertEqual(src_emp, EvidenceSource.CURRENT_OBSERVATION)

    def test_group_b_trajectory_retrieval_memory_exposure(self):
        """
        Verify that Group B correctly sets active_memory with full demonstration details
        when past trajectory is retrieved, and does not produce 'None' actions.
        """
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
