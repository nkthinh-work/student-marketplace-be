# THIẾT KẾ DATABASE — Marketplace C2C Sinh viên v7 (PostgreSQL)

## 0. Mục đích và quyết định chuẩn hoá

Tài liệu này là **nguồn chuẩn duy nhất (source of truth)** cho schema cơ sở dữ liệu quan hệ dùng chung bởi các backend của hệ thống Marketplace C2C.

- RDBMS: PostgreSQL 15+.
- Mục tiêu thiết kế cơ sở: 3NF.
- Định danh nghiệp vụ: `users.user_id` là khoá chính nội bộ được mọi FK nghiệp vụ sử dụng.
- Xác thực: Firebase Authentication.
- Danh tính Firebase bên ngoài được tách riêng trong `user_auth_identities`.
- Việc giữ một `firebase_uid` UNIQUE trong `users` tự nó không vi phạm 3NF vì thuộc tính UNIQUE có thể là candidate key. Tuy nhiên dự án vẫn tách identity vì danh tính xác thực là trách nhiệm khác với hồ sơ nghiệp vụ marketplace và cách tách này cho phép bổ sung nhà cung cấp danh tính khác về sau.
- Không lưu password hoặc password hash trong PostgreSQL.
- Blob ảnh/file được lưu ở Cloudinary; PostgreSQL chỉ lưu URL và metadata.
- Schema không phụ thuộc vào dạng client.
- Tối ưu mobile-first như kích thước ảnh responsive, payload gọn và cursor pagination thuộc tầng API/integration theo `TechStack_v2.md` §4.5, không yêu cầu thêm bảng riêng cho mobile.
- Người dùng có thể lưu tin bằng `favorites`; luồng mua bắt đầu trực tiếp từ chi tiết sản phẩm.
- Đấu giá là một chế độ bán của tin sản phẩm, không phải một loại sản phẩm riêng.

### Database dùng chung / độc lập với implementation

- Database được dùng chung cho backend hiện tại và các backend có thể xuất hiện trong tương lai.
- Backend hiện tại dùng Python/FastAPI.
- Backend Spring Boot trong tương lai có thể dùng cùng PostgreSQL schema.
- Schema database PHẢI độc lập với framework backend.
- Tài liệu này chỉ định nghĩa relational/domain schema và không được phụ thuộc vào FastAPI, Spring Boot hoặc framework cụ thể.

## 1. Danh sách bảng

Schema hiện có **17 bảng**:

1. `users`
2. `user_auth_identities`
3. `categories`
4. `products`
5. `product_images`
6. `orders`
7. `order_items`
8. `order_status_history`
9. `conversations`
10. `messages`
11. `message_attachments`
12. `reviews`
13. `favorites`
14. `auctions`
15. `auction_bids`
16. `notifications`
17. `reports`

Giỏ hàng không thuộc phạm vi hệ thống; không định nghĩa bảng `cart_items`.

## 2. Schema chính

### 2.1. users

Dữ liệu hồ sơ/nghiệp vụ của người dùng và quản trị viên marketplace. Dữ liệu xác thực thuộc `user_auth_identities`.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `user_id` | BIGINT IDENTITY | NO | auto | PK |
| `email` | VARCHAR(150) | NO | - | UNIQUE; email liên hệ/ứng dụng |
| `full_name` | VARCHAR(100) | NO | - | |
| `phone` | VARCHAR(20) | YES | - | Bắt buộc trước khi đăng bán hoặc tham gia giao dịch cần liên hệ |
| `avatar_url` | VARCHAR(500) | YES | - | Cloudinary |
| `bio` | VARCHAR(500) | YES | - | |
| `default_meetup_area` | VARCHAR(255) | YES | - | |
| `role` | VARCHAR(10) + CHECK | NO | `STUDENT` | `STUDENT` / `ADMIN` |
| `status` | `user_status` ENUM | NO | `ACTIVE` | `ACTIVE` / `BANNED` / `INACTIVE` |
| `last_active_at` | TIMESTAMP | YES | - | |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

