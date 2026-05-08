"""Generate tables, charts, and a printed summary from eval_results.csv."""
from evaluation import env_loader  # noqa: F401

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # safe for headless / docker

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


HERE = Path(__file__).resolve().parent
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def safe_gain(ls_val: float, bl_val: float) -> float:
    return round(((ls_val - bl_val) / bl_val) * 100, 1) if bl_val > 0 else float("inf")


def main() -> None:
    df = pd.read_csv(HERE / "eval_results.csv")
    n = len(df)

    # Coerce booleans (CSV roundtrip can leave them as strings).
    for col in ("intent_correct", "flags_correct"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().isin(("true", "1", "yes"))

    # ── Table 1: Comparative Results ──────────────────────────────────────────
    comparative = df[[
        "scenario_id", "title", "difficulty",
        "bl_correctness", "ls_correctness",
        "bl_faithfulness", "ls_faithfulness",
        "bl_relevance", "ls_relevance",
        "latency_seconds",
    ]].copy()
    avg_row = comparative.select_dtypes(include="number").mean()
    avg_row["scenario_id"] = "AVERAGE"
    avg_row["title"] = ""
    avg_row["difficulty"] = ""
    comparative.loc[len(comparative)] = avg_row
    comparative.to_csv(OUTPUT_DIR / "comparative_table.csv", index=False)
    print("=== Table 1: Comparative Results ===")
    print(comparative.to_string(index=False))

    # ── Table 2: Retrieval Performance ────────────────────────────────────────
    retrieval = df[[
        "scenario_id",
        "log_precision_at_k", "log_recall_at_k", "log_mrr", "log_hit_rate_at_k",
        "commit_precision_at_k", "commit_recall_at_k", "commit_mrr", "commit_hit_rate_at_k",
    ]].copy()
    avg_row = retrieval.select_dtypes(include="number").mean()
    avg_row["scenario_id"] = "AVERAGE"
    retrieval.loc[len(retrieval)] = avg_row
    retrieval.to_csv(OUTPUT_DIR / "retrieval_table.csv", index=False)
    print("\n=== Table 2: Retrieval Performance ===")
    print(retrieval.to_string(index=False))

    # ── Table 3: Aggregate Summary ────────────────────────────────────────────
    avg_ls_correctness = df["ls_correctness"].mean()
    avg_bl_correctness = df["bl_correctness"].mean()
    avg_ls_faithfulness = df["ls_faithfulness"].mean()
    avg_bl_faithfulness = df["bl_faithfulness"].mean()

    summary_rows = [
        ("N Scenarios", n),
        ("Intent Detection Accuracy (%)", round(df["intent_correct"].mean() * 100, 1)),
        ("Retrieval Flag Accuracy (%)",   round(df["flags_correct"].mean() * 100, 1)),
        ("Avg Log Precision@5",           round(df["log_precision_at_k"].mean(), 3)),
        ("Avg Log Recall@5",              round(df["log_recall_at_k"].mean(), 3)),
        ("Avg Log MRR",                   round(df["log_mrr"].mean(), 3)),
        ("Avg Log Hit Rate@5",            round(df["log_hit_rate_at_k"].mean(), 3)),
        ("Avg Commit Precision@5",        round(df["commit_precision_at_k"].mean(), 3)),
        ("Avg Commit Hit Rate@5",         round(df["commit_hit_rate_at_k"].mean(), 3)),
        ("LogiScout Avg Correctness",     round(avg_ls_correctness, 2)),
        ("Baseline Avg Correctness",      round(avg_bl_correctness, 2)),
        ("Correctness Improvement (%)",   safe_gain(avg_ls_correctness, avg_bl_correctness)),
        ("LogiScout Avg Faithfulness",    round(avg_ls_faithfulness, 2)),
        ("Baseline Avg Faithfulness",     round(avg_bl_faithfulness, 2)),
        ("Faithfulness Improvement (%)",  safe_gain(avg_ls_faithfulness, avg_bl_faithfulness)),
        ("LogiScout Avg Completeness",    round(df["ls_completeness"].mean(), 2)),
        ("Baseline Avg Completeness",     round(df["bl_completeness"].mean(), 2)),
        ("LogiScout Avg Actionability",   round(df["ls_actionability"].mean(), 2)),
        ("Baseline Avg Actionability",    round(df["bl_actionability"].mean(), 2)),
        ("Avg E2E Latency (s)",           round(df["latency_seconds"].mean(), 2)),
    ]

    summary_df = pd.DataFrame(summary_rows, columns=["Metric", "Value"])
    summary_df.to_csv(OUTPUT_DIR / "aggregate_summary.csv", index=False)
    print("\n=== Table 3: Aggregate Summary ===")
    print(summary_df.to_string(index=False))

    # ── Chart 1: Answer Quality ───────────────────────────────────────────────
    dims = ["correctness", "completeness", "actionability", "faithfulness", "relevance"]
    ls_means = [df[f"ls_{d}"].mean() for d in dims]
    bl_means = [df[f"bl_{d}"].mean() for d in dims]

    x = list(range(len(dims)))
    fig, ax = plt.subplots(figsize=(11, 5))
    bars1 = ax.bar([i - 0.2 for i in x], bl_means, 0.38, label="Baseline (Manual)", color="#e57373", alpha=0.9)
    bars2 = ax.bar([i + 0.2 for i in x], ls_means, 0.38, label="LogiScout",         color="#4db6ac", alpha=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels([d.capitalize() for d in dims], fontsize=11)
    ax.set_ylim(0, 5.5)
    ax.set_ylabel("Score (0-5)", fontsize=11)
    ax.set_title("Answer Quality: LogiScout vs Baseline (LLM-as-Judge)", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    for bar in list(bars1) + list(bars2):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                f"{bar.get_height():.1f}", ha="center", va="bottom", fontsize=8)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart_answer_quality.png", dpi=150)
    plt.close()
    print(f"\nSaved: {OUTPUT_DIR / 'chart_answer_quality.png'}")

    # ── Chart 2: Retrieval Metrics per Scenario ───────────────────────────────
    fig, ax = plt.subplots(figsize=(max(12, n), 5))
    x_labels = df["scenario_id"].tolist()
    x_pos = list(range(len(x_labels)))
    ax.plot(x_pos, df["log_precision_at_k"], marker="o", label="Log Precision@5", linewidth=1.5)
    ax.plot(x_pos, df["log_recall_at_k"],    marker="s", label="Log Recall@5",    linewidth=1.5)
    ax.plot(x_pos, df["log_hit_rate_at_k"],  marker="^", label="Log Hit Rate@5",  linewidth=1.5)
    ax.plot(x_pos, df["log_mrr"],            marker="D", label="Log MRR",         linewidth=1.5, linestyle="--")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(-0.05, 1.1)
    ax.set_ylabel("Score (0-1)")
    ax.set_title("Retrieval Metrics per Scenario (Logs Collection)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart_retrieval_metrics.png", dpi=150)
    plt.close()
    print(f"Saved: {OUTPUT_DIR / 'chart_retrieval_metrics.png'}")

    # ── Chart 3: Difficulty vs Correctness ────────────────────────────────────
    diff_map = {"easy": 1, "medium": 2, "hard": 3}
    df["difficulty_num"] = df["difficulty"].map(diff_map)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(df["difficulty_num"] - 0.05, df["ls_correctness"], color="#4db6ac",
               s=90, label="LogiScout", alpha=0.85, zorder=3)
    ax.scatter(df["difficulty_num"] + 0.05, df["bl_correctness"], color="#e57373",
               s=90, label="Baseline",  alpha=0.75, marker="x", zorder=3, linewidths=2)
    ax.set_xticks([1, 2, 3])
    ax.set_xticklabels(["Easy", "Medium", "Hard"])
    ax.set_ylim(-0.2, 5.5)
    ax.set_ylabel("Correctness (0-5)")
    ax.set_title("Scenario Difficulty vs Correctness Score")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "chart_difficulty_vs_correctness.png", dpi=150)
    plt.close()
    print(f"Saved: {OUTPUT_DIR / 'chart_difficulty_vs_correctness.png'}")

    # ── Final Summary ─────────────────────────────────────────────────────────
    print(f"""
==============================================================
  LOGISCOUT EVALUATION SUMMARY
  N = {n} incident scenarios | Judge: Groq llama-3.3-70b-versatile

  -- Answer Quality (LLM-as-Judge, 0-5 scale) ----------------
  Metric           LogiScout   Baseline    Improvement
  Correctness      {avg_ls_correctness:.2f}/5       {avg_bl_correctness:.2f}/5       +{safe_gain(avg_ls_correctness, avg_bl_correctness)}%
  Faithfulness     {df['ls_faithfulness'].mean():.2f}/5       {df['bl_faithfulness'].mean():.2f}/5       +{safe_gain(df['ls_faithfulness'].mean(), df['bl_faithfulness'].mean())}%
  Completeness     {df['ls_completeness'].mean():.2f}/5       {df['bl_completeness'].mean():.2f}/5       +{safe_gain(df['ls_completeness'].mean(), df['bl_completeness'].mean())}%
  Actionability    {df['ls_actionability'].mean():.2f}/5       {df['bl_actionability'].mean():.2f}/5       +{safe_gain(df['ls_actionability'].mean(), df['bl_actionability'].mean())}%
  Relevance        {df['ls_relevance'].mean():.2f}/5       {df['bl_relevance'].mean():.2f}/5

  -- Retrieval Quality ---------------------------------------
  Log Precision@5:  {df['log_precision_at_k'].mean():.3f}
  Log Recall@5:     {df['log_recall_at_k'].mean():.3f}
  Log MRR:          {df['log_mrr'].mean():.3f}
  Log Hit Rate@5:   {df['log_hit_rate_at_k'].mean():.3f}
  Commit Prec@5:    {df['commit_precision_at_k'].mean():.3f}
  Commit Hit@5:     {df['commit_hit_rate_at_k'].mean():.3f}

  -- Intent Detection ----------------------------------------
  Intent Accuracy:  {round(df['intent_correct'].mean() * 100, 1)}%
  Flag Accuracy:    {round(df['flags_correct'].mean() * 100, 1)}%

  -- Performance ---------------------------------------------
  Avg E2E Latency:  {round(df['latency_seconds'].mean(), 2)}s

  All scores computed via automated LLM-as-Judge.
  Zero human scoring at any point.
==============================================================
""")


if __name__ == "__main__":
    main()
