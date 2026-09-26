# TECH STACK & KIẾN TRÚC TRIỂN KHAI — Marketplace C2C Sinh viên

## 1. Mục đích và các nguồn chuẩn

Tài liệu này là nguồn chuẩn cho kiến trúc, ranh giới repository, lựa chọn công nghệ và quy trình triển khai.

- `DB_v7.md` = nguồn chuẩn cho relational database schema dùng chung.
- `TechStack_v2.md` = nguồn chuẩn cho kiến trúc và delivery.
- `.roo/rules/00-project.md` = bộ quy tắc agent cố định tại workspace root `student-marketplace/`.
- `student-marketplace-be/docs/PROJECT_STATE.md` = trạng thái triển khai ngắn hạn và công việc tiếp theo.
- `student-marketplace-be/docs/PROJECT_HISTORY.md` = kho lưu trữ lịch sử các giai đoạn đã hoàn thành.
- `student-marketplace-be/docs/API_CONTRACT.md` = API contract backend mà frontend và các client tương thích backend trong tương lai sử dụng.
- `student-marketplace-be/docs/QUERY_INDEX_AUDIT.md` = hồ sơ bằng chứng kiểm toán chỉ mục & hiệu năng truy vấn Phase 9C-A (tài liệu chuyên biệt, không phải nguồn chuẩn thay thế DB_v7.md).
- `student-marketplace-be/docs/BACKUP_RESTORE.md` = quy trình vận hành sao lưu, kiểm tra tính toàn vẹn và diễn tập khôi phục PostgreSQL.

Nếu thay đổi code mâu thuẫn với một trong các nguồn trên, phải dừng và báo conflict thay vì tự ý đổi thiết kế.

### Quyết định phạm vi nghiệp vụ hiện tại

- Không triển khai giỏ hàng (`cart_items` đã bị loại khỏi DB design).
- Người dùng có thể `favorite/unfavorite` sản phẩm để lưu lại.
- Mua hàng giá cố định đi theo luồng mua trực tiếp từ product detail.
- Một tin có thể bật chế độ đấu giá nếu đạt điều kiện nghiệp vụ.
- MVP đấu giá chỉ cho sản phẩm còn đúng một đơn vị hàng (`stock = 1`).
- Không áp dụng ngưỡng giá khởi điểm tối thiểu cố định cho auction trong MVP; sản phẩm đủ điều kiện về tồn kho và trạng thái đều có thể được đấu giá.
- PostgreSQL vẫn là source of truth cho bid/kết quả; WebSocket chỉ phục vụ realtime delivery.
- Đóng góp ủng hộ (Support Contributions & Claims):
  - Phân tách rạch ròi giữa lời khai người dùng (`support_claims` — staging queue phi tài chính) và sổ cái tài chính chính thức (`support_contributions` — authoritative financial ledger).
  - Khai báo chuyển khoản của người dùng chỉ là hỗ trợ đối soát, tuyệt đối không được xem là chân lý tài chính và không tác động trực tiếp lên Bảng tri ân.
  - Quản trị viên đối soát thủ công với sao kê tài khoản ngân hàng thực tế, xác nhận hoặc từ chối thông qua khóa giao dịch (`SELECT FOR UPDATE`). Chỉ sau khi Admin xác nhận thành công mới ghi một bản ghi duy nhất vào `support_contributions`.
  - Hoàn toàn không tích hợp banking API/webhook/OCR/tải ảnh bill.
  - Bảng tri ân công khai chỉ tổng hợp từ các bản ghi đã xác thực trong `support_contributions` có `is_public = TRUE`.
