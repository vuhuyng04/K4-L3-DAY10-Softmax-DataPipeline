# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Vũ Huy |
| MSSV | 2A202602662 |
| Khóa/Lớp | K4 — `K4-L3-DAY10` |
| Tên nhóm | NguyenVuHuy (làm cá nhân) |
| Vai trò chính | Thành viên duy nhất: source, cleaning, observability, corruption & integration |
| Repository | https://github.com/vuhuyng04/K4-L3A-Day10-Data-Pipeline-Data-Observability |
| Ngày hoàn thành | 2026-09-25 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Raw ingestion | `crossref.py`: `parse_crossref_payload`, `fetch_source_records`, `load_raw_records` | Crossref payload / snapshot | `data/raw/crossref_records.json` | Hoàn thành |
| Cleaning | `cleaning.py`: `build_clean_dataframe`, `refresh_derived_columns` | `list[PaperRecord]`, `run_date` | `data/clean/papers_clean.{csv,json}` | Hoàn thành |
| Quality & freshness | `quality.py`: `run_data_quality_checks`, `build_freshness_report` | Clean dataframe | `data/quality/*.json` | Hoàn thành |
| Evaluation set | `testset.py`: `build_test_set`; bổ sung `by_question_type` trong `metrics.py` | Clean dataframe | `data/eval/test_set.json` | Hoàn thành |
| Corruption & repair | `corruption.py`: `corrupt_clean_dataframe`; `corruption_flow.py`: `main`, `_repair_from_raw` | Baseline clean df, raw records | `corruption_log.json`, `repair_log.json`, corrupted/repaired metrics | Hoàn thành |
| Orchestration & reporting | `phase1.py`, `reporting.py`, `dashboard.py` | Tất cả artifact | `phase1_report.md`, `corruption_report.md`, `dashboard.html` | Hoàn thành |
| Test & CI (bonus B3) | `tests/*.py`, `.github/workflows/ci.yml` | Snapshot + mock LLM | 31 test, coverage 97% | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Sửa starter code `retrieval/index.py` | RAG & Vector Index | Manifest lưu `persist_path` tương đối; test `test_index_build_persists_portable_manifest` pass |
| Thêm alias provider `google` → `gemini` | `core/config.py` (multi-provider router) | `test_provider_router` pass |

Ghi chú minh bạch: tôi dùng trợ lý AI (Claude Code) để tăng tốc viết code và soạn tài liệu, đúng như `docs/RULES.md` §3 cho phép. Tôi đã đọc lại toàn bộ logic, tự chạy lại pipeline và bộ test, và có thể giải thích từng quyết định bên dưới.

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Parse snapshot và giữ lineage | `src/ingestion/crossref.py` | 24 record; `crossref_records.json` ghi lại **giống hệt** bản gốc trong repo | `git diff data/raw/` rỗng sau khi chạy |
| Quality Gate GX 1.x | `src/observability/quality.py` | Baseline 8/8 PASS; corrupted 4/8 (fail đúng 4 expectation tương ứng lỗi) | `data/quality/*_quality_report.json` |
| Tiêm 6 lỗi tất định + auto-repair | `corruption.py`, `corruption_flow.py` | Hit rate 1.0 → 0.8 → 1.0; `repaired_matches_baseline = true` | `data/results/repair_log.json`; chạy 2 lần cho kết quả giống hệt |
| Bộ test + CI | `tests/`, `.github/workflows/ci.yml` | 31 passed, coverage 97% | `uv run pytest --cov=src` |

Output cụ thể tôi muốn nhấn mạnh là `data/results/repair_log.json`. File này ghi lý do repair tự kích hoạt (4 expectation GX và `FreshnessSLA(stale_ratio=0.3636 > 0.25)`), nguồn phục hồi `data/raw/crossref_records.json`, và hai hash SHA-256 trùng nhau (`a0a868e2e56a…`). Đây là bằng chứng máy kiểm được rằng bản repaired giống baseline về nội dung.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Dữ liệu bẩn (mất bài mới, abstract rỗng hoặc lẫn rác, title bị cắt, ngày bị lùi, dòng trùng) không làm pipeline báo lỗi đỏ. Agent vẫn trả lời, chỉ là trả lời sai. Phần việc của tôi phải (1) chặn dữ liệu bẩn trước khi vào vector store, (2) đo được mức suy giảm khi dữ liệu bẩn lọt vào, và (3) tự phục hồi từ nguồn đáng tin.

