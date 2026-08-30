# TRẠNG THÁI DỰ ÁN — Backend & Frontend

## Giai đoạn hiện tại
Phase 5 — Đấu giá (Auctions) [Đã hoàn thành và VERIFIED 100%]

## Công việc hiện tại
Phase 5 (Auctions Vertical Slice) hoàn thành và VERIFIED 100%. Sẵn sàng bước sang Phase 6 (Reviews / Chat / Notifications).

## Trạng thái
- Phase 0: Verified
- Phase 1 (Backend + Frontend): Verified
- Phase 2A (Backend Categories + Products + Images): Verified
- Phase 2B (Frontend Categories + Products + Images + Search + Filters): Verified
- Cross-Layer Refactor (Remove Product Item Condition): Verified 100%
- Phase 2 Overall: Verified 100%
- Phase 3 (Favorites): Verified 100%
- Phase 4 (Orders + Payment - Backend + Frontend + Migrations + Tests + Worker): VERIFIED 100%
- Phase 4A (Bank Account Profile + VietQR - Backend + Frontend + Migrations + Tests): VERIFIED 100%
- Phase 4 Follow-up (Transaction Terms Editing + Cash with Shipping - Backend + Frontend + Tests): VERIFIED 100%
- Product UX Cleanup & Consistency Pass (Frontend UI/UX Polish & Unified Design): VERIFIED 100%
- **Phase 5 (Auctions — Backend + Frontend + Migrations + 25 Tests + Realtime WebSocket + Worker Sweeps)**: **VERIFIED 100%**

## Đã hoàn thành

### 0. Phase 5 — Đấu giá (Auctions) [Đã Verified 100%]
- [x] **Database Schema & Alembic Migration (`d4e6f8a2b1c3_create_auctions_and_auction_bids.py`)**:
  - `auctions`: `starting_price DECIMAL(12,0) NOT NULL CHECK >= 0`, `bid_step > 0`, `ends_at > starts_at`, status check, final_price check, winner consistency check, partial unique index `ux_auctions_product_active` on `(product_id) WHERE status IN ('SCHEDULED', 'ACTIVE')` cho phép lưu nhiều vòng lịch sử.
  - `auction_bids`: `amount > 0`, keyset pagination composite index `(auction_id, amount DESC, created_at ASC, bid_id ASC)`.
  - `orders`: `auction_id BIGINT NULL REFERENCES auctions(auction_id) ON DELETE RESTRICT`, partial unique index `ux_orders_auction_id` on `(auction_id) WHERE auction_id IS NOT NULL` (tối đa 1 Order duy nhất cho mỗi vòng đấu giá).
  - Migration round-trip verified (upgrade head -> downgrade -1 -> upgrade head -> check: 0 errors).
- [x] **Backend Services & Invariants**:
  - Snapshot cố định `starting_price = products.price` khi tạo auction round.
  - Quy tắc giá khởi điểm 0 VND: `amount > 0 AND amount >= starting_price`; khi chưa có bid: `minimum_next_bid = max(starting_price, 1)`.
  - Privacy-safe anonymization: `bidder_display: 'N*** A'`, ẩn hoàn toàn `winner_id` và `bidder_id` khỏi client công khai.
  - Deadlock-free product mutation lock order:Generic Product PATCH / HIDE / DELETE chỉ acquire `products(product_id) FOR UPDATE` và đọc non-locking auction state.
  - Winner checkout deadline chuẩn hóa qua `settings.AUCTION_WINNER_CHECKOUT_HOURS`.
  - Tái sử dụng reservation `reserved_stock = 1` khi winner tạo order (không tăng lần 2).
  - Background sweeps tích hợp vào single worker loop (`run_auction_scheduled_sweep`, `run_auction_close_sweep`, `run_winner_timeout_sweep`).
- [x] **Realtime WebSocket Bridge**:
  - `/ws/auctions/{auction_id}`: Hỗ trợ Redis Pub/Sub và in-memory fallback, heartbeat ping-pong, broadcast sự kiện `BID_PLACED`, `AUCTION_STARTED`, `AUCTION_ENDED`, `AUCTION_CANCELLED`.
- [x] **Frontend Feature Slice**:
  - `types.ts` & `api.ts` & `hooks.ts`: React Query hooks + WebSocket automatic reconnect & snapshot sync.
  - `AuctionCountdown.tsx`: Bộ đếm ngược realtime đồng bộ server-time offset (`serverOffsetMs`), UTC ISO parsing (`parseServerDateTime`), chuyển tiếp "Đang chốt kết quả..." khi đếm về 0.
  - `BidForm.tsx`: Định dạng tiền tệ VND chuẩn xác (`formatVND`, `formatNumberVND`), tiền gửi backend chuẩn integer (`normalizeMoney`), nút tăng nhanh bước giá linh hoạt ($+1\times, +2\times, +5\times \text{bid\_step}$) kèm xác thực giá tối thiểu.
  - `BidConfirmationModal.tsx`: Hộp thoại xác nhận đặt giá đấu hiển thị tiền tệ tiếng Việt rõ ràng.
  - `RecentBidsList.tsx`: Bảng lịch sử đặt giá bảo mật danh tính, format tiền VND chuẩn không lộ scientific notation.
  - `WinnerCheckoutModal.tsx`: Form tạo đơn hàng trúng đấu giá tích hợp giao nhận & thanh toán Phase 4.
  - `SellerAuctionModal.tsx`: Bắt đầu đấu giá ngay lập tức với `duration_minutes` (30m, 1h, 3h, 6h, 12h, 1d, hoặc tùy chỉnh giờ/phút), bỏ hoàn toàn form lên lịch phức tạp.
  - `AuctionPanel.tsx`: Hiển thị rõ ràng các trạng thái hậu đấu giá cho Seller (`NO_BIDS` -> Đấu giá lại / Bán giá cố định, `WAITING` -> Chờ người thắng, `ORDER_CREATED` -> Nút Xử lý đơn hàng, `EXPIRED` -> Đấu giá lại / Bán giá cố định).
  - Public Product Feed: Tối ưu query EXISTS chỉ hiển thị sản phẩm `AUCTION` khi có phiên đấu giá đang `ACTIVE`.
- [x] **Verification**:
  - 29/29 Auction backend unit/integration tests passing 100%.
  - 194/194 Backend test suite passing 100%.
  - Frontend build `tsc -b && vite build` clean with exit code 0.
  - `pytest`: **190/190 tests PASSED (100%)** (Bao gồm 25 auction tests).
  - `npm run build`: **0 errors**.