### 2.2. user_auth_identities

Ánh xạ một user nội bộ với danh tính xác thực bên ngoài.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `user_auth_identity_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_id` | BIGINT | NO | - | FK -> users; UNIQUE cho mapping 1:1 hiện tại |
| `provider` | VARCHAR(30) | NO | `FIREBASE` | CHECK IN (`FIREBASE`) trong release hiện tại |
| `provider_uid` | VARCHAR(128) | NO | - | Firebase project UID; UNIQUE theo provider |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

Quy tắc:

- Không bao giờ nhận `provider_uid` từ client như bằng chứng xác thực.
- Backend phải verify Firebase ID token trước, lấy Firebase UID đã được xác thực, sau đó tra `user_auth_identities`.
- Mọi FK nghiệp vụ trỏ tới `users.user_id`, không trỏ tới Firebase UID.
- Không lưu password, refresh token, service-account secret hoặc Firebase secret khác trong PostgreSQL.

### 2.3. categories

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `category_id` | INT IDENTITY | NO | auto | PK |
| `name` | VARCHAR(100) | NO | - | |
| `slug` | VARCHAR(120) | NO | - | UNIQUE khi chưa bị xoá mềm qua partial index |
| `is_deleted` | BOOLEAN | NO | FALSE | soft delete |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.4. products

`products` đại diện cho tin đăng bán hàng. Tên cột tồn kho chuẩn của dự án là `stock`, không phải `quantity`. `quantity` chỉ dùng ở cấp dòng đơn hàng.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `product_id` | BIGINT IDENTITY | NO | auto | PK |
| `seller_id` | BIGINT | NO | - | FK -> users RESTRICT |
| `category_id` | INT | NO | - | FK -> categories |
| `title` | VARCHAR(255) | NO | - | |
| `description` | TEXT | YES | - | |
| `listing_type` | VARCHAR(12) + CHECK | NO | `FIXED_PRICE` | `FIXED_PRICE` / `AUCTION` |
| `price` | DECIMAL(12,0) | NO | - | Giá bán khi `FIXED_PRICE`; giá khởi điểm khi `AUCTION`; CHECK >= 0 |
| `stock` | INT | NO | 1 | Số lượng hàng hiện có; CHECK >= 0 |
| `reserved_stock` | INT | NO | 0 | Số lượng đang được giữ cho giao dịch; CHECK 0 <= reserved_stock <= stock |
| `status` | VARCHAR(10) + CHECK | NO | - | `AVAILABLE` / `HIDDEN` / `SOLD_OUT` |
| `view_count` | INT | NO | 0 | projection đồng bộ từ Redis |
| `is_deleted` | BOOLEAN | NO | FALSE | soft delete |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

Quy tắc ý nghĩa:

- Với `FIXED_PRICE`, người dùng mua trực tiếp từ tin; không đi qua giỏ hàng.
- Với `AUCTION`, `products.price` là **giá khởi điểm**, không phải giá thắng cuối cùng.
- Điều kiện `stock = 1`, `reserved_stock = 0`, `status = AVAILABLE`, `is_deleted = FALSE` được kiểm tra khi **bật/kích hoạt đấu giá** ở service layer.
- MVP không áp dụng ngưỡng giá khởi điểm tối thiểu cố định cho đấu giá. Mọi sản phẩm đủ điều kiện về trạng thái và tồn kho đều có thể được bật đấu giá, không phụ thuộc giá trị sản phẩm.
- Không đặt CHECK cứng `stock = 1` cho mọi bản ghi `AUCTION` vì sau khi giao dịch hoàn tất tồn kho hợp lệ có thể giảm về `0` trong khi lịch sử tin vẫn là đấu giá.

### 2.5. product_images

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `image_id` | BIGINT IDENTITY | NO | auto | PK |
| `product_id` | BIGINT | NO | - | FK -> products CASCADE |
| `image_url` | VARCHAR(500) | NO | - | Cloudinary |
| `sort_order` | SMALLINT | NO | 0 | |
| `is_thumbnail` | BOOLEAN | NO | FALSE | partial UNIQUE: tối đa một thumbnail/product |

