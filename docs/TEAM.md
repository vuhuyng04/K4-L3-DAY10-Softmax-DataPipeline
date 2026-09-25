# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `NguyenVuHuy` (làm cá nhân — 1 thành viên)
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `https://github.com/vuhuyng04/K4-L3A-Day10-Data-Pipeline-Data-Observability`

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|
| 1 | Nguyễn Vũ Huy | 2A202602662 | nguyenvuhuyofficial@gmail.com | Làm một mình, đảm nhận toàn bộ 4 vai trò: Pipeline Integrator (`core/`, `phase1.py`, `corruption_flow.py`), Data Foundation & Recovery (`crossref.py`, `cleaning.py`, `corruption.py`), RAG & Vector Index (`retrieval/`), Observability & Evaluation (`quality.py`, `testset.py`, `reporting.py`, `dashboard.py`, `tests/`) | [`report/2A202602662_NguyenVuHuy.md`](../report/2A202602662_NguyenVuHuy.md) |

Phân công theo checkpoint (một người phụ trách tất cả):

| Checkpoint | Deliverable | Owner |
| --- | --- | --- |
| CP0 | Môi trường `uv` (Python 3.13), `.env` (không commit), `src/ingestion/crossref.py`, 2 raw artifacts | Nguyễn Vũ Huy |
| CP1 | `src/ingestion/cleaning.py`, `src/observability/quality.py` (GX 1.x + Freshness SLA) | Nguyễn Vũ Huy |
| CP2 | `src/evaluation/testset.py`, ChromaDB collection `papers-baseline` | Nguyễn Vũ Huy |
| CP3 | `src/pipelines/phase1.py`, `generate_phase1_report`, `baseline_metrics.json`, `phase1_report.md` | Nguyễn Vũ Huy |
| CP4 | `src/ingestion/corruption.py`, `corruption_log.json`, `corrupted_metrics.json` | Nguyễn Vũ Huy |
| CP5 | `src/pipelines/corruption_flow.py` (auto-repair), `generate_corruption_report`, `corruption_report.md`, `repaired_metrics.json` | Nguyễn Vũ Huy |
| Bonus | B1 `dashboard.html`, B2 auto-repair, B3 `tests/` + GitHub Actions (coverage 97%) | Nguyễn Vũ Huy |

---

## # Cá nhân

### ## NguyenVuHuy-2A202602662
- **Vai trò:** Thành viên duy nhất, phụ trách toàn bộ pipeline từ ingestion đến báo cáo và bonus.
- **Công việc chi tiết đã hoàn thành:**
  - **Ingestion & lineage** (`src/ingestion/crossref.py`): parse payload Crossref (bỏ tag JATS, ghép tên tác giả, chuẩn hoá ngày từ `date-parts`, bỏ record thiếu DOI/title/abstract). Có 2 chế độ: offline snapshot (mặc định, không ghi đè raw gốc) và live API bật bằng `REFRESH_SOURCE=1`, có retry/backoff cho 429/5xx và fallback về snapshot.
  - **Cleaning** (`src/ingestion/cleaning.py`): bỏ markup và khoảng trắng thừa, dedup theo `paper_id` (giữ bản `updated` mới nhất), tính `age_days`, sinh `text_for_embedding` 5 phần. Hàm `refresh_derived_columns` được dùng chung với corruption.
  - **Data Observability** (`src/observability/quality.py`): Quality Gate Great Expectations 1.x chạy ephemeral context với 8 expectation: đủ 4 loại bắt buộc, thêm độ dài title ≥ 8 và regex bắt ký tự rác. Freshness SLA: `is_fresh=False` khi hơn 25% số bài có `age_days > 180`.
  - **Evaluation** (`src/evaluation/testset.py`, `metrics.py`): test set cố định 10 câu thuộc 4 loại (3/3/2/2), bổ sung breakdown theo `question_type` và `judge_fallback_count`.
  - **Corruption & Repair** (`src/ingestion/corruption.py`, `src/pipelines/corruption_flow.py`): tiêm 6 loại lỗi, tất định với seed 42. Auto-repair tự kích hoạt khi GX hoặc Freshness fail, build lại từ raw snapshot và dùng hash nội dung để chứng minh `repaired == baseline`.
  - **Orchestration & báo cáo** (`src/pipelines/phase1.py`, `src/observability/reporting.py`, `dashboard.py`): quality gate chặn không cho index khi dữ liệu bẩn, sinh báo cáo 3 trạng thái kèm phân tích nhân quả, dashboard HTML tĩnh. Sửa manifest embeddings để lưu đường dẫn tương đối thay cho đường dẫn tuyệt đối.
  - **Kiểm thử**: 31 test pytest (unit và e2e), coverage 97%, CI GitHub Actions chạy offline với mock LLM.
- **Điều học được / Đóng góp chính:**
  - Silent failure là có thật: khi dữ liệu bẩn, agent vẫn trả lời trôi chảy. Có câu trả lời **đúng về chữ nhưng lấy từ sai tài liệu** (eval_002), chỉ retrieval hit rate mới phát hiện được.
  - Quality Gate (schema/validity) và Freshness SLA (theo thời gian) là hai lớp tín hiệu khác nhau, cần tách riêng. Repair đúng nghĩa là build lại từ raw bất biến, không vá tay dữ liệu hỏng.