### 0. Product UX Cleanup & Consistency Pass [Đã Verified 100%]
- [x] **Centralized Display-State & Terminology Mapping (`src/lib/orderDisplay.ts`)**:
  - Tạo helper tập trung `getOrderDisplayState(order, actor)` giải quyết xung đột nhiều badge, phân định rõ ràng góc nhìn người mua ("Chờ người bán xác nhận", "Cần thanh toán", "Đang giao đến bạn") và người bán ("Chờ bạn xác nhận đơn", "Cần kiểm tra thanh toán", "Sẵn sàng giao hàng").
  - Chuẩn hóa formatters tiếng Việt: "Gặp trực tiếp", "Giao hàng", "Tiền mặt khi gặp/nhận", "Chuyển khoản VietQR".
- [x] **Zero Payment UI Leakage cho đơn miễn phí (`total_amount == 0`)**:
  - Triệt tiêu toàn bộ rò rỉ thanh toán (ẩn thẻ VietQR, ẩn ghi chú thanh toán, ẩn tải biên nhận, ẩn các nút xác nhận tiền, ẩn badge thanh toán; hiển thị "Miễn phí" / "0 đ").
- [x] **Order List (Buying vs Selling)**:
  - Phân định rõ mục đích: Đơn mua ("Đơn hàng bạn đã đặt") và Đơn bán ("Đơn hàng người mua đã đặt từ các tin của bạn").
  - Empty states dạng card sáng đồng bộ (`ShoppingBag` / `Store`) với CTA rõ ràng ("Khám phá sản phẩm" / "Đăng tin bán ngay").
- [x] **OrderDetailPage Hierarchy**:
  - Cấu trúc lại theo thứ tự chuẩn: (1) Mã đơn & Action Bar, (2) Snapshot sản phẩm, (3) Thông tin đối tác, (4) Giao nhận (Người nhận + Địa chỉ/Địa điểm), (5) Thanh toán (Chỉ hiển thị khi có phí), (6) Lịch sử đơn hàng.
  - Tách bạch thông tin người nhận hàng trong giao nhận và danh tính đối tác (Avatar + Tên).
- [x] **Navigation Drawer**:
  - Phân nhóm menu trực quan: MUA HÀNG (Trang chủ, Tin đã lưu, Đơn mua), BÁN HÀNG (Đăng tin bán, Quản lý tin đăng, Đơn bán), TÀI KHOẢN (Hồ sơ cá nhân, Đăng xuất).
- [x] **Bank Account Profile & Card**:
  - Chuẩn hóa: 1 CTA duy nhất khi chưa có tài khoản; hiển thị gọn gàng với "Chỉnh sửa" / "Xóa" khi đã có tài khoản.
- [x] **Seller Identity Readiness**:
  - Chuẩn hóa cấu trúc hàng người bán trên `ProductCard` và `ProductDetailPage` sẵn sàng tích hợp Seller Storefront mà không tạo route gãy.
- [x] **Verification**:
  - `npm run build` (`tsc -b && vite build`): **0 errors**.
  - `pytest`: **165/165 tests PASSED (100%)**.

### 0. Phase 4 Follow-up — Order Transaction Terms Editing & Cash with Shipping [Đã Verified 100%]
- [x] **Business Rule Decision**:
  - `MEETUP` hỗ trợ cả `CASH_ON_MEETUP` và `BANK_TRANSFER`.
  - `SHIPPING` hỗ trợ cả `CASH_ON_MEETUP` (Tiền mặt khi nhận) và `BANK_TRANSFER`.
  - Xóa bỏ quy tắc cũ chỉ cho phép `SHIPPING -> BANK_TRANSFER`.
  - Đơn `SHIPPING + CASH_ON_MEETUP` được phép chuyển sang trạng thái `DELIVERING` khi `payment_status = 'UNPAID'`.
- [x] **Backend Service & Schemas & Endpoints**:
  - `CreateOrderRequest` & `UpdateOrderTransactionTermsRequest`: Hỗ trợ đầy đủ các cặp giao nhận - thanh toán.
  - `PATCH /api/v1/orders/{order_id}/transaction-terms`: Khóa dòng `SELECT ... FOR UPDATE`, cho phép người bán cập nhật hình thức nhận hàng, địa điểm/địa chỉ nhận, phương thức thanh toán, ghi chú thanh toán.
  - Chặn sửa phương thức thanh toán khi `payment_status` là `VERIFYING` hoặc `PAID`.
  - Snapshot / Clear ngân hàng tự động khi chuyển đổi `CASH_ON_MEETUP <-> BANK_TRANSFER`.
- [x] **Frontend Components & Modals**:
  - `DirectPurchaseModal.tsx`: Hỗ trợ chọn cả Tiền mặt và Chuyển khoản VietQR khi chọn Giao hàng.
  - `EditTransactionTermsModal.tsx`: Modal điều chỉnh giao nhận và thanh toán dành cho người bán, có xem trước thay đổi (diff summary) và cảnh báo tài khoản ngân hàng.
  - `OrderDetailPage.tsx`: Tích hợp nút điều chỉnh, cập nhật điều kiện giao hàng và xác nhận tiền mặt khi giao hàng.
- [x] **Automated Testing & Build**:
  - `tests/test_order_transaction_terms.py`: 24 test cases kiểm tra độc lập các luồng mua hàng, phân quyền, chuyển đổi điều khoản, xóa dữ liệu thừa, snapshot ngân hàng, giao hàng thu tiền mặt, và đơn 0đ.
  - Toàn bộ backend test suite: **165/165 tests PASSED 100%**.
  - Frontend build: `npm run build` thành công với **0 lỗi**.

### 0. Phase 4A — Bank Account Profile + VietQR (Backend + Frontend) [Đã Verified 100%]
- [x] **Static Bank Registry**:
  - `app/core/banks.py`: Danh mục chính thức 45 ngân hàng Việt Nam với mã BIN chuẩn NAPAS, bank code, short name, full name, và các hàm helper lookup (`get_bank_by_bin`, `get_bank_by_code`, `resolve_bank_bin`).
- [x] **Database & Migrations**:
  - Migration `c3e5f8a1b2d4_add_bank_profile_and_order_bank_snapshot.py`: Thêm `bank_bin`, `bank_account_number`, `bank_account_name` vào bảng `users`; thêm `payment_bank_bin`, `payment_bank_account_number`, `payment_bank_account_name` vào bảng `orders`.
  - Migration round-trip hoàn chỉnh: `upgrade head` -> `downgrade -1` -> `upgrade head` -> `alembic check` (`No new upgrade operations detected.`).