### 2.6. orders

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `order_id` | BIGINT IDENTITY | NO | auto | PK |
| `order_code` | VARCHAR(20) | NO | - | UNIQUE, mã tham chiếu VietQR/chuyển khoản |
| `buyer_id` | BIGINT | NO | - | FK -> users RESTRICT |
| `seller_id` | BIGINT | NO | - | FK -> users RESTRICT |
| `status` | VARCHAR(12) + CHECK | NO | `PENDING` | `PENDING` / `CONFIRMED` / `DELIVERING` / `COMPLETED` / `CANCELLED` |
| `payment_method` | VARCHAR(20) + CHECK | NO | `CASH_ON_MEETUP` | `CASH_ON_MEETUP` / `BANK_TRANSFER` / `OTHER` |
| `payment_status` | `payment_status_t` ENUM | NO | `UNPAID` | `UNPAID` / `VERIFYING` / `PAID` |
| `payment_receipt_url` | VARCHAR(500) | YES | - | Cloudinary; biên nhận người mua |
| `receipt_uploaded_at` | TIMESTAMP | YES | - | |
| `paid_confirmed_at` | TIMESTAMP | YES | - | thời điểm người bán xác nhận đã nhận tiền |
| `payment_note` | VARCHAR(255) | YES | - | |
| `fulfillment_method` | VARCHAR(10) + CHECK | NO | `MEETUP` | `MEETUP` / `SHIPPING` |
| `meetup_place` | VARCHAR(255) | YES | - | |
| `meetup_time` | TIMESTAMP | YES | - | |
| `shipping_address` | VARCHAR(500) | YES | - | dùng khi `SHIPPING` |
| `contact_name` | VARCHAR(100) | NO | - | snapshot; không join vào profile có thể thay đổi |
| `contact_phone` | VARCHAR(20) | NO | - | snapshot |
| `buyer_note` | VARCHAR(500) | YES | - | |
| `total_amount` | DECIMAL(12,0) | NO | - | snapshot = tổng các item snapshot |
| `auto_cancel_at` | TIMESTAMP | YES | - | hạn xác nhận của người bán |
| `confirmed_at` | TIMESTAMP | YES | - | |
| `completed_at` | TIMESTAMP | YES | - | |
| `cancelled_at` | TIMESTAMP | YES | - | |
| `cancelled_by` | VARCHAR(10) + CHECK | YES | - | `BUYER` / `SELLER` / `SYSTEM` |
| `cancel_reason` | VARCHAR(255) | YES | - | |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

Luồng mua:

- Sản phẩm `FIXED_PRICE`: tạo order trực tiếp với số lượng người mua chọn, sau khi kiểm tra `stock - reserved_stock`.
- Sản phẩm `AUCTION`: chỉ người thắng mới được tạo order sau khi đấu giá kết thúc; `quantity` bắt buộc bằng `1` và `price_at_purchase` phải bằng `auctions.final_price`.
- Khi người thắng đấu giá đã được giữ một đơn vị bằng `reserved_stock = 1`, bước tạo order từ kết quả đấu giá **không được tăng giữ hàng lần thứ hai**; service phải chuyển reservation hiện có sang order trong cùng transaction.

### 2.7. order_items

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `order_item_id` | BIGINT IDENTITY | NO | auto | PK |
| `order_id` | BIGINT | NO | - | FK -> orders CASCADE |
| `product_id` | BIGINT | NO | - | FK -> products RESTRICT |
| `product_title` | VARCHAR(255) | NO | - | snapshot bất biến tại thời điểm mua |
| `product_image_url` | VARCHAR(500) | YES | - | snapshot bất biến |
| `quantity` | INT | NO | 1 | CHECK > 0 |
| `price_at_purchase` | DECIMAL(12,0) | NO | - | CHECK >= 0 |

