from __future__ import annotations

import hashlib
import json
from json import JSONDecodeError
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import dataframe_records, now_utc, read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import CLEAN_COLUMNS, build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records, parse_crossref_payload
from observability.dashboard import render_dashboard
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex

CONTENT_COLUMNS = [column for column in CLEAN_COLUMNS if column != "age_days"]
CONSOLE_METRICS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")


def content_hash(df: pd.DataFrame) -> str:
    """Hash noi dung dataset (bo `age_days` vi phu thuoc ngay chay) de chung minh repaired == baseline."""
    records = dataframe_records(df[CONTENT_COLUMNS].sort_values("paper_id").reset_index(drop=True))
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def _save_frame(df: pd.DataFrame, csv_path, json_path) -> None:
    write_csv(df, csv_path)
    write_json(json_path, dataframe_records(df))


def _repair_from_raw(settings: Settings, run_date) -> tuple[pd.DataFrame, str]:
    """Idempotent repair: build lai clean dataset tu raw snapshot bat bien, khong va du lieu hong."""
    paths = settings.paths
    try:
        records = load_raw_records(paths.raw_records_json)
        source = "data/raw/crossref_records.json"
        if not records:
            raise ValueError("empty raw records")
    except (FileNotFoundError, JSONDecodeError, TypeError, ValueError):
        records = parse_crossref_payload(read_json(paths.raw_api_response))
        source = "data/raw/crossref_response.json"
    return build_clean_dataframe(records, run_date), source


def _repair_reasons(quality: dict[str, Any], freshness: dict[str, Any]) -> list[str]:
    reasons = list(quality.get("failed_expectations") or [])
    if not freshness.get("is_fresh"):
        reasons.append(f"FreshnessSLA(stale_ratio={freshness.get('stale_ratio')} > {freshness.get('max_stale_ratio')})")
    return reasons


def _question_impacts(
    baseline_answers: list[dict[str, Any]],
    corrupted_answers: list[dict[str, Any]],
    repaired_answers: list[dict[str, Any]],
    corruption_log: dict[str, Any],
) -> list[dict[str, Any]]:
    corrupted_by_id = {item["id"]: item for item in corrupted_answers}
    repaired_by_id = {item["id"]: item for item in repaired_answers}
    impacts = []
    for base in baseline_answers:
        corrupted = corrupted_by_id.get(base["id"])
        repaired = repaired_by_id.get(base["id"])
        if not corrupted or not repaired:
            continue
        changed = (
            base["retrieval_hit"] != corrupted["retrieval_hit"]
            or abs(base["token_f1"] - corrupted["token_f1"]) > 1e-9
            or base["retrieval_hit"] != repaired["retrieval_hit"]
            or abs(base["token_f1"] - repaired["token_f1"]) > 1e-9
        )
        if not changed:
            continue
        doc_ids = set(base["ground_truth_doc_ids"])
        impacts.append(
            {
                "id": base["id"],
                "question_type": base["question_type"],
                "baseline_hit": base["retrieval_hit"],
                "corrupted_hit": corrupted["retrieval_hit"],
                "repaired_hit": repaired["retrieval_hit"],
                "baseline_f1": base["token_f1"],
                "corrupted_f1": corrupted["token_f1"],
                "repaired_f1": repaired["token_f1"],
                "corruptions": [
                    event["corruption_type"]
                    for event in corruption_log.get("events", [])
                    if doc_ids & set(event.get("affected_paper_ids", []))
                ],
                "corrupted_answer": str(corrupted["answer"]),
            }
        )
    return impacts


def _print_comparison(states: dict[str, tuple[dict, dict, dict]]) -> None:
    names = list(states)
    print("\n" + "=" * 72)
    print(f"{'Metric / Signal':<24}" + "".join(f"{name:>16}" for name in names))
    print("-" * 72)
    for key in CONSOLE_METRICS:
        print(f"{key:<24}" + "".join(f"{states[name][0].get(key, float('nan')):>16.4f}" for name in names))
    print(f"{'GX quality gate':<24}" + "".join(f"{('PASS' if states[n][1].get('success') else 'FAIL'):>16}" for n in names))
    print(f"{'Freshness SLA':<24}" + "".join(f"{('FRESH' if states[n][2].get('is_fresh') else 'STALE'):>16}" for n in names))
    print(f"{'Row count':<24}" + "".join(f"{states[n][1].get('row_count', 'n/a'):>16}" for n in names))
    print("=" * 72 + "\n")