- [x] **Backend User Bank Account Endpoints**:
  - `GET /api/v1/users/banks`: Danh sách các ngân hàng hỗ trợ.
  - `GET /api/v1/users/me/bank-account`: Lấy thông tin tài khoản nhận tiền (200 OK với `null` khi chưa cấu hình).
  - `PUT /api/v1/users/me/bank-account`: Thiết lập / Cập nhật tài khoản nhận tiền với validation BIN và STK (200 OK).
  - `DELETE /api/v1/users/me/bank-account`: Xóa tài khoản nhận tiền (204 No Content).
  - Bảo vệ privacy: `UserResponse` và `UserUpdate` không để lộ / không cho phép sửa trường ngân hàng ngoài endpoint chuyên biệt.
- [x] **Backend Order Bank Snapshot & VietQR URL Generator**:
  - `generate_vietqr_url`: Tạo Quick Link chuẩn VietQR qua `https://img.vietqr.io/image/{bank_bin}-{account_number}-compact2.png?...` sử dụng `urllib.parse.urlencode` và mã hóa an toàn các tham số `amount`, `addInfo` (order_code), `accountName`.
  - Snapshot bất biến: Khi người bán xác nhận đơn `BANK_TRANSFER` có phí, backend kiểm tra và copy `bank_bin`, `account_number`, `account_name` của seller vào `orders`. Thay đổi/xóa tài khoản cá nhân sau đó không làm thay đổi các đơn hàng đã xác nhận.
  - Xử lý đơn miễn phí (`total_amount == 0`): Sử dụng sentinel nội bộ `payment_method = 'OTHER'`, tự động `payment_status = 'PAID'`, không yêu cầu phương thức thanh toán hoặc tài khoản ngân hàng.
- [x] **Backend Tests**:
  - `tests/test_bank_profile_and_vietqr.py`: 29 test cases kiểm tra toàn diện CRUD ngân hàng, validation, authorization, immutability snapshot, VietQR URL generation, privacy DTOs, và quy tắc đơn miễn phí/có phí.
  - Toàn bộ backend test suite: **141/141 tests PASSED 100%**.
- [x] **Frontend Implementation (`src/features/users/` & `src/features/orders/` & `src/features/profile/`)**:
  - `ProfilePage.tsx`: Thêm thẻ "Tài khoản nhận tiền (VietQR)" hiển thị thông tin ngân hàng, nút copy STK, modal thêm/chỉnh sửa với dropdown ngân hàng, modal xác nhận xóa an toàn.
  - `DirectPurchaseModal.tsx`: Tự động ẩn chọn phương thức thanh toán cho đơn 0đ; hiển thị options phù hợp theo `MEETUP` / `SHIPPING`.
  - `ConfirmOrderModal.tsx`: Kiểm tra tài khoản nhận tiền của người bán trước khi xác nhận đơn chuyển khoản; hiển thị cảnh báo và link đến Profile nếu chưa thiết lập.
  - `OrderDetailPage.tsx`: Thẻ VietQR chuẩn NAPAS với mã QR phóng to, chi tiết tài khoản thụ hưởng, các nút sao chép tiện lợi, hướng dẫn chuyển khoản và disclaimer rõ ràng; ẩn các khối thanh toán cho đơn miễn phí.
  - `PaymentStatusBadge.tsx`: Ẩn hoàn toàn sentinel `OTHER` ở UI client.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công với **0 lỗi**.
- [x] **Documentation**: Cập nhật đầy đủ `DB_v7.md`, `API_CONTRACT.md`, `PROJECT_STATE.md`.

### 0. Phase 4 — Orders + Payment (Backend + Frontend + Worker) [Đã Verified 100%]
- [x] **Database & Migrations**:
  - Tạo migration `b1c4e7f9a2d3_create_orders_order_items_and_status_history.py` tuân thủ nghiêm ngặt `DB_v7.md` §2.8, §2.9, §2.10: `payment_status_t` enum (`UNPAID`, `VERIFYING`, `PAID`), các bảng `orders`, `order_items`, `order_status_history`, database trigger `set_orders_updated_at` duy trì cột `updated_at`, toàn bộ check constraints (`chk_orders_amount_non_negative`, `chk_orders_payment_meetup_compat`, `chk_orders_fulfillment_fields`, `chk_order_items_price_non_negative`, `chk_order_items_quantity_positive`), physical unique constraint `ux_orders_order_code`.
  - Đã kiểm thử migration round-trip (`upgrade head` -> `downgrade -1` -> `upgrade head` -> `alembic check`).
  - `alembic check` báo `No new upgrade operations detected.`
- [x] **Backend Models & Schemas**:
  - Khởi tạo SQLAlchemy 2.x declarative models: `Order`, `OrderItem`, `OrderStatusHistory`, các Enums (`OrderStatus`, `PaymentStatus`, `PaymentMethod`, `FulfillmentMethod`, `CancelledBy`) với đầy đủ CheckConstraint & Index mappings.
  - DTOs `CreateOrderRequest`, `ConfirmOrderRequest`, `CancelOrderRequest`, `OrderItemResponse`, `OrderStatusHistoryResponse`, `OrderSummaryResponse`, `OrderDetailResponse`, `OrderCursorPage` với Pydantic v2 `extra="forbid"`.
- [x] **Backend Service & Repository**:
  - `OrderRepository` với keyset cursor pagination `(created_at, order_id) DESC`, savepoint-safe order code generation retry khi gặp `ux_orders_order_code` conflict, `get_order_by_id` dùng `selectinload` hỗ trợ `with_for_update()`.
  - `OrderService` với cơ chế lock dòng bi-directional `FOR UPDATE`, direct buy, seller confirm với bắt buộc `payment_note` cho BANK_TRANSFER, upload receipt cho buyer ở CONFIRMED, confirm payment theo từng phương thức, shipping delivery guard, complete order trừ tồn kho thực tế (`stock -= qty`, `reserved_stock -= qty`) và tự động dọn dẹp favorites khi `stock == 0`, hủy đơn miễn phí & có phí, isolated per-order background worker sweep.