### 2.8. order_status_history

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `history_id` | BIGINT IDENTITY | NO | auto | PK |
| `order_id` | BIGINT | NO | - | FK -> orders CASCADE |
| `from_status` | VARCHAR(12) | YES | - | NULL nghĩa là sự kiện tạo order |
| `to_status` | VARCHAR(12) | NO | - | |
| `changed_by` | BIGINT | YES | - | FK -> users; NULL = worker/system |
| `note` | VARCHAR(255) | YES | - | |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.9. conversations

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `conversation_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_one_id` | BIGINT | NO | - | FK -> users; luôn < user_two_id |
| `user_two_id` | BIGINT | NO | - | FK -> users; luôn > user_one_id |
| `last_message_at` | TIMESTAMP | YES | - | cache/projection từ messages |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.10. messages

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `message_id` | BIGINT IDENTITY | NO | auto | PK |
| `conversation_id` | BIGINT | NO | - | FK -> conversations CASCADE |
| `sender_id` | BIGINT | NO | - | FK -> users |
| `type` | VARCHAR(12) + CHECK | NO | `TEXT` | `TEXT` / `IMAGE` / `FILE` / `PRODUCT_CARD` / `ORDER_CARD` / `SYSTEM` |
| `content` | TEXT | YES | - | bắt buộc khi `TEXT` |
| `product_id` | BIGINT | YES | - | FK -> products SET NULL |
| `order_id` | BIGINT | YES | - | FK -> orders SET NULL |
| `is_deleted` | BOOLEAN | NO | FALSE | |
| `sent_at` | TIMESTAMP | NO | NOW() | |
| `read_at` | TIMESTAMP | YES | - | |

### 2.11. message_attachments

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `attachment_id` | BIGINT IDENTITY | NO | auto | PK |
| `message_id` | BIGINT | NO | - | FK -> messages CASCADE |
| `kind` | VARCHAR(5) + CHECK | NO | - | `IMAGE` / `FILE` |
| `file_url` | VARCHAR(500) | NO | - | Cloudinary |
| `file_name` | VARCHAR(255) | NO | - | |
| `mime_type` | VARCHAR(100) | NO | - | |
| `file_size` | INT | NO | - | CHECK > 0 |
| `width` | INT | YES | - | chỉ dùng cho ảnh |
| `height` | INT | YES | - | chỉ dùng cho ảnh |
| `thumbnail_url` | VARCHAR(500) | YES | - | Cloudinary |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.12. reviews

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `review_id` | BIGINT IDENTITY | NO | auto | PK |
| `order_item_id` | BIGINT | NO | - | FK -> order_items RESTRICT |
| `reviewer_id` | BIGINT | NO | - | FK -> users |
| `reviewee_id` | BIGINT | NO | - | FK -> users |
| `rating` | SMALLINT | NO | - | CHECK 1..5 |
| `comment` | TEXT | YES | - | |
| `is_deleted` | BOOLEAN | NO | FALSE | |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.13. favorites

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `user_id` | BIGINT | NO | - | PK/FK -> users CASCADE |
| `product_id` | BIGINT | NO | - | PK/FK -> products CASCADE |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.14. auctions

Cấu hình và trạng thái đấu giá của một sản phẩm. Mỗi product chỉ có tối đa một phiên đấu giá đang được biểu diễn trong bản ghi hiện tại của MVP.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `auction_id` | BIGINT IDENTITY | NO | auto | PK |
| `product_id` | BIGINT | NO | - | FK -> products CASCADE; UNIQUE |
| `bid_step` | DECIMAL(12,0) | NO | - | Bước giá; CHECK > 0 |
| `starts_at` | TIMESTAMP | NO | NOW() | Thời điểm bắt đầu |
| `ends_at` | TIMESTAMP | NO | - | Thời điểm kết thúc |
| `status` | VARCHAR(10) + CHECK | NO | `SCHEDULED` | `SCHEDULED` / `ACTIVE` / `ENDED` / `CANCELLED` |
| `winner_id` | BIGINT | YES | - | FK -> users RESTRICT; NULL nếu chưa có/không có người thắng |
| `final_price` | DECIMAL(12,0) | YES | - | Giá thắng được chốt khi kết thúc |
| `winner_checkout_deadline` | TIMESTAMP | YES | - | Hạn để người thắng hoàn tất tạo order |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