### Cách triển khai

- **GX 1.x:** `gx.get_context(mode="ephemeral")` → `data_sources.add_pandas` → `add_dataframe_asset` → `add_batch_definition_whole_dataframe` → `get_batch(batch_parameters={"dataframe": df})`, sau đó `batch.validate(suite)`. Suite có 8 expectation. Mỗi loại corruption được gắn với ít nhất một tín hiệu phát hiện: dup → `unique`, blank → `length(summary)`, noise → `not_match_regex`, truncate → `length(title)`, stale → Freshness SLA, drop → row count và `latest_published`.
- **Corruption tất định:** `random.Random(42)`. Mỗi loại lỗi lấy từ một nhóm dòng riêng (không chồng lấn, trừ duplicate) để có thể quy tác động về đúng loại lỗi. Sau khi làm bẩn, các cột dẫn xuất được tính lại bằng chính `refresh_derived_columns` của cleaning, để `text_for_embedding` phản ánh đúng dữ liệu bẩn.
- **Auto-repair:** mọi vi phạm được gom vào `reasons`. Nếu có vi phạm thì build lại từ raw, bắt bản repaired qua gate (fail thì `RuntimeError`, không index), rồi index `papers-repaired` và evaluate trên cùng test set.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | Clean dataframe theo `CLEAN_COLUMNS` (16 cột); `Settings` (threshold 180 ngày) |
| Output | Dict report `{success, failed_expectations, expectations[], row_count, freshness_signal}`, ghi ra `data/quality/<name>_quality_report.json` |
| Module phụ thuộc | `ingestion/cleaning.py` (schema), `core/config.py` (paths) |
| Module sử dụng output | `pipelines/phase1.py` (gate), `pipelines/corruption_flow.py` (trigger repair), `reporting.py`, `dashboard.py` |
| Điều kiện lỗi cần xử lý | Dataframe rỗng (freshness trả `is_fresh=False`); cột list gây unhashable (loại khỏi GX); giá trị numpy không serialize được JSON (`dataframe_records`) |

### Cách xác minh

```bash
uv run python -c "from core.config import load_settings; from observability.quality import run_data_quality_checks; import pandas as pd; s=load_settings(); df=pd.read_json(s.paths.clean_json); res=run_data_quality_checks(df, s, 'test'); print(f'Tín hiệu hoàn thành: Quality check status = {res[\"success\"]}')"
uv run python script/run_corruption_flow.py
uv run pytest tests/test_quality.py -q
```

