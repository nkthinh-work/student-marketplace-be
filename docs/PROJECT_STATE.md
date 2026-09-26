# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Phase 9 — Workers + Optimization + Deploy**

---

## 2. Current Task (Công việc hiện tại)
**Phase 9C-D Slice 2 — Urgent Public-Beta Rollout (Railway + Vercel)**
*Parent Task*: Phase 9C-D — CI / Deployment
*Deployment State*: INFRASTRUCTURE PROVISIONING IN PROGRESS

---

## 3. Status (Trạng thái)
**IN PROGRESS — INFRASTRUCTURE PROVISIONING (RAILWAY PUBLIC-BETA)**

---

## 4. Recently Completed (Các công việc vừa hoàn thành)

- **Phase 9C-D — GitHub Release & CI Verification** (COMPLETED & VERIFIED / USER ACCEPTED):
  - Nhánh `main` của cả hai kho mã nguồn `student-marketplace-be` và `student-marketplace-fe` đã được đẩy bản Release Candidate mới nhất.
  - Xác nhận trực tiếp từ giao diện GitHub Actions UI:
    - Backend: `Backend CI & Release Gate` (SUCCESS), `Backend Test Suite & Alembic Verification` (SUCCESS), `Production Docker Build & Artifact Hardening Gate` (SUCCESS).
    - Frontend: `Frontend CI & Build Gate` (SUCCESS), `Frontend Typecheck & Production Build` (SUCCESS).
    - Các thông báo runner / Node.js 20 deprecation từ GitHub chỉ là warning, không ảnh hưởng kết quả thành công của workflow.
- **Phase 9C-D — Release Candidate Hygiene & Production Data Preparation** (USER ACCEPTED / COMPLETED & VERIFIED):
  - Vệ sinh toàn diện repository: Triệt tiêu code debug, chuẩn hóa tiếng Việt giải thích invariant, zero secrets, cập nhật `.gitignore` (`*.dump`).
  - Phân định không gian lưu trữ Cloudinary theo môi trường (`student-marketplace/dev/...` vs `student-marketplace/prod/...`), bảo toàn 100% tài nguyên legacy.
  - Hoàn tất dọn dẹp Cloudinary sau rà soát thủ công: 50 tài nguyên legacy đang được CSDL tham chiếu được giữ lại nguyên vẹn (50 legacy referenced assets retained), 4 tài nguyên mồ côi đã được xóa an toàn (4 orphan assets deleted after manual review), 0 tài nguyên mồ côi còn lại (0 orphan remaining), 0 tài nguyên không xác định (0 unknown remaining).
  - Chiến lược CSDL Production sạch: Khởi tạo schema chuẩn từ đầu qua `alembic upgrade head`, nạp 10 danh mục chuẩn tắc bằng `scripts/seed_production_reference.py`, công cụ CLI bootstrap Admin an toàn qua Firebase Auth `scripts/promote_admin.py`.
  - Công cụ kiểm toán đọc-chỉ `scripts/audit_dev_db.py`: Báo cáo 1.375 bản ghi trên toàn bộ 32 bảng ứng dụng, bảo toàn nguyên vẹn dữ liệu thử nghiệm.
- **Pre-Deployment Acceptance Fix — Product Approval Completion & Inbox/Home UX** (USER ACCEPTED)
- **Pre-Deployment Amendment — Navigation-Aligned Tutorial & Presentation Media UX** (USER ACCEPTED)
- **Pre-Deployment UX Polish — Dynamic Tutorial Overlay & Admin CMS** (USER ACCEPTED)

---

## 5. Active Decisions (Quyết định kiến trúc đang hiệu lực)

- **Mục tiêu Triển khai Khẩn cấp Thử nghiệm Công khai (Urgent Public-Beta Target: Railway + Vercel)**:
  - **Mục tiêu vận hành**: Đáp ứng yêu cầu phát hành thử nghiệm công khai khẩn cấp trên nền tảng đám mây quản lý (PaaS).
  - **Phân bổ hạ tầng**:
    - **Frontend**: Triển khai trên **Vercel** kết nối repository `student-marketplace-fe` (Edge CDN, tối ưu static delivery).
    - **Backend trên Railway (Project "choptiters")**: Duy trì độc lập 4 dịch vụ cốt lõi:
      1. `FastAPI API`: Cung cấp HTTP REST và WebSocket.
      2. `Background Worker`: Chạy tiến trình `app.workers.order_auto_cancel` độc lập.
      3. `Railway PostgreSQL`: Dịch vụ CSDL quan hệ độc lập.
      4. `Railway Redis`: Dịch vụ lưu trữ bộ nhớ đệm, view counter và pub/sub realtime độc lập.
    - **External Providers**: Firebase Authentication (xác thực người dùng), Cloudinary (lưu trữ media nhị phân theo namespace `student-marketplace/prod/`).
