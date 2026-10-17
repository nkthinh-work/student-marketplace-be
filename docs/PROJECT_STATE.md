# TRẠNG THÁI DỰ ÁN (PROJECT STATE) — Marketplace C2C Sinh viên

> **Vai trò tài liệu**: Bộ nhớ ngắn hạn (Short-Term Memory) cho coding agent, tập trung vào trạng thái hiện tại, các quyết định đang hiệu lực và bước đi tiếp theo. Lịch sử chi tiết xem tại `PROJECT_HISTORY.md` và `QUERY_INDEX_AUDIT.md`.

---

## 1. Current Phase (Giai đoạn hiện tại)
**Production Hotfix & Stabilization (Tutorial Video Upload, CORS, Security ?token= Elimination, Concurrent 401 Refresh, Notification Sound Hardening, Web Push Notification) — IMPLEMENTED — AWAITING USER ACCEPTANCE**

---

## 2. Current Task (Công việc hiện tại)
1. **P0 Tutorial Video Upload Timeout & Progress Feedback**:
   - *Status*: IMPLEMENTED & LOCALLY VERIFIED; AWAITING USER MANUAL ACCEPTANCE.
   - *Issue*: Video replacement (`13248.mp4`, ~12.8 MB) hung indefinitely (>30s) on production due to missing upload timeouts, lack of upload progress feedback, and potential thread lock with SpooledTemporaryFile.
   - *Resolution*: Dedicated 180s timeout for video upload on both Axios and Cloudinary SDK; thread-safe `io.BytesIO` buffer stream; visual progress percentage (`Đang tải lên... X%`) and processing status (`Đang xử lý video...`); explicit HTTP 502/503 mapping; query cache invalidation on error/timeout.
2. **P0 Production Domain & CORS Hardening**:
   - *Status*: IMPLEMENTED & LOCALLY VERIFIED; AWAITING USER MANUAL ACCEPTANCE.
   - *Issue*: Railway CORS variable formatting risk when adding custom production domains (`choptiters.id.vn`).
   - *Resolution*: Upgraded `assemble_cors_origins` validator in `app/core/config.py` to parse JSON array strings, comma-separated lists, and strip whitespace.
3. **P0 Security & Sensitive Files**:
   - *Status*: IMPLEMENTED & LOCALLY VERIFIED; AWAITING USER MANUAL ACCEPTANCE.
   - *Resolution*: Excluded `production_backups/`, `*.dump`, `service-account*.json` in `.dockerignore`. Eliminated `?token=` query param from WebSocket `/ws/me` (switched to in-band `{"type": "AUTH"}`) and Admin feedback evidence video streaming (switched to header-authenticated `Blob` URL).
4. **P1 Concurrent 401 Token Refresh**:
   - *Status*: IMPLEMENTED & LOCALLY VERIFIED; AWAITING USER MANUAL ACCEPTANCE.
   - *Resolution*: Replaced race-prone `isRefreshing` boolean in `apiClient.ts` with single-flight shared Promise; shared refresh call across concurrent 401s; max 1 retry per request; account switch/logout safety.
5. **P0 Notification Sound & Multi-Tab Echo Hardening**:
   - *Status*: IMPLEMENTED & LOCALLY VERIFIED; AWAITING USER MANUAL ACCEPTANCE.
   - *Issue*: Chat incoming messages did not trigger sound chime; audio chimes played simultaneously in multiple tabs when events were broadcast.
   - *Resolution*: Hooked `playNotificationSound({ conversationId, isChatMessage: true })` inside `MESSAGE_CREATED` when `!isSelfEcho`; implemented multi-tab echo suppression with 600ms cooldown window via `localStorage: ptit_last_sound_timestamp`; active conversation foreground chime suppression; audio toggle persistence.
