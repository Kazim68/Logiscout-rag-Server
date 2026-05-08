"""
Main evaluation loop.

For every scenario in scenarios.json:
    1. Run LogiScout (live RAG server, NDJSON stream).
    2. Run baseline (raw log dump → plain LLM).
    3. Compute retrieval metrics (Precision/Recall/MRR/Hit@K).
    4. Score both pipelines via LLM-as-Judge (Groq llama-3.3-70b-versatile).

Saves all per-scenario rows to evaluation/eval_results.csv.

Run from inside the docker container:
    docker exec logiscout-rag-api python -m evaluation.run_evaluation
"""
from evaluation import env_loader  # noqa: F401

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

# Make `evaluation.*` importable when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.metrics import (  # noqa: E402
    hit_rate_at_k,
    llm_judge,
    mrr,
    precision_at_k,
    recall_at_k,
)
from evaluation.baseline import run_baseline  # noqa: E402
from evaluation.pipeline_runner import run_logiscout_pipeline  # noqa: E402


OUTPUT_K = 5
SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"
RESULTS_CSV = Path(__file__).resolve().parent / "eval_results.csv"


def _is_zero_scores(row: dict, prefix: str) -> bool:
    keys = [f"{prefix}_correctness", f"{prefix}_completeness",
            f"{prefix}_actionability", f"{prefix}_faithfulness",
            f"{prefix}_relevance"]
    return all(int(row.get(k, 0) or 0) == 0 for k in keys)


def _load_existing_results() -> dict:
    """Load existing eval_results.csv keyed by scenario_id (for resume mode)."""
    if not RESULTS_CSV.exists():
        return {}
    try:
        df = pd.read_csv(RESULTS_CSV).fillna("")
        return {row["scenario_id"]: {k: row[k] for k in df.columns}
                for _, row in df.iterrows()}
    except Exception as exc:
        print(f"  [warn] could not read existing eval_results.csv: {exc}")
        return {}


