from __future__ import annotations

from observability.dashboard import render_dashboard
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report, generate_phase1_report

METRICS = {
    "samples": 10,
    "retrieval_hit_rate": 1.0,
    "mean_token_f1": 1.0,
    "judge_accuracy": 1.0,
    "mean_judge_score": 5,
    "judge_fallback_count": 0,
    "by_question_type": {"summary": {"samples": 3, "retrieval_hit_rate": 1.0, "mean_token_f1": 1.0, "judge_accuracy": 1.0}},
}
CORRUPTED = {**METRICS, "retrieval_hit_rate": 0.8, "mean_token_f1": 0.7, "judge_accuracy": 0.8, "mean_judge_score": 4.1}


def test_phase1_report_contains_sections(settings, clean_df):
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    generate_phase1_report(settings.paths.baseline_report, {"Source": "Crossref"}, METRICS, quality, freshness)
    text = settings.paths.baseline_report.read_text(encoding="utf-8")
    assert "## 2. Baseline Metrics" in text
    assert "| Mean Judge Score (1-5) | 5.0000 |" in text
    assert "\\|" in text  # ky tu `|` trong regex duoc escape de khong vo bang markdown
    assert "FRESH" in text


def test_corruption_report_and_dashboard(settings, clean_df):
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    bad_quality = {**quality, "success": False, "failed_expectations": ["expect_x(col)"]}
    stale = {**freshness, "is_fresh": False, "stale_ratio": 0.4}
    log = {"meta": {"seed": 42, "rows_before": 24, "rows_after": 22}, "events": [
        {"corruption_type": "stale_date", "description": "d", "affected_count": 6, "affected_paper_ids": []}
    ]}
    impacts = [{"id": "eval_001", "question_type": "summary", "baseline_hit": True, "corrupted_hit": False,
                "repaired_hit": True, "baseline_f1": 1.0, "corrupted_f1": 0.0, "repaired_f1": 1.0,
                "corruptions": ["drop_latest_records"], "corrupted_answer": ""}]
    repair = {"triggered": True, "reasons": ["expect_x(col)"], "source": "data/raw/crossref_records.json",
              "procedure": "p", "repaired_matches_baseline": True, "baseline_content_hash": "a" * 64,
              "repaired_content_hash": "a" * 64}
    generate_corruption_report(
        settings.paths.comparison_report, METRICS, CORRUPTED, METRICS, bad_quality, quality, stale, freshness,
        baseline_quality=quality, baseline_freshness=freshness, corruption_log=log,
        extra={"repair": repair, "question_impacts": impacts},
    )
    text = settings.paths.comparison_report.read_text(encoding="utf-8")
    assert "| Retrieval Hit Rate | 1.0000 | 0.8000 | 1.0000 | -0.2000 | 100% |" in text
    assert "Row count | 24 | 24 | 24 | +0 |" in text
    assert "Silent Failure" in text and "Auto-Repair" in text
    assert "4/4 metric" in text

    # repaired chua khop baseline -> bao cao ghi ro metric nao lech
    generate_corruption_report(
        settings.paths.comparison_report, METRICS, METRICS, CORRUPTED, quality, quality, freshness, freshness
    )
    text = settings.paths.comparison_report.read_text(encoding="utf-8")
    assert "không suy giảm" in text
    assert "Metric chưa khớp tuyệt đối baseline" in text

    dashboard = render_dashboard(settings)
    html = dashboard.read_text(encoding="utf-8")
    assert "Data Observability Dashboard" in html and "<svg" in html