6. **P0 Web Push Notification (FCM Integration)**:
   - *Status*: IMPLEMENTED & LOCALLY VERIFIED; AWAITING USER MANUAL ACCEPTANCE.
   - *Issue*: Users missed order updates and chat messages when tabs were closed or in background.
   - *Resolution*: End-to-end Web Push system with `user_device_tokens` table (Alembic migration `c9d0e1f2a3b4` with `fcm_token TEXT`); authenticated endpoints `POST /api/v1/notifications/push/subscribe` and `/unsubscribe`; non-blocking worker thread push dispatch (`asyncio.to_thread` with 10s timeout) and concurrent member dispatch (`asyncio.gather`); automatic stale token cleanup; service worker `/firebase-messaging-sw.js` with duplicate suppression (`payload.notification` guard) and notification `tag` deduplication; polite UI banner with 7-day dismissal; settings toggle `WebPushToggle`.
7. **Pre-Production Audit (Final Hardening Gate)**:
   - *Status*: AUDITED & REMEDIATED — AWAITING USER ACCEPTANCE.
   - *Findings & Fixes*:
     - Backend FCM synchronous blocking eliminated via `asyncio.to_thread` with bounded 10s timeout; group chat push dispatch converted from sequential loop to concurrent `asyncio.gather`.
     - Service worker duplicate notification prevented by adding `payload.notification` guard in `firebase-messaging-sw.js` and setting `tag` in `WebpushNotification`.
     - `fcm_token` column upgraded from `VARCHAR(512)` to `TEXT` in model, migration `c9d0e1f2a3b4`, and `DB_v7.md` to prevent future token truncation crashes.
     - Cloudinary video upload timeout tightened to 150s (downstream < upstream Axios 180s), guaranteeing clean HTTP 502 handling without client-side abort race.
     - Railway pre-deploy requirement verified: Railway does NOT run migrations automatically without explicit Pre-deploy Command configured in Railway Dashboard.

---

## 3. Status (Trạng thái)
- **Production Hotfix & Stabilization (Pre-Production Audit Remediated)**: **IMPLEMENTED & AUDITED LOCALLY — AWAITING USER ACCEPTANCE** (Backend unit & push tests 5/5 PASS; Frontend unit & hardening tests 13/13 PASS; Frontend `npm run build` PASS with zero errors; `git diff --check` clean with 0 warnings/errors across both repositories).
- **Profile Navigation public_id Regression**: **IMPLEMENTED LOCALLY — AWAITING USER ACCEPTANCE** (Direct chat other participant, group chat member, user search, and message sender DTOs extended with `public_id: UUID` with zero N+1 queries; frontend `DirectInfoDrawer`, `GroupInfoDrawer`, `MessageBubble` updated to navigate strictly to `/users/${public_id}` with zero numeric fallback).
- **Security E-Lite & Chat Recall**: **USER ACCEPTED LOCALLY — PENDING RELEASE ACCEPTANCE**.

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
- **Backup & Retention Service (Dịch vụ Sao lưu & Lưu giữ Đám mây - Phase C Verified on Production)**:
  - Dịch vụ: `student-marketplace-backup` trên Railway, sử dụng image xây dựng từ `/Dockerfile.backup` (nền `postgres:18-alpine` client major 18 + Python 3 + boto3).
  - Biến kết nối CSDL: Tham chiếu Railway canonical `PGHOST=${{Postgres.PGHOST}}`, `PGPORT=${{Postgres.PGPORT}}`, `PGUSER=${{Postgres.PGUSER}}`, `PGPASSWORD=${{Postgres.PGPASSWORD}}`, `PGDATABASE=${{Postgres.PGDATABASE}}`.
  - Bộ lưu trữ từ xa: Cloudflare R2 bucket `choptiters-backups` (private, storage class `STANDARD`), xác thực qua dedicated scoped Object Read & Write token.
  - Lịch trình tự động: Cron `0 20 * * *` kích hoạt trên Railway.
  - Kiểm chứng sản xuất: Phiên sao lưu thật đầu tiên trên production đã hoàn thành thành công: `pg_dump` major 18 khớp server major 18, kiểm chứng toàn vẹn dump + manifest vượt qua, cả 2 đối tượng tải lên R2 thành công và khớp kích thước (`head_object`), chính sách retention hoàn tất an toàn.
  - Diễn tập ngoại vi: Diễn tập restore-from-R2 ngoại vi cục bộ tạm hoãn do image local bị xóa và DNS/pull Docker Hub gặp sự cố kết nối mạng phát triển; không ảnh hưởng tới vận hành production.