Quy ước:

- Giá khởi điểm lấy từ `products.price` tại thời điểm phiên đấu giá được kích hoạt.
- MVP không lưu `current_price` trong `auctions`; giá cao nhất hiện tại được lấy từ bid hợp lệ cao nhất trong `auction_bids`.
- PostgreSQL là nguồn dữ liệu chuẩn. Redis/WebSocket chỉ hỗ trợ phân phối sự kiện realtime, không quyết định người thắng.
- Sau khi đã có bid đầu tiên, seller không được thay đổi `products.price`, `products.stock`, `listing_type`, `bid_step`, `starts_at`, `ends_at` bằng luồng chỉnh sửa thông thường.
- Seller chỉ được huỷ đấu giá khi chưa có bid, trừ khi admin xử lý trường hợp đặc biệt.

### 2.15. auction_bids

Lưu toàn bộ lượt đặt giá hợp lệ để đảm bảo audit và xác định người thắng.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `bid_id` | BIGINT IDENTITY | NO | auto | PK |
| `auction_id` | BIGINT | NO | - | FK -> auctions CASCADE |
| `bidder_id` | BIGINT | NO | - | FK -> users RESTRICT |
| `amount` | DECIMAL(12,0) | NO | - | Giá đặt; CHECK > 0 |
| `created_at` | TIMESTAMP | NO | NOW() | |

Quy tắc đặt giá:

- Người bán không được đặt giá sản phẩm của chính mình.
- Chỉ user `ACTIVE` mới được bid.
- Chỉ nhận bid khi auction ở `ACTIVE` và thời gian server hiện tại nhỏ hơn `ends_at`.
- Bid đầu tiên phải `>= products.price`.
- Các bid tiếp theo phải `>= giá cao nhất hiện tại + bid_step`.
- Mỗi thao tác bid phải chạy trong transaction và khoá bản ghi `auctions` tương ứng bằng row lock trước khi đọc giá cao nhất và insert bid mới. Đây là cơ chế chống hai người cùng thắng do race condition.
- Client không được gửi hoặc quyết định `winner_id`, `final_price` hay trạng thái auction.

### 2.16. notifications

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `notification_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_id` | BIGINT | NO | - | FK -> users CASCADE |
| `type` | VARCHAR(20) + CHECK | NO | - | `NEW_ORDER` / `ORDER_STATUS` / `NEW_MESSAGE` / `NEW_REVIEW` / `AUCTION_BID` / `AUCTION_OUTBID` / `AUCTION_WON` / `AUCTION_ENDED` / `SYSTEM` |
| `title` | VARCHAR(255) | NO | - | |
| `body` | TEXT | YES | - | |
| `ref_type` | VARCHAR(20) | YES | - | polymorphic reference, chủ động không dùng FK |
| `ref_id` | BIGINT | YES | - | polymorphic reference, chủ động không dùng FK |
| `is_read` | BOOLEAN | NO | FALSE | |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.17. reports

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `report_id` | BIGINT IDENTITY | NO | auto | PK |
| `reporter_id` | BIGINT | NO | - | FK -> users CASCADE |
| `target_type` | VARCHAR(10) + CHECK | NO | - | `USER` / `PRODUCT` / `ORDER` |
| `target_id` | BIGINT | NO | - | polymorphic reference, chủ động không dùng FK |
| `reason` | VARCHAR(20) + CHECK | NO | - | `SCAM` / `FAKE_ITEM` / `SPAM` / `INAPPROPRIATE` / `NO_SHOW` / `OTHER` |
| `description` | TEXT | YES | - | |
| `status` | VARCHAR(10) + CHECK | NO | `OPEN` | `OPEN` / `REVIEWING` / `RESOLVED` / `REJECTED` |
| `handled_by` | BIGINT | YES | - | FK -> users SET NULL |
| `handled_at` | TIMESTAMP | YES | - | |
| `created_at` | TIMESTAMP | NO | NOW() | |

