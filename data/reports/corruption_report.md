# Corruption & Repair Report — Baseline vs Corrupted vs Repaired

> Sinh tự động bởi `script/run_corruption_flow.py` lúc 2026-09-25T07:47:42.522197+00:00. Cả 3 trạng thái được đánh giá trên **cùng** `data/eval/test_set.json` (10 câu hỏi), cùng embedding model và cùng `top_k`.

## 1. Bảng đối chiếu 3 trạng thái

| Metric / Signal | Baseline | Corrupted | Repaired | Δ do corruption | Mức phục hồi |
| --- | --- | --- | --- | --- | --- |
| Retrieval Hit Rate | 1.0000 | 0.8000 | 1.0000 | -0.2000 | 100% |
| Mean Token F1 | 1.0000 | 0.8000 | 1.0000 | -0.2000 | 100% |
| Judge Accuracy | 1.0000 | 0.8000 | 1.0000 | -0.2000 | 100% |
| Mean Judge Score (1-5) | 5.0000 | 4.3000 | 5.0000 | -0.7000 | 100% |
| GX Quality Gate | PASS | FAIL | PASS | — | — |
| GX expectations pass | 8/8 | 4/8 | 8/8 | — | — |
| Row count | 24 | 22 | 24 | -2 | — |
| Freshness is_fresh | PASS | FAIL | PASS | — | — |
| stale_ratio | 0.0417 | 0.3636 | 0.0417 | +0.3219 | — |
| latest_published | 2026-07-22 | 2026-06-12 | 2026-07-22 | — | — |

## 2. Theo loại câu hỏi (Baseline / Corrupted / Repaired)

| question_type | samples | Hit rate | Token F1 |
| --- | --- | --- | --- |
| authors | 3 | 1.0000 / 0.6667 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| categories | 2 | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| date | 2 | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 1.0000 |
| summary | 3 | 1.0000 / 0.6667 / 1.0000 | 1.0000 / 0.3333 / 1.0000 |

## 3. Quality Gate chi tiết (Great Expectations 1.x)

| Expectation | Baseline | Corrupted | Repaired |
| --- | --- | --- | --- |
| `expect_table_row_count_to_be_between`(table) [min_value=5, max_value=5000] | PASS | PASS | PASS |
| `expect_column_values_to_not_be_null`(paper_id) | PASS | PASS | PASS |
| `expect_column_values_to_be_unique`(paper_id) | PASS | FAIL (6 lỗi) | PASS |
| `expect_column_values_to_not_be_null`(title) | PASS | PASS | PASS |
| `expect_column_value_lengths_to_be_between`(title) [min_value=8] | PASS | FAIL (4 lỗi) | PASS |
| `expect_column_values_to_not_be_null`(text_for_embedding) | PASS | PASS | PASS |
| `expect_column_value_lengths_to_be_between`(summary) [min_value=30] | PASS | FAIL (3 lỗi) | PASS |
| `expect_column_values_to_not_match_regex`(summary) [regex=[#@$%^&*~\|]{3,}] | PASS | FAIL (3 lỗi) | PASS |

## 4. Nhật ký tiêm lỗi (6 kịch bản)

- Seed = `42`, rows: 24 → 22. Chi tiết: `data/results/corruption_log.json`.

| Corruption | Mô tả | Số bản ghi | Tín hiệu phát hiện kỳ vọng |
| --- | --- | --- | --- |
| `drop_latest_records` | Dropped the 5 most recently published records (20%). | 5 | Row count giảm, `latest_published` lùi về quá khứ; câu hỏi về bài bị mất không truy xuất được |
| `blank_summary` | Replaced the summary with an empty string. | 3 | GX `ExpectColumnValueLengthsToBeBetween(summary >= 30)` fail |
| `inject_noise` | Prepended garbage symbols to the summary. | 3 | GX `ExpectColumnValuesToNotMatchRegex(summary)` fail |
| `truncate_title` | Truncated the title to 6 characters. | 3 | GX `ExpectColumnValueLengthsToBeBetween(title >= 8)` fail |
| `stale_date` | Shifted the published date 365 days into the past. | 6 | Freshness SLA fail (`stale_ratio` > 25%) |
| `duplicate_rows` | Appended exact copies of existing rows. | 3 | GX `ExpectColumnValuesToBeUnique(paper_id)` fail |

## 5. Silent Failure — câu hỏi bị ảnh hưởng

Agent **không báo lỗi**: nó vẫn trả lời trôi chảy trên dữ liệu bẩn. Các câu dưới đây có kết quả khác baseline:

| id | type | Hit B→C→R | F1 B→C→R | Corruption chạm vào doc | Câu trả lời khi corrupted |
| --- | --- | --- | --- | --- | --- |
| eval_001 | summary | PASS→FAIL→PASS | 1.00→0.00→1.00 | drop_latest_records | `<rỗng>` |
| eval_002 | authors | PASS→FAIL→PASS | 1.00→1.00→1.00 | drop_latest_records | `Kien Duong, Vy Ly` |
| eval_005 | summary | PASS→PASS→PASS | 1.00→0.00→1.00 | inject_noise | `@@## %%&& ~~** \|\|^^ zqx#@!` |

## 6. Auto-Repair (self-healing) & tính Idempotent

- **Trigger tự động:** True — lý do: expect_column_values_to_be_unique(paper_id), expect_column_value_lengths_to_be_between(title), expect_column_value_lengths_to_be_between(summary), expect_column_values_to_not_match_regex(summary), FreshnessSLA(stale_ratio=0.3636 > 0.25).
- **Nguồn phục hồi:** `data/raw/crossref_records.json` (raw snapshot bất biến, không sửa tay dữ liệu hỏng).
- **Quy trình:** load_raw_records -> build_clean_dataframe -> GX quality gate (must pass) -> rebuild Chroma `papers-repaired` -> evaluate on the same test_set.json
- **Repaired == Baseline (hash nội dung, bỏ `age_days`):** True (`a0a868e2e56a` vs `a0a868e2e56a`).
- Chạy lại flow bao nhiêu lần cũng cho cùng kết quả: corruption dùng seed cố định, repair luôn build lại từ raw, Chroma collection được xoá và tạo lại (`papers-corrupted`, `papers-repaired`).

## 7. Phân tích & Kết luận

1. **Corruption → suy giảm chất lượng RAG:** Retrieval Hit Rate 1.0000 → 0.8000, Mean Token F1 1.0000 → 0.8000, Judge Accuracy 1.0000 → 0.8000, Mean Judge Score (1-5) 5.0000 → 4.3000.
2. **Observability bắt được lỗi:** Quality Gate = FAIL (4 expectation fail: expect_column_values_to_be_unique(paper_id), expect_column_value_lengths_to_be_between(title), expect_column_value_lengths_to_be_between(summary), expect_column_values_to_not_match_regex(summary)); Freshness is_fresh = FAIL (stale_ratio = 0.3636). Nếu không có gate, dữ liệu này sẽ lọt vào vector store và agent vẫn trả lời tự tin — đó là **silent failure**.
3. **Repair → phục hồi:** Quality Gate = PASS, is_fresh = PASS; 4/4 metric trở về đúng giá trị baseline (Retrieval Hit Rate, Mean Token F1, Judge Accuracy, Mean Judge Score (1-5)).