- **Backend Production Integrations**:
  - Firebase Admin SDK: Khởi tạo an toàn từ biến môi trường `FIREBASE_CREDENTIALS_JSON`.
  - Cloudinary: Cấu hình credentials sản xuất hoạt động (namespace `student-marketplace/prod/`).
  - Backend Production CORS: Cấu hình cho frontend production origin dưới dạng JSON-array Pydantic:
    `BACKEND_CORS_ORIGINS = ["https://student-marketplace-fe-production.up.railway.app"]`.

### 4.1. Monitoring-Lite Operator Guide (Hướng dẫn Vận hành Giám sát Tối giản)

- **Railway Healthcheck Path & Facts**:
  - Path: `/health`
  - Purpose: Deployment readiness gate, **KHÔNG PHẢI** là continuous uptime monitoring.
  - Hành vi chuẩn xác của Railway:
    - Khi có phiên bản triển khai mới (new deployment), Railway đợi nhận phản hồi HTTP 2xx từ `/health` trước khi kích hoạt container mới và chuyển traffic mạng sang.
    - Railway **KHÔNG** liên tục thăm dò (continuously monitor) endpoint này sau khi deployment đã vào trạng thái live.
    - Việc tiến trình sập/khởi động lại trong quá trình chạy (runtime crash/restart) được quản lý độc lập bởi cơ chế **Restart Policy** của container trên Railway, không phải do endpoint `/health`.
- **Backend Health Probe Contract (`GET /health`)**:
  - **A. PostgreSQL UP + Redis UP**: HTTP 200 `{"status": "healthy", "database": "up", "redis": "up", "service": "up"}`
  - **B. PostgreSQL UP + Redis DOWN**: HTTP 200 `{"status": "degraded", "database": "up", "redis": "down", "service": "up"}` (Redis là fail-open realtime dependency; sự cố Redis không làm nghẽn việc kích hoạt deployment).
  - **C. PostgreSQL DOWN hoặc DB probe timeout**: HTTP 503 `{"status": "unhealthy", "database": "down", "redis": "...", "service": "up"}` (PostgreSQL là persistent source of truth; Railway không được kích hoạt deployment mới nếu không kết nối được PostgreSQL).
  - **Guarantees**:
    - Bounded timeouts: PostgreSQL probe timeout = 2.0s (`asyncio.wait_for`), Redis probe timeout = 1.0s.
    - Zero secret leakage: Tuyệt đối không để lộ chi tiết exception, credentials, stack trace hay query trong payload JSON.
    - Rate-limit bypass: Bỏ qua rate limiting hoàn toàn qua Class A whitelist trong `RateLimitMiddleware`.
    - Thiết kế tối giản: Không phân tách `/live` và `/ready` phức tạp; giữ nguyên 1 endpoint duy nhất `/health`.
- **Production Runtime Monitoring (Giám sát Tiến trình Runtime)**:
  - Phương thức: Theo dõi trực tiếp Railway service/deployment logs và deployment state.
  - Vị trí: Railway Dashboard -> `student-marketplace-be` -> tab `Deployments` & `Logs`.
  - Điều tra lỗi 5xx: Lọc theo từ khóa `500` hoặc `ERROR`. Uvicorn access log ghi nhận method, path, HTTP status; Starlette/Uvicorn log traceback phía server; client nhận phản hồi an toàn `500 Internal Server Error`; tuyệt đối không log header `Authorization`, cookie, token Firebase hay request body.