def main(settings: Settings | None = None) -> dict[str, Any]:
    """Corruption -> evaluate -> auto-repair -> evaluate -> so sanh 3 trang thai."""
    settings = settings or load_settings()
    paths = settings.paths
    for required in (paths.clean_json, paths.baseline_metrics, paths.baseline_answers, paths.eval_testset):
        if not required.exists():
            raise FileNotFoundError(f"Missing baseline artifact {required.name}. Run `python script/run_phase1.py` first.")

    run_date = now_utc()
    baseline_metrics = read_json(paths.baseline_metrics)
    baseline_df = pd.DataFrame(read_json(paths.clean_json))
    baseline_quality = (
        read_json(paths.baseline_quality_report)
        if paths.baseline_quality_report.exists()
        else run_data_quality_checks(baseline_df, settings, "baseline")
    )
    baseline_freshness = (
        read_json(paths.freshness_report)
        if paths.freshness_report.exists()
        else build_freshness_report(baseline_df, settings, paths.freshness_report)
    )

    # 1. Tiem loi & do suy giam (co y index du lieu ban de mo phong he thong KHONG co quality gate).
    corrupted_df = corrupt_clean_dataframe(baseline_df, paths.corruption_log)
    corruption_log = read_json(paths.corruption_log)
    _save_frame(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_df, settings, paths.quality_dir / "corrupted_freshness_report.json"
    )
    print(
        f"[corruption] Injected {len(corruption_log['events'])} corruption types: rows {len(baseline_df)} -> {len(corrupted_df)} | "
        f"GX success={corrupted_quality['success']} failed={corrupted_quality['failed_expectations']} | "
        f"is_fresh={corrupted_freshness['is_fresh']}"
    )
    corrupted_index = LocalEmbeddingIndex.build(corrupted_df, settings, paths.corrupted_embeddings_json)
    corrupted_bundle = evaluate_pipeline(
        settings, corrupted_index, paths.eval_testset, paths.corrupted_metrics, paths.corrupted_answers
    )

    # 2. Auto-repair: tu kich hoat khi Quality Gate hoac Freshness SLA bi vi pham.
    reasons = _repair_reasons(corrupted_quality, corrupted_freshness)
    triggered = bool(reasons)
    if triggered:
        print(f"[repair] Violations detected -> auto-repair triggered: {reasons}")
        repaired_df, repair_source = _repair_from_raw(settings, run_date)
    else:
        print("[repair] No violation detected -> keeping current dataset")
        repaired_df, repair_source = corrupted_df.copy(), "none (no violation)"

    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = build_freshness_report(repaired_df, settings, paths.quality_dir / "repaired_freshness_report.json")
    if not repaired_quality["success"]:
        raise RuntimeError(f"Repaired dataset still fails the quality gate: {repaired_quality['failed_expectations']}")
    _save_frame(repaired_df, paths.repaired_clean_csv, paths.repaired_clean_json)
    repaired_index = LocalEmbeddingIndex.build(repaired_df, settings, paths.repaired_embeddings_json)
    repaired_bundle = evaluate_pipeline(
        settings, repaired_index, paths.eval_testset, paths.repaired_metrics, paths.repaired_answers
    )

    baseline_hash, repaired_hash = content_hash(baseline_df), content_hash(repaired_df)
    repair_log = {
        "decided_at": run_date.isoformat(),
        "triggered": triggered,
        "reasons": reasons,
        "source": repair_source,
        "procedure": (
            "load_raw_records -> build_clean_dataframe -> GX quality gate (must pass) -> "
            "rebuild Chroma `papers-repaired` -> evaluate on the same test_set.json"
        ),
        "repaired_quality_success": repaired_quality["success"],
        "repaired_is_fresh": repaired_freshness["is_fresh"],
        "baseline_content_hash": baseline_hash,
        "repaired_content_hash": repaired_hash,
        "repaired_matches_baseline": baseline_hash == repaired_hash,
    }
    write_json(paths.corruption_log.with_name("repair_log.json"), repair_log)

    impacts = _question_impacts(
        read_json(paths.baseline_answers), corrupted_bundle.answers, repaired_bundle.answers, corruption_log
    )
    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics,
        corrupted_bundle.summary,
        repaired_bundle.summary,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
        baseline_quality=baseline_quality,
        baseline_freshness=baseline_freshness,
        corruption_log=corruption_log,
        extra={"repair": repair_log, "question_impacts": impacts},
    )
    render_dashboard(settings)

    _print_comparison(
        {
            "Baseline": (baseline_metrics, baseline_quality, baseline_freshness),
            "Corrupted": (corrupted_bundle.summary, corrupted_quality, corrupted_freshness),
            "Repaired": (repaired_bundle.summary, repaired_quality, repaired_freshness),
        }
    )
    print(f"[repair] repaired_matches_baseline={repair_log['repaired_matches_baseline']}")
    print(f"[corruption] Report -> {paths.comparison_report.relative_to(paths.project_dir).as_posix()}")
    return {
        "baseline": baseline_metrics,
        "corrupted": corrupted_bundle.summary,
        "repaired": repaired_bundle.summary,
        "repair": repair_log,
    }
