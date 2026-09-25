from __future__ import annotations

from typing import Any

from core.utils import now_utc, write_text

METRIC_KEYS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")
METRIC_LABELS = {
    "retrieval_hit_rate": "Retrieval Hit Rate",
    "mean_token_f1": "Mean Token F1",
    "judge_accuracy": "Judge Accuracy",
    "mean_judge_score": "Mean Judge Score (1-5)",
}
EXPECTED_SIGNALS = {
    "drop_latest_records": "Row count giảm, `latest_published` lùi về quá khứ; câu hỏi về bài bị mất không truy xuất được",
    "blank_summary": "GX `ExpectColumnValueLengthsToBeBetween(summary >= 30)` fail",
    "inject_noise": "GX `ExpectColumnValuesToNotMatchRegex(summary)` fail",
    "truncate_title": "GX `ExpectColumnValueLengthsToBeBetween(title >= 8)` fail",
    "stale_date": "Freshness SLA fail (`stale_ratio` > 25%)",
    "duplicate_rows": "GX `ExpectColumnValuesToBeUnique(paper_id)` fail",
}


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None:
        return "n/a"
    return str(value)


def _metric(value: Any) -> Any:
    """Metric luon hien thi dang so thuc (mean() tra ve int khi moi gia tri bang nhau)."""
    return float(value) if isinstance(value, int) and not isinstance(value, bool) else value


def _cell(value: Any) -> str:
    return _fmt(value).replace("|", "\\|")


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return lines


def _expectation_label(item: dict[str, Any]) -> str:
    kwargs = item.get("kwargs") or {}
    bounds = []
    for key in ("min_value", "max_value", "regex"):
        if kwargs.get(key) is not None:
            bounds.append(f"{key}={kwargs[key]}")
    target = item.get("column") or "table"
    suffix = f" [{', '.join(bounds)}]" if bounds else ""
    return f"`{item['expectation_type']}`({target}){suffix}"


