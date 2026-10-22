"""
Offline test suite for RemoteLLMClient, BaseAgent action_templates mode,
ScienceWorldWrapper get_action_templates, DeepSeek parameters, and budget tracking.
"""

import os
import sys
import json
import pytest
from typing import Dict, Any, List

from remote_llm_client import (
    RemoteLLMClient,
    RemotePlannerError,
    ConfigurationError,
    NetworkAccessBlockedError,
    RemotePlannerTimeoutError,
    BudgetExceededError,
    PayloadSizeLimitExceededError,
)
from agents.base_agent import (
    BaseAgent,
    SCIENCEWORLD_ACTION_TEMPLATES,
    SYSTEM_PROMPT_ACTION_TEMPLATES,
)
import requests


def test_wrapper_get_action_templates():
    """Verifies that ScienceWorldWrapper exposes get_action_templates."""
    from env_wrapper import ScienceWorldWrapper
    # Mock underlying env without loading full heavyweight physics
    class MockInnerEnv:
        def get_possible_actions(self):
            return ["teleport OBJ", "focus on OBJ", "look around"]
    
    wrapper = ScienceWorldWrapper.__new__(ScienceWorldWrapper)
    wrapper.env = MockInnerEnv()
    templates = wrapper.get_action_templates()
    assert templates == ["teleport OBJ", "focus on OBJ", "look around"]


def test_base_agent_forbids_silent_fallback_when_templates_missing():
    """Verifies that BaseAgent in action_templates mode forbids silent fallback to hardcoded list."""
    client = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"action": "wait"}'}}]})
    agent = BaseAgent(llm_client=client, prompt_mode="action_templates", action_templates=None)
    
    with pytest.raises(ValueError) as exc:
        agent.select_action(
            task_desc="test",
            current_obs="obs",
            history=[],
            valid_actions=["wait"],
            action_templates=None  # Explicitly omitted
        )
    assert "silent fallback to hardcoded list is forbidden" in str(exc.value)


def test_fixed_accounting_case_first_40_10_retry_65_15():
    """
    Mandatory offline check:
    First attempt: input 40 / output 10 (invalid JSON)
    Retry attempt: input 65 / output 15 (valid JSON)
    Should return 2 calls, input 105, output 25.
    """
    call_count = 0

    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "choices": [{"message": {"role": "assistant", "content": "Thinking about picking up apple..."}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
            }
        else:
            return {
                "choices": [{"message": {"role": "assistant", "content": '{"thought": "ok", "action": "pick up apple"}'}}],
                "usage": {"prompt_tokens": 65, "completion_tokens": 15, "total_tokens": 80}
            }

    client = RemoteLLMClient(mock_transport=mock_transport)
    parsed, stats = client.generate_json("Take the apple", system_prompt="You are an assistant.")

    assert stats["calls"] == 2
    assert stats["total_calls"] == 2
    assert stats["input_tokens"] == 105
    assert stats["output_tokens"] == 25
    assert stats["total_tokens"] == 130
    assert stats["retry_attempted"] is True
    assert len(stats["attempts"]) == 2
    assert parsed["action"] == "pick up apple"
    assert client.total_calls == 2


def test_attempt_counted_on_timeout_or_error():
    """Verifies that sending to transport increments total_calls even if timeout or HTTP error occurs."""
    def timeout_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        raise requests.exceptions.Timeout("Read timeout")

    client = RemoteLLMClient(mock_transport=timeout_transport, timeout=10.0)
    assert client.total_calls == 0

    with pytest.raises(RemotePlannerTimeoutError):
        client.generate("hello", "sys")

    # Call attempt must be recorded!
    assert client.total_calls == 1
    # Cost for unknown failed request remains reserved conservatively
    assert client.unknown_reserved_cost_usd > 0.0


def test_deepseek_parameters_and_exclusion_of_temp_topp_seed():
    """Verifies that DeepSeek parameters are set and temperature/top_p/seed are NOT sent."""
    recorded_payloads = []

    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        recorded_payloads.append(payload)
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"action": "wait"}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
        }

    client = RemoteLLMClient(
        model_id="deepseek-flash",
        generation_params={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
            "max_tokens": 8192,
            "stream": False
        },
        mock_transport=mock_transport
    )

    client.generate("do something", "system prompt", max_new_tokens=256)

    assert len(recorded_payloads) == 1
    p = recorded_payloads[0]
    assert p["model"] == "deepseek-flash"
    assert p["thinking"] == {"type": "enabled"}
    assert p["reasoning_effort"] == "high"
    assert p["response_format"] == {"type": "json_object"}
    assert p["max_tokens"] == 8192  # Old 256 did NOT overwrite 8192!
    assert p["stream"] is False

    # Temperature, top_p, seed MUST NOT be present
    assert "temperature" not in p
    assert "top_p" not in p
    assert "seed" not in p


