"""
Remote LLM Client for OpenAI-compatible Chat Completions API (DeepSeek Official Interface):
Provides structured JSON generation, mock transport guard, fail-fast configuration validation,
real-time conservative budget tracking, token accounting, and deterministic offline verification.
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


class BudgetExceededError(RemotePlannerError):
    """Raised when call count or cost exceeds the authorized budget."""
    pass


class PayloadSizeLimitExceededError(RemotePlannerError):
    """Raised when message payload exceeds size limit (32 KiB)."""
    pass


class RemoteLLMClient:
    """
    Client for calling a remote chat completion endpoint adhering to
    the OpenAI-compatible format with DeepSeek thinking / json_object support.
    
    Default configuration uses mock transport; live network egress is strictly
    blocked unless allow_live_network=True is explicitly set AND all configuration
    (endpoint, model_id, api_key_env_var, non-empty env var) is complete.
    """

    # Official conservative peak pricing per 1M tokens (USD)
    PRICE_PER_M_INPUT_MISS = 0.55   # $0.55 / 1M tokens ($0.00000055/token)
    PRICE_PER_M_INPUT_HIT = 0.14    # $0.14 / 1M tokens ($0.00000014/token)
    PRICE_PER_M_OUTPUT = 2.19       # $2.19 / 1M tokens ($0.00000219/token)

    MAX_REQUEST_ATTEMPTS = 400
    MAX_BUDGET_USD = 10.00
    MAX_MESSAGES_BYTES = 32768  # 32 KiB

    def __init__(
        self,
        endpoint: str = "https://api.deepseek.com/chat/completions",
        model_id: str = "deepseek-flash",
        api_key_env_var: str = "DEEPSEEK_API_KEY",
        timeout: float = 180.0,
        generation_params: Optional[Dict[str, Any]] = None,
        allow_live_network: bool = False,
        mock_transport: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        max_budget_usd: float = 10.00,
        max_attempts: int = 400,
        initial_cost_usd: float = 0.0,
        initial_reserved_usd: float = 0.0,
        initial_calls: int = 0,
        initial_input_tokens: int = 0,
        initial_output_tokens: int = 0
    ):
        self.endpoint = (endpoint or "").strip()
        self.model_id = (model_id or "").strip()
        self.api_key_env_var = (api_key_env_var or "").strip()
        self.timeout = float(timeout)
        self.allow_live_network = allow_live_network
        self.mock_transport = mock_transport
        self.max_budget_usd = float(max_budget_usd)
        self.max_attempts = int(max_attempts)

        # Default DeepSeek reasoning generation parameters
        if generation_params is not None:
            self.generation_params = dict(generation_params)
        else:
            self.generation_params = {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
                "response_format": {"type": "json_object"},
                "max_tokens": 8192,
                "stream": False
            }

        # Global counters & ledger across entire client session
        self.total_calls = int(initial_calls)  # Total request attempts sent to transport
        self.total_input_tokens = int(initial_input_tokens)
        self.total_output_tokens = int(initial_output_tokens)
        self.has_unknown_tokens = False
        self.total_latency_seconds = 0.0

        # Cost tracking (USD)
        self.known_cost_usd = float(initial_cost_usd)
        self.unknown_reserved_cost_usd = float(initial_reserved_usd)

        # Attempt log
        self.call_history: List[Dict[str, Any]] = []

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
            endpoint=config.get("endpoint", "https://api.deepseek.com/chat/completions"),
            model_id=config.get("model_id", "deepseek-flash"),
            api_key_env_var=config.get("api_key_env_var", "DEEPSEEK_API_KEY"),
            timeout=config.get("timeout", 180.0),
            generation_params=config.get("generation_params"),
            allow_live_network=live_net,
            mock_transport=mock_transport,
            max_budget_usd=config.get("max_budget_usd", 10.00),
            max_attempts=config.get("max_attempts", 400)
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

    def _get_api_key(self) -> str:
        """Retrieves API key without printing or exposing secrets."""
        key = os.getenv(self.api_key_env_var)
        if not key:
            # Fallback: check ~/.bashrc for exported variable in non-interactive shells
            bashrc = os.path.expanduser("~/.bashrc")
            if os.path.exists(bashrc):
                with open(bashrc, "r", encoding="utf-8") as f:
                    for line in f:
                        if self.api_key_env_var in line and "=" in line:
                            val = line.strip().split("=", 1)[1].strip("\"' ")
                            if val:
                                os.environ[self.api_key_env_var] = val
                                key = val
                                break
        return (key or "").strip()

    def validate_live_configuration(self):
        """Validates required fields and environment secrets for live execution."""
        if not self.endpoint:
            raise ConfigurationError("Remote planner endpoint must be specified and non-empty.")
        if not self.model_id:
            raise ConfigurationError("Remote planner model_id must be specified and non-empty.")
        if not self.api_key_env_var:
            raise ConfigurationError("Remote planner api_key_env_var must be specified and non-empty.")
        api_key = self._get_api_key()
        if not api_key:
            raise ConfigurationError(
                f"API key environment variable '{self.api_key_env_var}' is not set or empty. "
                f"Fail-fast: local models will NOT be used as a fallback."
            )

    def _build_payload(self, user_prompt: str, system_prompt: str = "", max_new_tokens: Optional[int] = None) -> Dict[str, Any]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # DeepSeek Flash requires 8192 max_tokens; do not let smaller values (e.g. 256) override it
        configured_max = self.generation_params.get("max_tokens", 8192)
        if max_new_tokens is not None and max_new_tokens >= configured_max:
            max_tokens = max_new_tokens
        else:
            max_tokens = configured_max

        payload: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False
        }

        # Add optional DeepSeek parameters
        if "thinking" in self.generation_params:
            payload["thinking"] = self.generation_params["thinking"]
        if "reasoning_effort" in self.generation_params:
            payload["reasoning_effort"] = self.generation_params["reasoning_effort"]
        if "response_format" in self.generation_params:
            payload["response_format"] = self.generation_params["response_format"]

        # EXCLUSIONS: Do NOT send temperature, top_p, or seed as per user specification
        return payload

    def _reserve_budget_for_request(self, payload: Dict[str, Any]) -> float:
        """
        Validates messages payload size limit (32 KiB) and reserves conservative
        budget (peak pricing, cache miss, max output tokens) prior to sending.
        Refuses to send if reliable upper bound cannot be established.
        """
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) == 0:
            raise RemotePlannerError("Cannot establish reliable token upper bound: 'messages' is empty or invalid.")

        try:
            messages_bytes = json.dumps(messages, ensure_ascii=False).encode("utf-8")
        except Exception as e:
            raise RemotePlannerError(f"Cannot establish reliable token upper bound: failed to encode messages: {e}")

        if len(messages_bytes) > self.MAX_MESSAGES_BYTES:
            raise PayloadSizeLimitExceededError(
                f"Message payload size ({len(messages_bytes)} bytes) exceeds the 32 KiB (32,768 bytes) limit."
            )

        max_output_tokens = payload.get("max_tokens")
        if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
            raise RemotePlannerError(
                f"Cannot establish reliable token upper bound: max_tokens ({max_output_tokens}) is invalid."
            )

        if self.total_calls >= self.max_attempts:
            raise BudgetExceededError(
                f"Hard attempt limit ({self.max_attempts} calls) reached. Current calls: {self.total_calls}."
            )

        # In UTF-8, each byte can produce at most 1 token. With 1024 formatting tokens buffer:
        est_input_tokens = len(messages_bytes) + 1024

        reserved_cost = (
            (est_input_tokens / 1_000_000.0) * self.PRICE_PER_M_INPUT_MISS +
            (max_output_tokens / 1_000_000.0) * self.PRICE_PER_M_OUTPUT
        )

        projected_total = self.known_cost_usd + self.unknown_reserved_cost_usd + reserved_cost
        if projected_total > self.max_budget_usd:
            raise BudgetExceededError(
                f"Insufficient budget for request reservation: projected ${projected_total:.4f} > "
                f"authorized limit ${self.max_budget_usd:.2f}."
            )

        return reserved_cost

    def generate(self, user_prompt: str, system_prompt: str = "", max_new_tokens: Optional[int] = None) -> Tuple[str, Dict[str, Any]]:
        payload = self._build_payload(user_prompt, system_prompt=system_prompt, max_new_tokens=max_new_tokens)
        
        # Budget check & reservation prior to sending
        reserved_cost = self._reserve_budget_for_request(payload)

        # Increment call attempt as soon as request is dispatched
        self.total_calls += 1
        current_call_index = self.total_calls

        attempt_record: Dict[str, Any] = {
            "call_index": current_call_index,
            "timestamp": time.time(),
            "model": self.model_id,
            "reserved_cost_usd": reserved_cost,
            "status": "in_flight"
        }

        t0 = time.time()
        raw_response = None
        error_raised = None

        try:
            if self.mock_transport is not None:
                try:
                    raw_response = self.mock_transport(payload)
                except (TimeoutError, requests.exceptions.Timeout) as e:
                    raise RemotePlannerTimeoutError(f"Mock transport timed out after {self.timeout}s") from e
                except Exception as e:
                    if isinstance(e, RemotePlannerError):
                        raise
                    raise RemotePlannerError(f"Mock transport error: {e}") from e
            elif not self.allow_live_network:
                raise NetworkAccessBlockedError(
                    "Live network egress is blocked by default. "
                    "Provide a mock_transport or explicitly configure allow_live_network=True with valid credentials."
                )
            else:
                self.validate_live_configuration()
                api_key = self._get_api_key()
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
        except Exception as e:
            error_raised = e
            # Record failed request with permanent conservative reservation
            self.unknown_reserved_cost_usd += reserved_cost
            attempt_record["status"] = "failed"
            attempt_record["error"] = str(e)
            attempt_record["error_type"] = type(e).__name__
            self.call_history.append(attempt_record)
            raise

        dt = time.time() - t0
        self.total_latency_seconds += dt

        # Parse response
        choices = raw_response.get("choices", []) if isinstance(raw_response, dict) else []
        if not choices or not isinstance(choices, list):
            self.unknown_reserved_cost_usd += reserved_cost
            attempt_record["status"] = "invalid_format"
            self.call_history.append(attempt_record)
            raise RemotePlannerError(f"Unexpected response format: 'choices' missing. Received: {str(raw_response)[:200]}")

        first_choice = choices[0]
        message = first_choice.get("message", {})
        
        # Parse action ONLY from message.content; never from reasoning_content
        response_text = message.get("content", "") or ""
        reasoning_content = message.get("reasoning_content", "") or ""

        # Parse termination and content properties
        finish_reason = first_choice.get("finish_reason", "unknown")
        empty_content = (len(response_text.strip()) == 0)
        hit_output_token_limit = (finish_reason == "length")

        # Response metadata
        response_model = raw_response.get("model", self.model_id)
        system_fingerprint = raw_response.get("system_fingerprint", "unknown")
        request_id = raw_response.get("id", "unknown")

        # Usage accounting
        usage = raw_response.get("usage")
        if isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage:
            in_tokens = usage.get("prompt_tokens")
            out_tokens = usage.get("completion_tokens")
            tot_tokens = usage.get("total_tokens", (in_tokens + out_tokens) if (isinstance(in_tokens, int) and isinstance(out_tokens, int)) else "unknown")
            hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
            miss_tokens = usage.get("prompt_cache_miss_tokens", max(0, in_tokens - hit_tokens) if isinstance(in_tokens, int) else 0)

            if isinstance(in_tokens, int) and isinstance(out_tokens, int):
                self.total_input_tokens += in_tokens
                self.total_output_tokens += out_tokens
                # DeepSeek includes reasoning tokens inside completion_tokens; do not double charge
                actual_cost = (
                    (hit_tokens / 1_000_000.0) * self.PRICE_PER_M_INPUT_HIT +
                    (miss_tokens / 1_000_000.0) * self.PRICE_PER_M_INPUT_MISS +
                    (out_tokens / 1_000_000.0) * self.PRICE_PER_M_OUTPUT
                )
                self.known_cost_usd += actual_cost
                attempt_record["cost_usd"] = actual_cost
                attempt_record["status"] = "success"
            else:
                self.has_unknown_tokens = True
                self.unknown_reserved_cost_usd += reserved_cost
                attempt_record["status"] = "success_unknown_tokens"
        else:
            in_tokens = "unknown"
            out_tokens = "unknown"
            tot_tokens = "unknown"
            hit_tokens = "unknown"
            miss_tokens = "unknown"
            self.has_unknown_tokens = True
            self.unknown_reserved_cost_usd += reserved_cost
            attempt_record["status"] = "success_no_usage"

        attempt_record["input_tokens"] = in_tokens
        attempt_record["output_tokens"] = out_tokens
        attempt_record["total_tokens"] = tot_tokens
        attempt_record["latency_s"] = round(dt, 3)
        attempt_record["response_model"] = response_model
        attempt_record["system_fingerprint"] = system_fingerprint
        attempt_record["request_id"] = request_id
        attempt_record["has_reasoning_content"] = bool(reasoning_content)
        attempt_record["finish_reason"] = finish_reason
        attempt_record["empty_content"] = empty_content
        attempt_record["hit_output_token_limit"] = hit_output_token_limit
        self.call_history.append(attempt_record)

        stats = {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": tot_tokens,
            "prompt_cache_hit_tokens": hit_tokens,
            "prompt_cache_miss_tokens": miss_tokens,
            "latency_s": round(dt, 3),
            "call_index": current_call_index,
            "total_calls": self.total_calls,
            "model": response_model,
            "system_fingerprint": system_fingerprint,
            "request_id": request_id,
            "finish_reason": finish_reason,
            "empty_content": empty_content,
            "hit_output_token_limit": hit_output_token_limit,
            "reasoning_content_length": len(reasoning_content),
            "raw_text": response_text
        }

        return response_text, stats

    def generate_json(self, user_prompt: str, system_prompt: str = "", max_new_tokens: Optional[int] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Executes structured JSON generation with single retry on parse error.
        Returns combined usage across all attempts in this invocation and preserves
        detailed per-attempt metadata.
        """
        attempts: List[Dict[str, Any]] = []

        raw_text_1, stats_1 = self.generate(user_prompt, system_prompt, max_new_tokens=max_new_tokens)
        attempts.append(stats_1)
        parsed_1 = self._extract_json(raw_text_1)

        if parsed_1 is not None:
            combined_stats = self._aggregate_invocation_stats(attempts, parsed_1, retry_attempted=False)
            return parsed_1, combined_stats

        # Retry once if output was invalid JSON
        retry_prompt = f"{user_prompt}\n\nPREVIOUS OUTPUT WAS INVALID JSON:\n{raw_text_1}\nPlease output ONLY valid JSON."
        raw_text_2, stats_2 = self.generate(retry_prompt, system_prompt, max_new_tokens=max_new_tokens)
        attempts.append(stats_2)
        parsed_2 = self._extract_json(raw_text_2)

        if parsed_2 is not None:
            combined_stats = self._aggregate_invocation_stats(attempts, parsed_2, retry_attempted=True)
            return parsed_2, combined_stats

        # Fallback dictionary if parsing completely failed
        fallback_json = {"raw_text": raw_text_2, "parse_error": True}
        combined_stats = self._aggregate_invocation_stats(attempts, fallback_json, retry_attempted=True)
        return fallback_json, combined_stats

    def _aggregate_invocation_stats(
        self,
        attempts: List[Dict[str, Any]],
        parsed_json: Dict[str, Any],
        retry_attempted: bool
    ) -> Dict[str, Any]:
        """Combines stats across attempts in a single generate_json call."""
        calls = len(attempts)

        # Token summing: if any attempt is unknown, combined is unknown
        in_tokens: Any = 0
        out_tokens: Any = 0
        tot_tokens: Any = 0
        all_numeric = True

        for att in attempts:
            it = att.get("input_tokens")
            ot = att.get("output_tokens")
            if isinstance(it, int) and isinstance(ot, int) and all_numeric:
                in_tokens += it
                out_tokens += ot
                tot_tokens += (it + ot)
            else:
                all_numeric = False
                in_tokens = "unknown"
                out_tokens = "unknown"
                tot_tokens = "unknown"

        last_attempt = attempts[-1] if attempts else {}

        return {
            "calls": calls,
            "total_calls": calls,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": tot_tokens,
            "retry_attempted": retry_attempted,
            "finish_reason": last_attempt.get("finish_reason", "unknown"),
            "empty_content": last_attempt.get("empty_content", False),
            "hit_output_token_limit": any(a.get("hit_output_token_limit", False) for a in attempts),
            "parse_error": parsed_json.get("parse_error", False),
            "attempts": attempts,
            "raw_text": last_attempt.get("raw_text", ""),
            "model": last_attempt.get("model", self.model_id),
            "system_fingerprint": last_attempt.get("system_fingerprint", "unknown"),
            "request_id": last_attempt.get("request_id", "unknown"),
            "client_cumulative_calls": self.total_calls,
            "client_known_cost_usd": round(self.known_cost_usd, 6),
            "client_reserved_cost_usd": round(self.unknown_reserved_cost_usd, 6),
            "client_total_cost_usd": round(self.known_cost_usd + self.unknown_reserved_cost_usd, 6)
        }

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # Try finding markdown code block ```json ... ```
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

    def get_budget_ledger(self) -> Dict[str, Any]:
        """Returns comprehensive real-time financial and attempt ledger."""
        total_committed = self.known_cost_usd + self.unknown_reserved_cost_usd
        return {
            "max_budget_usd": self.max_budget_usd,
            "max_attempts": self.max_attempts,
            "total_request_attempts": self.total_calls,
            "remaining_attempts": max(0, self.max_attempts - self.total_calls),
            "known_cost_usd": round(self.known_cost_usd, 6),
            "estimated_cost_usd_from_usage": round(self.known_cost_usd, 6),
            "unknown_reserved_cost_usd": round(self.unknown_reserved_cost_usd, 6),
            "conservative_reserved_cost_usd": round(self.unknown_reserved_cost_usd, 6),
            "total_committed_cost_usd": round(total_committed, 6),
            "remaining_budget_usd": round(max(0.0, self.max_budget_usd - total_committed), 6),
            "budget_exceeded": total_committed > self.max_budget_usd,
            "total_input_tokens": self.total_input_tokens if not self.has_unknown_tokens else f">={self.total_input_tokens} (partial unknown)",
            "total_output_tokens": self.total_output_tokens if not self.has_unknown_tokens else f">={self.total_output_tokens} (partial unknown)",
            "has_unknown_tokens": self.has_unknown_tokens,
            "audited_bill_usd": None,
            "audited_bill_status": "pending_billing_audit"
        }

    def get_model_metadata(self) -> Dict[str, Any]:
        return {
            "backend": "deepseek_official_chat_api",
            "model_id": self.model_id,
            "target_version": "DeepSeek-V4.1-Flash-1017",
            "endpoint": self.endpoint,
            "api_key_env_var": self.api_key_env_var,
            "timeout": self.timeout,
            "generation_parameters": self.generation_params,
            "allow_live_network": self.allow_live_network,
            "pricing_usd_per_1m": {
                "input_cache_miss": self.PRICE_PER_M_INPUT_MISS,
                "input_cache_hit": self.PRICE_PER_M_INPUT_HIT,
                "output": self.PRICE_PER_M_OUTPUT
            }
        }