- **Backup Monitoring (Giám sát Sao lưu Tự động)**:
  - Phương thức: Theo dõi lịch sử thực thi Railway cron execution/deployment history + process exit code + explicit SUCCESS/ERROR log markers.
  - Vị trí: Railway Dashboard -> `student-marketplace-backup` -> cron execution history -> tab `Logs`.
  - Tiêu chí thành công (SUCCESS): Tiến trình kết thúc với exit code `0` (Railway hiển thị badge xanh) và log chứa marker rõ ràng: `[OK] CHU TRÌNH SAO LƯU TỰ ĐỘNG HOÀN TẤT THÀNH CÔNG`.
  - Tiêu chí thất bại (FAILURE): Tiến trình kết thúc với exit code khác 0 (exit `1`, Railway hiển thị badge đỏ), retention bị hủy bỏ ngay lập tức để bảo vệ bản sao lưu cũ, và log chứa marker: `[!] LỖI THỰC THI (REMOTE BACKUP): <lỗi đã được che giấu secret>`.

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
- [x] **Production Database Backup Automation & Retention (Phase C)**: Dịch vụ `student-marketplace-backup` chạy `Dockerfile.backup` trên Railway với cron `0 20 * * *`; phiên sao lưu thật đầu tiên hoàn tất thành công (`pg_dump` major 18 khớp server 18, upload R2 STANDARD bucket `choptiters-backups`, xác thực remote size match, rolling retention hoàn tất); off-platform restore-from-R2 drill tạm hoãn cục bộ, không cản trở production.

### TODO (Chưa Thực Hiện Trên Production)
- [ ] **Production Reference Seed**: Thực thi nạp 10 danh mục chuẩn tắc trên Railway PostgreSQL (`python -m scripts.seed_production_reference`).
- [ ] **Production Background Worker Deployment**: Triển khai dịch vụ worker độc lập (`python -m app.workers.order_auto_cancel`) trên Railway.

### UNKNOWN / TODO (Cần Xác Minh Thủ Công)
- [ ] **Firebase Authentication Authorized Domains**: Chưa có bằng chứng trong repo xác nhận domain `student-marketplace-fe-production.up.railway.app` đã được thêm vào danh sách Authorized Domains trên Firebase Console. Cần người vận hành kiểm tra trên Firebase Console.

---

## 6. Recently Completed (Các công việc vừa hoàn thành)

