# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung |
| --- | --- |
| Khóa/Lớp | K4 — `K4-L3-DAY10` |
| Tên nhóm | NguyenVuHuy (làm cá nhân) |
| Repository | https://github.com/vuhuyng04/K4-L3A-Day10-Data-Pipeline-Data-Observability |
| Ngày hoàn thành | 2026-09-25 |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Nguyễn Vũ Huy | 2A202602662 | Toàn bộ pipeline (source, cleaning, observability, corruption & integration) | `src/ingestion/*`, `src/observability/*`, `src/evaluation/testset.py`, `src/pipelines/*`, `tests/`, `.github/workflows/ci.yml` |

## 2. Tóm tắt kết quả

Tôi đã hoàn thành cả 12 hàm TODO và 3 hạng mục bonus: dashboard (B1), auto-repair (B2), pytest cùng GitHub Actions (B3). Baseline pipeline (`script/run_phase1.py`) lấy 24 bản ghi từ snapshot Crossref, làm sạch còn 24 dòng. Dữ liệu vượt Quality Gate Great Expectations 1.x (8/8 expectation) và đạt Freshness SLA (stale_ratio 0.0417). Pipeline index 24 tài liệu vào ChromaDB `papers-baseline`, đạt hit rate, token F1 và judge accuracy đều bằng 1.0 trên test set 10 câu. Judge là gpt-4o-mini, không lần nào phải fallback.

Corruption flow tiêm 6 loại lỗi và làm hit rate, token F1, judge accuracy cùng giảm từ 1.0 xuống 0.8. Lỗi ảnh hưởng rõ nhất là **drop_latest_records**: 2 câu hỏi về bài mới nhất mất tài liệu, và agent vẫn trả lời tự tin từ tài liệu khác. Quality Gate phát hiện 4/8 expectation fail và Freshness chuyển sang STALE (0.3636 > 0.25), từ đó kích hoạt auto-repair. Repair build lại từ `data/raw/crossref_records.json`, đưa toàn bộ metric về đúng baseline, và hash nội dung của bản repaired trùng với baseline.

Giới hạn lớn nhất: test set chỉ có 10 câu và QA dạng extractive, nên chỉ 3/10 câu thay đổi kết quả. Lỗi `stale_date` và `truncate_title` bị gate phát hiện nhưng không làm giảm metric nào trên test set này.

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

```text
Crossref snapshot (data/raw/crossref_response.json)  | live API khi REFRESH_SOURCE=1 (retry 429/5xx -> fallback)
    -> parse_crossref_payload -> data/raw/crossref_records.json               (raw lineage, bất biến)
    -> build_clean_dataframe  -> data/clean/papers_clean.{csv,json}            (24 dòng)
    -> GX 1.x Quality Gate + Freshness SLA -> data/quality/*.json              (gate FAIL => không index)
    -> MiniLM embeddings + ChromaDB `papers-baseline` -> data/embeddings/, data/chroma/
    -> evaluate_pipeline (test_set.json cố định) -> data/results/baseline_*.json, data/reports/phase1_report.md
    -> corrupt_clean_dataframe (6 lỗi, seed 42) -> `papers-corrupted` -> corrupted_*.json
    -> auto-repair (tự kích hoạt khi GX/Freshness fail) -> build lại từ raw -> `papers-repaired` -> repaired_*.json
    -> generate_corruption_report + dashboard -> data/reports/corruption_report.md, dashboard.html
```

### Trách nhiệm của từng khối