- Trung tâm Hướng dẫn (Tutorial Center v2 — Supersedes v1): Hệ thống hướng dẫn sử dụng nhanh (Quick-Help) định dạng dọc 9:16 do Admin quản trị toàn diện (Admin CMS). Video MP4 là tài sản nhị phân duy nhất của Tutorial được lưu trữ trên Cloudinary (backend tải lên và dọn dẹp an toàn). Ảnh thu nhỏ (thumbnail) là URL phân phối dẫn xuất (derived delivery transformation) tự động từ frame video trên Cloudinary, không lưu trữ tệp poster riêng biệt. Metadata lưu trữ bền vững trong bảng PostgreSQL `tutorials` (32 bảng nghiệp vụ). Giao diện người dùng tích hợp dạng Global Overlay Modal toàn cục, mở trực tiếp trên màn hình hiện tại mà không đổi route, bố cục Navigation Section -> Navigation Item -> Tutorials dạng accordion dọc, phát video bằng HTML5 native player với seeking tiện lợi, hỗ trợ nút hành động "Làm ngay" theo Action Registry chuẩn hóa. Không sử dụng WebSocket realtime và không theo dõi tiến độ học tập (không phải LMS).
- Quy tắc xử lý đa phương tiện (Media Handling Rules):
  - **PRESENTATION IMAGES** (ảnh khoảnh khắc cộng đồng, ảnh sản phẩm): client-side crop/reposition có thể được sử dụng trước khi upload để chuẩn hóa khung hình hiển thị (16:9 cho Hero Community Moments, 4:3 cho Product Images).
  - **EVIDENCE/CONTENT MEDIA** (minh chứng báo cáo, minh chứng phản hồi, biên nhận chuyển khoản, tệp đính kèm tin nhắn): bảo toàn nguyên vẹn khung hình gốc (original frame), tuyệt đối không áp dụng client-side crop.

## 2. Kiến trúc repository

Hệ thống gồm hai repository độc lập:

```text
student-marketplace-fe/
student-marketplace-be/
```

### Repository frontend

`student-marketplace-fe` là React client độc lập.

Frontend sở hữu:

- React + TypeScript + Vite
- UI/components/pages/features
- Firebase JS SDK
- API client
- frontend state/query management

Frontend KHÔNG sở hữu:

- PostgreSQL
- SQLAlchemy
- Alembic
- Redis server configuration
- Firebase Admin SDK
- Cloudinary server secrets

Frontend chỉ giao tiếp qua backend API contract.

### Repository backend

`student-marketplace-be` là mục tiêu triển khai hiện tại.

Cấu trúc thư mục ổn định:
- `app/`
- `alembic/`
- `docs/`
- `scripts/`
- `tests/`

Backend sở hữu:

- Python 3.12
- FastAPI
- SQLAlchemy 2.x async
- asyncpg
- Pydantic v2
- Alembic
- Firebase Admin SDK
- Redis integration
- Cloudinary server integration
- backend worker/scheduler
- backend Docker Compose infrastructure
- scripts/ (công cụ vận hành sao lưu, kiểm chứng & diễn tập phục hồi)

### Backend trong tương lai

Spring Boot là một backend implementation thay thế trong tương lai.

Nó KHÔNG thuộc phạm vi implementation hiện tại và KHÔNG được thêm vào repository chỉ để “đủ kiến trúc”.

Sau này nó có thể dùng chung PostgreSQL schema và API contract.

## 3. Ranh giới database dùng chung

```text
                         PostgreSQL
                         ▲       ▲
                         │       │
                  FastAPI BE   Spring Boot BE
                    (hiện tại)   (tương lai)

React FE
   │
   └── HTTPS REST / WebSocket
            │
            ▼
        FastAPI BE
```

Quy tắc bắt buộc:

- PostgreSQL được dùng chung bởi các backend implementation.
- Frontend KHÔNG BAO GIỜ truy cập PostgreSQL trực tiếp.
- Frontend giao tiếp với backend qua HTTP REST và WebSocket ở những nơi contract cho phép.
- Database schema phải độc lập với implementation.
- `DB_v7.md` là database source of truth.

## 4. Lựa chọn công nghệ

### Backend — mục tiêu hiện tại

- Python 3.12
- FastAPI
- Uvicorn
- SQLAlchemy 2.x async
- asyncpg
- Pydantic v2
- Alembic
- firebase-admin
- async Redis client
- Cloudinary SDK
- pytest + httpx

### Database

- PostgreSQL 15+
- PostgreSQL ENUM / CHECK / partial indexes / GIN full-text theo `DB_v7.md`