- **Bảo toàn Lộ trình Triển khai Chuẩn (VPS Architecture Preservation)**:
  - Lựa chọn Railway là mục tiêu vận hành tạm thời (operational target), không phải là sự thay đổi thiết kế kiến trúc nghiệp vụ (business-architecture redesign).
  - Tuyệt đối không xóa bỏ hay vô hiệu hóa đường lối triển khai VPS. Tệp `docker-compose.prod.yml` và cấu hình container hardening được giữ nguyên vẹn để sẵn sàng di trú sang VPS độc lập về sau.
- **Chiến lược Khởi tạo Cơ sở Dữ liệu Production & Di trú Tường minh**:
  - CSDL Production khởi tạo hoàn toàn sạch: Tuyệt đối không sao chép dữ liệu test từ dev sang Railway PostgreSQL.
  - Di trú tường minh (Explicit Migration): Không kích hoạt auto-migration tự động khi container API khởi động. Schema được nâng cấp có chủ đích qua lệnh `alembic upgrade head`.
  - Nạp dữ liệu tham chiếu: Chạy script lũy đẳng `scripts/seed_production_reference.py` nạp 10 danh mục chuẩn tắc, tuyệt đối không tạo dữ liệu giao dịch giả.
- **Quy trình Khởi tạo Quản trị viên Đầu tiên (First Admin Bootstrap)**:
  - Người vận hành đăng nhập lần đầu qua Google/Firebase Auth để tạo bản ghi tài khoản `ACTIVE`.
  - Thực thi CLI `python scripts/promote_admin.py --email <admin_email>` để thăng cấp `role = 'ADMIN'`. Không lưu mật khẩu hoặc thông tin đăng nhập trong mã nguồn.
- **Quy trình Phê duyệt Tin đăng Tiền xuất bản (Pre-Publication Product Approval)**:
  - Mọi tin đăng mới bắt buộc qua kiểm duyệt Admin trước khi công khai. Ảnh sản phẩm là tùy chọn (0, 1 hoặc nhiều ảnh).
- **Dọn dẹp Thông báo Cá nhân (Notification Hard-Delete Inbox Cleanup)**:
  - Hỗ trợ vuốt phải trực tiếp trên mobile; xóa thông báo không ảnh hưởng thực thể nghiệp vụ tham chiếu.
- **Hợp đồng Nhật ký & Marquee Trang chủ (Real-Data Daily Journal & Continuous Marquee Contract)**:
  - `GET /api/v1/daily-needs/recent` (limit clamp 1..10) phục vụ marquee trang chủ; backend không tạo dữ liệu giả.

---

## 6. Known Issues (Vấn đề đã biết & Hiện trạng Triển khai Thực tế)

- **Hiện trạng Cấp phát Hạ tầng Public-Beta (Railway + Vercel Status)**:
  - Project Railway "choptiters" đã được tạo thành công.
  - Railway PostgreSQL đã được cấp phát và đang trực tuyến (online).
  - Railway Redis đã được cấp phát.
  - Dịch vụ Backend GitHub đã được tạo trên Railway nhưng **CHƯA ĐƯỢC DEPLOY** (has not been deployed yet).
  - **Chưa có tên miền API sản xuất** (No production API domain exists yet).
  - **Dịch vụ Background Worker chưa được deploy** (No worker service has been deployed yet).
  - **Chưa chạy migration Alembic hoặc seed dữ liệu trên Railway** (No migration/seed has been run on Railway yet).
  - **Frontend chưa được triển khai lên Vercel** cho đợt public-beta rollout này (Frontend has not yet been deployed to Vercel).
  - Tuyệt đối không tự tiện bịa đặt API domain, TLS certificate, production secrets hay deployed URLs khi chưa thực sự diễn ra.