- **Chat Recall & Media Hardening Pass** (LOCAL WORKSPACE VERIFIED — NOT DEPLOYED):
  - **Message Sender Recall**: Triển khai `DELETE /api/v1/conversations/{conversation_id}/messages/{message_id}` với kiểm tra xác thực người gửi (`message.sender_id == current_user.user_id`), từ chối SYSTEM message (`400`), non-leaking `404` cho tin nhắn/hội thoại không thuộc quyền truy cập, `403` cho thành viên khác, và xử lý lũy thừa an toàn khi tin nhắn đã thu hồi.
  - **Tombstone Sanitization**: Soft-delete giữ nguyên dòng `messages` (`is_deleted=True, content=None`) bảo toàn cây trả lời (`reply_to_message_id`), tóm tắt preview trả lời trở thành "Tin nhắn không còn khả dụng", làm sạch hoàn toàn `attachments=[]`, `mentions=[]`, `reactions=[]` trong phản hồi API.
  - **Durable Media Cleanup Queue (`media_cleanup_jobs`)**: Tạo bảng PostgreSQL bền vững lưu trữ hàng đợi dọn dẹp Cloudinary media với migration Alembic `b8c9d0e1f2a3_create_media_cleanup_jobs_table.py` (`uq_media_cleanup_jobs_storage_key_resource` và chỉ mục `ix_media_cleanup_jobs_next_retry`). DB commit quyết định trạng thái nghiệp vụ trước khi dọn dẹp ngoại vi (không rollback DB delete khi Cloudinary lỗi).
  - **Immediate Post-Commit Cleanup & Retry Worker**: Xóa Cloudinary tức thì sau commit ngoài luồng (`asyncio.to_thread`), gỡ bỏ job khi thành công; nếu lỗi giữ pending job để background worker định kỳ quét với thuật toán exponential backoff có chặn trên (1m, 5m, 15m, 1h, 6h, tối đa 24h) và xử lý `not found` coi như thành công.
  - **Chat Video Anti-Spam Quota**: Chặn đứng spam video TRƯỚC KHI upload Cloudinary: tối đa 1 video / tin nhắn (từ chối `422 Unprocessable Content` trước khi upload), hạn ngạch rolling quota Redis 5 video uploads / 600s / user (từ chối `429 Too Many Requests` trước khi upload, chính sách fail-open khi Redis gặp sự cố).
  - **Video-Safe Swipe-To-Reply**: Xây dựng wrapper `SwipeToReply` dùng Pointer Events đồng nhất, khóa hướng horizontal gesture lock (`dx > 12 && dx > dy * 1.2`), dịch chuyển tối đa 72px, ngưỡng kích hoạt 56px; đặc biệt bảo vệ vùng native controls ~56px dưới cùng của video HTML5 (play, pause, seek, volume, fullscreen hoạt động bình thường, vuốt ngang vùng video phía trên để trả lời).
  - **Fallback Action Menu**: Bổ sung nút "Trả lời" và "Thu hồi" trong desktop hover bar và context menu / reaction picker, đi kèm modal xác nhận thu hồi an toàn.
  - **Realtime MESSAGE_DELETED Invalidation**: Phát sự kiện tối giản `{"type": "MESSAGE_DELETED", "conversation_id": ..., "message_id": ...}` qua `/ws/me`, frontend tự động vô hiệu hóa cache và refetch authoritative REST API.
  - Kiểm thử: 16/16 backend tests chuyên biệt (`tests/test_chat_recall_and_media_hardening.py`) PASS; 967/967 full backend tests PASS; 11/11 targeted frontend tests PASS; frontend production build PASS; `alembic check` clean; `git diff --check` sạch 100%.
- **Phase D-Lite — Minimal Production Monitoring & Operational Visibility Pass** (LOCAL WORKSPACE VERIFIED — READY FOR MANUAL RAILWAY CONFIGURATION):
  - Bổ sung bounded timeout 2.0s cho probe CSDL PostgreSQL trong `GET /health` (`asyncio.wait_for(..., timeout=2.0)`), đồng bộ với timeout 1.0s của Redis; đảm bảo `/health` phản hồi tức thì và không bị nghẽn (hang) khi mạng CSDL gặp sự cố.
  - Chuẩn hóa ngữ nghĩa Railway deployment readiness gate: `/health` trả về HTTP 200 `healthy` khi cả DB và Redis sẵn sàng; HTTP 200 `degraded` khi Redis gặp sự cố (bảo đảm tính năng fail-open của Redis không chặn việc kích hoạt deployment backend); và HTTP 503 `unhealthy` khi PostgreSQL down hoặc probe timeout (ngăn Railway kích hoạt deployment mới không thể kết nối tới cơ sở dữ liệu chính).
  - Đính chính thực tế Railway healthcheck: Railway Healthcheck Path đóng vai trò cổng kiểm tra sẵn sàng khi triển khai (deployment readiness gate) trước khi trỏ lưu lượng mạng, KHÔNG thăm dò liên tục để tự động restart container khi đã live; restart process runtime do Restart Policy container quyết định độc lập.
  - Kiểm toán ghi log 5xx và an toàn thông tin: Xác nhận Uvicorn access log và ASGI exception logger đáp ứng đầy đủ yêu cầu điều tra mà không trùng lặp; không để lộ header `Authorization`, Firebase token, cookie, password, `DATABASE_URL` hay body dữ liệu cá nhân; client nhận thông báo 500 không có stack trace.
  - Kiểm toán failure visibility của backup cron: Xác nhận `scripts/db_backup_remote.py` trả exit code 0 khi thành công kèm marker `[OK]`, trả exit code 1 khi thất bại kèm marker `[!]`, sanitize toàn bộ secret và hủy bỏ retention khi gặp lỗi.
  - Bộ kiểm thử: 8/8 health tests PASS (bao gồm ca degraded, db down 503, db timeout 503, both down 503, và kiểm toán không rò rỉ secret trong payload), 17/17 remote backup tests PASS (bao gồm ca kiểm thử exit code 0/1 của `main()`); toàn bộ 927/927 backend tests PASS; `git diff --check` sạch 100%.
