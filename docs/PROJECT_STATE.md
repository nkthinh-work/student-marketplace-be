# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Phase 9 — Workers + Optimization + Deploy**

---

## 2. Current Task (Công việc hiện tại)
**Phase 9C-D — CI / Deployment** (Current slice: CI / Release Gate & Deployment Preflight)

---

## 3. Status (Trạng thái)
**CI IMPLEMENTED — DEPLOYMENT TARGET PENDING**

---

## 4. Recently Completed (Các công việc vừa hoàn thành)

- **Phase 9C-C — Production Docker Build & Container Hardening** (USER ACCEPTED):
  - Dockerfile đa tầng `python:3.12-slim`, non-root user `appuser` (UID 10001), dùng chung image `student-marketplace-be:prod` cho API và Worker.
  - Cấu hình `docker-compose.prod.yml` độc lập: không bind mount mã nguồn, không auto-reload, PostgreSQL/Redis nội bộ, healthchecks chuẩn xác, migration Alembic tường minh. Diễn tập production smoke stack cô lập (`sm-prod-smoke`) thành công mỹ mãn.
- **Phase 9C-B — PostgreSQL Backup & Restore Procedure** (USER ACCEPTED):
  - Quy trình sao lưu logical dump PostgreSQL native (`pg_dump -Fc`), xác thực SHA-256 và manifest, diễn tập phục hồi cô lập trên Docker container thành công trong 1.13s.
  - Khớp 100% 29 bảng nghiệp vụ, bảo toàn CSDL nguồn, phân định rõ ranh giới phục hồi Redis / Cloudinary / Firebase, tài liệu vận hành tại `BACKUP_RESTORE.md`.
- **Phase 9C-A — Query & Index Audit / Performance Hardening** (USER ACCEPTED):
  - Kiểm toán toàn diện 21 nhóm truy vấn trọng yếu trên 29 bảng nghiệp vụ; xác nhận 100% khớp chỉ mục với phân trang Keyset và GIN FTS.
  - Khắc phục điểm nghẽn hàng đợi Admin trên bảng `reports` qua 2 chỉ mục chuyên biệt (migration `c2f84937f5d2`), tăng tốc 72% - 95%, triệt tiêu forced Seq Scan.
  - Xác thực 0 N+1 trên các endpoint danh sách (hồ sơ chi tiết tại `QUERY_INDEX_AUDIT.md`).

---

## 5. Active Decisions (Quyết định kiến trúc đang hiệu lực)

- **Giao diện Light-only**: Toàn bộ hệ thống frontend hoạt động ở chế độ sáng duy nhất, không duy trì theme toggle hay token dark mode.
- **PostgreSQL là Source of Truth**: Mọi trạng thái nghiệp vụ (đơn hàng, đấu giá, tồn kho, người dùng, báo cáo) lưu trữ bền vững tại PostgreSQL; Redis và WebSocket chỉ đóng vai trò bộ đệm và tối ưu phân phối realtime.
- **Redis Product View Counter**: Redis lưu bộ đếm tạm thời và khử trùng lặp 24h; PostgreSQL giữ projection bền vững. Sự cố Redis tuân thủ cơ chế fail-open, không gián đoạn duyệt hàng. Thẻ danh sách không gọi POST `/view`, không dùng `view_count` để sắp xếp hay xếp hạng.
- **Quy trình Sao lưu & Phục hồi PostgreSQL**: Sử dụng `scripts/db_backup.py` với logical format native (`pg_dump -Fc`), xác thực checksum SHA-256 và `pg_restore --list`. Diễn tập khôi phục tuyệt đối không ghi đè hay xóa DB nguồn (`student_marketplace`), luôn kiểm thử trên target cô lập tạm thời và dọn dẹp an toàn. Redis được làm sạch/khởi tạo mới khi khắc phục sự cố, tài nguyên Cloudinary/Firebase tuân thủ ranh giới nhà cung cấp bên ngoài. Hỗ trợ tùy chọn cờ `--compose-file` cho production.
- **Đóng gói Container Sản xuất (Production Docker)**: Sử dụng Dockerfile đa tầng (multi-stage) tối ưu `python:3.12-slim`, non-root user `appuser` (UID `10001`). Image `student-marketplace-be:prod` dùng chung cho cả `api` và `worker`. Cấu hình `docker-compose.prod.yml` không bind mount mã nguồn, không auto-reload, giữ PostgreSQL và Redis nội bộ mạng Compose, healthchecks định kỳ, không tự ý chạy migration khi boot API.
- **Quy chuẩn CI / Release Gate (GitHub Actions)**: Cấu hình CI độc lập tại `.github/workflows/ci.yml` cho từng repository (`student-marketplace-be` và `student-marketplace-fe`). Tự động thực thi trên `push` và `pull_request` nhánh `main`, sử dụng service containers cô lập cho PostgreSQL 15 & Redis 7, kiểm tra di trú và drift Alembic, chạy full test suite, validate Production Compose, build Production Docker image, kiểm tra non-root runtime `appuser` và ranh giới tệp tin. Hoàn toàn không sử dụng secrets thật trong CI.
- **Vòng đời Community Moments**: Giới hạn tối đa 5 ảnh đã duyệt đồng thời trên Hero carousel; duyệt hoặc từ chối thực hiện nguyên tử, không lưu trữ trạng thái REJECTED trong DB.
- **Mô hình Phản hồi (Site Feedback)**: Issue board công khai ẩn danh, không có rating, không tiền kiểm duyệt (PENDING/APPROVED), hỗ trợ đính kèm minh chứng và hard delete.
- **Chế tài Tài khoản (Capability Restrictions)**: Restriction mới luôn phải có thời hạn hữu hạn; tầng service yêu cầu `expires_at` với mọi chế tài mới. Cột vật lý vẫn nullable để tương thích dữ liệu legacy theo `DB_v7.md`.
- **Cổng Nghiệm thu Người dùng (User Acceptance Gate)**: Mọi phase/task có cổng nghiệm thu phải dừng và chờ người dùng xác nhận trước khi chuyển phase tiếp theo.