def _expectation_rows(quality: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in quality.get("expectations", []):
        observed = item.get("observed_value")
        if observed is None and item.get("unexpected_count") is not None:
            observed = f"unexpected={item['unexpected_count']}"
        rows.append([_expectation_label(item), bool(item["success"]), observed])
    return rows


def _freshness_rows(freshness: dict[str, Any]) -> list[list[Any]]:
    return [
        ["Ngưỡng tuổi (threshold_days)", freshness.get("threshold_days")],
        ["Tỷ lệ stale tối đa cho phép", freshness.get("max_stale_ratio")],
        ["Bài mới nhất (latest_published)", freshness.get("latest_published")],
        ["Bài cũ nhất (oldest_published)", freshness.get("oldest_published")],
        ["Số bài stale / tổng", f"{freshness.get('stale_rows')} / {freshness.get('total_rows')}"],
        ["stale_ratio", freshness.get("stale_ratio")],
        ["is_fresh", bool(freshness.get("is_fresh"))],
    ]


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Viet markdown report cho baseline phase tu cac artifact thuc te."""
    lines = [
        "# Phase 1 — Baseline Pipeline Report",
        "",
        f"> Sinh tự động bởi `script/run_phase1.py` lúc {now_utc().isoformat()}. Mọi số liệu đọc từ artifact thực tế.",
        "",
        "## 1. Nguồn dữ liệu & Lineage",
        "",
        *_table(["Thuộc tính", "Giá trị"], [[key, value] for key, value in source_summary.items()]),
        "",
        "## 2. Baseline Metrics",
        "",
        *_table(["Metric", "Giá trị"], [[METRIC_LABELS[key], _metric(metrics.get(key))] for key in METRIC_KEYS]),
        "",
        f"- Số câu hỏi đánh giá: **{metrics.get('samples')}**; số lần LLM judge phải fallback heuristic: "
        f"**{metrics.get('judge_fallback_count', 'n/a')}**.",
        "",
    ]
    by_type = metrics.get("by_question_type") or {}
    if by_type:
        lines += [
            "### Theo loại câu hỏi",
            "",
            *_table(
                ["question_type", "samples", "hit_rate", "token_f1", "judge_accuracy"],
                [
                    [name, item["samples"], item["retrieval_hit_rate"], item["mean_token_f1"], item["judge_accuracy"]]
                    for name, item in by_type.items()
                ],
            ),
            "",
        ]
    lines += [
        f"## 3. Data Quality Gate (Great Expectations 1.x) — **{_fmt(bool(quality.get('success')))}**",
        "",
        f"- Engine: `{quality.get('engine')}`, suite `{quality.get('suite_name')}`, "
        f"{quality.get('successful_expectations')}/{quality.get('evaluated_expectations')} expectations pass, "
        f"row_count = {quality.get('row_count')}.",
        "",
        *_table(["Expectation", "Kết quả", "Observed"], _expectation_rows(quality)),
        "",
        f"## 4. Freshness SLA — **{'FRESH' if freshness.get('is_fresh') else 'STALE'}**",
        "",
        *_table(["Thuộc tính", "Giá trị"], _freshness_rows(freshness)),
        "",
        "## 5. Kết luận",
        "",
    ]
    gate = "đã vượt" if quality.get("success") else "KHÔNG vượt"
    fresh = "đạt" if freshness.get("is_fresh") else "KHÔNG đạt"
    lines += [
        f"- Dữ liệu sạch {gate} Quality Gate và {fresh} Freshness SLA "
        f"(stale_ratio = {_fmt(freshness.get('stale_ratio'))} so với ngưỡng {freshness.get('max_stale_ratio')}).",
        f"- Baseline RAG đạt hit rate = {_fmt(metrics.get('retrieval_hit_rate'))}, "
        f"token F1 = {_fmt(metrics.get('mean_token_f1'))}, judge accuracy = {_fmt(metrics.get('judge_accuracy'))}. "
        "Đây là mốc tham chiếu cho corruption flow (dùng chung `data/eval/test_set.json`).",
        "",
    ]
    write_text(report_path, "\n".join(lines))


def _delta(after: Any, before: Any, *, integer: bool = False) -> str:
    if isinstance(after, (int, float)) and isinstance(before, (int, float)) and not isinstance(after, bool):
        return f"{after - before:+d}" if integer else f"{after - before:+.4f}"
    return "—"


def _recovery(baseline: Any, corrupted: Any, repaired: Any) -> str:
    numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (baseline, corrupted, repaired))
    if not numeric:
        return "—"
    drop = baseline - corrupted
    if abs(drop) < 1e-9:
        return "không suy giảm"
    return f"{(repaired - corrupted) / drop:.0%}"


def _signal_rows(
    baseline_quality: dict[str, Any] | None,
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    baseline_freshness: dict[str, Any] | None,
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> list[list[Any]]:
    bq = baseline_quality or {}
    bf = baseline_freshness or {}
    return [
        ["GX Quality Gate", bq.get("success"), corrupted_quality.get("success"), repaired_quality.get("success"), "—", "—"],
        [
            "GX expectations pass",
            f"{bq.get('successful_expectations', 'n/a')}/{bq.get('evaluated_expectations', 'n/a')}",
            f"{corrupted_quality.get('successful_expectations')}/{corrupted_quality.get('evaluated_expectations')}",
            f"{repaired_quality.get('successful_expectations')}/{repaired_quality.get('evaluated_expectations')}",
            "—",
            "—",
        ],
        ["Row count", bq.get("row_count"), corrupted_quality.get("row_count"), repaired_quality.get("row_count"),
         _delta(corrupted_quality.get("row_count"), bq.get("row_count"), integer=True), "—"],
        ["Freshness is_fresh", bf.get("is_fresh"), corrupted_freshness.get("is_fresh"), repaired_freshness.get("is_fresh"), "—", "—"],
        ["stale_ratio", bf.get("stale_ratio"), corrupted_freshness.get("stale_ratio"), repaired_freshness.get("stale_ratio"),
         _delta(corrupted_freshness.get("stale_ratio"), bf.get("stale_ratio")), "—"],
        ["latest_published", bf.get("latest_published"), corrupted_freshness.get("latest_published"),
         repaired_freshness.get("latest_published"), "—", "—"],
    ]


def _expectation_matrix(states: dict[str, dict[str, Any]]) -> list[list[Any]]:
    labels: list[str] = []
    lookup: dict[str, dict[str, dict[str, Any]]] = {}
    for state, quality in states.items():
        for item in quality.get("expectations", []):
            label = _expectation_label(item)
            if label not in lookup:
                labels.append(label)
                lookup[label] = {}
            lookup[label][state] = item
    rows = []
    for label in labels:
        row: list[Any] = [label]
        for state in states:
            item = lookup[label].get(state)
            if item is None:
                row.append("n/a")
                continue
            unexpected = item.get("unexpected_count")
            row.append(("PASS" if item["success"] else "FAIL") + (f" ({unexpected} lỗi)" if unexpected else ""))
        rows.append(row)
    return rows


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
    *,
    baseline_quality: dict[str, Any] | None = None,
    baseline_freshness: dict[str, Any] | None = None,
    corruption_log: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Viet markdown report so sanh Baseline vs Corrupted vs Repaired (kem phan tich nhan qua tu so lieu)."""
    extra = extra or {}
    metric_rows = [
        [
            METRIC_LABELS[key],
            _metric(baseline_metrics.get(key)),
            _metric(corrupted_metrics.get(key)),
            _metric(repaired_metrics.get(key)),
            _delta(corrupted_metrics.get(key), baseline_metrics.get(key)),
            _recovery(baseline_metrics.get(key), corrupted_metrics.get(key), repaired_metrics.get(key)),
        ]
        for key in METRIC_KEYS
    ]
    headers = ["Metric / Signal", "Baseline", "Corrupted", "Repaired", "Δ do corruption", "Mức phục hồi"]

    lines = [
        "# Corruption & Repair Report — Baseline vs Corrupted vs Repaired",
        "",
        f"> Sinh tự động bởi `script/run_corruption_flow.py` lúc {now_utc().isoformat()}. "
        "Cả 3 trạng thái được đánh giá trên **cùng** `data/eval/test_set.json` "
        f"({baseline_metrics.get('samples')} câu hỏi), cùng embedding model và cùng `top_k`.",
        "",
        "## 1. Bảng đối chiếu 3 trạng thái",
        "",
        *_table(headers, metric_rows),
        *_table(headers, _signal_rows(
            baseline_quality, corrupted_quality, repaired_quality,
            baseline_freshness, corrupted_freshness, repaired_freshness,
        ))[2:],
        "",
    ]

    types = sorted(
        set(baseline_metrics.get("by_question_type", {}))
        | set(corrupted_metrics.get("by_question_type", {}))
        | set(repaired_metrics.get("by_question_type", {}))
    )
    if types:
        type_rows = []
        for name in types:
            b = baseline_metrics.get("by_question_type", {}).get(name, {})
            c = corrupted_metrics.get("by_question_type", {}).get(name, {})
            r = repaired_metrics.get("by_question_type", {}).get(name, {})
            type_rows.append([
                name, b.get("samples"),
                f"{_fmt(b.get('retrieval_hit_rate'))} / {_fmt(c.get('retrieval_hit_rate'))} / {_fmt(r.get('retrieval_hit_rate'))}",
                f"{_fmt(b.get('mean_token_f1'))} / {_fmt(c.get('mean_token_f1'))} / {_fmt(r.get('mean_token_f1'))}",
            ])
        lines += [
            "## 2. Theo loại câu hỏi (Baseline / Corrupted / Repaired)",
            "",
            *_table(["question_type", "samples", "Hit rate", "Token F1"], type_rows),
            "",
        ]

    states = {"Baseline": baseline_quality or {}, "Corrupted": corrupted_quality, "Repaired": repaired_quality}
    lines += [
        "## 3. Quality Gate chi tiết (Great Expectations 1.x)",
        "",
        *_table(["Expectation", *states.keys()], _expectation_matrix(states)),
        "",
    ]

    if corruption_log:
        meta = corruption_log.get("meta", {})
        lines += [
            "## 4. Nhật ký tiêm lỗi (6 kịch bản)",
            "",
            f"- Seed = `{meta.get('seed')}`, rows: {meta.get('rows_before')} → {meta.get('rows_after')}. "
            "Chi tiết: `data/results/corruption_log.json`.",
            "",
            *_table(
                ["Corruption", "Mô tả", "Số bản ghi", "Tín hiệu phát hiện kỳ vọng"],
                [
                    [f"`{event['corruption_type']}`", event["description"], event["affected_count"],
                     EXPECTED_SIGNALS.get(event["corruption_type"], "—")]
                    for event in corruption_log.get("events", [])
                ],
            ),
            "",
        ]

    impacts = extra.get("question_impacts") or []
    if impacts:
        lines += [
            "## 5. Silent Failure — câu hỏi bị ảnh hưởng",
            "",
            "Agent **không báo lỗi**: nó vẫn trả lời trôi chảy trên dữ liệu bẩn. Các câu dưới đây có kết quả khác baseline:",
            "",
            *_table(
                ["id", "type", "Hit B→C→R", "F1 B→C→R", "Corruption chạm vào doc", "Câu trả lời khi corrupted"],
                [
                    [item["id"], item["question_type"],
                     f"{_fmt(item['baseline_hit'])}→{_fmt(item['corrupted_hit'])}→{_fmt(item['repaired_hit'])}",
                     f"{item['baseline_f1']:.2f}→{item['corrupted_f1']:.2f}→{item['repaired_f1']:.2f}",
                     ", ".join(item["corruptions"]) or "(gián tiếp: nhiễu retrieval)",
                     "`" + (item["corrupted_answer"][:80] or "<rỗng>") + "`"]
                    for item in impacts
                ],
            ),
            "",
        ]

    repair = extra.get("repair") or {}
    if repair:
        lines += [
            "## 6. Auto-Repair (self-healing) & tính Idempotent",
            "",
            f"- **Trigger tự động:** {repair.get('triggered')} — lý do: {', '.join(repair.get('reasons', [])) or 'không có'}.",
            f"- **Nguồn phục hồi:** `{repair.get('source')}` (raw snapshot bất biến, không sửa tay dữ liệu hỏng).",
            f"- **Quy trình:** {repair.get('procedure')}",
            f"- **Repaired == Baseline (hash nội dung, bỏ `age_days`):** {repair.get('repaired_matches_baseline')} "
            f"(`{repair.get('baseline_content_hash', '')[:12]}` vs `{repair.get('repaired_content_hash', '')[:12]}`).",
            "- Chạy lại flow bao nhiêu lần cũng cho cùng kết quả: corruption dùng seed cố định, repair luôn build lại từ raw, "
            "Chroma collection được xoá và tạo lại (`papers-corrupted`, `papers-repaired`).",
            "",
        ]

    lines += ["## 7. Phân tích & Kết luận", ""]
    lines += _conclusions(
        baseline_metrics, corrupted_metrics, repaired_metrics,
        corrupted_quality, repaired_quality, corrupted_freshness, repaired_freshness,
    )
    write_text(report_path, "\n".join(lines) + "\n")


def _conclusions(
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    repaired: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> list[str]:
    lines = []
    dropped = [key for key in METRIC_KEYS if (corrupted.get(key) or 0) < (baseline.get(key) or 0) - 1e-9]
    if dropped:
        changes = ", ".join(
            f"{METRIC_LABELS[key]} {_fmt(_metric(baseline.get(key)))} → {_fmt(_metric(corrupted.get(key)))}"
            for key in dropped
        )
        lines.append(f"1. **Corruption → suy giảm chất lượng RAG:** {changes}.")
    else:
        lines.append("1. **Corruption:** các metric RAG không giảm trên test set này (xem bảng mục 1).")

    failed = corrupted_quality.get("failed_expectations") or []
    lines.append(
        f"2. **Observability bắt được lỗi:** Quality Gate = {_fmt(bool(corrupted_quality.get('success')))} "
        f"({len(failed)} expectation fail: {', '.join(failed) or 'không có'}); Freshness is_fresh = "
        f"{_fmt(bool(corrupted_freshness.get('is_fresh')))} (stale_ratio = {_fmt(corrupted_freshness.get('stale_ratio'))}). "
        "Nếu không có gate, dữ liệu này sẽ lọt vào vector store và agent vẫn trả lời tự tin — đó là **silent failure**."
    )
    recovered = [key for key in METRIC_KEYS if abs((repaired.get(key) or 0) - (baseline.get(key) or 0)) < 1e-9]
    lines.append(
        f"3. **Repair → phục hồi:** Quality Gate = {_fmt(bool(repaired_quality.get('success')))}, "
        f"is_fresh = {_fmt(bool(repaired_freshness.get('is_fresh')))}; "
        f"{len(recovered)}/{len(METRIC_KEYS)} metric trở về đúng giá trị baseline"
        + (f" ({', '.join(METRIC_LABELS[key] for key in recovered)})." if recovered else ".")
    )
    not_recovered = [key for key in METRIC_KEYS if key not in recovered]
    if not_recovered:
        lines.append(
            "4. Metric chưa khớp tuyệt đối baseline: "
            + ", ".join(
                f"{METRIC_LABELS[key]} ({_fmt(_metric(repaired.get(key)))} vs {_fmt(_metric(baseline.get(key)))})"
                for key in not_recovered
            )
            + " — thường do LLM judge không tất định giữa các lần gọi; retrieval/token F1 là chỉ số tất định."
        )
    return lines