## 3. Khoá và hành động tham chiếu

| Bảng | PK | FK |
|---|---|---|
| `users` | user_id | - |
| `user_auth_identities` | user_auth_identity_id | user_id -> users (CASCADE) |
| `categories` | category_id | - |
| `products` | product_id | seller_id -> users (RESTRICT); category_id -> categories |
| `product_images` | image_id | product_id -> products (CASCADE) |
| `orders` | order_id | buyer_id -> users (RESTRICT); seller_id -> users (RESTRICT) |
| `order_items` | order_item_id | order_id -> orders (CASCADE); product_id -> products (RESTRICT) |
| `order_status_history` | history_id | order_id -> orders (CASCADE); changed_by -> users (SET NULL) |
| `conversations` | conversation_id | user_one_id -> users; user_two_id -> users |
| `messages` | message_id | conversation_id -> conversations (CASCADE); sender_id -> users; product_id -> products (SET NULL); order_id -> orders (SET NULL) |
| `message_attachments` | attachment_id | message_id -> messages (CASCADE) |
| `reviews` | review_id | order_item_id -> order_items (RESTRICT); reviewer_id -> users; reviewee_id -> users |
| `favorites` | (user_id, product_id) | user_id -> users (CASCADE); product_id -> products (CASCADE) |
| `auctions` | auction_id | product_id -> products (CASCADE); winner_id -> users (RESTRICT) |
| `auction_bids` | bid_id | auction_id -> auctions (CASCADE); bidder_id -> users (RESTRICT) |
| `notifications` | notification_id | user_id -> users (CASCADE) |
| `reports` | report_id | reporter_id -> users (CASCADE); handled_by -> users (SET NULL) |

## 4. UNIQUE constraint và index

### 4.1. UNIQUE constraints

- `users(email)`
- `user_auth_identities(user_id)`
- `user_auth_identities(provider, provider_uid)`
- `categories(slug)` WHERE `is_deleted = FALSE`
- `product_images(product_id, image_url)`
- `product_images(product_id)` WHERE `is_thumbnail = TRUE`
- `orders(order_code)`
- `order_items(order_id, product_id)`
- `conversations(user_one_id, user_two_id)`
- `reviews(order_item_id, reviewer_id, reviewee_id)`
- `favorites(user_id, product_id)` qua composite PK
- `auctions(product_id)`

### 4.2. Index thường

- `products(category_id, status, is_deleted, created_at)`
- `products(seller_id, status, created_at)`
- `products(listing_type, status, is_deleted, created_at)`
- GIN full-text index trên `products(title, description)` dùng `to_tsvector`
- `orders(buyer_id, status, created_at)`
- `orders(seller_id, status, created_at)`
- `orders(status, payment_status, auto_cancel_at)`
- `orders(payment_status, receipt_uploaded_at)`
- `order_items(product_id)`
- `conversations(user_one_id, last_message_at)` và `(user_two_id, last_message_at)`
- `messages(conversation_id, sent_at)`
- `messages(conversation_id, sender_id, read_at)`
- `message_attachments(message_id)`
- `reviews(reviewee_id, is_deleted, created_at)`
- `favorites(product_id)`
- `auctions(status, ends_at)` để worker tìm phiên cần đóng
- `auction_bids(auction_id, amount DESC, created_at ASC)` để lấy bid cao nhất ổn định
- `auction_bids(bidder_id, created_at)` để xem lịch sử bid của user
- `notifications(user_id, is_read, created_at)`

## 5. CHECK constraints

