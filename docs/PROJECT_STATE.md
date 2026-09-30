# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Phase 9 — Workers + Optimization + Deploy**

---

## 2. Current Task (Công việc hiện tại)
**PostgreSQL Production Backup & Restore Tooling Readiness (Direct Mode, Version Gate, Dynamic Restore Verification - Phase A Complete; Verified Locally, Production Not Mutated / Not Deployed)**
*Parent Task*: Phase 9C-D Release Verification & Disaster Recovery Readiness
*Deployment State*: LIVE PRODUCTION DEPLOYED ON RAILWAY (BACKUP TOOLING IMPLEMENTED & VERIFIED LOCALLY; PRODUCTION NOT MUTATED)

---

## 3. Status (Trạng thái)
**LOCAL WORKSPACE IMPLEMENTED / VERIFIED — DIRECT CONNECTION TOOLING & TESTS COMPLETE (15/15 BACKUP TESTS PASS, LOCAL DRILL 100% PASS, PRODUCTION NOT MUTATED / NOT DEPLOYED)**

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

- **PostgreSQL Production Backup Tooling Readiness Pass (Direct Mode, Version Gate & Dynamic Restore Verification)** (LOCAL WORKSPACE VERIFIED — NOT DEPLOYED):
  - Mở rộng `scripts/db_backup.py` hỗ trợ chế độ kết nối trực tiếp native (`--direct`, `--host`, `--port`, `--user`, `--dbname`, biến môi trường chuẩn `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGPASSWORD`) tương thích hoàn toàn với Railway tunnel (`railway connect postgres --tunnel-only -P 15432`).
  - Bảo toàn 100% tương thích ngược với chế độ Docker Compose mặc định.
  - Tích hợp cổng kiểm tra phiên bản PostgreSQL (Version Gate): đối soát `server_version` và `pg_dump --version`, chặn cứng lỗi nếu `pg_dump < server_major`, cảnh báo rõ ràng nếu `pg_dump > server_major`.
  - Phân tích và ban hành quyết định snapshot nhất quán: số lượng bản ghi `row_counts` là ảnh chụp thông tin (`informational snapshot`), không dùng làm hard failure làm sai lệch kết quả sao lưu khỏe mạnh khi production có ghi đồng thời; bảo toàn các hard gate kiểm chứng (schema, 100% bảng, Alembic head, TOC, SHA-256).
  - Khắc phục triệt để logic restore-drill: đọc toàn bộ mốc kỳ vọng động từ manifest, TUYỆT ĐỐI KHÔNG truy vấn source database trong quá trình diễn tập; hỗ trợ target trực tiếp cô lập; dọn dẹp an toàn sau drill.
  - Xử lý bảo mật: mật khẩu chỉ truyền qua `PGPASSWORD` trong process environment, tuyệt đối không lộ trong CLI args, log hay manifest.
  - Bộ kiểm thử tự động 15/15 tests (`tests/test_db_backup.py`) PASS; diễn tập end-to-end cục bộ thành công 100% (backup, verify, restore-drill).
- **P2 Public API Security Hardening Pass** (LOCAL WORKSPACE VERIFIED — NOT DEPLOYED):
  - **Daily Needs Rate Limiting**: Tái sử dụng bộ hạn mức Class C (`rate_limit_user_profile`, 60 req/60s theo Client IP) gắn vào endpoint công khai `GET /api/v1/daily-needs/users/{user_id}/today`; bảo vệ tuyệt đối chống quét dò nhật ký sinh viên theo dải `user_id`; bảo toàn trạng thái công khai không yêu cầu token, giữ nguyên cấu trúc phản hồi DTO và chuẩn hóa `429 Too Many Requests` kèm `Retry-After`.
  - **Auction WebSocket Connection Hardening**: Gia cố route `WS /ws/auctions/{auction_id}` trước khi `accept`: thẩm định tính hợp lệ của `auction_id > 0`, kiểm tra sự tồn tại trong CSDL và xác thực trạng thái phiên đấu giá hợp lệ nhận sự kiện thời gian thực (`status` thuộc `SCHEDULED`, `ACTIVE`). Mọi yêu cầu không hợp lệ, không tồn tại hoặc không ở trạng thái hoạt động (như `CANCELLED`, `ENDED`) đều bị đóng/từ chối tức thì với mã đóng WebSocket `1008` (Policy Violation), hoàn toàn không được lưu trữ trong `AuctionConnectionManager` và không tạo tác vụ Redis pub/sub listener rò rỉ.
  - **Client/IP WebSocket Limit Audit**: Kiểm toán connection manager cho thấy kiến trúc sử dụng `set[WebSocket]` tự hủy rò rỉ theo vòng đời kết nối. Báo cáo giới hạn kỹ thuật: không thể áp dụng hạn mức kết nối per-IP tùy tiện trên WebSocket do kiến trúc proxy đa tầng (Cloudflare + Railway Envoy) và đặc thù mạng NAT trường học/ký túc xá (hàng trăm sinh viên dùng chung 1 IP public IPv4).
  - Kiểm thử: 897/897 backend pytest tests PASS (bao gồm 22/22 rate limiter tests, 6/6 auction websocket hardening tests, 55/55 auction suite tests, 29/29 daily needs tests).