- [x] **Backend Router & Endpoints (10 endpoints)**:
  - `POST /api/v1/orders`: Đặt mua trực tiếp (201).
  - `GET /api/v1/orders/me/buying`: Danh sách đơn mua (200).
  - `GET /api/v1/orders/me/selling`: Danh sách đơn bán (200).
  - `GET /api/v1/orders/{id}`: Xem chi tiết đơn hàng (200).
  - `POST /api/v1/orders/{id}/confirm`: Người bán xác nhận đơn (200).
  - `POST /api/v1/orders/{id}/receipt`: Người mua upload biên nhận (200).
  - `POST /api/v1/orders/{id}/confirm-payment`: Người bán xác nhận nhận tiền (200).
  - `POST /api/v1/orders/{id}/deliver`: Người bán bắt đầu giao hàng (200).
  - `POST /api/v1/orders/{id}/complete`: Hoàn tất đơn hàng (200).
  - `POST /api/v1/orders/{id}/cancel`: Hủy đơn hàng (200).
- [x] **Auto-Cancel Background Worker**:
  - `app/workers/order_auto_cancel.py`: Vòng lặp quét đơn quá hạn (`auto_cancel_at <= now()`) với session độc lập từng đơn, xử lý signal `SIGINT`/`SIGTERM` an toàn.
  - Cập nhật lệnh chạy worker trong `docker-compose.yml`: `python -m app.workers.order_auto_cancel`.
- [x] **Backend Test Suite**:
  - 4 test modules: `test_orders_crud.py` (12 tests), `test_orders_payment.py` (7 tests), `test_orders_concurrency.py` (2 tests concurrency không oversell và invariant guard), `test_orders_worker.py` (2 tests quét hủy tự động).
  - Toàn bộ backend test suite: **112/112 tests PASSED 100%**.
- [x] **Frontend Feature (`src/features/orders/`)**:
  - `types.ts`, `schemas.ts`, `api.ts`, `hooks.ts`.
  - Components: `OrderStatusBadge.tsx`, `PaymentStatusBadge.tsx`, `OrderCard.tsx`, `DirectPurchaseModal.tsx`, `ConfirmOrderModal.tsx`, `UploadReceiptModal.tsx`, `CancelOrderModal.tsx`.
  - Pages: `BuyingOrdersPage.tsx` (`/orders/buying`), `SellingOrdersPage.tsx` (`/orders/selling`), `OrderDetailPage.tsx` (`/orders/:orderId`).
  - Nâng cấp `ProductDetailPage.tsx`: Thêm CTA "Mua ngay", xử lý disable khi hết hàng đang giao dịch (`available_stock <= 0`), mở DirectPurchaseModal.
  - Nâng cấp `Header.tsx`: Thêm liên kết "Đơn mua của tôi" và "Đơn bán của tôi" trong menu drawer.
  - Đăng ký toàn bộ routes bảo vệ trong `App.tsx`.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công với **0 lỗi**.
- [x] **API Contract**: Cập nhật mục 6 trong `API_CONTRACT.md` ghi nhận đầy đủ 10 endpoints Orders & Payment.

### 1. Phase 3 — Favorites (Backend + Frontend) [Đã Verified]
- [x] **Database & Migrations**:
  - Tạo migration `a915fd3dfb98_create_favorites.py` tuân thủ nghiêm ngặt `DB_v7.md` §2.13: composite PK `(user_id, product_id)`, foreign keys trỏ tới `users(user_id)` và `products(product_id)` với `ON DELETE CASCADE`, index `ix_favorites_product_id`.
  - Đã kiểm thử migration round-trip (`upgrade head` -> `downgrade -1` -> `upgrade head` -> `alembic check`).
  - `alembic current` & `alembic heads` ở trạng thái `a915fd3dfb98 (head)`.
  - `alembic check` báo `No new upgrade operations detected.`
- [x] **Backend Models & Schemas**:
  - Khởi tạo SQLAlchemy 2.x declarative model `Favorite` (`app/modules/favorites/models.py`).
  - Khởi tạo DTOs `FavoriteProductResponse`, `FavoriteListResponse`, `FavoriteIdsResponse` với `extra="forbid"` (`app/modules/favorites/schemas.py`).
- [x] **Backend Service & Repository**:
  - `FavoriteRepository` với `INSERT ... ON CONFLICT DO NOTHING` lũy đẳng chống race condition, delete lũy đẳng, cursor-based pagination `(favorites.created_at, favorites.product_id)` DESC, và query `get_visible_favorite_ids` siêu nhẹ.
  - `FavoriteService` enforce domain visibility rules: chỉ cho phép lưu sản phẩm `status = 'AVAILABLE'` và `is_deleted = False`, 404 cho `HIDDEN`/`SOLD_OUT`/soft-deleted, cho phép người bán lưu sản phẩm của chính mình, delete không phụ thuộc availability.
- [x] **Backend Router & Endpoints (4 endpoints)**:
  - `POST /api/v1/favorites/{product_id}`: Lưu tin (204, idempotent).
  - `DELETE /api/v1/favorites/{product_id}`: Bỏ lưu tin (204, idempotent).
  - `GET /api/v1/favorites/ids`: Lấy danh sách ID đã lưu cho Set lookup O(1) (200, static route đặt trước dynamic route tránh collision).
  - `GET /api/v1/favorites`: Lấy danh sách tin đã lưu phân trang cursor (200).
- [x] **Backend Tests**:
  - Tạo test suite `tests/test_favorites.py` (19 test cases) bao phủ 100% các kịch bản: available product, duplicate idempotent, missing auth (401), banned/inactive (403), nonexistent/hidden/sold_out/deleted (404), seller favorite own product (204), unfavorite idempotent (204), unfavorite when product unavailable (204), user isolation, visibility exclusions, route collision safety, cursor pagination stability, và stock reduction partial purchase (7 -> 3) keeps favorite.
  - Toàn bộ test suite backend: **89/89 tests PASSED 100%**.
- [x] **Frontend Feature (`src/features/favorites/`)**:
  - `types.ts`, `api.ts`, `hooks.ts` với `useFavorites` (infinite query cursor), `useFavoriteIds` (Set<number> O(1) lookup), `useToggleFavorite` (optimistic update với rollback khi lỗi).
  - Nâng cấp `ProductCard.tsx`: chuyển tim trang trí thành nút bấm lưu tin thật có `stopPropagation`/`preventDefault`, visual state rõ ràng, accessible labeling.
  - Nâng cấp `ProductDetailPage.tsx`: bổ sung nút lưu tin ở thanh điều hướng trên cùng, dùng chung mutation state.
  - Triển khai `FavoritesPage.tsx` (`/favorites`): trang danh sách tin đã lưu với responsive grid, infinite scroll sentinel, loading skeletons, error retry, và empty state thân thiện.
  - Nâng cấp `Header.tsx`: menu drawer bổ sung mục "Tin đã lưu" (`/favorites`) cho tài khoản đã đăng nhập, bảo tồn 100% fixed/sticky geometry.
  - Đăng ký route `/favorites` bảo vệ bởi `<ProtectedRoute>` trong `App.tsx`.
  - Cập nhật `.heart-btn` micro-animations trong `index.css`.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công với **0 lỗi**.