def test_action_parsed_only_from_content_never_reasoning_content():
    """Verifies that action is extracted strictly from message.content, not reasoning_content."""
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"thought": "final", "action": "teleport to workshop"}',
                        "reasoning_content": '{"thought": "hidden", "action": "focus on illegal_door"}'
                    }
                }
            ],
            "usage": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50}
        }

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=["teleport to workshop"])

    action, thought, stats, telemetry = agent.select_action("task", "obs", [], ["teleport to workshop"])
    assert action == "teleport to workshop"
    assert action != "focus on illegal_door"


def test_messages_payload_size_limit_32kib():
    """Verifies that payloads exceeding 32 KiB are rejected without sending."""
    client = RemoteLLMClient(mock_transport=lambda p: {"choices": []})
    giant_prompt = "x" * 35000  # > 32 KiB

    with pytest.raises(PayloadSizeLimitExceededError):
        client.generate(giant_prompt, "sys")
    assert client.total_calls == 0  # Was not sent to transport


def test_budget_reservation_and_enforcement():
    """Verifies that budget cannot be exceeded."""
    client = RemoteLLMClient(
        max_budget_usd=0.01,  # very tiny budget
        mock_transport=lambda p: {"choices": [{"message": {"content": '{"action": "look around"}'}}]}
    )

    # A single request with 8192 max tokens output at $2.19/1M requires ~$0.018 reservation
    # It should exceed $0.01 budget limit before sending
    with pytest.raises(BudgetExceededError) as exc:
        client.generate("hello", "sys")
    assert "Insufficient budget" in str(exc.value)


def test_native_action_passthrough_with_env_templates():
    """Verifies that environment templates enter prompt intact and native action is passed through."""
    recorded_prompts = []

    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        recorded_prompts.append(payload["messages"][-1]["content"])
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"thought": "Go", "action": "  focus on book  "}'}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        }

    client = RemoteLLMClient(mock_transport=mock_transport)
    custom_env_templates = ["activate OBJ", "focus on OBJ", "look around", "teleport OBJ"]
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=custom_env_templates)

    action, thought, stats, telemetry = agent.select_action("task desc", "obs", [], ["look around"])

    assert action == "focus on book"  # Whitespace stripped, no synonym conversion
    user_prompt = recorded_prompts[0]
    for tmpl in custom_env_templates:
        assert f"- {tmpl}" in user_prompt
    assert "Action Syntax Reference:" in user_prompt
    assert "These templates describe action syntax. They do not guarantee that an action is executable in the current state." in user_prompt


def test_conservative_byte_token_reservation_and_unbound_rejection():
    """Verifies that token reservation uses byte length + 1024 formatting overhead and rejects unbound requests."""
    client = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": "{}"}}]})
    
    # Valid payload should compute reservation >= len(bytes) + 1024
    payload = client._build_payload("Short prompt", system_prompt="Sys")
    msg_bytes_len = len(json.dumps(payload["messages"], ensure_ascii=False).encode("utf-8"))
    reserved = client._reserve_budget_for_request(payload)
    est_in_tokens = msg_bytes_len + 1024
    expected_reserved = (est_in_tokens / 1e6) * client.PRICE_PER_M_INPUT_MISS + (8192 / 1e6) * client.PRICE_PER_M_OUTPUT
    assert abs(reserved - expected_reserved) < 1e-9

    # Rejection when max_tokens is invalid
    bad_payload = dict(payload)
    bad_payload["max_tokens"] = None
    with pytest.raises(RemotePlannerError) as exc:
        client._reserve_budget_for_request(bad_payload)
    assert "Cannot establish reliable token upper bound" in str(exc.value)


