# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Phase 9 — Workers + Optimization + Deploy**

---

## 2. Current Task (Công việc hiện tại)
**Phase 9C-D — Release Candidate Hygiene & Production Data Preparation**
*Parent Task*: Phase 9C-D — CI / Deployment
*Deployment State*: NOT STARTED — RELEASE CANDIDATE PREPARATION

---

## 3. Status (Trạng thái)
**IMPLEMENTED — AWAITING USER ACCEPTANCE**

---

## 4. Recently Completed (Các công việc vừa hoàn thành)

- **Phase 9C-D — Release Candidate Hygiene & Production Data Preparation** (IMPLEMENTED — AWAITING USER ACCEPTANCE):
  - **Vệ sinh Toàn diện Repository (BE & FE Code & File Hygiene)**:
    - Triệt tiêu code debug, `console.debug`, chuẩn hóa thông báo lỗi tải ảnh tự nhiên tiếng Việt (`Tải ảnh lên thất bại. Vui lòng thử lại.`).
    - Chuẩn hóa comment giải thích bằng tiếng Việt súc tích (giải thích TẠI SAO/invariant), giữ nguyên định danh kỹ thuật chuẩn tiếng Anh; không sửa đổi chuỗi hợp đồng runtime API/DB/Enums.
    - Rà soát .gitignore: bổ sung `*.dump`, `*.dump.part` ngăn chặn rò rỉ bản sao lưu CSDL vào Git; 0 tệp lớn > 500KB được theo dõi; 0 secret rò rỉ trong cả hai repo.
  - **Phân định Không gian Lưu trữ Cloudinary theo Môi trường (dev vs prod)**:
    - Bộ giải quyết tập trung duy nhất qua `get_cloudinary_root_folder()`: `student-marketplace/dev/...` cho môi trường phát triển và `student-marketplace/prod/...` cho môi trường sản xuất; bảo toàn nguyên vẹn 100% các tài nguyên legacy hiện có.
    - Cấu hình biến môi trường `ENVIRONMENT=development` trong config và `.env.example`.
  - **Công cụ Kiểm toán Cloudinary An toàn (Safe Media Audit Tool — DRY RUN Default)**:
    - Triển khai `scripts/audit_cloudinary_media.py`: kiểm toán toàn diện 8 bảng CSDL (`product_images`, `message_attachments`, `report_attachments`, `community_moments`, `site_feedback_attachments`, `tutorials`, `orders`, `users`) trên cả 3 loại tài nguyên (`image`, `video`, `raw`).
    - Mặc định DRY RUN; xóa tài nguyên bắt buộc đồng thời 2 cờ `--execute` VÀ `--confirm`. Kết quả quét thực tế 54 assets: 50 legacy referenced, 4 orphan candidates, 0 deleted.
  - **Chiến lược Chuẩn bị Dữ liệu CSDL Production**:
    - Cơ chế chuẩn: CSDL Production mới tinh từ đầu qua `alembic upgrade head`; tuyệt đối không sao chép CSDL development chứa dữ liệu kiểm thử.
    - Idempotent Production Seed Script (`scripts/seed_production_reference.py`): nạp chính xác 10 danh mục chuẩn tắc, an toàn khi chạy lại nhiều lần, tuyệt đối không nạp dữ liệu giao dịch giả.
    - Quy trình Bootstrap Admin An toàn (`scripts/promote_admin.py`): thăng cấp tài khoản quản trị viên đầu tiên sau khi đăng nhập qua Firebase Auth, không hardcode mật khẩu, không tạo backdoor.
    - Công cụ Kiểm toán CSDL Dev Đọc-chỉ (`scripts/audit_dev_db.py`): báo cáo chi tiết 1.375 bản ghi trên toàn bộ 32 bảng ứng dụng, 0 biến đổi dữ liệu.
- **Pre-Deployment Acceptance Fix — Product Approval Completion & Inbox/Home UX** (USER ACCEPTED)
- **Pre-Deployment Amendment — Navigation-Aligned Tutorial & Presentation Media UX** (USER ACCEPTED)
- **Pre-Deployment UX Polish — Dynamic Tutorial Overlay & Admin CMS** (USER ACCEPTED)
- **Pre-Deployment Hardening — Complete User + Admin Notification Coverage** (USER ACCEPTED)

---

## 5. Active Decisions (Quyết định kiến trúc đang hiệu lực)

