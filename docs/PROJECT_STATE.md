# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Phase 9 — Workers + Optimization + Deploy**

---

## 2. Current Task (Công việc hiện tại)
**Phase 9C-D Slice 2 — Remote Deployment**
*Parent Task*: Phase 9C-D — CI / Deployment
*Deployment State*: READY FOR INFRASTRUCTURE PROVISIONING

---

## 3. Status (Trạng thái)
**READY FOR INFRASTRUCTURE PROVISIONING**

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

- **Kiến trúc Triển khai Khái niệm (Conceptual Deployment Architecture)**:
  - **Frontend**: Triển khai trên **Vercel** kết nối repository `student-marketplace-fe`, tự động build & deploy khi có commit mới.
  - **Backend**: Ban đầu triển khai trên **một máy chủ VPS sản xuất (one production VPS initially)**. Không gắn cứng nhà cung cấp VPS cụ thể trong kiến trúc chuẩn (lựa chọn nhà cung cấp thuộc phạm vi vận hành).
  - **Các dịch vụ vận hành trên VPS**:
    1. Reverse Proxy / HTTPS termination
    2. FastAPI API (`student-marketplace-be:prod`)
    3. Background Worker (`order_auto_cancel`)
    4. PostgreSQL
    5. Redis
  - **Dịch vụ Đám mây Bên ngoài (External Providers)**: Firebase Authentication (xác thực người dùng), Cloudinary (lưu trữ media nhị phân theo namespace `student-marketplace/prod/`).
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

- **Chờ Cung cấp Thông số Hạ tầng Triển khai (Awaiting Infrastructure Provisioning)**:
  - Toàn bộ quy trình kiểm thử cục bộ, kiểm tra vệ sinh phát hành và kiểm chứng CI trên GitHub Actions đã hoàn tất thành công 100%.
  - Hệ thống đang ở trạng thái sẵn sàng triển khai (`READY FOR INFRASTRUCTURE PROVISIONING`). Chờ người dùng/vận hành cung cấp thông số hạ tầng máy chủ thực tế (VPS IP, domain DNS, TLS certificate, production secrets).
  - Tuyệt đối không tự tiện bịa đặt VPS IP, domain, chứng chỉ TLS, production secrets hay deployed URLs khi chưa có thông số thực tế.
- **Hệ thống Đạt Trạng thái Tối ưu**: Toàn bộ **842/842 tests backend** vượt qua, frontend build thành công không lỗi (0 errors), Alembic 0 schema drift ở head `4414f46b5404`, CSDL duy trì 32 bảng ứng dụng + 1 bảng `alembic_version` = 33 bảng vật lý.

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

- **Phase 9C-D Slice 2 — Remote Deployment**:
  - Tiếp nhận thông số máy chủ VPS sản xuất (IP, SSH access, OS user) và tên miền từ người dùng.
  - Cấu hình hạ tầng trên VPS: Reverse proxy (Nginx/Caddy) với HTTPS tự động, mạng Docker nội bộ, khởi chạy Production Docker Compose (`api`, `worker`, `postgres`, `redis`).
  - Thiết lập triển khai Frontend trên Vercel: Cấu hình biến môi trường kết nối API domain backend và Firebase.
  - Thực thi di trú cơ sở dữ liệu sản xuất sạch (`alembic upgrade head`) và nạp danh mục tham chiếu (`python -m scripts.seed_production_reference`).
  - Hướng dẫn bootstrap tài khoản Quản trị viên đầu tiên (`python -m scripts.promote_admin --email <admin_email>`).
  - Diễn tập kiểm thử thông luồng (Smoke Test) trực tiếp trên môi trường sản xuất từ xa.