- `orders.buyer_id <> orders.seller_id`
- `orders.payment_status <> 'VERIFYING' OR payment_receipt_url IS NOT NULL`
- `orders.payment_status <> 'PAID' OR paid_confirmed_at IS NOT NULL`
- `products.price >= 0`
- `products.stock >= 0`
- `products.reserved_stock BETWEEN 0 AND products.stock`
- `products.listing_type IN ('FIXED_PRICE', 'AUCTION')`
- `order_items.quantity > 0`
- `order_items.price_at_purchase >= 0`
- `conversations.user_one_id < conversations.user_two_id`
- `messages.type <> 'TEXT' OR content IS NOT NULL`
- `reviews.rating BETWEEN 1 AND 5`
- `reviews.reviewer_id <> reviews.reviewee_id`
- `message_attachments.file_size > 0`
- `auctions.bid_step > 0`
- `auctions.ends_at > auctions.starts_at`
- `auctions.final_price IS NULL OR auctions.final_price >= 0`
- `(auctions.winner_id IS NULL AND auctions.final_price IS NULL) OR (auctions.winner_id IS NOT NULL AND auctions.final_price IS NOT NULL)`
- `auction_bids.amount > 0`
- mọi enum/check value phải khớp chính xác tài liệu này.

Lưu ý: MVP không áp dụng ngưỡng giá khởi điểm tối thiểu cố định cho đấu giá. Nếu sau này cần hạn chế spam hoặc giới hạn theo chính sách, ngưỡng giá tối thiểu phải được triển khai dưới dạng business rule/config và không hard-code thành DB CHECK.

## 6. Phi chuẩn hoá có chủ đích / projection / snapshot

Các field sau được giữ có chủ đích và **không được agent tự ý xoá chỉ vì muốn “chuẩn hoá 3NF”**:

- `products.view_count`: counter projection dựa trên Redis.
- `conversations.last_message_at`: inbox projection.
- `orders.total_amount`: snapshot giao dịch.
- `order_items.product_title`, `product_image_url`, `price_at_purchase`: snapshot bất biến khi mua.
- `auctions.winner_id`, `final_price`: kết quả chốt của phiên đấu giá để audit và tạo order sau đó.
- các timestamp vận hành dùng cho audit/state transition.

Đây là quyết định thiết kế ở application level, không phải bằng chứng để thiết kế lại toàn bộ domain model.

## 7. Business rules bắt buộc ở service + transaction

### 7.1. Mua trực tiếp / order

1. User không được mua sản phẩm của chính mình.
2. Tạo order không được vượt `stock - reserved_stock`.
3. Giữ/giải phóng stock và tạo order phải atomic.
4. Order status transition phải theo state machine hợp lệ.
5. `VERIFYING` yêu cầu có payment receipt.
6. `PAID` yêu cầu có `paid_confirmed_at`.
7. Chỉ order `COMPLETED` mới được review.
8. Review phải thuộc người tham gia giao dịch.
9. User không được tự review chính mình.
10. Một conversation là duy nhất cho một cặp user không xét thứ tự.
11. Product/category/review đã soft-delete không xuất hiện trong listing thông thường.
12. Không có cart; luồng mua hàng bắt đầu trực tiếp từ product detail hoặc từ quyền mua của người thắng auction.

### 7.2. Điều kiện bật đấu giá

Seller chỉ được bật đấu giá khi đồng thời thoả:

1. Seller là chủ sở hữu product.
2. User/seller đang `ACTIVE`.
3. `products.listing_type` được chuyển sang `AUCTION` trong cùng transaction tạo auction.
4. `products.stock = 1`.
5. `products.reserved_stock = 0`.
6. `products.status = 'AVAILABLE'`.
7. `products.is_deleted = FALSE`.
8. Chưa tồn tại order/reservation đang chiếm sản phẩm.
9. `bid_step > 0`.
10. `ends_at > starts_at`.

MVP không áp dụng ngưỡng giá khởi điểm tối thiểu cố định cho đấu giá. Một sản phẩm có thể được bật đấu giá bất kể giá trị, miễn là thoả đầy đủ các điều kiện nghiệp vụ ở trên.

Nếu sau này cần chống spam hoặc giới hạn auction theo chính sách, ngưỡng giá tối thiểu phải được triển khai dưới dạng business rule/config để có thể thay đổi mà không cần migration database.

### 7.3. Đặt giá và chống race condition

