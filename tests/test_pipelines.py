from __future__ import annotations

import pytest

from core.utils import read_json
from pipelines import corruption_flow, phase1


def test_corruption_flow_requires_baseline(settings):
    with pytest.raises(FileNotFoundError):
        corruption_flow.main(settings)


def test_end_to_end_baseline_corruption_repair(settings):
    paths = settings.paths
    baseline = phase1.main(settings)
    assert baseline["quality"]["success"] is True
    assert baseline["metrics"]["retrieval_hit_rate"] == 1.0
    assert baseline["metrics"]["judge_fallback_count"] == baseline["metrics"]["samples"] == 10
    for artifact in (
        paths.clean_csv,
        paths.clean_json,
        paths.eval_testset,
        paths.baseline_metrics,
        paths.baseline_answers,
        paths.baseline_quality_report,
        paths.freshness_report,
        paths.baseline_report,
        paths.demo_answers,
    ):
        assert artifact.exists(), artifact
    assert "Baseline Metrics" in paths.baseline_report.read_text(encoding="utf-8")

    # Chay lai phase 1: tai su dung test set co dinh, metrics khong doi (idempotent).
    test_set_before = read_json(paths.eval_testset)
    assert phase1.main(settings)["metrics"]["mean_token_f1"] == baseline["metrics"]["mean_token_f1"]
    assert read_json(paths.eval_testset) == test_set_before

    result = corruption_flow.main(settings)
    assert result["corrupted"]["retrieval_hit_rate"] < result["baseline"]["retrieval_hit_rate"]
    assert result["corrupted"]["mean_token_f1"] < result["baseline"]["mean_token_f1"]
    for key in ("retrieval_hit_rate", "mean_token_f1"):
        assert result["repaired"][key] == result["baseline"][key]
    assert result["repair"]["triggered"] is True
    assert result["repair"]["repaired_matches_baseline"] is True
    assert read_json(paths.corrupted_quality_report)["success"] is False
    assert read_json(paths.quality_dir / "repaired_quality_report.json")["success"] is True

    report = paths.comparison_report.read_text(encoding="utf-8")
    assert "| Metric / Signal | Baseline | Corrupted | Repaired |" in report
    assert "Silent Failure" in report
    assert paths.baseline_report.with_name("dashboard.html").exists()

    # Chay lai corruption flow: ket qua tat dinh.
    again = corruption_flow.main(settings)
    assert again["corrupted"]["retrieval_hit_rate"] == result["corrupted"]["retrieval_hit_rate"]
    assert again["repaired"]["mean_token_f1"] == result["repaired"]["mean_token_f1"]


def test_phase1_blocks_indexing_when_gate_fails(settings, monkeypatch):
    monkeypatch.setattr(
        phase1,
        "run_data_quality_checks",
        lambda df, settings, name: {"success": False, "failed_expectations": ["x"], "successful_expectations": 0,
                                    "evaluated_expectations": 1},
    )
    with pytest.raises(RuntimeError, match="refusing to index"):
        phase1.main(settings)
    assert not settings.paths.embeddings_json.exists()


def test_redact_secrets():
    assert phase1.redact_secrets("bad key sk-proj-abcdef123456") == "bad key sk-***"