- **Phân định Không gian Lưu trữ Cloudinary (Cloudinary Environment Separation)**:
  - Tách bạch `student-marketplace/dev/...` và `student-marketplace/prod/...` qua `get_cloudinary_root_folder()`.
  - Giữ nguyên các đường dẫn legacy cho các bản ghi CSDL hiện hữu; không tự động đổi tên hay di dời asset trên đám mây.
- **Chiến lược Khởi tạo Cơ sở Dữ liệu Production (Production Clean DB Strategy)**:
  - CSDL Production khởi tạo hoàn toàn sạch: `alembic upgrade head` -> chạy `scripts/seed_production_reference.py` nạp 10 danh mục chuẩn tắc. Tuyệt đối không import dump dev chứa dữ liệu test.
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

## 6. Known Issues (Vấn đề đã biết)

- **Chờ Người dùng Nghiệm thu Gói Vệ sinh Phát hành (Awaiting User Acceptance)**:
  - Gói `Phase 9C-D — Release Candidate Hygiene & Production Data Preparation` đã hoàn tất kiểm chứng cục bộ và đang chờ người dùng kiểm tra báo cáo vệ sinh trước khi đẩy lên GitHub.
- **Môi trường Triển khai Từ xa Chưa được Cấu hình (Remote Deployment Target Pending)**: Dự án chưa có cấu hình cụ thể về máy chủ VPS, nền tảng PaaS, container registry hoặc domain/TLS thực tế. Việc triển khai từ xa tạm dừng cho đến khi người dùng sẵn sàng hạ tầng.
- **Hệ thống Cục bộ Đạt Trạng thái Tối ưu**: Toàn bộ **842/842 tests backend** vượt qua, frontend build thành công không lỗi (0 errors), Alembic 0 schema drift ở head `4414f46b5404`, CSDL duy trì 32 bảng ứng dụng + 1 bảng `alembic_version` = 33 bảng vật lý.

---

## 7. Verification Baseline (Đường cơ sở kiểm thử)

- **Backend Full Suite**: **842/842 PASS** (`pytest tests/ -q` in 115.23s).
- **Cloudinary Tests**: 15/15 PASS (`tests/test_cloudinary.py`).
- **Tutorial Backend Suite**: 31/31 PASS (`tests/test_tutorials.py`).
- **Product Approval Suite**: 15/15 PASS (`tests/test_product_approval.py`).
- **Daily Needs Suite**: 29/29 PASS (`tests/test_daily_needs.py`).
- **Notifications Suite**: 14/14 PASS (`tests/test_notifications.py`).
- **Frontend Acceptance Suite**: **14/14 PASS** (`node src/__tests__/pre_deployment_acceptance_fixes.test.mjs`).
- **Frontend Tutorial Suite**: 12/12 PASS (`src/features/tutorials/__tests__/tutorials.test.mjs`).
- **Frontend Production Build**: `tsc -b && vite build` PASS (0 errors, 6.19s).
- **Alembic State**: Head `4414f46b5404`, 0 schema drift (`alembic check` clean, No new upgrade operations detected).
- **Cơ sở dữ liệu vật lý**: 32 bảng nghiệp vụ + 1 bảng metadata (`alembic_version`) = 33 bảng vật lý.
- **Cloudinary Media Audit**: 54 assets quét (50 legacy referenced, 4 orphan candidates, 0 deleted).
- **Production Reference Seed**: 10 danh mục chuẩn tắc được nạp lũy đẳng (`scripts/seed_production_reference.py`).
- **Dịch vụ môi trường phát triển**: Backend port 8000 hoạt động, Frontend port 3000 hoạt động, Dev PostgreSQL/Redis container hoạt động, Dev Tunnel hoạt động.

---

## 8. Next Exact Task (Công việc chính xác tiếp theo)

- **Phase 9C-D — GitHub Release & CI Verification**:
  - Người dùng rà soát báo cáo vệ sinh mã nguồn, thực hiện commit và push Git lên repository chính thức.
  - Kích hoạt và kiểm chứng hệ thống GitHub Actions CI cho cả Backend (Alembic check, pytest, Docker prod build, security boundaries) và Frontend (Node 22, npm ci, build verification).
  - Chuẩn bị tiếp nhận thông số hạ tầng từ xa để tiến hành **Phase 9C-D Slice 2 — Remote Deployment**.
