# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Phase 9 — Workers + Optimization + Deploy**

---

## 2. Current Task (Công việc hiện tại)
**Phase 9C-D Slice 2 — Railway Production Live Environment & Release Readiness**
*Parent Task*: Phase 9C-D — CI / Deployment
*Deployment State*: LIVE PRODUCTION DEPLOYED (OPERATOR CONFIRMED)

---

## 3. Status (Trạng thái)
**LIVE PRODUCTION DEPLOYED — OPERATIONAL VERIFICATION & READINESS AUDIT**

---

## 4. Production Environment (Môi trường Sản xuất Live trên Railway)

- **Platform**: Railway (Project: `choptiters`)
- **Frontend Service**:
  - Dịch vụ: `student-marketplace-fe`
  - Production URL: `https://student-marketplace-fe-production.up.railway.app`
  - Trạng thái triển khai: React + TypeScript + Vite, production build thành công, server runtime chạy `npm run start` (`serve --single --listen $PORT dist`), lắng nghe cổng container qua `$PORT` (8080), domain công khai đã được cấp phát và truy cập ổn định.
- **Backend Service**:
  - Dịch vụ: `student-marketplace-be`
  - Production URL: `https://student-marketplace-be-production.up.railway.app`
  - Trạng thái triển khai: FastAPI + Uvicorn runtime qua `$PORT`, migration tiền triển khai tự động `alembic upgrade head`.
  - Trạng thái sức khỏe: Endpoint `/health` công khai đã được xác nhận hoạt động bình thường (`status: healthy`, `database: up`, `redis: up`, `service: up`).
- **Data Infrastructure (Hạ tầng Dữ liệu Sản xuất)**:
  - **Railway PostgreSQL**: CSDL PostgreSQL được quản lý trên Railway, là nguồn dữ liệu chuẩn xác duy nhất (persistent production source of truth) của môi trường sản xuất. **TUYỆT ĐỐI KHÔNG PHẢI là local Docker PostgreSQL**.
  - **Railway Redis**: Redis được quản lý trên Railway, kết nối qua `REDIS_URL` / mạng nội bộ Railway. **TUYỆT ĐỐI KHÔNG PHẢI là local Docker Redis**.
- **Backend Production Integrations**:
  - Firebase Admin SDK: Khởi tạo an toàn từ biến môi trường `FIREBASE_CREDENTIALS_JSON`.
  - Cloudinary: Cấu hình credentials sản xuất hoạt động (namespace `student-marketplace/prod/`).
  - Backend Production CORS: Cấu hình cho frontend production origin dưới dạng JSON-array Pydantic:
    `BACKEND_CORS_ORIGINS = ["https://student-marketplace-fe-production.up.railway.app"]`.

### Ranh giới Môi trường & Bản chất các Thao tác (Environment & Operation Boundaries)

Local Docker (`sm_api`, `sm_postgres`, `sm_redis`, `sm_worker`) duy trì vai trò môi trường dev/test cô lập cục bộ. Các lệnh thực thi trong `sm_api`, `localhost`, local PostgreSQL/Redis, hoặc local `.venv` **TUYỆT ĐỐI KHÔNG tác động lên Railway production** trừ khi được cấu hình tường minh kết nối production.

Mọi coding agent bắt buộc phải phân biệt rạch ròi 6 thao tác:

- **A. SOURCE CODE CHANGE (Thay đổi mã nguồn)**: Chỉnh sửa mã nguồn chỉ thay đổi working tree cục bộ trên máy phát triển.
- **B. GIT PUSH / DEPLOYMENT (Phát hành mã nguồn)**: Mã nguồn chỉ đến Railway khi commit được push lên GitHub và dịch vụ Railway build & deploy thành công commit đó.
- **C. DATABASE DATA MUTATION (Thay đổi dữ liệu CSDL)**: Lệnh CSDL chỉ tác động lên database mà tiến trình đó kết nối tới. Cập nhật dữ liệu cục bộ **KHÔNG TỰ ĐỘNG** đồng bộ sang Railway PostgreSQL.
- **D. MIGRATION (Di trú Schema)**: `alembic upgrade head` chỉ thay đổi cấu trúc bảng trên CSDL mà tiến trình nhắm tới.
- **E. BUILD-TIME FRONTEND CONFIG (Cấu hình Frontend lúc đóng gói)**: Biến `VITE_*` được nhúng tĩnh (inlined) vào bundle khi build `tsc -b && vite build`. Thay đổi biến môi trường frontend bắt buộc phải re-build và re-deploy container frontend thì trình duyệt mới nhận giá trị mới.
- **F. BACKEND RUNTIME CONFIG (Cấu hình Backend lúc thực thi)**: Biến môi trường Railway backend được inject vào container lúc runtime và cần container restart/redeploy để có hiệu lực.

### Admin Bootstrap Environment Note (Lưu ý Môi trường khi Khởi tạo Quản trị viên)