- [x] **API Contract**: Cập nhật mục 5 trong `API_CONTRACT.md` ghi nhận đầy đủ 4 endpoints Favorites.

## Đã hoàn thành

### 1. Cross-Layer Refactor — Loại bỏ hoàn toàn `item_condition`
- [x] **Database & Migrations**: Cập nhật `DB_v7.md` loại bỏ cột `item_condition` và check constraint `chk_products_item_condition` khỏi bảng `products`. Tạo migration `8b242495fd1d_remove_products_item_condition.py` (kèm chiến lược downgrade backfill an toàn). Đã kiểm thử migration round-trip (`upgrade head` -> `downgrade -1` -> `upgrade head` -> `alembic check`).
- [x] **Backend Models & Schemas**: Xoá `ItemCondition` enum, column mapping, và check constraint trong `models.py`. Loại bỏ `item_condition` khỏi toàn bộ DTOs (`ProductCreate`, `ProductUpdate`, `ProductSummaryResponse`, `ProductDetailResponse`, `SellerProductResponse`) với `extra="forbid"`.
- [x] **Backend Service, Repository & Router**: Loại bỏ bộ lọc `item_condition` khỏi repository query `list_public`, service layer mapping, và router query params `GET /api/v1/products`.
- [x] **Backend Tests**: Cập nhật toàn bộ test fixtures trong `test_products_crud.py`, `test_products_list.py`, `test_products_detail.py`, `test_product_images.py`. Bổ sung regression tests kiểm tra reject 422 khi client gửi `item_condition` và kiểm tra response không chứa field. Toàn bộ **54/54 tests PASSED**.
- [x] **API Contract**: Cập nhật `API_CONTRACT.md` loại bỏ `item_condition` khỏi query params, request bodies, và response examples.
- [x] **Frontend Types & Schemas**: Xoá type `ItemCondition` và field `item_condition` khỏi toàn bộ TypeScript interfaces trong `types.ts` và Zod schemas trong `schemas.ts`.
- [x] **Frontend Formatters & API**: Xoá `getItemConditionMeta` trong `formatters.ts`, xoá query param trong `api.ts`.
- [x] **Frontend UI & Forms**: Xoá hoàn toàn section bộ lọc "TÌNH TRẠNG" trong `ProductFilters.tsx`, xoá condition badges khỏi `ProductCard.tsx`, `SellerProductCard.tsx`, `ProductDetailPage.tsx`, xoá radio selection khỏi `ProductForm.tsx` và cập nhật placeholder mô tả thân thiện (`"Mô tả chi tiết sản phẩm, tình trạng thực tế, phụ kiện đi kèm, lý do bán..."`). Loại bỏ `item_condition` khỏi URL params sync trong `HomePage.tsx`.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công 100% với **0 lỗi**.

### 2. Frontend — Phase 2B (Categories, Products, Images, Search, Filters, Seller Management)
- [x] Tạo `src/lib/formatters.ts` tập trung format tiền tệ VND an toàn (`formatVND`), thời gian tương đối (`formatRelativeTime`), ngày tháng (`formatDate`), hình thức bán (`getListingTypeMeta`), và trạng thái tin (`getProductStatusMeta`).
- [x] Triển khai feature `src/features/categories/` (`types.ts`, `api.ts`, `hooks.ts`) với `useCategories()` và hierarchical query keys.
- [x] Triển khai feature `src/features/products/` (`types.ts`, `schemas.ts`, `api.ts`, `hooks.ts`) kết nối đầy đủ **12 endpoints** của Phase 2:
  - Categories (2): `GET /api/v1/categories`, `GET /api/v1/categories/{id}`
  - Public Products (2): `GET /api/v1/products` (Keyset cursor pagination, search `q`, filters), `GET /api/v1/products/{id}`
  - Seller Management (4): `GET /api/v1/products/me`, `POST /api/v1/products`, `PATCH /api/v1/products/{id}`, `DELETE /api/v1/products/{id}`
  - Product Images (4): `POST /api/v1/products/{id}/images/upload`, `DELETE /api/v1/products/{id}/images/{img_id}`, `PATCH /api/v1/products/{id}/images/{img_id}/thumbnail`, `PUT /api/v1/products/{id}/images/reorder`
- [x] Triển khai bộ components sản phẩm chất lượng cao:
  - `ProductCard.tsx`: Thumbnail `w_200`, giá, danh mục, badge Đấu giá nếu có, seller avatar, decorative heart.
  - `ProductFeedSection.tsx`: Feed sản phẩm kèm `useInfiniteQuery` keyset cursor, Sentinel `IntersectionObserver` tự động nạp trang kế tiếp, fallback button, loading skeletons, error retry UI, empty states.
  - `ProductFilters.tsx`: Bottom sheet lọc theo khoảng giá min/max, hình thức bán (Fixed Price / Auction).
  - `ProductImageGallery.tsx`: Gallery xem ảnh chi tiết với transformed `detail_url` (`w_800`), slider điều hướng và thumbnail strip.
  - `ProductImageManager.tsx`: Upload ảnh song song có kiểm soát (`concurrency = 2`), hàng đợi với trạng thái từng file (`queued`, `uploading`, `success`, `error`), nút Retry riêng từng ảnh, dọn dẹp bộ nhớ `URL.revokeObjectURL`, sắp xếp thứ tự ảnh (`←` / `→`), đặt ảnh chính, xóa ảnh.
  - `ProductForm.tsx`: Form dùng chung cho Create và Edit với Zod validation, tự động điền danh mục từ backend, tuân thủ chính sách Phase 2B (Create mặc định `FIXED_PRICE`, Edit không đổi `listing_type`, hỗ trợ chuyển trạng thái `AVAILABLE <-> HIDDEN`).
  - `SellerProductCard.tsx`: Quản lý tin đăng hiển thị tồn kho (`stock`, `reserved_stock`, `available_stock`), toggle nhanh ẩn/hiện tin, sửa, xóa với xác nhận.