- **Hệ thống Cục bộ & CI Đạt Trạng thái Tối ưu**: Toàn bộ **842/842 tests backend** vượt qua, frontend build thành công không lỗi (0 errors), Alembic 0 schema drift ở head `4414f46b5404`, CSDL duy trì 32 bảng ứng dụng + 1 bảng `alembic_version` = 33 bảng vật lý.

---

## 7. Verification Baseline (Đường cơ sở kiểm thử)

- **Backend Full Suite**: **842/842 PASS** (`pytest tests/ -q` in 115.23s).
- **Backend GitHub Actions Release Gate**: **SUCCESS** (`Backend CI & Release Gate`, `Backend Test Suite & Alembic Verification`, `Production Docker Build & Artifact Hardening Gate`).
- **Frontend GitHub Actions Build Gate**: **SUCCESS** (`Frontend CI & Build Gate`, `Frontend Typecheck & Production Build`).
- **Cloudinary Cleanup**: **HOÀN TẤT** (50 legacy referenced assets retained, 4 orphan assets deleted after manual review, 0 orphan remaining, 0 unknown remaining).
- **Alembic State**: Head `4414f46b5404`, 0 schema drift (`alembic check` clean, No new upgrade operations detected).
- **Cơ sở dữ liệu vật lý**: 32 bảng nghiệp vụ + 1 bảng metadata (`alembic_version`) = 33 bảng vật lý.
- **Production Reference Seed**: 10 danh mục chuẩn tắc được nạp lũy đẳng (`scripts/seed_production_reference.py`).
- **Cloudinary Tests**: 15/15 PASS (`tests/test_cloudinary.py`).
- **Tutorial Backend Suite**: 31/31 PASS (`tests/test_tutorials.py`).
- **Product Approval Suite**: 15/15 PASS (`tests/test_product_approval.py`).
- **Daily Needs Suite**: 29/29 PASS (`tests/test_daily_needs.py`).
- **Notifications Suite**: 14/14 PASS (`tests/test_notifications.py`).
- **Frontend Acceptance Suite**: **14/14 PASS** (`node src/__tests__/pre_deployment_acceptance_fixes.test.mjs`).
- **Frontend Tutorial Suite**: 12/12 PASS (`src/features/tutorials/__tests__/tutorials.test.mjs`).
- **Frontend Production Build**: `tsc -b && vite build` PASS (0 errors, 6.19s / 8.31s).
- **Dịch vụ môi trường phát triển**: Backend port 8000 hoạt động, Frontend port 3000 hoạt động, Dev PostgreSQL/Redis container hoạt động, Dev Tunnel hoạt động.

---

## 8. Next Exact Task (Công việc chính xác tiếp theo)

- **Phase 9C-D Slice 2 — Urgent Public-Beta Rollout Execution**:
  1. Cấu hình biến môi trường kết nối Railway PostgreSQL và Redis (`DATABASE_URL`, `REDIS_URL` hoặc các biến tương ứng).
  2. Cấu hình các production secrets an toàn trên Railway (`FIREBASE_CREDENTIALS_PATH` / service account, Cloudinary API keys, v.v.).
  3. Triển khai dịch vụ API (`FastAPI API` service) trên Railway và thiết lập public networking domain.
  4. Thực thi di trú cơ sở dữ liệu sản xuất sạch (`alembic upgrade head`) trên CSDL Railway PostgreSQL.
  5. Chạy script nạp 10 danh mục tham chiếu chuẩn tắc (`python -m scripts.seed_production_reference`).
  6. Triển khai dịch vụ Background Worker (`python -m app.workers.order_auto_cancel`) độc lập trên Railway.
  7. Thiết lập dự án Frontend trên Vercel: Kết nối repository `student-marketplace-fe`, cấu hình `VITE_API_URL` trỏ về domain API Railway.
  8. Cấu hình CORS (`BACKEND_CORS_ORIGINS`) trên Backend khớp domain Vercel và bổ sung domain Vercel vào Firebase Authorized Domains.
  9. Thực hiện diễn tập kiểm thử thông luồng (Smoke Test) trực tiếp trên môi trường public-beta.
  10. Xác thực quy trình sao lưu CSDL (Backup verification) trên môi trường Railway PostgreSQL.