- Lệnh hỗ trợ chuẩn tắc: `python -m scripts.promote_admin --email <email>`
- Chạy `docker exec sm_api python -m scripts.promote_admin ...` CHỈ tác động lên CSDL cục bộ `sm_postgres`.
- Để thăng cấp tài khoản trên Railway Production: Script phải được chạy trong tiến trình kết nối với Railway PostgreSQL (ví dụ: qua tab Shell/Console của dịch vụ `student-marketplace-be` trên Railway dashboard).
- Điều kiện tiên quyết: Người dùng phải đăng nhập Google lần đầu trên frontend production để tạo bản ghi tài khoản `ACTIVE` trong PostgreSQL trước khi chạy lệnh.
- Tuyệt đối không hardcode email admin trong mã nguồn, migrations hay rules.

---

## 5. Release Readiness Checklist (Bảng Kiểm Soát Sẵn Sàng Phát Hành)

> Quy ước trạng thái: Chỉ sử dụng `CONFIRMED`, `TODO`, `UNKNOWN`.

### CONFIRMED (Đã Xác Nhận Hoạt Động Trên Production)
- [x] **Railway PostgreSQL**: Đã cấp phát và trực tuyến (online).
- [x] **Railway Redis**: Đã cấp phát và trực tuyến (online).
- [x] **Railway Backend (`student-marketplace-be`)**: Đã deploy thành công.
- [x] **Backend Health Check**: Endpoint `/health` công khai xác nhận `healthy` (`db: up`, `redis: up`).
- [x] **Railway Frontend (`student-marketplace-fe`)**: Đã deploy thành công.
- [x] **Frontend Public Domain**: `https://student-marketplace-fe-production.up.railway.app` hoạt động.
- [x] **Backend Public Domain**: `https://student-marketplace-be-production.up.railway.app` hoạt động.
- [x] **Backend Production CORS**: Đã cấu hình chấp nhận domain frontend production (`["https://student-marketplace-fe-production.up.railway.app"]`).
- [x] **Firebase Admin Backend Integration**: Khởi tạo thành công từ `FIREBASE_CREDENTIALS_JSON`.
- [x] **Cloudinary Backend Integration**: Cấu hình credentials sản xuất hoạt động.
- [x] **Frontend VITE Production Variables**: Đã cấu hình và đóng gói vào build artifact.
- [x] **First Production ADMIN Bootstrap**: Khởi tạo và thăng cấp tài khoản Quản trị viên đầu tiên đã hoàn thành và được xác nhận trên môi trường Railway production (First production ADMIN bootstrap completed and verified).

### TODO (Chưa Thực Hiện Trên Production)
- [ ] **Production Reference Seed**: Thực thi nạp 10 danh mục chuẩn tắc trên Railway PostgreSQL (`python -m scripts.seed_production_reference`).
- [ ] **Production Background Worker Deployment**: Triển khai dịch vụ worker độc lập (`python -m app.workers.order_auto_cancel`) trên Railway.
- [ ] **Production Backup Verification**: Diễn tập và xác thực sao lưu trên Railway PostgreSQL.

### UNKNOWN / TODO (Cần Xác Minh Thủ Công)
- [ ] **Firebase Authentication Authorized Domains**: Chưa có bằng chứng trong repo xác nhận domain `student-marketplace-fe-production.up.railway.app` đã được thêm vào danh sách Authorized Domains trên Firebase Console. Cần người vận hành kiểm tra trên Firebase Console.

---

## 6. Recently Completed (Các công việc vừa hoàn thành)

- **First Production ADMIN Bootstrap** (CONFIRMED BY OPERATOR):
  - Khởi tạo và thăng cấp tài khoản Quản trị viên đầu tiên hoàn thành và được xác nhận trên môi trường Railway production bằng công cụ chuẩn tắc `scripts/promote_admin.py` kết nối trực tiếp CSDL Railway PostgreSQL.
- **Phase 9C-D — Railway Production Deployment & Service Verification** (CONFIRMED BY OPERATOR):
  - Frontend (`student-marketplace-fe`) và Backend (`student-marketplace-be`) đã được triển khai trực tiếp trên Railway.
  - Cả hai domain công khai đã hoạt động; endpoint `/health` backend xác nhận kết nối CSDL và Redis thành công.
  - Tích hợp credentials `FIREBASE_CREDENTIALS_JSON` không ghi file đĩa, bảo đảm an toàn bảo mật tuyệt đối.
- **Phase 9C-D — Minimal Railway-Compatible Firebase Credentials Support** (COMPLETED & VERIFIED):
  - Bổ sung cấu hình `FIREBASE_CREDENTIALS_JSON` trong `Settings`, ưu tiên JSON trực tiếp cho Railway, bảo toàn 100% đường dẫn tệp cục bộ (`FIREBASE_CREDENTIALS_PATH`).
  - Viết suite kiểm thử 7/7 tests (`tests/test_firebase.py`) bao phủ đầy đủ kịch bản phân giải, ưu tiên và xử lý lỗi không lộ secret.