- **P1 Public API Security Remediations Pass** (LOCAL WORKSPACE VERIFIED — NOT DEPLOYED):
  - **Finding-01 (Public Reviews Rate Limiting)**: Gắn `rate_limit_user_profile` (Class C Sensitive Public, 60 req/60s theo Client IP) vào route `GET /api/v1/users/{user_id}/reviews`, triệt tiêu lỗ hổng active-user enumeration oracle; bảo toàn tuyệt đối truy cập công khai không yêu cầu token và chuẩn hóa phản hồi `429 Too Many Requests` kèm `Retry-After`.
  - **Finding-02 (Omit Internal Role from Public Profile)**: Loại bỏ triệt để trường `role` khỏi `PublicUserProfileResponse` backend DTO và `get_public_profile` service; cập nhật frontend `PublicProfilePage` hiển thị huy hiệu cộng đồng chuẩn "Thành viên Chợ PTITers" không rẽ nhánh theo role nội bộ; bảo toàn trường `role` trong `UserResponse` cho authenticated current user (`/users/me`) và toàn bộ logic phân quyền Admin backend.
  - **Finding-04 (Disable OpenAPI/Swagger in Production)**: Cấu hình `docs_url=None`, `redoc_url=None`, `openapi_url=None` khi `ENVIRONMENT == "production"`; trả về `404 Not Found` trên production, bảo toàn khả năng truy cập `/docs`, `/redoc`, `/openapi.json` (`200 OK`) trên development và test; không ảnh hưởng các route nghiệp vụ và healthcheck.
  - Kiểm thử: 890/890 backend pytest tests PASS (bao gồm 21/21 rate limiter tests, 14/14 reviews tests, 15/15 user profile tests, 2/2 OpenAPI config tests, 95/95 auth/admin tests); frontend build `tsc -b && vite build` PASS; 30/30 frontend hardening tests PASS.
- **Production Security Hardening Pass — Anti-Scraping, Request Rate Limiting & User Enumeration Defense** (LOCAL WORKSPACE VERIFIED — NOT DEPLOYED):
  - Triển khai `app.core.rate_limiter` trên Redis với thuật toán Atomic Fixed-Window Counter qua Lua Script, hỗ trợ `Retry-After` và HTTP 429 chuẩn tắc.
  - Phân tầng hạn mức đa lớp: Emergency flood ceiling (3.000 req/60s per IP - sized for 100+ concurrent students on shared campus NAT/CGNAT, không phải bộ lọc chống cào chính), Public browsing (120 req/60s), Sensitive public profile (60 req/60s), Authenticated search & candidates (30 req/60s theo `user_id`), Write mutations (30 req/60s theo `user_id`), Chat messages (60 req/60s theo `user_id`), Auth sensitive (20 req/60s theo `user_id`). Healthcheck `/health` và static docs hoàn toàn không bị hạn chế.
  - Khắc phục Blocker 1 (Railway / Cloudflare Client IP Trust): Thẩm định nút mạng kết nối vào Railway trực tiếp qua header `X-Real-IP` do Railway ghi nhận đối soát với dải CIDR Cloudflare chính thức (`CLOUDFLARE_NETWORKS`), không phụ thuộc vào giả định `X-Forwarded-For`. Khi gọi trực tiếp vào Railway origin, `CF-Connecting-IP` giả mạo bị loại bỏ hoàn toàn và hạn mức trói buộc vào chính `X-Real-IP`.
  - Khắc phục Blocker 2 (Global Campus NAT Quota): Nâng ngưỡng lũ lụt khẩn cấp lên 3.000 req/60s per IP, bảo đảm cô lập trọn vẹn quota authenticated theo `user_id` và không làm nghẽn mạng các sinh viên dùng chung Wi-Fi/CGNAT ký túc xá.
  - Chính sách chịu lỗi Fail-Open: Redis timeout/lỗi kết nối không làm crash ứng dụng hay chặn sinh viên.
  - Kiểm toán quyền riêng tư: Xác nhận `PublicUserProfileResponse` không rò rỉ email/bank/provider UID, số điện thoại tuân thủ nghiêm ngặt cờ `show_phone_publicly`.
  - Bộ kiểm thử an ninh chuyên biệt 20/20 tests (`tests/test_rate_limiter.py`) PASS; bao phủ toàn diện 7 ca kiểm thử Client IP trust theo chuẩn tài liệu chính thức, spoofing defense và campus NAT volume.
