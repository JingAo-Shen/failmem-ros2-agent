"""
Offline test suite for RemoteLLMClient and BaseAgent action_templates mode.
Verifies payload assembly, native action pass-through, invalid JSON retry,
timeout handling, network blocking, fail-fast configuration without local model fallback,
and token accounting.
"""

import os
import sys
import pytest
from typing import Dict, Any, List

from remote_llm_client import (
    RemoteLLMClient,
    RemotePlannerError,
    ConfigurationError,
    NetworkAccessBlockedError,
    RemotePlannerTimeoutError,
)
from agents.base_agent import (
    BaseAgent,
    SCIENCEWORLD_ACTION_TEMPLATES,
    SYSTEM_PROMPT_ACTION_TEMPLATES,
)
import requests


def test_prompt_and_templates_reach_payload():
    """Verifies that prompt_mode='action_templates' assembles prompt and templates into OpenAI payload."""
    recorded_payloads: List[Dict[str, Any]] = []

    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        recorded_payloads.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"thought": "Examine environment", "action": "look around"}'
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 15,
                "total_tokens": 135
            }
        }

    client = RemoteLLMClient(
        endpoint="https://api.example.com/v1/chat/completions",
        model_id="test-strong-planner",
        mock_transport=mock_transport,
        allow_live_network=False
    )

    agent = BaseAgent(
        llm_client=client,
        adapter_mode="native",
        prompt_mode="action_templates"
    )

    action, thought, stats, telemetry = agent.select_action(
        task_desc="test conductivity of paper clip in workshop",
        current_obs="You are in the hallway. You see a closed door to workshop.",
        history=[("open door", "You opened the door.")],
        valid_actions=["teleport to workshop", "look around", "inventory"]
    )

    assert len(recorded_payloads) == 1
    payload = recorded_payloads[0]

    assert payload["model"] == "test-strong-planner"
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"

    sys_text = payload["messages"][0]["content"]
    assert "ScienceWorld scientific virtual environment" in sys_text
    assert "Choose the single most effective valid action." in sys_text

    user_text = payload["messages"][1]["content"]
    assert "Action Syntax Reference:" in user_text
    assert "These templates describe action syntax. They do not guarantee that an action is executable in the current state." in user_text
    assert "Candidate Valid Actions (select one from these" not in user_text

    # All 27 templates present verbatim
    for tmpl in SCIENCEWORLD_ACTION_TEMPLATES:
        assert f"- {tmpl}" in user_text

    assert action == "look around"
    assert telemetry["prompt_mode"] == "action_templates"
    assert telemetry["adapter_reason"] == "native_passthrough"


def test_native_action_extraction_and_whitespace_trimming():
    """Verifies that native mode extracts action string and trims whitespace without replacement."""
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"thought": "Moving to workshop", "action": "  teleport to workshop \\n\\t"}'
                    }
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        }

    client = RemoteLLMClient(mock_transport=mock_transport)
    agent = BaseAgent(llm_client=client, adapter_mode="native", prompt_mode="action_templates")

    action, thought, stats, telemetry = agent.select_action(
        task_desc="test task",
        current_obs="obs",
        history=[],
        valid_actions=["look around"]
    )

    assert action == "teleport to workshop"
    assert telemetry["proposed_action"] == "  teleport to workshop \n\t"
    assert telemetry["executed_action"] == "teleport to workshop"
    assert telemetry["executed_action_equals_trimmed_proposed"] is True
    assert telemetry["adapter_reason"] == "native_passthrough"
    assert telemetry["adapter_modified"] is True  # because raw had whitespace


def test_invalid_json_retry_and_logging():
    """Verifies retry upon invalid JSON and logging of retry attempts."""
    call_count = 0
    recorded_prompts: List[str] = []

    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal call_count
        call_count += 1
        user_msg = payload["messages"][-1]["content"]
        recorded_prompts.append(user_msg)
        if call_count == 1:
            return {
                "choices": [{"message": {"role": "assistant", "content": "I recommend taking the paper clip."}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}
            }
        else:
            return {
                "choices": [{"message": {"role": "assistant", "content": '{"thought": "Retrying JSON", "action": "pick up paper clip"}'}}],
                "usage": {"prompt_tokens": 65, "completion_tokens": 15, "total_tokens": 80}
            }

    client = RemoteLLMClient(mock_transport=mock_transport)
    parsed, stats = client.generate_json("What is your next move?", system_prompt="You are a helper.")

    assert call_count == 2
    assert "PREVIOUS OUTPUT WAS INVALID JSON:" in recorded_prompts[1]
    assert "I recommend taking the paper clip." in recorded_prompts[1]
    assert stats["retry_attempted"] is True
    assert parsed["action"] == "pick up paper clip"


def test_invalid_json_unrecovered_fallback():
    """Verifies fallback dictionary when JSON remains malformed after retry."""
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "choices": [{"message": {"role": "assistant", "content": "Still plain text!"}}],
            "usage": None
        }

    client = RemoteLLMClient(mock_transport=mock_transport)
    parsed, stats = client.generate_json("prompt", "sys")

    assert parsed.get("parse_error") is True
    assert parsed.get("raw_text") == "Still plain text!"
    assert stats["retry_attempted"] is True