| Khối | Input | Xử lý chính | Output/artifact | Owner |
| --- | --- | --- | --- | --- |
| Ingestion | Crossref snapshot / API | Parse, bỏ tag JATS, retry/backoff, fallback | `data/raw/crossref_records.json` | Nguyễn Vũ Huy |
| Cleaning | `list[PaperRecord]` | Normalize, dedup `paper_id`, `age_days`, `text_for_embedding` | `data/clean/papers_clean.csv/json` | Nguyễn Vũ Huy |
| Embedding/index | Clean dataframe | `all-MiniLM-L6-v2`, Chroma cosine, 3 collection tách biệt | `data/chroma/`, `data/embeddings/*.json` | Nguyễn Vũ Huy |
| Evaluation | `test_set.json` + index | Hit rate, token F1, LLM judge (gpt-4o-mini) | `data/results/*_metrics.json` | Nguyễn Vũ Huy |
| Observability | Clean/corrupted/repaired df | GX 1.x (8 expectation), Freshness SLA | `data/quality/*.json` | Nguyễn Vũ Huy |
| Corruption/repair | Baseline clean df, raw records | 6 lỗi tất định, auto-repair từ raw | `corruption_log.json`, `repair_log.json` | Nguyễn Vũ Huy |
| Orchestration | Tất cả ở trên | `phase1.py`, `corruption_flow.py` | `data/reports/*.md`, `dashboard.html` | Nguyễn Vũ Huy |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
| --- | --- |
| `LLM_PROVIDER` | `openai` (CI/test dùng `mock`) |
| `LLM_MODEL` | `gpt-4o-mini` |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Số lượng Crossref records | 24 (offline snapshot) |
| Retrieval `top_k` | 4 |
| Freshness threshold | 180 ngày, tối đa 25% bài stale |
| Random seed | 42 (corruption) |

### Lệnh cài đặt

```bash
uv sync --extra dev --python 3.13
```

(Máy có Python 3.14 mặc định, nằm ngoài `requires-python <3.14`, nên phải chỉ định rõ 3.13.)

### Lệnh chạy

```bash
uv run python script/run_phase1.py
uv run python script/run_corruption_flow.py
uv run pytest --cov=src          # 31 passed, coverage 97%
```

### Kết quả tái hiện

| Lệnh | Trạng thái | Thời điểm chạy gần nhất | Bằng chứng |
| --- | --- | --- | --- |
| Baseline pipeline | Thành công (exit 0) | 2026-09-25 07:46 UTC | `data/reports/phase1_report.md`, `data/results/baseline_metrics.json` |
| Corruption flow | Thành công (exit 0) | 2026-09-25 07:47 UTC | `data/reports/corruption_report.md`, `data/results/repair_log.json` |

Lần chạy cuối bắt đầu từ `data/chroma/` rỗng. Chạy corruption flow hai lần liên tiếp cho `corruption_log.events`, `papers_clean_repaired.json`, `corrupted_metrics.json` và `repaired_metrics.json` giống hệt nhau (idempotent).

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Source | Crossref REST API `https://api.crossref.org/works` (chế độ offline: `data/raw/crossref_response.json`) |
| Query/filter | `agentic retrieval augmented generation large language model`; `from-pub-date:<run_date-180d>,has-abstract:true` (chỉ dùng ở live mode) |
| Thời điểm lấy dữ liệu | Snapshot offline có sẵn trong repo; parse lại lúc 2026-09-25 |
| Số record nhận được | 24 |
| Cơ chế retry/backoff | 3 lần, backoff 2s → 4s cho HTTP 429/500/502/503/504 và lỗi mạng; hết lượt retry thì fallback về snapshot |

### Raw và clean schema

| Trường | Kiểu dữ liệu | Bắt buộc? | Ý nghĩa | Xử lý khi thiếu/sai |
| --- | --- | --- | --- | --- |
| `paper_id` | str (DOI) | Có | Document ID ổn định | Thiếu → bỏ record; dedup không phân biệt hoa thường |
| `title` | str | Có | Tiêu đề (đã bỏ markup) | Thiếu → bỏ record |
| `summary` | str | Có (raw) | Abstract đã bỏ `<jats:p>` | Raw thiếu abstract → bỏ record |
| `authors` / `categories` | list[str] | Không | Tác giả / subject | Thiếu → `[]`; loại bỏ phần tử trùng |
| `primary_category` | str | Không | Subject đầu tiên | Thiếu → `Uncategorized` |
| `published` / `updated` | str ISO `YYYY-MM-DD` | `published` có | Ngày xuất bản / ngày tạo record | `date-parts` thiếu tháng/ngày → mặc định 01; sai định dạng → bỏ record |
| `age_days` | int | Có (derived) | `(run_date - published).days` | Tính lại mỗi lần chạy |
| `authors_joined`, `categories_joined`, `summary_chars`, `text_for_embedding` | str/int | Có (derived) | Cột helper cho index/QA | Build lại bằng `refresh_derived_columns` |

