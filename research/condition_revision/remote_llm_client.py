"""
Remote LLM Client for OpenAI-compatible Chat Completions API:
Provides structured JSON generation, mock transport guard, token accounting (with "unknown" fallback),
and deterministic offline verification.
"""

import os
import re
import json
import time
from typing import Dict, Any, Optional, Tuple, List, Callable
import requests


class RemotePlannerError(Exception):
    """Base exception for remote planner errors."""
    pass


class ConfigurationError(RemotePlannerError):
    """Raised when configuration is incomplete or invalid."""
    pass


class NetworkAccessBlockedError(RemotePlannerError):
    """Raised when live network access is attempted while forbidden."""
    pass


class RemotePlannerTimeoutError(RemotePlannerError):
    """Raised when a remote request times out."""
    pass


class RemoteLLMClient:
    """
    Client for calling a remote chat completion endpoint adhering to
    the standard OpenAI-compatible format.
    
    Default configuration uses mock transport; live network egress is strictly
    blocked unless allow_live_network=True is explicitly set AND all configuration
    (endpoint, model_id, api_key_env_var, non-empty env var) is complete.
    """

    def __init__(
        self,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
        model_id: str = "remote-chat-model",
        api_key_env_var: str = "REMOTE_PLANNER_API_KEY",
        timeout: float = 60.0,
        generation_params: Optional[Dict[str, Any]] = None,
        allow_live_network: bool = False,
        mock_transport: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    ):
        self.endpoint = (endpoint or "").strip()
        self.model_id = (model_id or "").strip()
        self.api_key_env_var = (api_key_env_var or "").strip()
        self.timeout = float(timeout)
        self.generation_params = generation_params if generation_params is not None else {
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 256
        }
        self.allow_live_network = allow_live_network
        self.mock_transport = mock_transport

        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.has_unknown_tokens = False
        self.total_latency_seconds = 0.0

        if self.allow_live_network:
            self.validate_live_configuration()

    @classmethod
    def from_config_dict(
        cls,
        config: Dict[str, Any],
        allow_live_network: Optional[bool] = None,
        mock_transport: Optional[Callable] = None
    ) -> "RemoteLLMClient":
        live_net = allow_live_network if allow_live_network is not None else config.get("allow_live_network", False)
        return cls(
            endpoint=config.get("endpoint", ""),
            model_id=config.get("model_id", ""),
            api_key_env_var=config.get("api_key_env_var", ""),
            timeout=config.get("timeout", 60.0),
            generation_params=config.get("generation_params"),
            allow_live_network=live_net,
            mock_transport=mock_transport
        )

    @classmethod
    def from_config_file(
        cls,
        config_path: str,
        allow_live_network: Optional[bool] = None,
        mock_transport: Optional[Callable] = None
    ) -> "RemoteLLMClient":
        if not os.path.exists(config_path):
            raise ConfigurationError(f"Config file not found at: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cls.from_config_dict(cfg, allow_live_network=allow_live_network, mock_transport=mock_transport)

    def validate_live_configuration(self):
        """Validates that all required fields and environment secrets are present for live execution."""
        if not self.endpoint:
            raise ConfigurationError("Remote planner endpoint must be specified and non-empty.")
        if not self.model_id:
            raise ConfigurationError("Remote planner model_id must be specified and non-empty.")
        if not self.api_key_env_var:
            raise ConfigurationError("Remote planner api_key_env_var must be specified and non-empty.")
        api_key = os.getenv(self.api_key_env_var)
        if not api_key or not api_key.strip():
            raise ConfigurationError(
                f"API key environment variable '{self.api_key_env_var}' is not set or empty. "
                f"Fail-fast: local models will NOT be used as a fallback."
            )

    def _build_payload(self, user_prompt: str, system_prompt: str = "", max_new_tokens: Optional[int] = None) -> Dict[str, Any]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        max_tokens = max_new_tokens if max_new_tokens is not None else self.generation_params.get("max_tokens", 256)

        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.generation_params.get("temperature", 0.0),
            "top_p": self.generation_params.get("top_p", 1.0),
            "max_tokens": max_tokens
        }
        return payload

    def generate(self, user_prompt: str, system_prompt: str = "", max_new_tokens: Optional[int] = None) -> Tuple[str, Dict[str, Any]]:
        payload = self._build_payload(user_prompt, system_prompt=system_prompt, max_new_tokens=max_new_tokens)
        t0 = time.time()

        if self.mock_transport is not None:
            try:
                raw_response = self.mock_transport(payload)
            except (TimeoutError, requests.exceptions.Timeout) as e:
                raise RemotePlannerTimeoutError(f"Mock transport timed out after {self.timeout}s") from e
            except Exception as e:
                if isinstance(e, RemotePlannerError):
                    raise
                raise RemotePlannerError(f"Mock transport raised error: {e}") from e
        elif not self.allow_live_network:
            raise NetworkAccessBlockedError(
                "Live network egress is blocked by default. "
                "Provide a mock_transport or explicitly configure allow_live_network=True with valid credentials."
            )
        else:
            self.validate_live_configuration()
            api_key = os.getenv(self.api_key_env_var)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            try:
                resp = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )
                if resp.status_code != 200:
                    raise RemotePlannerError(
                        f"Remote endpoint returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                raw_response = resp.json()
            except requests.exceptions.Timeout as e:
                raise RemotePlannerTimeoutError(f"Request to {self.endpoint} timed out after {self.timeout}s") from e
            except requests.exceptions.RequestException as e:
                raise RemotePlannerError(f"Request to {self.endpoint} failed: {type(e).__name__}") from e

        dt = time.time() - t0

        # Extract message content
        choices = raw_response.get("choices", [])
        if not choices or not isinstance(choices, list):
            raise RemotePlannerError(f"Unexpected response format: 'choices' missing or invalid. Received: {str(raw_response)[:200]}")
        
        first_choice = choices[0]
        message = first_choice.get("message", {})
        response_text = message.get("content", "")
        if response_text is None:
            response_text = ""

        # Token accounting: must record 'unknown' when provider does not return tokens
        usage = raw_response.get("usage")
        if isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage:
            in_tokens = usage.get("prompt_tokens")
            out_tokens = usage.get("completion_tokens")
            tot_tokens = usage.get("total_tokens", (in_tokens + out_tokens) if (isinstance(in_tokens, int) and isinstance(out_tokens, int)) else "unknown")
            if isinstance(in_tokens, int) and isinstance(out_tokens, int):
                self.total_input_tokens += in_tokens
                self.total_output_tokens += out_tokens
            else:
                self.has_unknown_tokens = True
        else:
            in_tokens = "unknown"
            out_tokens = "unknown"
            tot_tokens = "unknown"
            self.has_unknown_tokens = True

        self.total_calls += 1
        self.total_latency_seconds += dt

        stats = {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": tot_tokens,
            "latency_s": round(dt, 3),
            "total_calls": self.total_calls,
            "model": self.model_id
        }

        return response_text, stats

    def generate_json(self, user_prompt: str, system_prompt: str = "", max_new_tokens: Optional[int] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raw_text, stats = self.generate(user_prompt, system_prompt, max_new_tokens=max_new_tokens)
        stats["raw_text"] = raw_text
        parsed = self._extract_json(raw_text)
        if parsed is not None:
            stats["retry_attempted"] = False
            return parsed, stats

        # Retry once if JSON was invalid
        stats["retry_attempted"] = True
        stats["invalid_json_received"] = raw_text
        retry_prompt = f"{user_prompt}\n\nPREVIOUS OUTPUT WAS INVALID JSON:\n{raw_text}\nPlease output ONLY valid JSON."
        raw_text2, stats2 = self.generate(retry_prompt, system_prompt, max_new_tokens=max_new_tokens)
        stats2["raw_text"] = raw_text2
        stats2["retry_attempted"] = True
        stats2["first_attempt_raw"] = raw_text
        parsed2 = self._extract_json(raw_text2)
        if parsed2 is not None:
            return parsed2, stats2

        # Fallback dictionary if parsing completely failed
        return {"raw_text": raw_text2, "parse_error": True}, stats2

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # Try finding markdown code block
        code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except Exception:
                pass
        # Try finding outermost braces { ... }
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0).strip())
            except Exception:
                pass
        return None

    def get_aggregate_stats(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens if not self.has_unknown_tokens else f">={self.total_input_tokens} (partial unknown)",
            "total_output_tokens": self.total_output_tokens if not self.has_unknown_tokens else f">={self.total_output_tokens} (partial unknown)",
            "total_tokens": (self.total_input_tokens + self.total_output_tokens) if not self.has_unknown_tokens else "unknown",
            "has_unknown_tokens": self.has_unknown_tokens,
            "total_latency_seconds": round(self.total_latency_seconds, 2),
            "avg_latency_per_call": round(self.total_latency_seconds / max(1, self.total_calls), 3)
        }

    def get_model_metadata(self) -> Dict[str, Any]:
        return {
            "backend": "remote_chat_api",
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "api_key_env_var": self.api_key_env_var,
            "timeout": self.timeout,
            "generation_parameters": self.generation_params,
            "allow_live_network": self.allow_live_network
        }