- **Phase 9C-D — GitHub Release & CI Verification** (COMPLETED & VERIFIED / USER ACCEPTED):
  - Toàn bộ release gates trên GitHub Actions của cả Backend và Frontend đạt `SUCCESS`.
- **Phase 9C-D — Release Candidate Hygiene & Production Data Preparation** (USER ACCEPTED / COMPLETED & VERIFIED):
  - Vệ sinh toàn diện repository: Triệt tiêu code debug, bảo toàn 100% tài nguyên Cloudinary legacy, chuẩn bị scripts quản trị sạch.

---

## 7. Active Decisions (Quyết định kiến trúc đang hiệu lực)

- **Mục tiêu Triển khai Public-Beta Trực tiếp trên Railway (Project "choptiters")**:
  - Dịch vụ Frontend và Backend hiện tại đều được triển khai trực tiếp trên nền tảng đám mây quản lý Railway (PaaS).
  - Vercel vẫn là tùy chọn Edge CDN khả dụng trong tương lai khi có nhu cầu tối ưu phân phối static assets.
- **Bảo toàn Lộ trình Triển khai Chuẩn (VPS Architecture Preservation)**:
  - Railway là mục tiêu vận hành (operational target), không làm thay đổi thiết kế kiến trúc hệ thống.
  - Tệp `docker-compose.prod.yml` và cấu hình container hardening được giữ nguyên vẹn để phục vụ di trú sang VPS độc lập về sau.
- **Chiến lược Khởi tạo Cơ sở Dữ liệu Production & Di trú Tường minh**:
  - CSDL Railway PostgreSQL khởi tạo sạch hoàn toàn; không sao chép dữ liệu test từ dev.
  - Di trú tường minh: `alembic upgrade head` được cấu hình dạng pre-deploy command trên Railway.
  - Nạp dữ liệu tham chiếu: Chạy script `python -m scripts.seed_production_reference` nạp 10 danh mục chuẩn tắc.
- **Quy trình Khởi tạo Quản trị viên Đầu tiên (First Admin Bootstrap)**:
  - Người vận hành đăng nhập lần đầu qua Google/Firebase Auth trên frontend production để tạo bản ghi `ACTIVE`.
  - Thực thi CLI `python -m scripts.promote_admin --email <admin_email>` trên Railway backend console.
- **Quy trình Phê duyệt Tin đăng Tiền xuất bản (Pre-Publication Product Approval)**:
  - Mọi tin đăng mới bắt buộc qua kiểm duyệt Admin trước khi công khai.
- **Dọn dẹp Thông báo Cá nhân (Notification Hard-Delete Inbox Cleanup)**:
  - Hỗ trợ vuốt phải trực tiếp trên mobile; xóa thông báo không ảnh hưởng thực thể nghiệp vụ tham chiếu.
- **Hợp đồng Nhật ký & Marquee Trang chủ (Real-Data Daily Journal & Continuous Marquee Contract)**:
  - `GET /api/v1/daily-needs/recent` (limit clamp 1..10) phục vụ marquee trang chủ; backend không tạo dữ liệu giả.

---

## 8. Verification Baseline (Đường cơ sở kiểm thử)

- **Backend Full Suite**: **849/849 PASS** (`pytest tests/ -q` in 165.85s).
- **Backend GitHub Actions Release Gate**: **SUCCESS** (`Backend CI & Release Gate`, `Backend Test Suite & Alembic Verification`, `Production Docker Build & Artifact Hardening Gate`).
- **Frontend GitHub Actions Build Gate**: **SUCCESS** (`Frontend CI & Build Gate`, `Frontend Typecheck & Production Build`).
- **Production Endpoint Health**: `/health` endpoint trên Railway trả về HTTP 200 `{"status": "healthy", "database": "up", "redis": "up", "service": "up"}`.
- **Alembic State**: Head `4414f46b5404`, 0 schema drift (`alembic check` clean).
- **Cơ sở dữ liệu vật lý**: 32 bảng nghiệp vụ + 1 bảng metadata (`alembic_version`) = 33 bảng vật lý.
- **Firebase Credentials Tests**: 7/7 PASS (`tests/test_firebase.py`).
- **Frontend Acceptance Suite**: **14/14 PASS** (`node src/__tests__/pre_deployment_acceptance_fixes.test.mjs`).
- **Frontend Production Build**: `tsc -b && vite build` PASS (0 errors).

---

## 9. Next Exact Task (Công việc chính xác tiếp theo)

- **Phase 9C-D Slice 2 — Production Data Bootstrap & Release Verification**:
  1. Thực thi nạp 10 danh mục tham chiếu trên Railway PostgreSQL: `python -m scripts.seed_production_reference`.
  2. Triển khai dịch vụ Background Worker (`python -m app.workers.order_auto_cancel`) độc lập trên Railway kết nối Railway PostgreSQL và Redis.
  3. Kiểm tra và xác nhận cấu hình Firebase Authorized Domains trên Firebase Console cho domain frontend production.
  4. Diễn tập kiểm thử thông luồng (Smoke Test) trực tiếp trên môi trường Railway live và xác thực quy trình sao lưu.
