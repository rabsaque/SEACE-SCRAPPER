"""
AI filtering layer — supports Azure OpenAI, Groq, and Google Gemini.

Set AI_PROVIDER in .env to choose:
  AI_PROVIDER=groq    (default — free tier at console.groq.com)
  AI_PROVIDER=gemini  (free tier at aistudio.google.com)
  AI_PROVIDER=azure   (Azure OpenAI)

All three use the openai Python package via compatible endpoints.
No AI key configured → returns a SKIPPED result silently.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from loguru import logger

from src.config import settings


# ── Result model ──────────────────────────────────────────────────────────────

@dataclass
class AIFilterResult:
    match_score: int
    match_level: str             # HIGH | MEDIUM | LOW | NO_MATCH | SKIPPED
    summary: str
    key_requirements: list[str]
    disqualifiers: list[str]
    raw_response: str
    ai_used: bool = False
    provider: str = ""           # which provider was used


def _skipped_result(reason: str = "AI scoring disabled") -> AIFilterResult:
    return AIFilterResult(
        match_score=0, match_level="SKIPPED", summary=reason,
        key_requirements=[], disqualifiers=[], raw_response="",
        ai_used=False, provider="",
    )


def _level(score: int) -> str:
    if score >= 75: return "HIGH"
    if score >= 40: return "MEDIUM"
    if score >= 15: return "LOW"
    return "NO_MATCH"


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a business development analyst for a Peruvian facilities-management company.
Evaluate a government procurement document and decide whether our company should bid.

Respond ONLY with valid JSON — no markdown fences, no extra text.

JSON schema:
{
  "match_score": <integer 0-100>,
  "summary": "<2-4 sentences in Spanish explaining the fit>",
  "key_requirements": ["<requirement 1>", ...],
  "disqualifiers": ["<issue 1>", ...]
}

Scoring guide:
  90-100  Perfect fit
  70-89   Strong fit
  40-69   Partial fit
  15-39   Weak fit
   0-14   No match
"""


def _build_user_message(tech_specs: str, entity: str, description: str) -> str:
    return f"""\
## Company Capabilities
{settings.company_capabilities.strip()}

## Procurement
Entity: {entity}
Description: {description}

## Technical Specifications (from PDF)
{tech_specs[:12_000]}

Respond with JSON only.
"""


# ── Client factory ────────────────────────────────────────────────────────────

_client = None
_active_provider: str = ""


def _get_client():
    """Return (openai_client, model_name, provider_label) for the configured provider."""
    global _client, _active_provider

    provider = settings.ai_provider.lower()

    if _client is not None and _active_provider == provider:
        return _client

    from openai import AzureOpenAI, OpenAI

    if provider == "azure":
        if not settings.azure_api_key:
            return None
        _client = AzureOpenAI(
            api_key=settings.azure_api_key,
            azure_endpoint=settings.azure_api_base,
            api_version=settings.azure_api_version,
        )

    elif provider == "groq":
        if not settings.groq_api_key:
            return None
        _client = OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

    elif provider == "gemini":
        if not settings.gemini_api_key:
            return None
        _client = OpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    else:
        logger.warning("Unknown AI_PROVIDER={!r}. Use azure, groq, or gemini.", provider)
        return None

    _active_provider = provider
    return _client


def _get_model() -> str:
    provider = settings.ai_provider.lower()
    if provider == "azure":   return settings.azure_deployment
    if provider == "groq":    return settings.groq_model
    if provider == "gemini":  return settings.gemini_model
    return "gpt-4o"


def _call_ai(user_message: str) -> str:
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
    from openai import APITimeoutError, RateLimitError

    client = _get_client()
    model  = _get_model()

    @retry(
        retry=retry_if_exception_type((APITimeoutError, RateLimitError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
    )
    def _inner() -> str:
        response = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
        )
        return response.choices[0].message.content or ""

    return _inner()


def _parse_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]+\}", cleaned)
        if m:
            return json.loads(m.group())
        raise


# ── Public API ────────────────────────────────────────────────────────────────

def _has_api_key() -> bool:
    p = settings.ai_provider.lower()
    if p == "azure":  return bool(settings.azure_api_key)
    if p == "groq":   return bool(settings.groq_api_key)
    if p == "gemini": return bool(settings.gemini_api_key)
    return False


def analyse_lead(
    tech_specs: str,
    entity: str = "",
    description: str = "",
    skip: bool = False,
) -> AIFilterResult:
    if skip:
        return _skipped_result("AI scoring skipped (--no-ai flag)")

    if not _has_api_key():
        return _skipped_result(
            f"AI scoring skipped — no API key set for provider '{settings.ai_provider}'. "
            "Add the key to .env to enable scoring."
        )

    if not tech_specs.strip():
        return _skipped_result("No technical specifications text extracted from PDF.")

    provider = settings.ai_provider.lower()
    model    = _get_model()
    logger.info("Sending specs to {} / {} ({} chars)…", provider, model, len(tech_specs))

    try:
        raw  = _call_ai(_build_user_message(tech_specs, entity, description))
        data = _parse_response(raw)
        score = max(0, min(100, int(data.get("match_score", 0))))
        result = AIFilterResult(
            match_score=score,
            match_level=_level(score),
            summary=data.get("summary", ""),
            key_requirements=data.get("key_requirements", []),
            disqualifiers=data.get("disqualifiers", []),
            raw_response=raw,
            ai_used=True,
            provider=f"{provider}/{model}",
        )
        logger.info("AI score: {} ({}) — {}", score, result.match_level, result.summary[:80])
        return result

    except Exception as exc:
        logger.error("AI filter failed: {}", exc)
        return _skipped_result(f"AI call failed: {exc}")
