from abc import ABC, abstractmethod
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from groq import Groq

from config import Settings, get_settings
from prompts import build_answer_prompt, build_sql_prompt, build_sql_repair_prompt


LLM_CACHE_PATH = Path("llm_cache.json")
RETRY_DELAYS_SECONDS = (5, 10, 20)
TASK_MAX_TOKENS = {
    "sql_generation": 700,
    "sql_repair": 700,
    "result_summary": 350,
}


class LLMError(Exception):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def generate_sql(self, question: str, conversation_context: str = "") -> str:
        raise NotImplementedError

    @abstractmethod
    def summarize_results(self, question: str, sql: str, results: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def repair_sql(
        self,
        question: str,
        invalid_sql: str,
        validation_error: str,
        conversation_context: str = "",
    ) -> str:
        raise NotImplementedError

def _load_cache() -> dict[str, str]:
    if not LLM_CACHE_PATH.exists():
        return {}

    try:
        cache = json.loads(LLM_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(cache, dict):
            return {str(key): str(value) for key, value in cache.items()}
    except (OSError, json.JSONDecodeError):
        return {}

    return {}


def _save_cache(cache: dict[str, str]) -> None:
    LLM_CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(*, model_name: str, task_type: str, prompt: str) -> str:
    payload = json.dumps(
        {"model": model_name, "task": task_type, "prompt": prompt},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _exception_code(exc: Exception) -> str:
    candidates: list[Any] = [
        getattr(exc, "code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "status", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ]
    text = " ".join(str(value) for value in candidates if value is not None)
    return f"{text} {exc}".lower()


def _is_retryable_error(exc: Exception) -> bool:
    error_text = _exception_code(exc)
    return any(marker in error_text for marker in ("429", "too many requests", "rate", "500", "503", "unavailable"))


def _is_rate_limit_error(exc: Exception) -> bool:
    error_text = _exception_code(exc)
    return any(marker in error_text for marker in ("429", "too many requests", "rate limit", "quota"))


class GroqProvider(LLMProvider):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.groq_api_key:
            raise LLMError("Groq API key is missing.")

        self.client = Groq(api_key=self.settings.groq_api_key)

    def _generate_text(self, prompt: str, task_type: str) -> str:
        key = _cache_key(model_name=self.settings.groq_model, task_type=task_type, prompt=prompt)
        cache = _load_cache()
        cached_text = cache.get(key)
        if cached_text:
            return cached_text

        last_error: Exception | None = None
        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.settings.groq_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=TASK_MAX_TOKENS.get(task_type, 500),
                )
                text = response.choices[0].message.content or ""
                if not text.strip():
                    raise LLMError("The AI service returned an empty response.")
                cache[key] = text.strip()
                _save_cache(cache)
                return text.strip()
            except LLMError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= len(RETRY_DELAYS_SECONDS) or not _is_retryable_error(exc):
                    break
                time.sleep(RETRY_DELAYS_SECONDS[attempt])

        if last_error is not None and _is_rate_limit_error(last_error):
            raise LLMRateLimitError("The AI service is temporarily rate-limited. Please wait a moment and try again.") from last_error

        raise LLMError("The AI service is temporarily unavailable. Please try again.") from last_error

    def generate_sql(self, question: str, conversation_context: str = "") -> str:
        return self._generate_text(build_sql_prompt(question, conversation_context), task_type="sql_generation")

    def summarize_results(self, question: str, sql: str, results: str) -> str:
        return self._generate_text(build_answer_prompt(question, sql, results), task_type="result_summary")

    def repair_sql(
        self,
        question: str,
        invalid_sql: str,
        validation_error: str,
        conversation_context: str = "",
    ) -> str:
        return self._generate_text(
            build_sql_repair_prompt(question, invalid_sql, validation_error, conversation_context),
            task_type="sql_repair",
        )


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    return GroqProvider(settings)