### Frontend

- React + TypeScript
- Vite
- React Router
- TanStack Query
- Zustand
- Axios
- Firebase JS SDK
- React Hook Form + Zod
- TailwindCSS + shadcn/ui

### Hạ tầng — backend repository

- Docker / Docker Compose
- PostgreSQL container
- Redis container
- API container
- Worker container

Frontend repository có thể có cấu hình container riêng, nhưng không nằm trong Compose stack của backend repository.

Không thêm library nếu chưa có yêu cầu thực tế rõ ràng và không phù hợp với tài liệu này.

## 4.5. Yêu cầu phi chức năng: Mobile-first

Client chính là trình duyệt mobile của sinh viên, thường dùng 3G/4G và có thể đổi mạng. Điều này ảnh hưởng API và integration từ Phase 1 dù frontend chưa nằm trong phạm vi Phase 0.

### Kỷ luật payload API

- List endpoint cho products, orders, auctions, chat trả DTO gọn; không nhúng object dư thừa.
- Không trả toàn bộ `product` bên trong `order_item` ở list response; dùng các snapshot bất biến đã có trong `DB_v7.md`.
- Pagination dùng **cursor-based/keyset**, không dùng offset cho infinite scroll. Mặc định 20 item, tối đa 50.
- Bật response compression gzip/br tại reverse-proxy/API layer.

### Phân phối ảnh qua Cloudinary

- Backend không trả raw/original Cloudinary URL cho listing/thumbnail.
- URL trả về phải được tạo qua helper dùng transformation:
  - luôn có `f_auto,q_auto`
  - `w_200` cho thumbnail
  - `w_800` cho detail
- Không hard-code transformation rải rác trong endpoint.
- Upload từ camera mobile phải validate file size/metadata hợp lý; Cloudinary xử lý format/orientation phía server.

### Khả năng chịu reconnect của realtime

Áp dụng cho Chat và Auction:

- WebSocket phải hỗ trợ reconnect-with-backoff.
- REST persistence/PostgreSQL là source of truth.
- WebSocket chỉ là tối ưu delivery; không được là đường duy nhất để đọc dữ liệu.
- Client reconnect phải lấy lại snapshot qua REST.
- Với auction, client không được quyết định highest bid hoặc winner dựa trên state local.

### Xử lý auth token

- Firebase ID token hết hạn khoảng 1 giờ; mobile browser có thể background tab lâu.
- Backend trả 401 rõ ràng khi token hết hạn, không âm thầm coi request là anonymous.
- Frontend refresh token và retry theo contract.

Phần này chủ yếu ràng buộc API contract, Cloudinary integration và realtime design; không yêu cầu bảng riêng cho mobile.

## 5. Cấu trúc repository

### Workspace Scope
Quy tắc agent `.roo/rules/00-project.md` nằm tại workspace root `student-marketplace/`. Các tài liệu chuẩn của toàn bộ hệ thống (`DB_v7.md`, `TechStack_v2.md`, `API_CONTRACT.md`, `PROJECT_STATE.md`, `PROJECT_HISTORY.md`) cùng hồ sơ kiểm toán (`QUERY_INDEX_AUDIT.md`) được lưu trữ tập trung tại `student-marketplace-be/docs/`.

```text
student-marketplace/
├── .roo/
│   └── rules/
│       └── 00-project.md
├── student-marketplace-be/
│   ├── docs/
│   │   ├── DB_v7.md
│   │   ├── TechStack_v2.md
│   │   ├── API_CONTRACT.md
│   │   ├── PROJECT_STATE.md
│   │   ├── PROJECT_HISTORY.md
│   │   ├── QUERY_INDEX_AUDIT.md
│   │   └── BACKUP_RESTORE.md
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── db/
│   │   ├── integrations/
│   │   ├── modules/
│   │   └── workers/
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── scripts/
│   ├── tests/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── .gitignore
│   ├── .dockerignore
│   ├── alembic.ini
│   ├── requirements.txt
│   └── README.md
└── student-marketplace-fe/
    ├── src/
    │   ├── app/
    │   ├── components/
    │   ├── features/
    │   ├── lib/
    │   └── ...
    ├── public/
    │   └── support/
    ├── index.html
    ├── package.json
    ├── package-lock.json
    ├── tsconfig*.json
    ├── vite.config.ts
    ├── .env.example
    ├── .gitignore
    └── README.md
```