---

## 6. Known Issues (Vấn đề đã biết)

- **Môi trường Triển khai Từ xa Chưa được Cấu hình (Remote Deployment Target Pending)**: Dự án chưa có cấu hình cụ thể về máy chủ VPS, nền tảng PaaS, container registry hoặc domain/TLS thực tế. Đã sẵn sàng các pipeline CI và gating artifact; việc triển khai từ xa sẽ được kích hoạt khi có chỉ định hạ tầng chính thức từ người dùng.
- Không có vấn đề chặn (Zero blocking issues). Toàn bộ 744 tests backend vượt qua, frontend build thành công, Alembic 0 drift.

---

## 7. Verification Baseline (Đường cơ sở kiểm thử)

- **Backend Full Suite**: 744/744 PASS (`pytest tests/ -q` in 167.60s).
- **Focused Backup Suite**: 6/6 PASS (`tests/test_db_backup.py`).
- **Phase 9A Worker Hardening Suite**: 13/13 PASS (`tests/test_worker_hardening.py`).
- **Phase 9B Product View Counter Suite**: 26/26 PASS (`tests/test_product_view_counter.py`).
- **Production Docker Smoke Drill**: Đã diễn tập thực tế thành công trên stack cô lập `sm-prod-smoke` (API port 18000, volume cô lập, `c2f84937f5d2 (head)` migration tường minh, API & Redis & DB `healthy`, Worker liveness ổn định, restart & graceful shutdown SIGTERM 15 thành công, volume CSDL bền vững qua restart, dọn dẹp an toàn không ảnh hưởng dev environment).
- **Backend CI Workflow Syntax**: Validated (Python yaml check exit 0).
- **Frontend CI Workflow Syntax**: Validated (Python yaml check exit 0).
- **Frontend Lockfile Installation Check**: `npm ci --dry-run` PASS.
- **Alembic State**: Head `c2f84937f5d2`, 0 schema drift (`alembic check` clean).
- **Cơ sở dữ liệu vật lý**: 29 bảng nghiệp vụ + 1 bảng metadata (`alembic_version`) = 30 bảng vật lý; 96 application indexes.
- **Frontend Build**: `tsc -b && vite build` PASS (0 errors, 0 warnings).
- **Dịch vụ môi trường phát triển**: Backend port 8000 hoạt động, Frontend port 3000 hoạt động, Dev PostgreSQL/Redis container hoạt động, Dev Tunnel hoạt động.

---

## 8. Next Exact Task (Công việc chính xác tiếp theo)

- Nghiệm thu từ người dùng cho **Phase 9C-D Slice 1 — CI + Release Gate + Deployment Preflight** (`USER ACCEPTANCE OF PHASE 9C-D SLICE 1`).
- Sau khi người dùng chấp thuận chính thức và cung cấp thông tin hạ tầng triển khai từ xa: Tiến hành **Phase 9C-D Slice 2 — Remote Deployment**. Tuyệt đối không tự ý giả định hay triển khai lên cloud ảo khi chưa có thông tin cấu hình thực tế.