- **Phase C — Production Database Backup Automation & Retention Pass** (CONFIRMED ON PRODUCTION BY OPERATOR):
  - Xây dựng và triển khai dịch vụ `student-marketplace-backup` chạy `Dockerfile.backup` trên Railway với cron `0 20 * * *`.
  - Phiên sao lưu thật đầu tiên trên production hoàn tất thành công: `pg_dump` major 18 khớp server major 18, kiểm chứng toàn vẹn dump + manifest vượt qua, tải lên Cloudflare R2 STANDARD bucket `choptiters-backups`, xác thực remote size match, rolling retention hoàn tất an toàn. Off-platform restore drill tạm hoãn cục bộ, không cản trở production.
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

- **Chat Recall & Media Cleanup Invariants**:
  - PostgreSQL là persistent source of truth: tin nhắn recall được soft-delete (`is_deleted = TRUE, content = NULL`), dòng `messages` và `reply_to_message_id` không bao giờ bị hard-delete.
  - Media cleanup queue `media_cleanup_jobs` được ghi bền vững trong cùng giao dịch CSDL; commit CSDL quyết định trạng thái nghiệp vụ trước khi dọn dẹp ngoại vi (không rollback DB delete khi Cloudinary lỗi).
  - Tránh tranh chấp giữa immediate cleanup và background worker: Khi tạo job mới trong transaction thu hồi, gán `next_retry_at = now() + 60s` (`MEDIA_CLEANUP_INITIAL_RETRY_SECONDS = 60`). Luồng request thực thi immediate destroy ngay sau commit (t=0); worker không tranh chấp xử lý job trước thời hạn 60s.
  - Bảo vệ đa worker replica (Multi-Worker Concurrency): Worker query sử dụng `SELECT ... FOR UPDATE SKIP LOCKED ORDER BY next_retry_at, cleanup_id LIMIT 50` kết hợp composite index `(next_retry_at, cleanup_id)`. Claim lease nguyên tử gia hạn `next_retry_at = now() + 300s` và commit ngay trước khi thực thi xóa Cloudinary ngoài luồng, không giữ DB lock trong lúc gọi mạng I/O.
  - Làm sạch lỗi ngoại vi (Sanitized `last_error`): Cột `last_error` kiểu `VARCHAR(500)`. Hàm `sanitize_external_error` tước bỏ toàn bộ sensitive URLs, credentials, query parameters, signed tokens; DB và logger đều chỉ lưu giữ tóm tắt chẩn đoán an toàn, tối đa 500 ký tự.
  - True Rolling Video Quota: Triển khai atomic sliding-window rate limiter bằng Redis Sorted Set (ZSET) + Lua script (`chat:video-upload:u:{user_id}`). Cửa sổ trượt 600s, tối đa 5 uploads. `Retry-After` tính động từ event cũ nhất còn tồn tại trong rolling window. Fail-open an toàn khi Redis gián đoạn.
  - Phía Frontend: Kiểu `MessageItem.is_deleted: boolean` bắt buộc (non-optional). Handler sự kiện realtime `MESSAGE_DELETED` thực hiện invalidate toàn diện 5 query authoritative: `messageLists`, `detail`, `attachments`, `attachments-summary`, và `lists` (inbox preview).
  - Worker Entrypoint Ownership: Worker process chính `python -m app.workers.order_auto_cancel` là canonical background process duy nhất của dự án (được định nghĩa trong `docker-compose.prod.yml` và Railway), điều phối cả hai chu trình `order auto cancel` và `run_media_cleanup_sweep`.
  - **CẢNH BÁO PHỤ THUỘC MIGRATION (SECURITY E-LITE DEPENDENCY BLOCKER)**:
    Migration Chat Recall (`b8c9d0e1f2a3`) có `down_revision = 'a7b8c9d0e1f2'` (Security E-Lite).
    Do Security E-Lite vẫn đang ở trạng thái `AWAITING USER REVIEW — DO NOT DEPLOY`, Chat Recall **TUYỆT ĐỐI KHÔNG ĐƯỢC PUSH/DEPLOY ĐỘC LẬP** lên Railway production.
    Railway áp dụng migration tự động theo chuỗi pre-deploy (`alembic upgrade head`); push Chat Recall sẽ kéo theo cả migration Security E-Lite chưa được nghiệm thu lên production database. Trước khi push, người dùng phải nghiệm thu Security E-Lite hoặc chuỗi migration phải được chủ động tách/rebase.
  - **TRẠNG THÁI KIỂM CHỨNG NATIVE VIDEO CONTROLS**:
    AUTOMATED GESTURE LOGIC VERIFIED (kiểm chứng bằng unit test tự động với layout mock và pointer event filter).
    NATIVE VIDEO CONTROLS REQUIRE MANUAL BROWSER ACCEPTANCE: Hành vi tương tác thực tế của controls thanh tua, âm lượng, fullscreen trên Chrome desktop, Chrome Android và Safari/iOS bắt buộc phải được người dùng nghiệm thu thủ công trên trình duyệt thật.

