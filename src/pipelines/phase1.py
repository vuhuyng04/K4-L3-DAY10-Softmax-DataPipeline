from __future__ import annotations

import re
from typing import Any

from core.config import Settings, load_settings, normalized_provider
from core.utils import dataframe_records, now_utc, read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.dashboard import render_dashboard
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.agent import build_agent, run_agent_question
from retrieval.index import LocalEmbeddingIndex

AGENT_DEMO_QUESTIONS = (
    "Which indexed papers discuss data quality gates or observability for production RAG systems?",
)


def redact_secrets(text: str) -> str:
    return re.sub(r"(sk-|AIza|sk-ant-)[A-Za-z0-9_\-\*]{4,}", r"\1***", text)


def _load_or_build_test_set(settings: Settings, df) -> list[dict[str, Any]]:
    path = settings.paths.eval_testset
    if path.exists() and not settings.refresh_test_set:
        test_set = read_json(path)
        known_ids = set(df["paper_id"])
        if test_set and all(doc_id in known_ids for item in test_set for doc_id in item["ground_truth_doc_ids"]):
            print(f"[phase1] Reusing fixed benchmark {path.name} ({len(test_set)} questions)")
            return test_set
        print("[phase1] Existing test set references unknown documents -> rebuilding")
    return build_test_set(df, path)


def _run_agent_demo(settings: Settings, index: LocalEmbeddingIndex, test_set: list[dict[str, Any]]) -> dict[str, Any]:
    questions = [test_set[0]["question"], *AGENT_DEMO_QUESTIONS]
    payload: dict[str, Any] = {"provider": normalized_provider(settings), "model": settings.model_name}
    try:
        agent = build_agent(settings, index)
        payload["answers"] = [{"question": question, "answer": run_agent_question(agent, question)} for question in questions]
        payload["status"] = "ok"
    except Exception as exc:  # demo khong duoc lam hong baseline pipeline
        payload["status"] = "skipped"
        payload["reason"] = redact_secrets(f"{type(exc).__name__}: {exc}")[:500]
    return payload


def main(settings: Settings | None = None) -> dict[str, Any]:
    """Baseline pipeline end-to-end: ingest -> clean -> quality gate -> index -> evaluate -> report."""
    settings = settings or load_settings()
    paths = settings.paths
    run_date = now_utc()
    print(f"[phase1] Run date {run_date.date()} | provider={normalized_provider(settings)} model={settings.model_name}")

    records = fetch_source_records(settings)
    print(f"[phase1] Ingested {len(records)} raw records")

    df = build_clean_dataframe(records, run_date)
    write_csv(df, paths.clean_csv)
    write_json(paths.clean_json, dataframe_records(df))
    print(f"[phase1] Cleaned {len(df)} rows -> {paths.clean_csv.name}, {paths.clean_json.name}")

    quality = run_data_quality_checks(df, settings, "baseline")
    freshness = build_freshness_report(df, settings, paths.freshness_report)
    print(
        f"[phase1] Quality gate success={quality['success']} "
        f"({quality['successful_expectations']}/{quality['evaluated_expectations']}) | "
        f"freshness is_fresh={freshness['is_fresh']} stale_ratio={freshness['stale_ratio']}"
    )
    if not quality["success"]:
        # Quality Gate: khong cho du lieu vi pham vao vector store.
        raise RuntimeError(f"Baseline quality gate failed, refusing to index: {quality['failed_expectations']}")
    if not freshness["is_fresh"]:
        print("[phase1] WARNING: Freshness SLA violated - corpus needs a refresh (REFRESH_SOURCE=1).")

    index = LocalEmbeddingIndex.build(df, settings, paths.embeddings_json)
    print(f"[phase1] Indexed {len(index.documents)} documents into Chroma collection '{index.collection_name}'")

    test_set = _load_or_build_test_set(settings, df)
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)
    metrics = bundle.summary

    source_summary = {
        "Source": settings.source_api,
        "Chế độ": "live Crossref API" if settings.refresh_source else "offline snapshot (`data/raw/crossref_response.json`)",
        "Query": settings.source_query,
        "Filter (live mode)": settings.source_filter,
        "Raw records": len(records),
        "Clean rows": len(df),
        "Bị loại khi cleaning": len(records) - len(df),
        "Run date (UTC)": run_date.date().isoformat(),
        "Embedding model": settings.embedding_model,
        "Chroma collection": index.collection_name,
        "Retrieval top_k": settings.top_k,
        "LLM provider / model": f"{normalized_provider(settings)} / {settings.model_name}",
        "Test set": f"`data/eval/test_set.json` ({len(test_set)} câu)",
    }
    generate_phase1_report(paths.baseline_report, source_summary, metrics, quality, freshness)

    demo = _run_agent_demo(settings, index, test_set)
    write_json(paths.demo_answers, demo)
    print(f"[phase1] Agent demo status={demo['status']}")

    render_dashboard(settings)
    print(
        "[phase1] Baseline metrics: "
        + ", ".join(f"{key}={metrics[key]:.4f}" for key in ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"))
    )
    print(f"[phase1] Report -> {paths.baseline_report.relative_to(paths.project_dir).as_posix()}")
    return {"metrics": metrics, "quality": quality, "freshness": freshness}