def test_finish_reason_and_empty_content_tracking():
    """Verifies that finish_reason, empty_content, and hit_output_token_limit are recorded."""
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "choices": [{
                "message": {"role": "assistant", "content": '{"action": "wait"}'},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }

    client = RemoteLLMClient(mock_transport=mock_transport)
    parsed, stats = client.generate_json("Prompt", "Sys")
    assert stats["finish_reason"] == "stop"
    assert stats["empty_content"] is False
    assert stats["hit_output_token_limit"] is False
    assert stats["parse_error"] is False


def test_initial_cost_and_budget_continuation():
    """Verifies that client initializes with prior costs and enforces overall budget."""
    prior_cost = 0.126752
    client = RemoteLLMClient(
        max_budget_usd=0.14,  # only ~0.013 left
        initial_cost_usd=prior_cost,
        initial_calls=57,
        mock_transport=lambda p: {"choices": [{"message": {"content": "{}"}}]}
    )
    assert client.known_cost_usd == prior_cost
    assert client.total_calls == 57

    # Since 8192 output tokens reserve ~$0.018, having only 0.14 - 0.126752 = ~0.0132 left should raise BudgetExceededError
    with pytest.raises(BudgetExceededError) as exc:
        client.generate("test", "sys")
    assert "Insufficient budget" in str(exc.value)


def test_menu_blank_cancellation_protocol():
    """Offline fixtures verifying ambiguous menu blank cancellation vs error branches."""
    menu_obs = "Ambiguous request: Please enter the number for the action you intended (or blank to cancel):\n0:\tdunk cup\n1:\tdunk jar"
    normal_obs = "This room is called the kitchen."

    # 1. Blank string in ambiguous menu -> allowed, returns ""
    client1 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "cancel", "action": ""}'}}]})
    agent1 = BaseAgent(llm_client=client1, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act1, _, _, telem1 = agent1.select_action("task", menu_obs, [], ["wait"])
    assert act1 == ""
    assert telem1["adapter_reason"] == "menu_blank_cancellation"

    # 2. Whitespace-only string in ambiguous menu -> allowed, returns ""
    client2 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "cancel", "action": "   "}'}}]})
    agent2 = BaseAgent(llm_client=client2, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act2, _, _, telem2 = agent2.select_action("task", menu_obs, [], ["wait"])
    assert act2 == ""
    assert telem2["adapter_reason"] == "menu_blank_cancellation"

    # 3. Blank string in normal observation -> rejected as error, returns None
    client3 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "noop", "action": ""}'}}]})
    agent3 = BaseAgent(llm_client=client3, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act3, _, _, telem3 = agent3.select_action("task", normal_obs, [], ["wait"])
    assert act3 is None
    assert telem3["adapter_reason"] == "empty_or_non_string_terminate"

    # 4. Action missing in ambiguous menu -> rejected, returns None
    client4 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "cancel"}'}}]})
    agent4 = BaseAgent(llm_client=client4, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act4, _, _, telem4 = agent4.select_action("task", menu_obs, [], ["wait"])
    assert act4 is None
    assert telem4["adapter_reason"] == "empty_or_non_string_terminate"

    # 5. Action null in ambiguous menu -> rejected, returns None
    client5 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "cancel", "action": null}'}}]})
    agent5 = BaseAgent(llm_client=client5, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act5, _, _, telem5 = agent5.select_action("task", menu_obs, [], ["wait"])
    assert act5 is None
    assert telem5["adapter_reason"] == "empty_or_non_string_terminate"

    # 6. Action non-string (int) in ambiguous menu -> rejected, returns None
    client6 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "zero", "action": 0}'}}]})
    agent6 = BaseAgent(llm_client=client6, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act6, _, _, telem6 = agent6.select_action("task", menu_obs, [], ["wait"])
    assert act6 is None
    assert telem6["adapter_reason"] == "empty_or_non_string_terminate"

    # 7. Valid choice "0" in ambiguous menu -> passed through
    client7 = RemoteLLMClient(mock_transport=lambda p: {"choices": [{"message": {"content": '{"thought": "pick 0", "action": "0"}'}}]})
    agent7 = BaseAgent(llm_client=client7, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])
    act7, _, _, telem7 = agent7.select_action("task", menu_obs, [], ["wait"])
    assert act7 == "0"
    assert telem7["adapter_reason"] == "native_passthrough"