*Ghi chú*: Các thư mục phát sinh hoặc cục bộ (`.venv`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, `*.tsbuildinfo`, `.env`, `scratch`, `secrets`) được cố tình lược bỏ khỏi cây cấu trúc chuẩn. Dùng `docs/`, không dùng `.docs/`. Không nhân bản rule `.roo` vào các thư mục con.

## 6. Kiến trúc backend

Mỗi domain module đi theo luồng:

```text
router -> service -> repository -> SQLAlchemy -> PostgreSQL
```

- router: HTTP layer, wiring validation, auth dependencies
- service: business rules, transaction orchestration
- repository: persistence/query logic
- model: SQLAlchemy mapping
- schema: Pydantic DTOs

Không đặt business rule cốt lõi trong router.

### Transaction-sensitive modules

Các module sau bắt buộc để service điều phối transaction rõ ràng:

- order creation/reservation
- payment confirmation
- auction bid placement
- auction ending/winner selection
- auction winner checkout

Đặc biệt, bid phải lock bản ghi auction trước khi validate highest bid để tránh race condition.

## 7. Kiến trúc frontend

Mỗi feature nên được tổ chức gần domain của nó:

```text
features/products/
  api.ts
  hooks.ts
  schemas.ts
  types.ts
  components/

features/auctions/
  api.ts
  hooks.ts
  schemas.ts
  types.ts
  components/
```

Quy tắc:

- TanStack Query = server state.
- Zustand = client/global UI state thực sự.
- Axios = HTTP transport.
- Firebase SDK = authentication state.
- UI validation chỉ phục vụ UX; backend vẫn là authority.
- Highest bid/winner hiển thị trên client phải đến từ backend state.

## 8. Firebase contract

### Frontend

1. Khởi tạo Firebase Web SDK.
2. Authenticate bằng provider được duyệt cho dự án.
3. Theo dõi auth state.
4. Lấy Firebase ID token cho authenticated API calls.
5. Axios interceptor gửi `Authorization: Bearer <ID_TOKEN>`.
6. Không bao giờ dùng raw Firebase UID do client gửi như bằng chứng xác thực.

### Backend

1. Verify Firebase ID token bằng `firebase-admin`.
2. Lấy Firebase UID đã được verify.
3. Map UID -> `user_auth_identities.user_id`.
4. Load `users`.
5. Enforce status và role.
6. Expose `user_id` nội bộ cho domain service.

## 9. Phương pháp delivery: vertical slice

KHÔNG xây toàn bộ backend trước rồi mới làm toàn bộ frontend.

Mỗi phase đi theo chuỗi:

```text
DB/model/migration
      ↓
repository
      ↓
service/business rules
      ↓
API
      ↓
backend tests
      ↓
frontend API/hooks
      ↓
frontend UI
      ↓
verification
```

Ở Phase 0, frontend implementation NGOÀI PHẠM VI. Phase 0 chỉ dựng nền tảng backend.

## 10. Thứ tự triển khai bắt buộc

### Phase 0 — Backend Foundation

Phạm vi:

- khởi tạo backend repository
- Docker Compose
- PostgreSQL
- Redis
- FastAPI
- environment configuration
- SQLAlchemy async session foundation
- Alembic
- health check
- logging baseline
- tests
- `.env.example`
- README
- `student-marketplace-be/docs/PROJECT_STATE.md`

Backend Compose services:

- `api`
- `worker`
- `postgres`
- `redis`

Tiêu chí hoàn thành:

- backend containers build/start được
- PostgreSQL truy cập được
- Redis truy cập được
- FastAPI khởi động được
- `GET /health` trả success
- basic health test pass
- chưa triển khai marketplace feature module