### Quy tắc cleaning

| Quy tắc | Quality dimension liên quan | Số record bị tác động | Cách xác minh |
| --- | --- | ---: | --- |
| Bỏ tag JATS/HTML trong abstract + decode entity | Validity | 24 | `data/raw/crossref_response.json` có 24 `<jats:p>`, `papers_clean.json` không còn tag; `tests/test_ingestion.py` |
| Gom khoảng trắng thừa ở title/summary | Consistency | 0 (snapshot đã gọn) | `tests/test_cleaning.py::test_cleaning_rules_dedup_markup_and_age` |
| Loại record thiếu `paper_id`/`title`/`published` | Completeness | 0 | Raw 24 → clean 24 (`phase1_report.md`) |
| Dedup theo `paper_id`, giữ bản `updated` mới nhất | Uniqueness | 0 trên snapshot | GX `expect_column_values_to_be_unique` PASS; unit test có record trùng |

`text_for_embedding` gồm 5 dòng `Title / Authors / Published / Categories / Summary`, giúp embedding nắm cả metadata lẫn nội dung. Document ID là DOI (`paper_id`); record ID trong Chroma là `paper_id::index` để vẫn index được các dòng trùng khi mô phỏng corruption. `age_days` được tính theo ngày UTC của lần chạy.

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
| --- | --- |
| Số câu hỏi | 10 |
| Các `question_type` | summary (3), authors (3), date (2), categories (2) |
| Ground-truth document ID | DOI của paper được hỏi (`ground_truth_doc_ids`) |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store/collection | ChromaDB persistent `data/chroma/`, cosine; `papers-baseline` / `papers-corrupted` / `papers-repaired` |
| Retrieval `top_k` | 4 |
| LLM provider/model | openai / gpt-4o-mini (LLM judge + agent demo) |
| Test set dùng chung cho ba trạng thái | `data/eval/test_set.json` (phase1 tái sử dụng file đã có trừ khi đặt `REFRESH_TEST_SET=1`) |

Test set được giữ nguyên để khi so sánh baseline, corrupted và repaired chỉ có **dữ liệu** thay đổi, còn câu hỏi, ground truth, model và `top_k` giữ cố định. Test set chọn 10 paper cách đều nhau theo ngày xuất bản (mới → cũ), nên phủ cả bài mới nhất là nhóm chịu tác động của `drop_latest_records`.

## 7. Kết quả baseline

### Artifact checklist

| Artifact | Đường dẫn thực tế | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| Raw response/records | `data/raw/` | Có | Offline mode không ghi đè response gốc |
| Cleaned dataset | `data/clean/` | Có | 24 dòng, kèm bản corrupted và repaired |
| Embedding manifest/index | `data/embeddings/`, `data/chroma/` | Có | `persist_path` tương đối (`data/chroma`) |
| Evaluation set | `data/eval/test_set.json` | Có | 10 câu |
| Baseline metrics | `data/results/baseline_metrics.json` | Có | Kèm `by_question_type` |
| Quality/freshness | `data/quality/` | Có | baseline/corrupted/repaired + 3 freshness report |
| Baseline report | `data/reports/phase1_report.md` | Có | Sinh tự động |

### Baseline metrics

| Metric | Giá trị | Diễn giải |
| --- | ---: | --- |
| `retrieval_hit_rate` | 1.0 | Cả 10 câu đều truy xuất đúng DOI trong top-4 |
| `mean_token_f1` | 1.0 | QA dạng extractive lấy đúng trường metadata nên khớp tuyệt đối ground truth |
| `judge_accuracy` | 1.0 | gpt-4o-mini chấm cả 10 câu là đúng, `judge_fallback_count = 0` |
| `mean_judge_score` | 5.0 | Điểm tối đa |
| Ragas, nếu có | N/A | Không chạy (`RUN_RAGAS` chưa bật) vì chậm và tốn thêm lượt gọi LLM |

## 8. Data quality và freshness

### Quality checks