def test_step_budget_json_error_then_transport_error():
    """
    Offline check for combination: JSON error on attempt 1, transport error on attempt 2.
    - Exactly 2 attempts must be dispatched.
    - Third request must NOT be issued.
    - Total calls = 2.
    - Action returned is None.
    - Adapter reason is step_request_budget_exhausted.
    """
    call_count = 0
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "choices": [{"message": {"role": "assistant", "content": "I will think about this invalid JSON output."}}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40}
            }
        elif call_count == 2:
            raise requests.exceptions.ConnectionError("Connection aborted by peer")
        else:
            raise AssertionError(f"Third attempt was illegally issued! call_count={call_count}")

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])

    action, thought, stats, telemetry = agent.select_action("task", "obs", [], ["wait"])

    assert call_count == 2
    assert client.total_calls == 2
    assert action is None
    assert telemetry["adapter_reason"] == "step_request_budget_exhausted"
    assert telemetry["budget_exhausted"] is True


def test_step_budget_transport_error_then_json_error():
    """
    Offline check for combination: transport error on attempt 1, JSON error on attempt 2.
    - Exactly 2 attempts must be dispatched.
    - Third request must NOT be issued.
    - Total calls = 2.
    - Action returned is None.
    - Adapter reason is step_request_budget_exhausted.
    """
    call_count = 0
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.exceptions.Timeout("Read timeout")
        elif call_count == 2:
            return {
                "choices": [{"message": {"role": "assistant", "content": "Still not valid JSON"}}],
                "usage": {"prompt_tokens": 35, "completion_tokens": 10, "total_tokens": 45}
            }
        else:
            raise AssertionError(f"Third attempt was illegally issued! call_count={call_count}")

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])

    action, thought, stats, telemetry = agent.select_action("task", "obs", [], ["wait"])

    assert call_count == 2
    assert client.total_calls == 2
    assert action is None
    assert telemetry["adapter_reason"] == "step_request_budget_exhausted"
    assert telemetry["budget_exhausted"] is True


def test_step_budget_double_transport_error():
    """
    Offline check for combination: 2 consecutive transport errors.
    - Exactly 2 attempts must be dispatched.
    - Third request must NOT be issued.
    - Total calls = 2.
    - Action returned is None.
    - Adapter reason is step_request_budget_exhausted.
    """
    call_count = 0
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise requests.exceptions.ConnectionError(f"Network failure attempt {call_count}")
        else:
            raise AssertionError(f"Third attempt was illegally issued! call_count={call_count}")

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])

    action, thought, stats, telemetry = agent.select_action("task", "obs", [], ["wait"])

    assert call_count == 2
    assert client.total_calls == 2
    assert action is None
    assert telemetry["adapter_reason"] == "step_request_budget_exhausted"
    assert telemetry["budget_exhausted"] is True


def test_step_budget_transport_error_then_success():
    """
    Offline check for combination: transport error on attempt 1, success on attempt 2.
    - Exactly 2 attempts dispatched.
    - Total calls = 2.
    - Action returned successfully.
    """
    call_count = 0
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.exceptions.Timeout("Read timeout on attempt 1")
        elif call_count == 2:
            return {
                "choices": [{"message": {"role": "assistant", "content": '{"thought": "Recovered", "action": "wait"}'}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
            }
        else:
            raise AssertionError(f"Third attempt was illegally issued! call_count={call_count}")

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])

    action, thought, stats, telemetry = agent.select_action("task", "obs", [], ["wait"])

    assert call_count == 2
    assert client.total_calls == 2
    assert action == "wait"
    assert stats["calls"] == 2
    assert telemetry["adapter_reason"] == "native_passthrough"


def test_prompt_slots_ordering():
    """Verifies that prompt slots are ordered: Generic Semantics -> Experience -> Base Task."""
    recorded_prompts = []
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        recorded_prompts.append(payload["messages"][-1]["content"])
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"action": "wait"}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
        }

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates", action_templates=["wait"])

    g_text = "Generic action semantics:\n1. Dunk semantics."
    c_text = "Experience from a previous ScienceWorld interaction:\nSink is broken."
    
    agent.select_action("Task boil water", "Current obs", [], ["wait"], extra_context=c_text, generic_semantics=g_text)

    prompt = recorded_prompts[0]
    idx_g = prompt.index("Generic action semantics:")
    idx_c = prompt.index("Experience from a previous ScienceWorld interaction:")
    idx_task = prompt.index("Task Description:\nTask boil water")

    assert idx_g < idx_c < idx_task