1. Seller không được bid product của mình.
2. Auction phải `ACTIVE` và chưa quá `ends_at` theo thời gian server.
3. Bid đầu tiên phải >= `products.price`.
4. Bid sau phải >= `highest_bid + bid_step`.
5. Không tin giá cao nhất do client gửi lên.
6. Trong transaction đặt bid, repository/service phải lock bản ghi `auctions` bằng `SELECT ... FOR UPDATE`, đọc bid cao nhất trong PostgreSQL, validate rồi mới insert.
7. Sau commit, backend mới publish sự kiện cập nhật qua WebSocket/Redis nếu dùng.
8. Nếu hai request bid đến cùng lúc, transaction hợp lệ được commit trước sẽ làm giá chuẩn cho transaction còn lại.

### 7.4. Realtime

1. PostgreSQL là source of truth của bid và kết quả đấu giá.
2. REST endpoint đọc auction/bid phải luôn cho client khôi phục state sau reconnect.
3. WebSocket chỉ là kênh delivery realtime cho `highest_bid`, số lượt bid, trạng thái và thời gian kết thúc.
4. Redis có thể dùng pub/sub khi có nhiều API instance, nhưng không được là nơi duy nhất lưu bid.
5. Client reconnect phải fetch snapshot hiện tại qua REST trước hoặc ngay sau khi subscribe lại.

### 7.5. Kết thúc đấu giá

1. Worker/scheduler tìm auction `ACTIVE` có `ends_at <= NOW()`.
2. Mỗi auction phải được đóng trong transaction có row lock để tránh xử lý hai lần.
3. Nếu không có bid: đặt `status = ENDED`, `winner_id = NULL`, `final_price = NULL`; seller có thể chỉnh sửa/mở lại tin sau đó.
4. Nếu có bid: lấy bid hợp lệ cao nhất; khi bằng giá, bid được tạo sớm hơn thắng để kết quả deterministic.
5. Ghi `winner_id`, `final_price`, `status = ENDED`.
6. Nếu product vẫn còn `stock = 1` và `reserved_stock = 0`, giữ 1 đơn vị cho winner bằng `reserved_stock = 1` và đặt `winner_checkout_deadline`.
7. Trong thời gian giữ quyền mua, chỉ `winner_id` được phép tạo order từ auction đó.
8. Order từ auction có `quantity = 1`, `price_at_purchase = final_price`.
9. Nếu winner tạo order, reservation đã có phải được chuyển sang order, không cộng `reserved_stock` thêm lần nữa.
10. Nếu quá `winner_checkout_deadline` mà chưa có order, worker giải phóng reservation. MVP **không tự động chuyển quyền mua cho người trả giá thứ hai**; seller có thể mở lại đấu giá.
11. Gửi notification phù hợp cho seller, winner và người vừa bị vượt giá khi cần.

## 8. Quy ước đặt tên

- Table: snake_case, số nhiều.
- Column: snake_case.
- PK: `<entity>_id`.
- FK theo vai trò: dùng tên có nghĩa như `seller_id`, `buyer_id`, `bidder_id`, `winner_id`.
- Boolean: `is_` / `has_`.
- Timestamp: `_at`.
- PostgreSQL ENUM type: `<entity>_status` / `<column>_t`.
- UNIQUE index: `ux_<table>_<columns>`.
- Index thường: `ix_<table>_<columns>`.
- CHECK constraint: `chk_<table>_<meaning>`.
- FK constraint: `fk_<table>_<referenced_table>`.
- Trigger: `trg_<table>_<action>`.

## 9. Chính sách migration

Mọi thay đổi schema phải đi qua Alembic. Không chỉnh production schema thủ công ngoài migration có chủ đích. Với thay đổi phá huỷ dữ liệu, phải có kế hoạch data migration/rollback trước khi áp dụng.

Database được dùng chung cho các backend có thể xuất hiện trong tương lai. Backend hiện tại là FastAPI/Python; Spring Boot có thể dùng lại schema sau này. Vì vậy schema phải luôn độc lập với framework implementation.
