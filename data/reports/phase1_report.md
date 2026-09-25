# Phase 1 — Baseline Pipeline Report

> Sinh tự động bởi `script/run_phase1.py` lúc 2026-09-25T07:46:45.250050+00:00. Mọi số liệu đọc từ artifact thực tế.

## 1. Nguồn dữ liệu & Lineage

| Thuộc tính | Giá trị |
| --- | --- |
| Source | Crossref REST API |
| Chế độ | offline snapshot (`data/raw/crossref_response.json`) |
| Query | agentic retrieval augmented generation large language model |
| Filter (live mode) | from-pub-date:2026-03-29,has-abstract:true |
| Raw records | 24 |
| Clean rows | 24 |
| Bị loại khi cleaning | 0 |
| Run date (UTC) | 2026-09-25 |
| Embedding model | sentence-transformers/all-MiniLM-L6-v2 |
| Chroma collection | papers-baseline |
| Retrieval top_k | 4 |
| LLM provider / model | openai / gpt-4o-mini |
| Test set | `data/eval/test_set.json` (10 câu) |

## 2. Baseline Metrics

| Metric | Giá trị |
| --- | --- |
| Retrieval Hit Rate | 1.0000 |
| Mean Token F1 | 1.0000 |
| Judge Accuracy | 1.0000 |
| Mean Judge Score (1-5) | 5.0000 |

- Số câu hỏi đánh giá: **10**; số lần LLM judge phải fallback heuristic: **0**.

### Theo loại câu hỏi

| question_type | samples | hit_rate | token_f1 | judge_accuracy |
| --- | --- | --- | --- | --- |
| authors | 3 | 1.0000 | 1.0000 | 1.0000 |
| categories | 2 | 1.0000 | 1.0000 | 1.0000 |
| date | 2 | 1.0000 | 1.0000 | 1.0000 |
| summary | 3 | 1.0000 | 1.0000 | 1.0000 |

## 3. Data Quality Gate (Great Expectations 1.x) — **PASS**

- Engine: `great_expectations 1.18.0`, suite `papers_baseline_suite`, 8/8 expectations pass, row_count = 24.

| Expectation | Kết quả | Observed |
| --- | --- | --- |
| `expect_table_row_count_to_be_between`(table) [min_value=5, max_value=5000] | PASS | 24 |
| `expect_column_values_to_not_be_null`(paper_id) | PASS | unexpected=0 |
| `expect_column_values_to_be_unique`(paper_id) | PASS | unexpected=0 |
| `expect_column_values_to_not_be_null`(title) | PASS | unexpected=0 |
| `expect_column_value_lengths_to_be_between`(title) [min_value=8] | PASS | unexpected=0 |
| `expect_column_values_to_not_be_null`(text_for_embedding) | PASS | unexpected=0 |
| `expect_column_value_lengths_to_be_between`(summary) [min_value=30] | PASS | unexpected=0 |
| `expect_column_values_to_not_match_regex`(summary) [regex=[#@$%^&*~\|]{3,}] | PASS | unexpected=0 |

## 4. Freshness SLA — **FRESH**

| Thuộc tính | Giá trị |
| --- | --- |
| Ngưỡng tuổi (threshold_days) | 180 |
| Tỷ lệ stale tối đa cho phép | 0.2500 |
| Bài mới nhất (latest_published) | 2026-07-22 |
| Bài cũ nhất (oldest_published) | 2026-03-28 |
| Số bài stale / tổng | 1 / 24 |
| stale_ratio | 0.0417 |
| is_fresh | PASS |

## 5. Kết luận

- Dữ liệu sạch đã vượt Quality Gate và đạt Freshness SLA (stale_ratio = 0.0417 so với ngưỡng 0.25).
- Baseline RAG đạt hit rate = 1.0000, token F1 = 1.0000, judge accuracy = 1.0000. Đây là mốc tham chiếu cho corruption flow (dùng chung `data/eval/test_set.json`).