| Check | Quality dimension | Ngưỡng/kỳ vọng | Kết quả baseline | Bằng chứng |
| --- | --- | --- | --- | --- |
| `ExpectTableRowCountToBeBetween` | Volume | 5–5000 dòng | PASS (24) | `data/quality/baseline_quality_report.json` |
| `ExpectColumnValuesToNotBeNull` × 3 | Completeness | `paper_id`, `title`, `text_for_embedding` không null | PASS (0 lỗi) | như trên |
| `ExpectColumnValuesToBeUnique` | Uniqueness | `paper_id` duy nhất | PASS (0 lỗi) | như trên |
| `ExpectColumnValueLengthsToBeBetween(summary)` | Validity | ≥ 30 ký tự | PASS (0 lỗi) | như trên |
| `ExpectColumnValueLengthsToBeBetween(title)` | Validity | ≥ 8 ký tự | PASS (0 lỗi) | như trên |
| `ExpectColumnValuesToNotMatchRegex(summary)` | Validity (noise) | không chứa `[#@$%^&*~\|]{3,}` | PASS (0 lỗi) | như trên |

### Freshness

| Thuộc tính | Giá trị |
| --- | --- |
| Freshness được đo tại | Clean dataset trước khi index (`age_days`) |
| Timestamp mới nhất | `latest_published = 2026-07-22` (65 ngày) |
| Ngưỡng freshness | `age_days > 180` là stale; SLA vi phạm khi hơn 25% số bài stale |
| Trạng thái baseline | Fresh |
| Lý do | 1/24 bài stale (bài 2026-03-28, 181 ngày) → stale_ratio 0.0417 ≤ 0.25 |

Freshness **không** được tính vào GX `success`. Quality Gate đo cấu trúc và tính hợp lệ, cho kết quả như nhau dù chạy ngày nào. Freshness đo độ cũ theo ngày chạy, nên baseline sẽ tự chuyển sang STALE khoảng từ 2026-11-29 (đây là hành vi đúng).

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair |
| --- | --- | ---: | --- | --- | --- |
| `drop_latest_records` | Bỏ `ceil(20%)` bài mới nhất | 5 | Row count giảm, `latest_published` lùi | 24→22 dòng, latest 2026-07-22→2026-06-12; eval_001 và eval_002 mất tài liệu (hit FAIL) | Build lại từ raw records |
| `blank_summary` | `summary = ""` | 3 | GX length(summary) fail | FAIL (3 lỗi); gián tiếp làm eval_001 trả lời rỗng vì top-1 là doc bị xoá summary | như trên |
| `inject_noise` | Chèn ký tự rác vào đầu summary | 3 | GX regex fail | FAIL (3 lỗi); eval_005 F1 1.0→0.0, judge 5→1 | như trên |
| `truncate_title` | `title[:6]` | 3 | GX length(title) fail | FAIL (4 lỗi, có 1 dòng bị nhân bản) | như trên |
| `stale_date` | Lùi `published` 365 ngày | 6 | Freshness SLA fail | stale_ratio 0.0417→0.3636, is_fresh=False | như trên |
| `duplicate_rows` | Nhân bản dòng | 3 | GX unique(paper_id) fail | FAIL (6 giá trị trùng = 3 cặp) | như trên |

Corruption log:

- Đường dẫn: `data/results/corruption_log.json`
- Trạng thái: Có
- Nhận xét: Log ghi đủ 6 loại lỗi, tham số, số bản ghi và danh sách `paper_id` bị ảnh hưởng của từng loại, kèm `seed`, `rows_before`/`rows_after`.