- **First Production ADMIN Bootstrap** (CONFIRMED BY OPERATOR):
  - Khởi tạo và thăng cấp tài khoản Quản trị viên đầu tiên hoàn thành và được xác nhận trên môi trường Railway production bằng công cụ chuẩn tắc `scripts/promote_admin.py` kết nối trực tiếp CSDL Railway PostgreSQL.
- **Phase 9C-D — Railway Production Deployment & Service Verification** (CONFIRMED BY OPERATOR):
  - Frontend (`student-marketplace-fe`) và Backend (`student-marketplace-be`) đã được triển khai trực tiếp trên Railway.
  - Cả hai domain công khai đã hoạt động; endpoint `/health` backend xác nhận kết nối CSDL và Redis thành công.
  - Tích hợp credentials `FIREBASE_CREDENTIALS_JSON` không ghi file đĩa, bảo đảm an toàn bảo mật tuyệt đối.

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

- **Backend Full Suite**: **906/906 PASS** (`pytest tests/ -q`, 0 failures, 10 warnings).
- **Backend Backup & Restore Tooling Suite**: **15/15 PASS** (`tests/test_db_backup.py`).
- **Backend Rate Limiter Security Suite**: **22/22 PASS** (`tests/test_rate_limiter.py`).
- **Backend Auction WebSocket Hardening Suite**: **6/6 PASS** (`tests/test_auctions_websocket_hardening.py`).
- **Backend Daily Needs Suite**: **29/29 PASS** (`tests/test_daily_needs.py`).
- **Backend Reviews Suite**: **14/14 PASS** (`tests/test_reviews.py`).
- **Backend User Profile Suite**: **15/15 PASS** (`tests/test_user_profile.py`).
- **Backend OpenAPI Production Configuration Suite**: **2/2 PASS** (`tests/test_openapi_config.py`).
- **Backend Auth & Admin Authorization Suite**: **95/95 PASS** (`tests/test_auth.py`, `tests/test_admin_user_enforcement.py`, `tests/test_admin_reports.py`, `tests/test_admin_product_enforcement.py`).
- **Backend Hardening Suite**: **11/11 PASS** (`tests/test_official_support_and_profile_validation.py`).
- **Backend Conversations Regression Suite**: **58/58 PASS** (`tests/test_conversations_social_and_groups.py`, `tests/test_conversations_phase7c.py`, `tests/test_group_mention_notifications.py`).
- **Backend GitHub Actions Release Gate**: **SUCCESS** (`Backend CI & Release Gate`, `Backend Test Suite & Alembic Verification`, `Production Docker Build & Artifact Hardening Gate`).
- **Frontend GitHub Actions Build Gate**: **SUCCESS** (`Frontend CI & Build Gate`, `Frontend Typecheck & Production Build`).
- **Production Endpoint Health**: `/health` endpoint trên Railway trả về HTTP 200 `{"status": "healthy", "database": "up", "redis": "up", "service": "up"}`.
- **Alembic State**: Head `f1a2b3c4d5e6`, 0 schema drift (`alembic check` clean, 0 new migrations).
- **Cơ sở dữ liệu vật lý**: 32 bảng nghiệp vụ + 1 bảng metadata (`alembic_version`) = 33 bảng vật lý.
- **Firebase Credentials Tests**: 7/7 PASS (`tests/test_firebase.py`).
- **Frontend Hardening & Acceptance Suite**: **30/30 PASS** (`node src/__tests__/post_deployment_hardening.test.mjs`).
- **Frontend ESLint Baseline**: **0 errors**, 80 historical warnings (`npm run lint`).
- **Frontend Production Build**: `tsc -b && vite build` PASS (0 errors).

---

## 9. Next Exact Task (Công việc chính xác tiếp theo)

- **Phase 9C-D Slice 2 — Production Data Bootstrap & Release Verification**:
  1. Thực thi nạp 10 danh mục tham chiếu trên Railway PostgreSQL: `python -m scripts.seed_production_reference`.
  2. Triển khai dịch vụ Background Worker (`python -m app.workers.order_auto_cancel`) độc lập trên Railway kết nối Railway PostgreSQL và Redis.
  3. Kiểm tra và xác nhận cấu hình Firebase Authorized Domains trên Firebase Console cho domain frontend production.
  4. Diễn tập kiểm thử thông luồng (Smoke Test) trực tiếp trên môi trường Railway live và xác thực quy trình sao lưu.
