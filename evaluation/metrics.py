"""Retrieval metrics + LLM-as-Judge for the RAG evaluation pipeline."""

from evaluation import env_loader  # noqa: F401

import json
import os
import time
from typing import Iterable, List

import httpx


# ── Retrieval Metrics ─────────────────────────────────────────────────────────

def precision_at_k(retrieved_ids: List[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant_set = set(relevant_ids)
    top_k = retrieved_ids[:k]
    if k <= 0:
        return 0.0
    hits = sum(1 for rid in top_k if rid in relevant_set)
    return hits / k


def recall_at_k(retrieved_ids: List[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant_set = set(relevant_ids)
    if not relevant_set:
        # Vacuously perfect: nothing relevant means nothing to miss.
        return 1.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for rid in top_k if rid in relevant_set)
    return hits / len(relevant_set)


def mrr(retrieved_ids: List[str], relevant_ids: Iterable[str]) -> float:
    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 0.0
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_set:
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(retrieved_ids: List[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 1.0
    return 1.0 if any(r in relevant_set for r in retrieved_ids[:k]) else 0.0


# ── LLM-as-Judge ──────────────────────────────────────────────────────────────

JUDGE_PROMPT = """You are an impartial evaluator of an incident resolution AI system.

Ground Truth Root Cause:
{ground_truth}

Retrieved Evidence Provided to the System:
{retrieved_context}

System's Answer:
{answer}

Score each dimension from 0 to 5 using these exact criteria:

1. correctness: Did the answer correctly identify the root cause?
   5 = exact match to ground truth | 3 = partially correct | 0 = completely wrong or missing

2. completeness: Did the answer reference all the key evidence?
   5 = all key evidence cited | 3 = some cited | 0 = none cited

3. actionability: Did the answer provide specific, useful next steps?
   5 = clear actionable steps | 3 = vague suggestions | 0 = no next steps

4. faithfulness: Does the answer ONLY use information from the retrieved evidence?
   5 = fully grounded in evidence | 3 = minor extrapolation | 0 = hallucinated facts

5. relevance: Is the answer directly addressing what the user asked?
   5 = directly on-topic | 3 = partially relevant | 0 = off-topic

Respond ONLY with a JSON object. No explanation. No markdown. No preamble:
{{"correctness": N, "completeness": N, "actionability": N, "faithfulness": N, "relevance": N}}"""


JUDGE_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

REQUIRED_JUDGE_KEYS = {"correctness", "completeness", "actionability",
                       "faithfulness", "relevance"}


def _gemini_key() -> str:
    return (os.environ.get("JUDGE_GEMINI_KEY")
            or os.environ.get("GEMINI_KEY")
            or "")


def _parse_scores(text: str) -> dict:
    text = (text or "").strip().replace("```json", "").replace("```", "").strip()
    scores = json.loads(text)
    if not REQUIRED_JUDGE_KEYS.issubset(scores.keys()):
        raise ValueError(f"missing keys: {REQUIRED_JUDGE_KEYS - set(scores.keys())}")
    return {k: int(round(float(scores[k]))) for k in REQUIRED_JUDGE_KEYS}


def llm_judge(ground_truth: str, retrieved_context: str, answer: str,
              max_retries: int = 6) -> dict:
    """Score an answer using Gemini 2.5 Flash.

    Gemini-only path by user instruction — Groq quota is exhausted with very
    long retry-after windows. All requests go through the global rate limiter
    so we stay under Gemini's 10 req/min free-tier limit.

    Bias caveat: Gemini is also LogiScout's primary LLM, which violates the
    'judge != system-under-test' guidance. Document this in the FYP report.
    """
    from evaluation.rate_limiter import gemini_acquire

    prompt = JUDGE_PROMPT.format(
        ground_truth=ground_truth,
        retrieved_context=(retrieved_context or "")[:3000],
        answer=(answer or "")[:3000],
    )

    api_key = _gemini_key()
    if not api_key:
        print("  [Judge] No Gemini key configured; returning zeros")
        return {k: 0 for k in REQUIRED_JUDGE_KEYS}

    url = GEMINI_URL_TEMPLATE.format(model=JUDGE_GEMINI_MODEL)
    body = {
        "contents": [{"parts": [{"text": prompt}], "role": "user"}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
        },
    }

    last_err: Exception | None = None
    for attempt in range(max_retries):
        gemini_acquire()
        try:
            resp = httpx.post(url, params={"key": api_key}, json=body, timeout=60)
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after else 30.0 * (attempt + 1)
                wait = min(wait, 90.0)
                print(f"  [Judge/Gemini] 429; sleeping {wait:.1f}s "
                      f"(attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise ValueError(f"empty candidates: {data}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts)
            return _parse_scores(text)
        except Exception as e:
            last_err = e
            time.sleep(min(20.0, 2 ** attempt))

    print(f"  [Judge/Gemini] Failed after {max_retries} attempts: {last_err}")
    return {k: 0 for k in REQUIRED_JUDGE_KEYS}