Repair **không** vá tay dữ liệu hỏng. `corruption_flow` gom mọi vi phạm (4 GX expectation cùng Freshness SLA) vào `reasons` và tự kích hoạt repair. Repair đọc lại `data/raw/crossref_records.json`, là raw snapshot bất biến (nếu hỏng thì parse lại `crossref_response.json`), rồi chạy lại đúng `build_clean_dataframe`. Dữ liệu repaired phải vượt Quality Gate mới được index vào `papers-repaired`. Hash SHA-256 nội dung của bản repaired (bỏ `age_days`) trùng với baseline: `a0a868e2e56a…` (`data/results/repair_log.json`).

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0 | 0.8 | 1.0 | −0.2 | 100% | 2 câu về bài bị drop |
| `mean_token_f1` | 1.0 | 0.8 | 1.0 | −0.2 | 100% | eval_001 (answer rỗng), eval_005 (noise) |
| `judge_accuracy` | 1.0 | 0.8 | 1.0 | −0.2 | 100% | eval_002 vẫn được chấm đúng dù lấy sai doc |
| `mean_judge_score` | 5.0 | 4.3 | 5.0 | −0.7 | 100% | Điểm judge: eval_001 = 2, eval_005 = 1 |
| Quality checks pass/fail | PASS 8/8 | FAIL 4/8 | PASS 8/8 | −4 expectation | 100% | unique, len(title), len(summary), regex |
| Freshness status | Fresh (0.0417) | Stale (0.3636) | Fresh (0.0417) | +0.3219 stale_ratio | 100% | Do `stale_date` và `drop_latest_records` |

Kết luận nhân quả (có artifact chứng minh):

1. `drop_latest_records` bỏ mất 5 bài mới nhất, làm row count giảm 24→22 và `latest_published` lùi về 2026-06-12. Hai câu hỏi về bài mới nhất bị hit FAIL, kéo hit rate từ 1.0 xuống 0.8. Ở eval_002, agent vẫn trả lời `Kien Duong, Vy Ly` (F1 = 1.0, judge 5/5) vì bài "Advanced Perspectives on…" song sinh có cùng tác giả, nhưng tài liệu nguồn là sai. Đây là silent failure mà chỉ hit rate phát hiện được (`corrupted_answers.json`).
2. `inject_noise` làm GX `expect_column_values_to_not_match_regex` fail và câu trả lời eval_005 thành chuỗi rác (F1 0.0, judge 1). Auto-repair build lại từ raw, GX quay về 8/8 PASS, is_fresh = True, và cả 4 metric về đúng baseline (`repaired_metrics.json`, `repair_log.json`).

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** Starter code ghi `persist_path` tuyệt đối (đường dẫn ổ đĩa Windows tới thư mục user) vào `data/embeddings/*.json`. Khi commit, repo sẽ chứa đường dẫn tuyệt đối của máy local (bị trừ 5đ theo rubric), và `LocalEmbeddingIndex.load()` trên máy giám khảo sẽ trỏ tới thư mục không tồn tại.
- **Nguyên nhân:** `LocalEmbeddingIndex.build` ghi thẳng `str(persist_path)`.
- **Cách xử lý:** Manifest giờ lưu đường dẫn tương đối với project (`data/chroma`), còn `load()` resolve lại theo `settings.paths.project_dir`.
- **Cách xác minh:** `tests/test_retrieval.py::test_index_build_persists_portable_manifest`. Grep đường dẫn tuyệt đối kiểu ổ đĩa Windows trong `data/`, `src/` và `report/` không còn kết quả.

Hai vấn đề phụ cũng đã xử lý:
- Stdout dùng cp1252 khi chạy qua pipe trên Windows gây `UnicodeEncodeError`. Cả hai entrypoint giờ ép stdout về UTF-8.
- Cột list (`authors`, `categories`) không đưa vào GX validation để tránh lỗi unhashable.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng | Hướng cải thiện có thể kiểm chứng |
| --- | --- | --- |
| Test set chỉ 10 câu, QA extractive dựa trên metadata | Metric rất thô (bước nhảy 0.1); chỉ 3/10 câu đổi kết quả; `stale_date` và `truncate_title` không làm giảm metric vì không trúng trường được hỏi | Tăng lên ≥ 40 câu, sinh câu hỏi cho đúng các doc và trường bị corrupt; đo lại mức giảm theo từng loại lỗi |
| LLM judge (gpt-4o-mini) không tất định | Judge score có thể lệch nhẹ giữa các lần chạy | Chạy judge nhiều lần rồi lấy trung bình, hoặc dùng mô hình judge cố định seed; theo dõi `judge_fallback_count` |
| Freshness phụ thuộc ngày chạy, snapshot offline sẽ cũ dần | Sau khoảng 2026-11-29 baseline sẽ báo STALE | Chạy định kỳ `REFRESH_SOURCE=1`, dùng dashboard để theo dõi drift `age_days` |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact truy cập được.
- [x] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng.
- [x] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.