- [x] Triển khai các trang (Pages):
  - `ProductDetailPage.tsx` (`/products/:productId`): Chi tiết sản phẩm, gallery ảnh, thông tin người bán, khu vực giao dịch, nút quản lý nhanh nếu là chủ sở hữu.
  - `CreateProductPage.tsx` (`/products/new`): Luồng 2 bước mượt mà (Bước 1: Điền thông tin -> Bước 2: Tải ảnh sản phẩm).
  - `EditProductPage.tsx` (`/products/:productId/edit`): Chỉnh sửa thông tin, giá, tồn kho, trạng thái và quản lý ảnh.
  - `MyProductsPage.tsx` (`/my-products`): Quản lý tin theo tabs (Tất cả, Đang bán, Đã ẩn, Đã bán), nút Đăng tin mới.
- [x] Nâng cấp `Header.tsx`: Chế độ tìm kiếm inline chiếm trọn container `h-14` (chiều cao document-flow cố định 56px, triệt tiêu nguy cơ xô lệch sticky bar), menu drawer bổ sung "Đăng tin bán" và "Quản lý tin đăng".
- [x] Nâng cấp `CategoryBar.tsx` & `HomePage.tsx`: CategoryBar lấy danh mục thật từ backend + tab "Dành cho bạn" (`category_id = undefined`), sticky `top-14 pt-0` bám sát mép dưới Header không khe hở. Đồng bộ URL search params `q`, `category_id`, `listing_type`, `min_price`, `max_price`.
- [x] Đăng ký toàn bộ routes mới trong `src/app/App.tsx`.

### 3. Backend — Phase 2A (Categories, Products, Product Images, Cloudinary) [Đã Verified]
- [x] Khởi tạo SQLAlchemy 2.x declarative models cho `Category`, `Product`, `ProductImage` tuân thủ nghiêm ngặt `DB_v7.md`.
- [x] Alembic migration `3d2ea1176b6a_create_categories_products_product_.py` bao gồm GIN full-text index `ix_products_search_gin`.
- [x] Endpoints Categories, Products, Seller Management, Cloudinary Image Management (12 endpoints).
- [x] Pytest suite: **54/54 tests PASSED**.

### 4. Backend & Frontend — Phase 1 (Auth + Users) [Đã Verified]
- [x] Firebase Google Sign-In frontend, AuthContext, Axios interceptor với token refresh.
- [x] ProfilePage chỉnh sửa thông tin cá nhân.
- [x] Endpoints `GET /api/v1/users/me` và `PATCH /api/v1/users/me`.

### 5. Backend — Cloudinary Folder Namespace Standardization [Đã Verified]
- [x] Cấu hình `CLOUDINARY_ROOT_FOLDER=student-marketplace` trong `app/core/config.py` và `.env.example`.
- [x] Chuẩn hóa integration layer `app/integrations/cloudinary.py`:
  - Thêm helper phân giải folder `get_cloudinary_folder(folder_key)` cho `Literal["products"]`.
  - Phân giải `products` -> `student-marketplace/products`.
  - Tự động chuẩn hóa root folder, tránh duplicate slashes.
- [x] Cập nhật `ProductService.upload_product_image` gọi `upload_image(file_bytes, folder_key="products")`.
- [x] Sửa lỗi thụt lề environment service `worker` trong `docker-compose.yml`, kiểm tra `docker compose config` hợp lệ 100%.
- [x] Bổ sung suite `tests/test_cloudinary.py` (12 tests) và cập nhật `tests/test_product_images.py` (11 tests). Toàn bộ **23/23 tests PASSED**.
- [x] Live end-to-end verification: Upload ảnh thực tế lên Cloudinary vào đúng thư mục `student-marketplace/products`, kiểm tra URL, responsive transformations (`w_200`, `w_800`), lưu DB `product_images` và dọn dẹp asset thành công.

### 6. Frontend — Product Image Upload Queue Bug Fix [Đã Verified]
- [x] **Root Cause**: Hàm `processUploadQueue` trong `ProductImageManager.tsx` sử dụng anti-pattern `setUploadQueue((prev) => { currentQueue = prev; return prev; })`. Trong React 18 / batching, callback updater được lên lịch bất đồng bộ, dẫn đến biến `currentQueue` luôn rỗng (`[]`), `nextQueued` luôn `undefined`, vòng lặp thoát ngay lập tức và `uploadMutation.mutate` không bao giờ được kích hoạt khiến file kẹt ở `"Đang chờ..."`.
- [x] **Giải pháp & Kiến trúc Queue mới**:
  - Chuyển sang mô hình điều phối khai báo (declarative dispatcher) với `activeUploadsRef` (`useRef<Set<string>>`) theo dõi các item đang upload độc lập.
  - Áp dụng kiểm soát concurrency = 2 chuẩn xác (`availableSlots = 2 - uploadingCount`).
  - Gọi trực tiếp `uploadProductImage(productId, file)` qua Axios instance chia sẻ `apiClient` (được gắn kèm Firebase ID Token qua interceptor).
  - Tự động thu hồi object URL (`URL.revokeObjectURL`) khi upload thành công hoặc khi unmount.
  - Tự động invalidate và làm mới query cache (`productKeys.detail(productId)`, `productKeys.myLists()`, `productKeys.publicLists()`).
  - Hỗ trợ đầy đủ trạng thái `queued` ("Đang chờ..."), `uploading` ("Đang tải..."), `success` ("Đã tải lên"), `error` ("Upload ảnh thất bại") kèm nút Thử lại (Retry) và Hủy bỏ (Remove).
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công 100% với **0 lỗi**.

### 7. Backend — Product-Scoped Cloudinary Folders [Đã Verified]
- [x] Thêm helper `get_product_cloudinary_folder(product_id: int) -> str` trong `app/integrations/cloudinary.py` phân giải theo quy ước:
  $$\text{student-marketplace/products/product-}\{\text{product\_id}\}$$
- [x] Cập nhật `upload_image` nhận `product_id: Optional[int] = None` và tự động phân giải thư mục scoped khi `folder_key="products"`.
- [x] Cập nhật `ProductService.upload_product_image` truyền `product_id=product_id` vào `upload_image`.
- [x] Giữ nguyên toàn bộ existing assets cũ (không migration/delete ảnh cũ).
- [x] Pytest suite: Mở rộng `tests/test_cloudinary.py`, toàn bộ tests PASSED.
- [x] Live end-to-end verification: Thử nghiệm upload đồng thời cho 2 product khác nhau (`product-692` và `product-693`), xác nhận các asset được lưu cô lập vào đúng thư mục con tương ứng và dọn dẹp compensation thành công.