def test_timeout_handling():
    """Verifies that timeouts in remote calls raise RemotePlannerTimeoutError."""
    def mock_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
        raise requests.exceptions.Timeout("Connection timed out after 15s")

    client = RemoteLLMClient(timeout=15.0, mock_transport=mock_transport)

    with pytest.raises(RemotePlannerTimeoutError) as exc_info:
        client.generate("prompt", "sys")
    assert "timed out after 15.0s" in str(exc_info.value)


def test_default_network_block():
    """Verifies that live network requests are strictly blocked by default when no mock transport is provided."""
    client = RemoteLLMClient(
        endpoint="https://api.openai.com/v1/chat/completions",
        model_id="gpt-4o",
        allow_live_network=False,
        mock_transport=None
    )

    with pytest.raises(NetworkAccessBlockedError) as exc_info:
        client.generate("hello", "sys")
    assert "Live network egress is blocked by default" in str(exc_info.value)


def test_incomplete_config_fail_fast_without_local_fallback(monkeypatch):
    """Verifies that missing config fails fast with ConfigurationError and never falls back to local models."""
    # Ensure local model singletons are untouched
    monkeypatch.delenv("TEST_KEY_ENV", raising=False)

    # 1. Missing endpoint
    with pytest.raises(ConfigurationError) as exc:
        RemoteLLMClient(endpoint="", model_id="gpt-4o", api_key_env_var="TEST_KEY_ENV", allow_live_network=True)
    assert "endpoint" in str(exc.value)

    # 2. Missing model_id
    with pytest.raises(ConfigurationError) as exc:
        RemoteLLMClient(endpoint="https://example.com", model_id="", api_key_env_var="TEST_KEY_ENV", allow_live_network=True)
    assert "model_id" in str(exc.value)

    # 3. Missing api_key_env_var
    with pytest.raises(ConfigurationError) as exc:
        RemoteLLMClient(endpoint="https://example.com", model_id="gpt-4o", api_key_env_var="", allow_live_network=True)
    assert "api_key_env_var" in str(exc.value)

    # 4. Environment variable not set in OS
    with pytest.raises(ConfigurationError) as exc:
        RemoteLLMClient(endpoint="https://example.com", model_id="gpt-4o", api_key_env_var="TEST_KEY_ENV", allow_live_network=True)
    assert "TEST_KEY_ENV" in str(exc.value)
    assert "Fail-fast: local models will NOT be used as a fallback." in str(exc.value)

    # Verify no local model was imported or loaded
    assert "llm_client" not in sys.modules or not hasattr(sys.modules.get("llm_client"), "_instance_called")


def test_token_usage_accounting():
    """Verifies that token usage records 'unknown' rather than 0 when provider omits usage."""
    # 1. Normal usage
    def mock_normal(payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"action": "test"}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        }

    client1 = RemoteLLMClient(mock_transport=mock_normal)
    _, stats1 = client1.generate("p", "s")
    assert stats1["input_tokens"] == 100
    assert stats1["output_tokens"] == 20
    assert stats1["total_tokens"] == 120

    # 2. Missing usage
    def mock_missing_usage(payload):
        return {
            "choices": [{"message": {"role": "assistant", "content": '{"action": "test"}'}}],
            "usage": None
        }

    client2 = RemoteLLMClient(mock_transport=mock_missing_usage)
    _, stats2 = client2.generate("p", "s")
    assert stats2["input_tokens"] == "unknown"
    assert stats2["output_tokens"] == "unknown"
    assert stats2["total_tokens"] == "unknown"
    assert stats2["total_tokens"] != 0