### Phase 1 — Auth + Users

- Firebase verification
- `users` + `user_auth_identities`
- current-user endpoint
- role/status authorization

### Phase 2 — Categories + Products + Images

- categories
- product CRUD/soft-delete
- `listing_type` cho `FIXED_PRICE` / `AUCTION`
- Cloudinary image integration
- image ordering/thumbnail
- search/filter/cursor pagination
- validate quyền seller chỉnh sửa tin
- chưa triển khai bid ở phase này

### Phase 3 — Favorites

- favorite product
- unfavorite product
- list favorites
- loại product đã unavailable/soft-delete khỏi response phù hợp

Không có Cart phase.

### Phase 4 — Orders + Payment

- mua trực tiếp từ product detail
- order creation
- transactional stock reservation/release
- item snapshots
- order state machine
- payment receipt
- seller confirmation
- order history
- auto-cancel worker
- không cho mua trực tiếp product đang ở phiên `AUCTION` active

### Phase 5 — Auctions

Triển khai theo thứ tự bắt buộc:

1. migration/model cho `auctions`, `auction_bids` và field liên quan trong `products`
2. repository query/locking
3. service bật/tắt đấu giá
4. REST endpoint đọc auction state
5. REST endpoint đặt bid với transaction + row lock
6. backend tests cho concurrency/business rules
7. WebSocket realtime delivery sau khi persistence ổn định
8. worker/scheduler đóng auction khi hết hạn
9. xác định winner/final price
10. giữ một đơn vị stock cho winner
11. luồng winner tạo order trực tiếp với `quantity = 1`
12. worker giải phóng winner reservation nếu quá deadline
13. frontend auction detail/bid UI
14. verification end-to-end

Điều kiện bật auction tối thiểu:

- seller sở hữu product
- seller đang ở trạng thái `ACTIVE`
- product `AVAILABLE`, chưa soft-delete
- `stock = 1`
- `reserved_stock = 0`
- chưa có order/reservation đang chiếm sản phẩm
- `bid_step > 0`
- `ends_at > starts_at`

MVP không áp dụng ngưỡng giá khởi điểm tối thiểu cố định cho auction.

Nếu sau này cần hạn chế spam hoặc áp dụng chính sách giá tối thiểu, giá trị này phải được xử lý ở business/config layer thay vì hard-code vào database schema.

Quy tắc realtime:

- DB/REST là source of truth
- WebSocket chỉ push state mới
- Redis pub/sub chỉ dùng khi cần fan-out nhiều API instance
- reconnect phải fetch snapshot lại

### Phase 6 — Reviews

- review order đã completed
- participant authorization
- duplicate prevention
- listing/average rating

### Phase 7 — Chat

1. REST message persistence
2. WebSocket realtime delivery
3. read state
4. Cloudinary attachments

Không bắt đầu WebSocket trước khi persistence và authorization ổn định.

### Phase 8 — Notifications + Reports + Admin

- notifications/read state (PostgreSQL persistent state là chân lý duy nhất; phát tán realtime fan-out qua WebSocket private `/ws/me` là best-effort post-commit)
- auction notifications (`AUCTION_BID`, `AUCTION_OUTBID`, `AUCTION_WON`, `AUCTION_ENDED`)
- reports + admin notifications fan-out (`ADMIN_REPORT`, `ADMIN_COMMUNITY`, `ADMIN_FEEDBACK`, `ADMIN_SUPPORT_CLAIM`)
- admin permissions/moderation & user lifecycle notifications (`SUPPORT_CLAIM`, `COMMUNITY_MOMENT`, `COMMUNITY_REJECTED`, `REPORT`, `ACCOUNT_ACCESS`)

### Phase 8H — Community Engagement

- Phase 8H-A: Community Hero Moments (ảnh khoảnh khắc sinh viên trên Hero carousel)
- Phase 8H-B: Feedback (phản hồi & đóng góp ý kiến sinh viên)

### Phase 9 — Workers + Optimization + Deploy