### 8. Frontend — Sticky Seller Management Controls [Đã Verified]
- [x] Triển khai thanh điều khiển sticky `top-14` (56px) trên trang `MyProductsPage.tsx`:
  - Giữ nguyên tiêu đề và mô tả trong normal document flow.
  - Đưa bộ lọc trạng thái (`filterTabs`: Tất cả, Đang bán, Đã ẩn, Đã bán) và nút `Đăng tin mới` vào thanh sticky `top-14 z-40 bg-brand-cream isolate -mx-4 px-4 py-2`.
  - Tích hợp `IntersectionObserver` sentinel với `rootMargin: '-56px 0px 0px 0px'` để tự động kích hoạt `shadow-sticky` và `border-b border-brand-border/70` khi thanh điều khiển chạm mép dưới Header, đảm bảo **0px gap**, không layout shift và không lộ content khi scroll.
  - Tối ưu mobile-first (`flex items-center justify-between gap-2`): filter chips cuộn ngang mượt mà (`overflow-x-auto hide-scrollbar`), nút Đăng tin luôn cố định ở góc phải, hiển thị `"Đăng tin mới"` trên desktop và `"Đăng tin"` trên mobile.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công 100% với **0 lỗi**.

### 9. Frontend — Product Price Validation & Mobile Header Stability Fix [Đã Verified]
- [x] **Product Price Validation (BUG A)**:
  - Cập nhật `productCreateSchema` và `productUpdateSchema` với `z.preprocess` phân biệt rõ ràng chuỗi rỗng `""` / whitespace / `undefined` với số `0`.
  - Chặn submit khi bỏ trống giá với thông báo: `"Vui lòng nhập giá. Nhập 0 nếu muốn cho miễn phí."`.
  - Chặn giá âm với thông báo: `"Giá không được nhỏ hơn 0."`.
  - Cho phép giá `0` (Miễn phí) hợp lệ khi tạo hoặc sửa.
  - Cập nhật `ProductForm.tsx` hiển thị helper text `"Nhập 0 nếu muốn cho miễn phí."` và khởi tạo đúng giá trị `0` khi edit.
  - Cập nhật `formatVND` trong `src/lib/formatters.ts` tự động render nhãn `"Miễn phí"` trên `ProductCard`, `SellerProductCard` và `ProductDetailPage` khi `price === 0`.
- [x] **Mobile Header Stability (BUG B)**:
  - Khóa cứng layer đồ họa độc lập cho `<header>` bằng `isolate [transform:translateZ(0)] [backface-visibility:hidden]`.
  - Chuẩn hóa typography phần wordmark logo (loại bỏ `leading-[0.8]` và `mt-[1px]`, chuyển sang `leading-none pt-0.5 select-none`) để triệt tiêu hoàn toàn hiện tượng lệch 1px do subpixel rasterization trên mobile.
  - Thu hẹp `transition-all` trên các secondary sticky chips sang `transition-colors` / `transition-shadow`.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công 100% với **0 lỗi**.

### 10. Frontend — Product Title Overflow & Fixed Header Stability [Đã Verified]
- [x] **Product Detail Title Overflow (BUG 1)**:
  - Bổ sung `min-w-0 max-w-full break-words [overflow-wrap:anywhere]` vào `<h1>` và container cha trong `ProductDetailPage.tsx`.
  - Bổ sung phòng thủ `break-words [overflow-wrap:anywhere] min-w-0` vào `ProductCard.tsx` và `SellerProductCard.tsx`.
  - Đảm bảo các chuỗi liên tục dài không có khoảng trắng (như `sdssssssssssssssssssss...`) tự động xuống dòng gọn gàng trong card, không gây tràn ngang (`scrollWidth === clientWidth`) và không làm xô lệch giá bán/badge.
- [x] **Mobile Header Stability (BUG 2)**:
  - Chuyển `Header` sang kiến trúc `position: fixed` (`fixed top-0 inset-x-0 z-50 h-14 bg-brand-burgundy px-4 shadow-header`) đi kèm document flow spacer `h-14 w-full shrink-0`.
  - Khóa cứng Header vào tọa độ tuyệt đối của viewport (`top: 0`), triệt tiêu 100% việc tính toán lại bounding box hay subpixel rounding khi cuộn trang.
  - Các secondary sticky layers (`CategoryBar` trên HomePage, Seller management toolbar trên MyProductsPage) giữ nguyên `sticky top-14 z-40`, bám sát mép dưới của Fixed Header với **0px gap**, **0px overlap** và **0px jitter**.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công 100% với **0 lỗi**.

### 11. Frontend — Secondary Sticky Invariant Geometry Fix [Đã Verified]
- [x] **Secondary Sticky Jitter Fix (HomePage CategoryBar & MyProducts Toolbar)**:
  - Loại bỏ hoàn toàn `IntersectionObserver`, sentinel `h-0` và state `isSticky` gây hysteresis layout flutter (vòng lặp tăng/giảm 1px chiều cao khi thêm `border-b` ở ranh giới cuộn).
  - Cố định box model bất biến với `border-b border-brand-border/60` từ thời điểm render đầu tiên; kích thước và padding không bao giờ thay đổi giữa các frame.
  - Sử dụng pixel nguyên tuyệt đối `top-[56px]` cho secondary sticky và `h-[56px]` cho Fixed Header/Spacer để triệt tiêu hoàn toàn sai số làm tròn subpixel trên các màn hình có DPR lẻ.
  - Vị trí pinned của secondary sticky luôn luôn là **chính xác 56px** trên mọi frame, **0px gap**, **0px overlap**, **0px jitter**.
- [x] **Frontend Build**: `npm run build` (`tsc -b && vite build`) hoàn thành thành công 100% với **0 lỗi**.

