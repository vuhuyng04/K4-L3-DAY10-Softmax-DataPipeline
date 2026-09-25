from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from core.config import Settings
from core.utils import now_utc, read_json, write_text

STATES = ("baseline", "corrupted", "repaired")
STATE_LABELS = {"baseline": "Baseline", "corrupted": "Corrupted", "repaired": "Repaired"}
AGE_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, 120), (121, 180), (181, 365), (366, None)]
CHART_METRICS = (
    ("retrieval_hit_rate", "Hit rate", 1.0),
    ("mean_token_f1", "Token F1", 1.0),
    ("judge_accuracy", "Judge acc.", 1.0),
    ("mean_judge_score", "Judge score /5", 5.0),
)

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--text:#1d2330;--muted:#5b6475;--line:#dfe3ea;
--baseline:#2f6fdf;--corrupted:#d9480f;--repaired:#2b8a3e;--pass:#2b8a3e;--fail:#c92a2a;}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--card:#1b2029;--text:#e6e9ef;--muted:#9aa3b2;
--line:#2c3340;--baseline:#6d9cf0;--corrupted:#ff8a4c;--repaired:#5cc774;--pass:#5cc774;--fail:#ff6b6b;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:1.6rem;margin:0 0 4px}
h2{font-size:1.1rem;margin:32px 0 12px}.muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h3{margin:0 0 8px;font-size:1rem}.kpi{display:flex;justify-content:space-between;padding:3px 0;
border-bottom:1px dashed var(--line)}.kpi:last-child{border:0}.num{font-variant-numeric:tabular-nums;font-weight:600}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.8rem;font-weight:700;color:#fff}
.pass{background:var(--pass)}.fail{background:var(--fail)}
.dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:.9rem}
th{background:color-mix(in srgb,var(--line) 45%,transparent)}.scroll{overflow-x:auto}
svg text{fill:var(--text);font-size:12px}svg .axis{stroke:var(--line)}
code{font-size:.85em}
"""


def _load(path: Path) -> Any:
    try:
        return read_json(path)
    except (FileNotFoundError, ValueError):
        return None


def _badge(ok: Any, yes: str = "PASS", no: str = "FAIL") -> str:
    if ok is None:
        return '<span class="muted">n/a</span>'
    return f'<span class="badge {"pass" if ok else "fail"}">{yes if ok else no}</span>'


def _num(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "n/a"


def _metrics_chart(metrics: dict[str, dict | None]) -> str:
    width, height, left, bottom = 640, 260, 40, 40
    plot_h = height - bottom - 20
    group_w = (width - left) / len(CHART_METRICS)
    bar_w = group_w / (len(STATES) + 1.5)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Metrics by state" width="100%">']
    for tick in (0, 0.5, 1.0):
        y = 20 + plot_h * (1 - tick)
        parts.append(f'<line class="axis" x1="{left}" x2="{width}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{tick:.1f}</text>')
    for group, (key, label, scale) in enumerate(CHART_METRICS):
        x0 = left + group * group_w + bar_w * 0.75
        for offset, state in enumerate(STATES):
            value = (metrics.get(state) or {}).get(key)
            if not isinstance(value, (int, float)):
                continue
            ratio = max(0.0, min(1.0, value / scale))
            bar_h = plot_h * ratio
            x = x0 + offset * bar_w
            y = 20 + plot_h - bar_h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 3:.1f}" height="{bar_h:.1f}" rx="2" '
                f'fill="var(--{state})"><title>{STATE_LABELS[state]} {label}: {value:.3f}</title></rect>'
            )
        parts.append(
            f'<text x="{x0 + bar_w * 1.5:.1f}" y="{height - 14}" text-anchor="middle">{escape(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _bucket_label(low: int, high: int | None) -> str:
    return f">{low - 1}" if high is None else f"{low}-{high}"


def _age_histogram(frames: dict[str, list[dict] | None], threshold: int) -> str:
    counts: dict[str, list[int]] = {}
    for state, rows in frames.items():
        if not rows:
            continue
        values = [int(row.get("age_days", 0)) for row in rows]
        counts[state] = [
            sum(1 for v in values if v >= low and (high is None or v <= high)) for low, high in AGE_BUCKETS
        ]
    if not counts:
        return '<p class="muted">Chưa có dữ liệu.</p>'
    width, height, left, bottom = 640, 240, 40, 40
    plot_h = height - bottom - 20
    peak = max(max(values) for values in counts.values()) or 1
    group_w = (width - left) / len(AGE_BUCKETS)
    bar_w = group_w / (len(counts) + 1)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="age_days distribution" width="100%">']
    parts.append(f'<line class="axis" x1="{left}" x2="{width}" y1="{20 + plot_h}" y2="{20 + plot_h}"/>')
    for bucket, (low, high) in enumerate(AGE_BUCKETS):
        x0 = left + bucket * group_w + bar_w / 2
        for offset, (state, values) in enumerate(counts.items()):
            bar_h = plot_h * values[bucket] / peak
            x = x0 + offset * bar_w
            parts.append(
                f'<rect x="{x:.1f}" y="{20 + plot_h - bar_h:.1f}" width="{bar_w - 3:.1f}" height="{bar_h:.1f}" rx="2" '
                f'fill="var(--{state})"><title>{STATE_LABELS[state]} {_bucket_label(low, high)} ngày: '
                f'{values[bucket]} bài</title></rect>'
            )
        parts.append(
            f'<text x="{x0 + bar_w * len(counts) / 2:.1f}" y="{height - 14}" text-anchor="middle">'
            f"{_bucket_label(low, high)}</text>"
        )
    threshold_x = left + 5 * group_w
    parts.append(
        f'<line x1="{threshold_x:.1f}" x2="{threshold_x:.1f}" y1="14" y2="{20 + plot_h}" stroke="var(--fail)" '
        f'stroke-dasharray="4 3"/><text x="{threshold_x + 4:.1f}" y="14">SLA {threshold} ngày</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _legend(states: tuple[str, ...]) -> str:
    return " ".join(
        f'<span><span class="dot" style="background:var(--{state})"></span>{STATE_LABELS[state]}</span>'
        for state in states
    )


def render_dashboard(settings: Settings) -> Path:
    """Sinh `data/reports/dashboard.html` (HTML tinh, khong phu thuoc CDN) tu cac artifact quality/results."""
    paths = settings.paths
    quality = {state: _load(paths.quality_dir / f"{state}_quality_report.json") for state in STATES}
    freshness = {
        "baseline": _load(paths.freshness_report),
        "corrupted": _load(paths.quality_dir / "corrupted_freshness_report.json"),
        "repaired": _load(paths.quality_dir / "repaired_freshness_report.json"),
    }
    metrics = {
        "baseline": _load(paths.baseline_metrics),
        "corrupted": _load(paths.corrupted_metrics),
        "repaired": _load(paths.repaired_metrics),
    }
    frames = {
        "baseline": _load(paths.clean_json),
        "corrupted": _load(paths.corrupted_clean_json),
        "repaired": _load(paths.repaired_clean_json),
    }
    corruption_log = _load(paths.corruption_log) or {}
    repair_log = _load(paths.corruption_log.with_name("repair_log.json")) or {}
    available = tuple(state for state in STATES if metrics.get(state) or quality.get(state))

    cards = []
    for state in available:
        m, q, f = metrics.get(state) or {}, quality.get(state) or {}, freshness.get(state) or {}
        cards.append(
            f'<div class="card"><h3><span class="dot" style="background:var(--{state})"></span>{STATE_LABELS[state]}</h3>'
            f'<div class="kpi"><span>GX Quality Gate</span>{_badge(q.get("success") if q else None)}</div>'
            f'<div class="kpi"><span>Freshness SLA</span>{_badge(f.get("is_fresh") if f else None, "FRESH", "STALE")}</div>'
            f'<div class="kpi"><span>Rows</span><span class="num">{q.get("row_count", "n/a")}</span></div>'
            f'<div class="kpi"><span>Stale ratio</span><span class="num">{_num(f.get("stale_ratio"))}</span></div>'
            f'<div class="kpi"><span>Hit rate</span><span class="num">{_num(m.get("retrieval_hit_rate"))}</span></div>'
            f'<div class="kpi"><span>Token F1</span><span class="num">{_num(m.get("mean_token_f1"))}</span></div>'
            f'<div class="kpi"><span>Judge accuracy</span><span class="num">{_num(m.get("judge_accuracy"))}</span></div>'
            "</div>"
        )

    expectation_rows = []
    labels: list[str] = []
    lookup: dict[str, dict[str, dict]] = {}
    for state in available:
        for item in (quality.get(state) or {}).get("expectations", []):
            label = f'{item["expectation_type"]} ({item.get("column") or "table"})'
            if label not in lookup:
                labels.append(label)
                lookup[label] = {}
            lookup[label][state] = item
    for label in labels:
        cells = "".join(
            f"<td>{_badge(lookup[label][state]['success']) if state in lookup[label] else 'n/a'}"
            + (
                f' <span class="muted">({lookup[label][state]["unexpected_count"]})</span>'
                if state in lookup[label] and lookup[label][state].get("unexpected_count")
                else ""
            )
            + "</td>"
            for state in available
        )
        expectation_rows.append(f"<tr><td><code>{escape(label)}</code></td>{cells}</tr>")

    corruption_rows = "".join(
        f"<tr><td><code>{escape(event['corruption_type'])}</code></td><td>{escape(event['description'])}</td>"
        f"<td class='num'>{event['affected_count']}</td></tr>"
        for event in corruption_log.get("events", [])
    )
    repair_html = ""
    if repair_log:
        repair_html = (
            '<div class="card"><h3>Auto-repair (self-healing)</h3>'
            f'<div class="kpi"><span>Triggered</span>{_badge(repair_log.get("triggered"), "YES", "NO")}</div>'
            f'<div class="kpi"><span>Source</span><code>{escape(str(repair_log.get("source")))}</code></div>'
            f'<div class="kpi"><span>Repaired == Baseline</span>{_badge(repair_log.get("repaired_matches_baseline"), "MATCH", "DIFF")}</div>'
            f'<p class="muted">Lý do: {escape(", ".join(repair_log.get("reasons", [])) or "không có")}</p></div>'
        )

    head_cells = "".join(f"<th>{STATE_LABELS[state]}</th>" for state in available)
    html = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Observability Dashboard</title><style>{CSS}</style></head>
<body><main>
<h1>Data Observability Dashboard</h1>
<p class="muted">Day 10 RAG pipeline · sinh tự động lúc {escape(now_utc().isoformat())} từ <code>data/quality/</code> và <code>data/results/</code></p>
<h2>Trạng thái theo pipeline</h2><div class="grid">{''.join(cards)}{repair_html}</div>
<h2>Chất lượng RAG theo trạng thái</h2><div class="card">{_legend(available)}{_metrics_chart(metrics)}</div>
<h2>Phân bố tuổi bài báo (age_days)</h2><div class="card">{_legend(tuple(s for s in STATES if frames.get(s)))}
{_age_histogram(frames, settings.freshness_threshold_days)}</div>
<h2>Great Expectations 1.x — chi tiết expectation</h2>
<div class="scroll"><table><thead><tr><th>Expectation</th>{head_cells}</tr></thead><tbody>{''.join(expectation_rows)}</tbody></table></div>
<h2>Nhật ký tiêm lỗi</h2>
<div class="scroll"><table><thead><tr><th>Corruption</th><th>Mô tả</th><th>Số bản ghi</th></tr></thead>
<tbody>{corruption_rows or '<tr><td colspan="3" class="muted">Chưa chạy corruption flow.</td></tr>'}</tbody></table></div>
</main></body></html>
"""
    output = paths.baseline_report.with_name("dashboard.html")
    write_text(output, html)
    return output