- **Phase 9A**: Worker synchronization hardening, retry/idempotency hardening cho scheduled jobs (`execute_with_retry`, `SweepResult`, exponential backoff).
- **Phase 9B — Redis Product View Counter**:
  - Tầng ghi nhận tần suất cao trên Redis với biến đếm số nguyên chính xác (Exact Atomic Integer Counter via Redis Lua scripts).
  - Khử trùng lặp người xem 24 giờ (`product:views:seen:{product_id}:{viewer_token}`).
  - Định danh người xem: Ưu tiên `u:{user_id}` từ verified Firebase token; khách vãng lai dùng `a:{anonymous_uuid}`; tuyệt đối không lưu IP hay fingerprint.
  - Cơ chế đồng bộ bền vững (Durable Monotonic PostgreSQL Projection): Worker quét định kỳ `product:views:dirty`, cập nhật `products.view_count = GREATEST(...)` bảo toàn `updated_at`.
  - Khả năng chịu lỗi cao (Fail-open): Sự cố Redis không làm gián đoạn việc xem chi tiết hoặc duyệt sản phẩm.
- **Phase 9C-A — Query & Index Audit / Performance Hardening**:
  - Kiểm toán khớp chỉ mục và tối ưu hóa truy vấn cơ sở dữ liệu trên toàn bộ các bảng nghiệp vụ.
  - Bổ sung các chỉ mục chuyên biệt cho hàng đợi xử lý báo cáo vi phạm, loại bỏ toàn bộ Seq Scan trên tập dữ liệu lớn.
  - Xác thực không phát sinh N+1 truy vấn trên các endpoint danh sách.
  - Chi tiết hồ sơ đo lường, kế hoạch thực thi EXPLAIN và kết quả kiểm toán thuộc quyền sở hữu của `QUERY_INDEX_AUDIT.md`.
- **Phase 9C-B — Backup & Restore Procedure**:
  - Quy trình sao lưu logic PostgreSQL native (`pg_dump --format=custom`) bảo đảm tính nhất quán giao dịch (MVCC snapshot).
  - Tự động kiểm tra tính toàn vẹn (checksum SHA-256) và bảng mục lục lưu trữ (manifest metadata).
  - Diễn tập khôi phục cục bộ trên database tạm thời cô lập; kiểm chứng khớp 100% schema, Alembic revision và số lượng bản ghi nghiệp vụ.
  - Phân định rõ ranh giới phục hồi: PostgreSQL là nguồn dữ liệu nghiệp vụ chuẩn xác; Redis được khởi tạo mới; tài nguyên Cloudinary và tài khoản Firebase Auth tuân thủ ranh giới nhà cung cấp bên ngoài.
- **Phase 9C-C — Production Docker Build & Container Hardening**:
  - Đóng gói ứng dụng backend đa tầng (Multi-stage build) trên nền `python:3.12-slim`, loại bỏ trình biên dịch khỏi runtime image.
  - Sử dụng chung một image (`student-marketplace-be:prod`) cho cả API và Background Worker, phân tách qua command thực thi.
  - Cấu hình Production Compose (`docker-compose.prod.yml`) chuẩn hóa 4 services (`api`, `worker`, `postgres`, `redis`), loại bỏ hoàn toàn source bind mounts và dev reload.
  - Phân quyền người dùng an toàn (non-root `appuser`, UID `10001`), cô lập cổng kết nối PostgreSQL và Redis trong mạng nội bộ Compose.
  - Thiết lập cơ chế kiểm tra sức khỏe (Healthchecks) và dừng mượt mà (Graceful SIGTERM handling); migration CSDL được thực thi tường minh qua lệnh của người vận hành, không chạy tự động khi khởi động API.