---

## 8. Verification Baseline (Đường cơ sở kiểm thử)

- **Backend Full Suite**: **972/972 PASS** (`pytest tests/ -q`, 0 failures, 11 warnings in 212.83s).
- **Backend Chat Recall & Media Hardening Suite**: **20/20 PASS** (`tests/test_chat_recall_and_media_hardening.py`, including sliding-window boundary, initial retry delay race protection, skip-locked concurrency, and log/error sanitization).
- **Backend Public User ID Suite**: **17/17 PASS** (`tests/test_public_user_id.py`, covering regression tests A through I + conversation participants and members `public_id` exposure).
- **Backend Reports & Notifications Suite**: **35/35 PASS** (`tests/test_reports.py`, `tests/test_admin_and_lifecycle_notifications.py`).
- **Backend BOLA / IDOR Authorization Suite**: **5/5 PASS** (`tests/test_bola_authorization.py`).
- **Backend Daily Needs Suite**: **29/29 PASS** (`tests/test_daily_needs.py`).
- **Backend Reviews Suite**: **14/14 PASS** (`tests/test_reviews.py`).
- **Backend User Profile Suite**: **15/15 PASS** (`tests/test_user_profile.py`).
- **Backend Rate Limiter Security Suite**: **22/22 PASS** (`tests/test_rate_limiter.py`).
- **Backend Products CRUD Suite**: **22/22 PASS** (`tests/test_products_crud.py`).
- **Backend Support Contributions & Claims Suite**: **33/33 PASS** (`tests/test_support_contributions.py`, `tests/test_support_claims.py`).
- **Backend Health & Readiness Suite**: **8/8 PASS** (`tests/test_health.py`).
- **Backend Backup & Remote Retention Tooling Suite**: **32/32 PASS** (`tests/test_db_backup.py`, `tests/test_db_backup_remote.py`).
- **Backend Auction WebSocket Hardening Suite**: **6/6 PASS** (`tests/test_auctions_websocket_hardening.py`).
- **Backend Auth & Admin Authorization Suite**: **95/95 PASS** (`tests/test_auth.py`, `tests/test_admin_user_enforcement.py`, `tests/test_admin_reports.py`, `tests/test_admin_product_enforcement.py`).
- **Backend Conversations Regression Suite**: **58/58 PASS** (`tests/test_conversations_social_and_groups.py`, `tests/test_conversations_phase7c.py`, `tests/test_group_mention_notifications.py`).
- **Alembic State**: Head `b8c9d0e1f2a3_create_media_cleanup_jobs_table.py`, 0 schema drift (`alembic check` clean, 0 new migrations, composite index `(next_retry_at, cleanup_id)` verified, `last_error` VARCHAR(500) synchronized).
- **Frontend Chat Profile Navigation Hardening Suite**: **10/10 PASS** (`src/__tests__/chat_profile_navigation_hardening.test.mjs`, covering reproduction cases `user_id: 4` and `user_id: 10`, absence guard against numeric fallback, group member profile navigation, and message sender profile navigation).
- **Frontend Full/Hardening Suite**: **45/45 PASS** (`post_deployment_hardening.test.mjs`, `pre_deployment_acceptance_fixes.test.mjs`).
- **Frontend Chat Recall & Media Hardening Suite**: **15/15 PASS** (`src/__tests__/chat_recall_media_hardening.test.mjs`, covering desktop action bar with Trash2 icon, mobile popover layout with stacked rows, tombstone high contrast and CircleSlash icon, zero parent opacity, and realtime cache invalidation).
- **Frontend Production Build**: `tsc -b && vite build` PASS (0 errors, bundle generated in 11.51s).
- **Git Hygiene**: `git diff --check` clean across both backend and frontend repositories (0 whitespace errors, 0 conflict markers).

