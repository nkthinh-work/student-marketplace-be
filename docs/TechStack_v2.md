# TECH STACK & KIẾN TRÚC TRIỂN KHAI — Marketplace C2C Sinh viên v3

## 1. Mục đích và các nguồn chuẩn

Tài liệu này là nguồn chuẩn cho kiến trúc, ranh giới repository, lựa chọn công nghệ và quy trình triển khai.

- `DB_v7.md` = nguồn chuẩn cho relational database schema dùng chung.
- `TechStack_v2.md` = nguồn chuẩn cho kiến trúc và delivery.
- `.roo/rules/00-project.md` = bộ quy tắc agent cố định cho repository hiện tại.
- `student-marketplace-be/docs/PROJECT_STATE.md` = trạng thái triển khai ngắn hạn và công việc tiếp theo.
- `student-marketplace-be/docs/API_CONTRACT.md` = API contract backend mà frontend và các client tương thích backend trong tương lai sử dụng.

Nếu thay đổi code mâu thuẫn với một trong các nguồn trên, phải dừng và báo conflict thay vì tự ý đổi thiết kế.

### Quyết định phạm vi nghiệp vụ hiện tại

- Không triển khai giỏ hàng (`cart_items` đã bị loại khỏi DB design).
- Người dùng có thể `favorite/unfavorite` sản phẩm để lưu lại.
- Mua hàng giá cố định đi theo luồng mua trực tiếp từ product detail.
- Một tin có thể bật chế độ đấu giá nếu đạt điều kiện nghiệp vụ.
- MVP đấu giá chỉ cho sản phẩm còn đúng một đơn vị hàng (`stock = 1`).
- Không áp dụng ngưỡng giá khởi điểm tối thiểu cố định cho auction trong MVP; sản phẩm đủ điều kiện về tồn kho và trạng thái đều có thể được đấu giá.
- PostgreSQL vẫn là source of truth cho bid/kết quả; WebSocket chỉ phục vụ realtime delivery.

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

### Backend

```text
student-marketplace-be/
├── .roo/
│   └── rules/
│       └── 00-project.md
├── docs/
│   ├── DB.md
│   ├── TechStack.md
│   ├── API_CONTRACT.md
│   └── PROJECT_STATE.md
├── app/
│   ├── main.py
│   ├── core/
│   ├── db/
│   ├── integrations/
│   ├── modules/
│   └── workers/
├── alembic/
│   ├── versions/
│   └── env.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Ở Phase 0 chỉ tạo skeleton/foundation cần thiết. Không triển khai toàn bộ business module.

### Frontend

```text
student-marketplace-fe/
├── .roo/
│   └── rules/
│       └── 00-project.md
├── docs/
│   ├── API_CONTRACT.md
│   └── PROJECT_STATE.md
├── src/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── pages/
│   ├── services/
│   ├── hooks/
│   ├── stores/
│   ├── lib/
│   ├── types/
│   └── utils/
├── public/
├── Dockerfile
├── nginx.conf
├── .env.example
├── package.json
└── README.md
```

Dùng `docs/`, không dùng `.docs/`.

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

- notifications/read state
- auction notifications (`AUCTION_BID`, `AUCTION_OUTBID`, `AUCTION_WON`, `AUCTION_ENDED`)
- reports
- admin permissions/moderation

### Phase 9 — Workers + Optimization + Deploy

- Redis view counter
- worker synchronization hardening
- retry/idempotency hardening cho scheduled jobs
- query/index checks
- backup procedure
- production Docker build
- CI
- deployment

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

`student-marketplace-be/docs/PROJECT_STATE.md` phải chứa:

```text
Giai đoạn hiện tại
Công việc hiện tại
Trạng thái
Đã hoàn thành
Vấn đề đã biết
Quyết định / ADR links
File đã thay đổi
Trạng thái kiểm thử
Công việc tiếp theo
```

Đây là short-term memory cho agent và không được ghi nhận công việc chưa được verify như thể đã hoàn thành.

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