- **Kết quả mong đợi:** baseline `True`; corrupted `False` với đúng 4 expectation fail cộng Freshness STALE; repaired `True`.
- **Kết quả thực tế:** `Quality check status = True`; bảng console `GX quality gate PASS / FAIL / PASS`, `Freshness SLA FRESH / STALE / FRESH`; 4 test quality pass.
- **Artifact/log:** `data/quality/baseline_quality_report.json`, `corrupted_quality_report.json`, `repaired_quality_report.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Docstring gợi ý gộp freshness vào `run_data_quality_checks`. Nhưng `age_days` phụ thuộc ngày chạy, nên kết quả gate sẽ đổi theo lịch dù dữ liệu không đổi.
- **Các phương án đã cân nhắc:** (A) thêm expectation GX `age_days <= 180` với `mostly=0.75` vào suite, để `success` bao gồm cả freshness; (B) giữ `success` chỉ cho các expectation về cấu trúc và tính hợp lệ, còn freshness là một SLA riêng (`build_freshness_report`) kèm tín hiệu tham khảo `freshness_signal` trong quality report.
- **Phương án đã chọn:** B.
- **Lý do:** Gate phải tất định. Giám khảo chạy lại vào tháng 12 thì tín hiệu CP1 `Quality check status = True` vẫn phải đúng. Freshness là vấn đề vận hành (cần refresh nguồn), không phải dữ liệu hỏng. Với phương án A, pipeline sẽ tự chặn index khi dữ liệu chỉ cũ đi chứ không sai. Auto-repair vẫn xét **cả hai** tín hiệu khi quyết định trigger.
- **Bằng chứng quyết định phù hợp:** baseline GX 8/8 PASS và freshness 0.0417; corrupted có cả hai tín hiệu cùng bật (`reasons` gồm 4 expectation GX và `FreshnessSLA`); `test_freshness_sla` kiểm tra riêng trường hợp stale.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `UnicodeEncodeError: 'charmap' codec can't encode character 'ệ' in position 6: character maps to <undefined>` khi chạy lệnh tự kiểm tra CP1 (in `Tín hiệu hoàn thành…`) qua Git Bash.
- **Lệnh hoặc bước tái hiện:** `uv run python -c "print('Tín hiệu hoàn thành')" | cat` trên Windows.
- **Nguyên nhân gốc:** Khi stdout bị pipe (không phải console), Python trên Windows dùng mã hoá locale `cp1252`, không có ký tự tiếng Việt. Lỗi không nằm ở logic cleaning.
- **Cách xử lý:** Cả hai entrypoint `script/run_*.py` gọi `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`. Với lệnh `python -c` tuỳ ý thì đặt `PYTHONIOENCODING=utf-8`.
- **Cách xác minh sau khi sửa:** Chạy lại cùng lệnh, in ra `Tín hiệu hoàn thành: Clean thành công 24 dòng`; cả hai pipeline chạy qua pipe đều exit 0.
- **Điều học được:** Phải phân biệt lỗi môi trường (encoding, phiên bản Python 3.14 nằm ngoài `requires-python`, BOM trong `.env` khi ghi bằng PowerShell 5.1) với lỗi logic. Mỗi loại cần một cách xác minh riêng.

## 7. Hiểu biết về luồng end-to-end

1. **Crossref → vector index:** response JSON thô được giữ nguyên trong `data/raw/`. `parse_crossref_payload` sinh `PaperRecord` (bỏ `<jats:p>`, ghép tác giả, chuẩn hoá ngày). `build_clean_dataframe` dedup, tính `age_days` và `text_for_embedding` 5 phần. Dữ liệu phải qua GX gate rồi mới được MiniLM embed (vector chuẩn hoá) và nạp vào collection Chroma dùng khoảng cách cosine.
2. **Evaluation set:** mỗi câu hỏi có `ground_truth_doc_ids` là DOI. Retrieval hit tính là đúng khi DOI nằm trong top-4 kết quả. Token F1 so câu trả lời với ground truth. LLM judge (gpt-4o-mini) chấm mức đúng về nội dung. Ba metric bổ sung cho nhau: eval_002 có F1 = 1.0 và judge 5/5, nhưng hit = FAIL vì lấy từ tài liệu khác.
3. **Quality checks và freshness:** quality kiểm tra cấu trúc và tính hợp lệ tại một thời điểm (null, unique, độ dài, regex) và cho kết quả tất định. Freshness đo độ cũ của corpus so với ngày chạy theo SLA (180 ngày / 25%), nên kết quả thay đổi theo thời gian.
4. **Cùng test set:** khi câu hỏi, ground truth, model và `top_k` cố định, mọi chênh lệch metric chỉ có thể do dữ liệu. Đổi test set thì không tách được tác động của corruption.
5. **Repair thành công dựa trên:** `repaired_quality_report.json` có `success=true`, `repaired_freshness_report.json` có `is_fresh=true`, `repaired_metrics.json` bằng `baseline_metrics.json`, và `repair_log.json` có `repaired_matches_baseline=true` (hash trùng).

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0 | 0.8 | 1.0 | Chỉ `drop_latest_records` làm hỏng retrieval (eval_001, eval_002) |
| `mean_token_f1` | 1.0 | 0.8 | 1.0 | eval_001 trả lời rỗng; eval_005 trả chuỗi rác |
| `judge_accuracy` | 1.0 | 0.8 | 1.0 | Judge **không** bắt được eval_002 (đúng chữ, sai nguồn) |
| `mean_judge_score` | 5.0 | 4.3 | 5.0 | eval_001 được 2 điểm, eval_005 được 1 điểm |
| Quality checks | PASS 8/8 | FAIL 4/8 | PASS 8/8 | Mỗi loại lỗi về cấu trúc kích hoạt đúng expectation đã thiết kế |
| Freshness status | Fresh 0.0417 | Stale 0.3636 | Fresh 0.0417 | 8/22 bài stale sau `stale_date` và `drop` |