---

## 9. Next Exact Task (Công việc chính xác tiếp theo)

**User-Managed Production Release (Quy trình Phát hành do Người dùng Điều phối)**:
1. **Pre-Deploy Verification**:
   - Xác nhận phiên sao lưu tự động gần nhất trên Railway (`student-marketplace-backup`) đẩy lên Cloudflare R2 đạt trạng thái `SUCCESS`.
   - Xác nhận endpoint `/health` trên Railway backend hiện tại trả về HTTP 200 `{"status": "healthy"}`.
   - Xác nhận không có incident hay alert đang mở trên hạ tầng Railway.
2. **Push Backend**:
   - Người dùng tự thực hiện commit và push branch `main` của `student-marketplace-be` lên GitHub.
   - Theo dõi Railway build & pre-deploy command (`alembic upgrade head`): Áp dụng thành công tuần tự `a7b8c9d0e1f2` (Security E-Lite) và `b8c9d0e1f2a3` (Media Cleanup Jobs).
   - Xác nhận deployment backend chuyển sang trạng thái Live (màu xanh), endpoint `/health` đạt HTTP 200.
3. **Push Frontend**:
   - Sau khi backend live và migration ổn định, người dùng tự thực hiện commit và push branch `main` của `student-marketplace-fe` lên GitHub.
   - Theo dõi Railway build container frontend (`tsc -b && vite build`) hoàn tất và deploy live thành công.
4. **Production Smoke Acceptance**:
   - Kiểm tra định danh công khai: Mở trang cá nhân với `public_id`, mở cuộc trò chuyện trực tiếp.
   - Kiểm tra Chat Recall & Media Hardening: Gửi tin nhắn text/ảnh/video, vuốt trả lời, thao tác thu hồi trên desktop (Trash2) và mobile (long-press), xác nhận tombstone hiển thị rõ nét, tệp đính kèm bị xóa khỏi danh sách shared attachments, và tài khoản thứ hai nhận realtime `MESSAGE_DELETED`.
   - Kiểm tra Worker: Xác nhận worker container chạy ổn định, không có vòng lặp lỗi media cleanup hay crash.
