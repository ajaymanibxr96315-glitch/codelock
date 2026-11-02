"""Small configurable AI provider layer; credentials are read only from env."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


class AIError(RuntimeError):
    """Provider configuration, network, or response validation error."""


def _redact(text: str, api_key: str) -> str:
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return re.sub(r"(?i)bearer\s+[^\s\"',}]+", "Bearer [redacted]", text)


@dataclass(frozen=True)
class AIProvider:
    provider: str
    endpoint: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 75.0

    @classmethod
    def from_environment(cls) -> "AIProvider":
        provider = os.environ.get("CODELOCK_AI_PROVIDER", "").strip().lower()
        model = os.environ.get("CODELOCK_AI_MODEL", "").strip()
        api_key = os.environ.get("CODELOCK_AI_API_KEY", "").strip()
        endpoint = os.environ.get("CODELOCK_AI_ENDPOINT", "").strip()
        if provider not in {"ollama", "gemini", "openai-compatible"}:
            raise AIError(
                "AI generation is unavailable. Set CODELOCK_AI_PROVIDER to ollama, gemini, "
                "or openai-compatible and configure its model."
            )
        if not model:
            raise AIError("Set CODELOCK_AI_MODEL to the model name to enable AI generation.")
        if api_key and not api_key.isprintable():
            raise AIError(
                "CODELOCK_AI_API_KEY contains invalid control characters. "
                "Remove line breaks and try again."
            )
        if provider == "ollama":
            endpoint = endpoint or "http://localhost:11434/api/chat"
        elif provider == "gemini":
            endpoint = endpoint or "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            if not api_key:
                raise AIError("Set CODELOCK_AI_API_KEY for the Gemini provider.")
        elif not endpoint:
            raise AIError("Set CODELOCK_AI_ENDPOINT for the OpenAI-compatible provider.")
        return cls(provider, endpoint, model, api_key)

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict | list:
        if self.provider == "ollama":
            payload = {
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        else:
            payload = {
                "model": self.model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            detail = _redact(
                exc.read(1200).decode("utf-8", errors="replace"), self.api_key
            )
            if exc.code == 429:
                raise AIError("The AI provider rate limit was reached. Try again later.") from exc
            raise AIError(f"AI provider returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AIError(
                f"Could not reach the AI provider: {_redact(str(exc), self.api_key)}"
            ) from exc
        if len(raw) > 2_000_000:
            raise AIError("AI response exceeded the 2 MB limit.")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIError("AI provider did not return valid JSON. Nothing was saved.") from exc
        try:
            if self.provider == "ollama":
                content = envelope["message"]["content"]
            else:
                content = envelope["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(
                "AI provider response is missing the expected chat message. Nothing was saved."
            ) from exc
        text = str(content).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        try:
            result = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AIError("AI provider did not return valid JSON. Nothing was saved.") from exc
        if not isinstance(result, (dict, list)):
            raise AIError("AI provider response must be a JSON object or list.")
        return result