### Kết luận từ số liệu

1. `drop_latest_records` (5 bài) làm row count giảm 24→22 và `latest_published` lùi 2026-07-22→2026-06-12. Retrieval của eval_001 và eval_002 fail, kéo hit rate từ 1.0 xuống 0.8.
2. Auto-repair build lại từ raw, GX quay về 8/8 PASS và is_fresh = True. Cả 4 metric trở về đúng 1.0/1.0/1.0/5.0, và hash nội dung trùng baseline.

**Corruption ảnh hưởng rõ nhất:** `drop_latest_records`. Nó là lỗi duy nhất phá được retrieval, và gần như vô hình với GX, vì 22 dòng vẫn nằm trong ngưỡng 5–5000. Chỉ freshness (`latest_published` lùi) và hit rate cho thấy vấn đề. Đây đúng là kịch bản "quên cập nhật vector store" trong đề bài.

**Kết quả khác kỳ vọng:** Tôi kỳ vọng `stale_date` sẽ làm sai các câu hỏi dạng `date`, nhưng metric không đổi. Kiểm tra `corruption_log.json` so với `test_set.json` cho thấy 6 bài bị lùi ngày không trùng bài nào được hỏi `date`. Cụ thể, eval_008 (doc `…1801`) và eval_009 (doc `…1806`) bị stale nhưng lại hỏi categories và summary. Tương tự, các doc bị blank summary nằm ở câu hỏi date, categories và authors. Tổng cộng 6/10 câu rơi vào doc bị hỏng nhưng không đổi metric, vì lỗi chỉ gây hại khi chạm đúng trường mà câu hỏi dùng. Metric trên test set nhỏ có thể che mất lỗi, nên quality gate là bắt buộc chứ không chỉ để tham khảo.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. **Data pipeline:** giữ raw bất biến và cleaning tất định thì repair chỉ còn là "chạy lại từ raw". Idempotency kiểm chứng được bằng hash, không cần tin bằng lời.
2. **Data quality/observability:** mỗi dạng lỗi cần ít nhất một tín hiệu phát hiện riêng. Row count 5–5000 không phát hiện được việc mất 20% bài mới, nên cần thêm freshness và theo dõi `latest_published`.
3. **Ảnh hưởng của data đến RAG agent:** LLM judge và token F1 có thể chấm đúng một câu trả lời lấy từ tài liệu sai (eval_002). Retrieval hit rate theo DOI là lớp phòng vệ không thể thiếu.

### Nếu có thêm thời gian

Tôi sẽ sinh test set có chủ đích theo corruption: mỗi loại lỗi có ít nhất 2 câu hỏi chạm đúng trường bị hỏng, ví dụ doc bị `stale_date` thì hỏi `date`. Test set cũng cần tăng lên ≥ 40 câu. Cách đo: số loại corruption gây giảm metric có ý nghĩa. Hiện có 2/6 loại gây giảm trực tiếp (drop, noise), còn blank_summary chỉ tác động gián tiếp qua eval_001. Mục tiêu 5/6. `duplicate_rows` có thể vẫn không làm giảm metric với QA extractive.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Vũ Huy
**Ngày xác nhận:** 2026-09-25