- **Phase 9C-D — CI / Deployment**:
  - **CI Provider**: Sử dụng GitHub Actions độc lập cho từng repository (`student-marketplace-be` và `student-marketplace-fe`), tuân thủ nguyên tắc least-privilege (`contents: read`), hủy job cũ khi có commit mới (`cancel-in-progress: true`), không sử dụng secrets sản xuất trong kiểm thử thông thường.
  - **Backend CI Gates**: Python 3.12, container dịch vụ PostgreSQL 15 & Redis 7 cô lập tạm thời, migration Alembic (`alembic upgrade head`), kiểm toán drift (`alembic check`), toàn bộ test suite (`pytest tests/ -q`), kiểm tra cú pháp Production Compose, build image Production Docker, xác thực non-root runtime (`appuser`), kiểm tra toàn vẹn dependencies (`pip check`) và kiểm toán ranh giới tệp tin. Toàn bộ release gates trên GitHub Actions đã đạt `SUCCESS`.
  - **Frontend CI Gates**: Node.js 22, cài đặt khóa sạch (`npm ci`), kiểm tra kiểu tĩnh TypeScript và đóng gói tối ưu (`tsc -b && vite build`), xác thực artifact `dist/index.html`. Toàn bộ build gates trên GitHub Actions đã đạt `SUCCESS`.
  - **Kiến trúc Triển khai Khái niệm (Conceptual Deployment Architecture)**:
    - Frontend: Triển khai trên Vercel kết nối repository `student-marketplace-fe`.
    - Backend: Ban đầu triển khai trên một máy chủ VPS sản xuất (one production VPS initially). Các dịch vụ vận hành trên VPS bao gồm: Reverse proxy / HTTPS termination, FastAPI API (`student-marketplace-be:prod`), Background Worker (`order_auto_cancel`), PostgreSQL, Redis. Không gắn cứng nhà cung cấp VPS cụ thể trong kiến trúc chuẩn (lựa chọn nhà cung cấp thuộc phạm vi vận hành).
    - Nhà cung cấp bên ngoài (External Providers): Firebase Authentication (xác thực người dùng), Cloudinary (lưu trữ media nhị phân theo namespace `student-marketplace/prod/`).
    - Trạng thái triển khai: `READY FOR INFRASTRUCTURE PROVISIONING`. Tuyệt đối không tự tiện bịa đặt VPS IP, domain, chứng chỉ TLS, production secrets hay deployed URLs khi chưa có thông số hạ tầng thực tế từ người dùng.

Phase 5 được phép dùng worker cho **domain requirement bắt buộc** là đóng auction đúng hạn. Phase 9 dành cho hardening/optimization toàn hệ thống, không trì hoãn correctness của đấu giá.

## 11. Kiểm soát phạm vi

Một task của agent = một primary vertical slice.

Agent KHÔNG ĐƯỢC:

- triển khai toàn bộ module trong một task
- nhảy sang phase sau khi phase hiện tại chưa đạt acceptance criteria
- tự thiết kế lại DB theo sở thích cá nhân
- thêm library “để phòng khi cần”
- tự ý đổi enum value hoặc endpoint contract
- triển khai Spring Boot trong backend project hiện tại
- tự thêm lại Cart khi scope đã bỏ Cart
- dùng Redis làm source of truth cho bid/winner
- để frontend tự tính winner

Kết thúc task phải:

1. chạy test liên quan
2. chạy lint/type-check liên quan nếu đã cấu hình
3. kiểm tra migration/schema state nếu DB thay đổi
4. cập nhật `student-marketplace-be/docs/PROJECT_STATE.md`
5. liệt kê file đã thay đổi
6. nêu acceptance criteria pass/fail
7. nêu chính xác task tiếp theo
8. dừng

## 12. Project state

`student-marketplace-be/docs/PROJECT_STATE.md` là bộ nhớ ngắn hạn (short-term memory) của dự án, phản ánh chính xác trạng thái thực thi hiện tại và không ghi nhận công việc chưa được verify như thể đã hoàn thành.

Nguyên tắc quản lý, cấu trúc mẫu và quy chuẩn phân chia giữa `PROJECT_STATE.md` và `PROJECT_HISTORY.md` được quy định tập trung tại `.roo/rules/00-project.md`.

## 13. Definition of Done

Một feature chỉ được coi là DONE khi:

- schema/constraints đúng
- authorization đúng
- transaction boundaries đúng
- API contract rõ ràng
- backend tests bao phủ success path và failure path quan trọng
- concurrency test tồn tại cho hành vi dễ race như auction bidding khi phù hợp
- frontend integration hoàn tất nếu phase có frontend work
- existing tests vẫn pass
- không commit secret
- `PROJECT_STATE.md` được cập nhật
- tài liệu liên quan phản ánh đúng behavior mới

### Definition of Done bổ sung cho Auction

Auction chỉ DONE khi thêm các điều kiện:

- không thể bật auction cho product không đủ điều kiện
- seller không thể bid chính sản phẩm của mình
- bid cạnh tranh không tạo hai “highest bid” hợp lệ cùng thời điểm
- request sau `ends_at` không được chấp nhận
- worker đóng auction idempotent
- winner được xác định deterministic
- fixed-price purchase bị chặn khi auction đang active
- winner checkout dùng `quantity = 1` và đúng `final_price`
- reservation được giải phóng đúng khi winner timeout
- reconnect WebSocket không làm client mất state vì REST có thể phục hồi snapshot

## 14. Architectural Decisions — Pre-Publication Approval & Inbox Cleanup

- **Bắt buộc kiểm duyệt tin đăng tiền xuất bản**: Mọi tin đăng mới đều khởi tạo ở trạng thái `DRAFT`. Ảnh sản phẩm là tùy chọn (cho phép 0, 1, 2... ảnh khi gửi duyệt `submit-review` -> `PENDING`). Quản trị viên duyệt qua hàng đợi chuyên dụng `/admin/product-approvals`, giao diện thẩm định hiển thị rõ ràng placeholder `Tin đăng này không có ảnh.` khi tin không có ảnh và cho phép Approve/Reject bình thường. Nếu người bán thêm hoặc xóa ảnh sau khi đã được duyệt, hệ thống tự động reset `approval_status -> DRAFT`.
- **Tách biệt rõ ràng 3 miền trạng thái của Product**:
  1. `status`: Trạng thái kinh doanh của người bán (`AVAILABLE`, `HIDDEN`, `SOLD_OUT`).
  2. `approval_status`: Trạng thái thẩm định trước xuất bản (`DRAFT`, `PENDING`, `APPROVED`, `REJECTED`).
  3. `moderation_status`: Chế tài vi phạm sau báo cáo (`CLEAR`, `BLOCKED`).
- **Notification Hard-delete (User Inbox Cleanup)**: Cho phép người dùng dọn dẹp hòm thư thông báo bằng thao tác hard-delete bản ghi thông báo cá nhân (`DELETE /api/v1/notifications/{id}`); trên thiết bị di động hỗ trợ thao tác vuốt sang phải trực tiếp (direct swipe-right release commit >= 38% chiều rộng và >= 90px) để xóa ngay lập tức khi thả tay mà không cần chạm lần 2 hay modal xác nhận; thao tác này là dọn dẹp hiển thị cục bộ, tuyệt đối không gây hiệu ứng phụ lên các thực thể nghiệp vụ được tham chiếu (Đơn hàng, Báo cáo, Đấu giá, Tin đăng).
- **Daily Journal Real-data Contract & Continuous Two-Way Marquee**: Giữ nguyên endpoint `/api/v1/daily-needs/today` cho ngữ nghĩa nhật ký hôm nay. Bổ sung `GET /api/v1/daily-needs/recent` (limit clamped 1..10, sắp xếp xác định `note_date DESC, updated_at DESC, daily_need_id DESC`) lấy 10 bản ghi nhật ký thật gần nhất xuyên suốt các ngày để cung cấp dữ liệu cho Marquee trang chủ. Tuyệt đối không sinh dữ liệu giả ở backend. Trên frontend, khi có 1..9 bản ghi thật, tạo presentation pool 10 slots thông qua round-robin tuần hoàn (render key duy nhất dạng `${daily_need_id}-${slotIndex}`) để hai hàng marquee liên tục chuyển động ngược hướng (RTL và LTR) mượt mà; track B phục vụ loop mang `aria-hidden="true"`; khi 0 bản ghi hiển thị empty state trang trọng.