def run_evaluation(only_failed: bool = False) -> pd.DataFrame:
    with open(SCENARIOS_PATH) as f:
        scenarios = json.load(f)

    existing = _load_existing_results() if only_failed else {}

    results: list[dict] = []
    if only_failed:
        # Carry over previously-good rows so the final CSV stays complete.
        for sid, row in existing.items():
            row_zero_ls = _is_zero_scores(row, "ls")
            row_zero_bl = _is_zero_scores(row, "bl")
            err = str(row.get("pipeline_error") or "").strip()
            if err or row_zero_ls or row_zero_bl:
                continue
            results.append(row)

    for i, scenario in enumerate(scenarios):
        if only_failed and scenario["id"] in existing:
            row = existing[scenario["id"]]
            err = str(row.get("pipeline_error") or "").strip()
            if not err and not _is_zero_scores(row, "ls") and not _is_zero_scores(row, "bl"):
                # Already good; skip.
                continue
            print(f"\n[resume] Re-running {scenario['id']} "
                  f"(error={bool(err)}, ls_zero={_is_zero_scores(row, 'ls')}, "
                  f"bl_zero={_is_zero_scores(row, 'bl')})")
        print(f"\n{'='*65}")
        print(f"[{i+1}/{len(scenarios)}] {scenario['id']} — {scenario['title']}")
        print(f"  Category: {scenario['incident_category']} | Difficulty: {scenario['difficulty']}")
        print(f"{'='*65}")

        # 1. LogiScout pipeline
        print("  [1/4] Running LogiScout pipeline...")
        ls = run_logiscout_pipeline(scenario)
        if ls.get("error"):
            print(f"  [!] LogiScout error: {ls['error']}")

        # 2. Baseline
        print("  [2/4] Running baseline (raw log dump → LLM)...")
        baseline_answer, baseline_context = run_baseline(
            scenario["query"], scenario["project_id"]
        )

        # 3. Retrieval metrics
        print("  [3/4] Computing retrieval metrics...")
        relevant_cids = set(scenario["relevant_log_cids"])
        relevant_shas = set(scenario["relevant_commit_shas"])

        log_retrieval = {
            "log_precision_at_k": precision_at_k(ls["retrieved_log_cids"], relevant_cids, OUTPUT_K),
            "log_recall_at_k":    recall_at_k(ls["retrieved_log_cids"], relevant_cids, OUTPUT_K),
            "log_mrr":            mrr(ls["retrieved_log_cids"], relevant_cids),
            "log_hit_rate_at_k":  hit_rate_at_k(ls["retrieved_log_cids"], relevant_cids, OUTPUT_K),
        }
        commit_retrieval = {
            "commit_precision_at_k": precision_at_k(ls["retrieved_commit_shas"], relevant_shas, OUTPUT_K),
            "commit_recall_at_k":    recall_at_k(ls["retrieved_commit_shas"], relevant_shas, OUTPUT_K),
            "commit_mrr":            mrr(ls["retrieved_commit_shas"], relevant_shas),
            "commit_hit_rate_at_k":  hit_rate_at_k(ls["retrieved_commit_shas"], relevant_shas, OUTPUT_K),
        }

        # 4. LLM judge
        print("  [4/4] Grading both pipelines with LLM-as-Judge...")
        ls_context_str = json.dumps(ls.get("retrieved_contexts_raw") or [], indent=2)
        ls_scores = llm_judge(
            scenario["ground_truth_root_cause"],
            ls_context_str,
            ls.get("answer") or "",
        )
        # Gemini free tier is ~10 req/min. Space judge calls to avoid bursts.
        time.sleep(7)
        bl_scores = llm_judge(
            scenario["ground_truth_root_cause"],
            baseline_context,
            baseline_answer,
        )

        intent_correct = ls.get("intent") == scenario["expected_intent"]
        actual_flags = {
            "needs_logs":      ls.get("needs_logs", False),
            "needs_commits":   ls.get("needs_commits", False),
            "needs_postmortem": ls.get("needs_postmortem", False),
        }
        flags_correct = actual_flags == scenario["expected_retrieval_flags"]

        row = {
            "scenario_id":      scenario["id"],
            "title":            scenario["title"],
            "category":         scenario["incident_category"],
            "difficulty":       scenario["difficulty"],

            "latency_seconds":  ls.get("latency_seconds", 0.0),

            "expected_intent":  scenario["expected_intent"],
            "detected_intent":  ls.get("intent"),
            "intent_correct":   intent_correct,
            "flags_correct":    flags_correct,

            "ls_correctness":   ls_scores["correctness"],
            "ls_completeness":  ls_scores["completeness"],
            "ls_actionability": ls_scores["actionability"],
            "ls_faithfulness":  ls_scores["faithfulness"],
            "ls_relevance":     ls_scores["relevance"],

            "bl_correctness":   bl_scores["correctness"],
            "bl_completeness":  bl_scores["completeness"],
            "bl_actionability": bl_scores["actionability"],
            "bl_faithfulness":  bl_scores["faithfulness"],
            "bl_relevance":     bl_scores["relevance"],

            **log_retrieval,
            **commit_retrieval,

            "ls_answer":        (ls.get("answer") or "")[:500],
            "bl_answer":        (baseline_answer or "")[:500],
            "pipeline_error":   ls.get("error") or "",
        }
        results.append(row)

        print(
            f"  ✓ LogiScout correctness: {ls_scores['correctness']}/5 "
            f"| Baseline: {bl_scores['correctness']}/5 "
            f"| Intent: {'✓' if intent_correct else '✗'} "
            f"| Latency: {ls.get('latency_seconds', 0.0)}s"
        )

        # Persist after every scenario so a crash mid-run doesn't lose work.
        pd.DataFrame(results).to_csv(RESULTS_CSV, index=False)

        # Spacing between scenarios. Gemini free tier is ~10 req/min. One
        # scenario uses 5 Gemini calls (server intent + answer, baseline,
        # LS judge, BL judge). The RAG server's intent+answer happen
        # OUTSIDE our limiter, so the limiter only sees 3 of those 5 calls
        # (budget=5/min). 60s between scenarios -> 1 scenario/min = 5
        # calls/min, leaving 5/min headroom for the unlimited server calls.
        time.sleep(60)

    df = pd.DataFrame(results)
    # Sort by scenario_id so rerun-merged output matches original order.
    if "scenario_id" in df.columns:
        df = df.sort_values("scenario_id").reset_index(drop=True)
    df.to_csv(RESULTS_CSV, index=False)
    print(f"\n{'='*65}")
    print(f"Evaluation complete. Results saved to: {RESULTS_CSV}")
    print(f"{'='*65}")
    return df


if __name__ == "__main__":
    only_failed = "--resume" in sys.argv or "--only-failed" in sys.argv
    run_evaluation(only_failed=only_failed)