## Quyết định thiết kế quan trọng
- **Invariant Sticky Geometry Architecture**: Mọi sticky layer phải có kích thước và box-model bất biến (chiều cao, padding, border-width không được thay đổi theo trạng thái cuộn) để ngăn chặn hiện tượng hysteresis loop.
- **Fixed Header with Spacer Architecture**: Sử dụng `position: fixed` kết hợp document flow spacer 56px (`h-[56px]`) đảm bảo Header hoàn toàn đứng yên (visually locked) trong mọi điều kiện cuộn trên mobile/desktop, đồng thời giữ vững quy tắc bám dính 0px gap cho các secondary sticky container bên dưới.
- **Defensive Text Wrapping**: Áp dụng `min-w-0 break-words [overflow-wrap:anywhere]` cho toàn bộ các tiêu đề động nhằm bảo vệ layout trên các màn hình hẹp (360px - 430px) khi người dùng nhập chuỗi liên tục không có dấu cách.
- **Price Preprocessing**: Sử dụng `z.preprocess` cho các trường số dạng input text/number để ngăn chặn anti-pattern `z.coerce.number()` biến `""` thành `0`.
- **Seller Management Sticky Bar**: Đảm bảo trải nghiệm quản lý tin đăng liền mạch khi danh sách tin dài, cho phép seller đổi filter trạng thái và tạo tin mới bất kỳ lúc nào mà không cần cuộn ngược về đầu trang.
- **Product-Scoped Cloudinary Folder**: Phân tách rõ ràng asset theo từng sản phẩm:
  - `student-marketplace/products/product-{product_id}` cho ảnh sản phẩm.
  - Giúp quản trị asset dễ dàng, không gây lẫn lộn giữa các sản phẩm khi số lượng listing tăng cao.
- **User Avatars Architecture**:
  - User avatars are derived from verified Google/Firebase identity data and cached in `users.avatar_url`.
  - The application does not provide custom avatar uploads.
  - Cloudinary is used for product images only.
- **Declarative Upload Queue Architecture**: Sử dụng `activeUploadsRef` kết hợp `useEffect` điều phối concurrency = 2 thay vì synchronous setState mutation loops, triệt tiêu hoàn toàn nguy cơ stale closure, duplicate upload và infinite pending.
- **Loại bỏ item_condition**: Đã loại bỏ hoàn toàn khái niệm `item_condition` (và các giá trị NEW_99, USED_GOOD, USED_FAIR) khỏi toàn bộ hệ thống để tối ưu trải nghiệm mobile-first; tình trạng thực tế của sản phẩm được mô tả linh hoạt trong `description`.
- **Header Search & Sticky Stability**: Header giữ nguyên chiều cao `h-14` (56px) cả khi mở hoặc đóng Search mode; CategoryBar sticky tại `top-14 pt-0` bám sát mép dưới Header đảm bảo 0px gap và 0px layout shift trên mọi viewport.
- **Listing Type Policy**: Phase 2B chỉ cho phép tạo tin với `FIXED_PRICE`. Form Edit không gửi `listing_type`. Nếu có record `AUCTION` trong DB, frontend render dưới dạng badge "Đấu giá" và nhãn "Giá khởi điểm" (read-only), không tạo các chức năng đấu giá giả trước Phase 5.
- **Image Upload Controlled Concurrency**: Hàng đợi upload song song tối đa 2 ảnh cùng lúc, có feedback trạng thái từng ảnh và dọn dẹp bộ nhớ `URL.revokeObjectURL`.
- **Hierarchical Query Invalidation**: Sử dụng query key factory phân cấp giúp các mutations tự động làm mới chính xác các danh sách public và danh sách seller mà không làm bẩn cache toàn cục.
- **Favorites Idempotency & Set Lookup Architecture**:
  - Endpoint `GET /api/v1/favorites/ids` trả về danh sách ID đang AVAILABLE phục vụ việc dựng `Set<number>` phía client, kiểm tra tim $O(1)$ mà không phát sinh N+1 API calls và không làm bẩn public `ProductSummaryResponse` DTO.
  - Sử dụng `INSERT ... ON CONFLICT DO NOTHING` trên composite PK `(user_id, product_id)` để đảm bảo thao tác favorite có tính lũy đẳng tuyệt đối, an toàn trước race condition / duplicate requests đồng thời.

## Trạng thái kiểm thử
- Frontend Build: **Passed** (`npm run build` with 0 errors)
- Full Pytest Regression Suite: **221/221 passed 100%** (pytest `tests/`)
- User Profile & Public Profile Tests: **7/7 passed** (pytest `tests/test_user_profile.py`)
- Order Transaction Terms & Expected Time Tests: **26/26 passed** (pytest `tests/test_order_transaction_terms.py`)
- Realtime Orders WebSocket Suite: **9/9 passed** (pytest `tests/test_orders_realtime_ws.py`)
- Alembic Migration Round-Trip & Check: **Passed** (`upgrade head` -> `downgrade -1` -> `upgrade head` -> `alembic check` - No new upgrade operations detected)
- Profile Coverage Simplification: **VERIFIED 100%**

## Hồ sơ & Phạm vi giao nhận (Profile Coverage Simplification)
- Loại bỏ hoàn toàn khái niệm "Điểm hẹn mặc định" / "Khu vực hẹn gặp mặc định" khỏi giao diện người dùng và luồng tạo đơn hàng.
- Thống nhất duy nhất một khái niệm khu vực trên Profile: "Phạm vi giao / nhận hàng" (`delivery_area`), mang tính chất thông tin khu vực hoạt động chung (VD: `Hà Đông, Thanh Xuân, Cầu Giấy`).
- Cung cấp endpoint công khai `GET /api/v1/users/{user_id}` và trang `/users/:userId` hiển thị thông tin hồ sơ công khai (tên, avatar, bio, phạm vi giao / nhận, ngày tham gia) mà không làm lộ các dữ liệu riêng tư (email, SĐT, ngân hàng, địa chỉ đơn hàng).
- Địa điểm hẹn gặp cụ thể (`meetup_place`) và địa chỉ giao hàng (`shipping_address`) được nhập trực tiếp, độc lập theo từng đơn hàng cụ thể, không phụ thuộc vào Profile.

## Giao nhận & Transaction Terms (Order Fulfillment UX)
- Single edit entry point: Nút "Chỉnh sửa" duy nhất nằm trong header card GIAO NHẬN; đã loại bỏ nút edit thừa ở top action bar.
- Stacked mobile-friendly layout cho thông tin Người nhận (tên và số điện thoại chia dòng mạch lạc, không bị đẩy tràn sang phải).
- Format thời gian hẹn / giao dự kiến dạng chuẩn tiếng Việt `12:35, 30/08/2026`, tuyệt đối không bao giờ hiển thị chuỗi ISO thô.
- Hỗ trợ thời gian dự kiến tùy chọn cho cả MEETUP (`meetup_time`) và SHIPPING (`shipping_expected_at`), tự động dọn dẹp giá trị không thuộc hình thức khi chuyển đổi.
- Ẩn hoàn toàn dòng thời gian khi giá trị là NULL.

## Vấn đề đã biết (Known Issues)
- Không có lỗi tồn đọng. Hệ thống ổn định 100%.

