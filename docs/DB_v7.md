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

Schema hiện có **32 bảng** (28 bảng thực thể chính và 4 bảng quan hệ phụ trợ tin nhắn/nhóm):

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
18. `daily_needs`
19. `daily_journal_checkins`
20. `report_attachments`
21. `moderation_actions`
22. `user_capability_restrictions`
23. `community_moments`
24. `site_feedback`
25. `site_feedback_attachments`
26. `conversation_members`
27. `conversation_invites`
28. `message_mentions`
29. `message_reactions`
30. `support_contributions`
31. `support_claims`
32. `tutorials`

> Ngoài ra, cơ sở dữ liệu có 1 bảng quản lý phiên bản di trú hệ thống của Alembic là `alembic_version` (tổng cộng 33 bảng vật lý).


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
| `avatar_url` | VARCHAR(500) | YES | - | Google / Firebase Auth sync |
| `bio` | VARCHAR(500) | YES | - | |
| `delivery_area` | VARCHAR(255) | YES | - | Phạm vi giao / nhận hàng công khai của người dùng |
| `default_meetup_area` | VARCHAR(255) | YES | - | Legacy/deprecated |
| `bank_bin` | VARCHAR(10) | YES | - | Mã BIN ngân hàng VietQR/NAPAS |
| `bank_account_number` | VARCHAR(30) | YES | - | Số tài khoản ngân hàng thụ hưởng |
| `bank_account_name` | VARCHAR(100) | YES | - | Tên chủ tài khoản thụ hưởng |
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
| `status` | VARCHAR(10) + CHECK | NO | - | Business/Seller state: `AVAILABLE` / `HIDDEN` / `SOLD_OUT` |
| `approval_status` | VARCHAR(20) + CHECK | NO | `DRAFT` | Pre-publication review state: `DRAFT` / `PENDING` / `APPROVED` / `REJECTED` |
| `submitted_for_review_at` | TIMESTAMPTZ | YES | - | Thời điểm người bán gửi duyệt tin đăng |
| `reviewed_by` | BIGINT | YES | - | FK -> users(user_id) ON DELETE SET NULL; Quản trị viên duyệt |
| `reviewed_at` | TIMESTAMPTZ | YES | - | Thời điểm quản trị viên duyệt/từ chối |
| `review_note` | VARCHAR(500) | YES | - | Lý do từ chối kiểm duyệt (khi REJECTED) |
| `moderation_status` | VARCHAR(20) + CHECK | NO | `CLEAR` | Platform enforcement: `CLEAR` / `BLOCKED` (chk_products_moderation_status) |
| `view_count` | INT | NO | 0 | durable monotonic projection synchronized periodically from Redis Product View Counter |
| `is_deleted` | BOOLEAN | NO | FALSE | soft delete |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

Tách bạch rõ ba miền trạng thái của Product:
1. **Business Status (`status`)**: Trạng thái bán hàng do người bán quản lý (`AVAILABLE`, `HIDDEN`, `SOLD_OUT`).
2. **Pre-publication Approval (`approval_status`)**: Quy trình kiểm duyệt trước khi công khai do Admin quản trị (`DRAFT`, `PENDING`, `APPROVED`, `REJECTED`). Mặc định khi tạo tin là `DRAFT`.
3. **Platform Moderation (`moderation_status`)**: Xử lý vi phạm/báo cáo (`CLEAR`, `BLOCKED`).

Quy tắc xuất bản công khai (Public Visibility Invariant):
Tin đăng chỉ được xuất hiện công khai trên sàn (Danh sách sản phẩm, Tìm kiếm, Chi tiết công khai, Yêu thích, Đặt hàng, v.v.) khi thỏa mãn đồng thời:
`is_deleted = FALSE AND status = 'AVAILABLE' AND approval_status = 'APPROVED' AND moderation_status = 'CLEAR'` cùng các điều kiện về tài khoản người bán (`ACTIVE`, không bị hạn chế SELL).

Quy tắc ý nghĩa:

- Với `FIXED_PRICE`, người dùng mua trực tiếp từ tin; không đi qua giỏ hàng.
- Với `AUCTION`, `products.price` là **giá khởi điểm**, không phải giá thắng cuối cùng.
- Điều kiện `stock = 1`, `reserved_stock = 0`, `status = AVAILABLE`, `approval_status = APPROVED`, `is_deleted = FALSE` được kiểm tra khi **bật/kích hoạt đấu giá** ở service layer.
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
| `payment_note` | VARCHAR(255) | YES | - | ghi chú thanh toán / chuyển khoản |
| `payment_bank_bin` | VARCHAR(10) | YES | - | snapshot BIN ngân hàng nhận tiền tại thời điểm CONFIRMED |
| `payment_bank_account_number` | VARCHAR(30) | YES | - | snapshot STK ngân hàng nhận tiền tại thời điểm CONFIRMED |
| `payment_bank_account_name` | VARCHAR(100) | YES | - | snapshot Tên chủ TK nhận tiền tại thời điểm CONFIRMED |
| `fulfillment_method` | VARCHAR(10) + CHECK | NO | `MEETUP` | `MEETUP` / `SHIPPING` |
| `meetup_place` | VARCHAR(255) | YES | - | |
| `meetup_time` | TIMESTAMP | YES | - | |
| `shipping_address` | VARCHAR(500) | YES | - | dùng khi `SHIPPING` |
| `shipping_expected_at` | TIMESTAMP | YES | - | ngày dự kiến giao hàng (dùng khi `SHIPPING`) |
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
| `auction_id` | BIGINT | YES | - | FK -> auctions RESTRICT; partial UNIQUE `ux_orders_auction_id` WHERE auction_id IS NOT NULL (tối đa 1 Order duy nhất cho mỗi vòng đấu giá) |
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
| `type` | VARCHAR(20) | NO | `DIRECT` | `DIRECT` / `GROUP` / `COMMUNITY` |
| `title` | VARCHAR(255) | YES | - | Tiêu đề nhóm / cộng đồng |
| `description` | TEXT | YES | - | Mô tả nhóm / cộng đồng |
| `avatar_url` | VARCHAR(500) | YES | - | Avatar nhóm |
| `user_one_id` | BIGINT | YES | - | FK -> users; cho DIRECT chat (luôn < user_two_id) |
| `user_two_id` | BIGINT | YES | - | FK -> users; cho DIRECT chat (luôn > user_one_id) |
| `created_by` | BIGINT | YES | - | FK -> users; người tạo nhóm |
| `requires_approval` | BOOLEAN | NO | FALSE | Khi TRUE, thành viên mới cần Trưởng nhóm (OWNER) phê duyệt |
| `last_message_at` | TIMESTAMP | YES | - | cache/projection từ messages (SYSTEM message KHÔNG cập nhật trường này) |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `deleted_at` | TIMESTAMP | YES | - | Soft delete nhóm |

### 2.9.1. conversation_members

Quản lý thành viên tham gia nhóm / cộng đồng / hội thoại. Thành viên hợp lệ/đang hoạt động được xác định bằng điều kiện `left_at IS NULL`.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `conversation_id` | BIGINT | NO | - | PK (composite 1/2); FK -> conversations CASCADE |
| `user_id` | BIGINT | NO | - | PK (composite 2/2); FK -> users CASCADE |
| `role` | VARCHAR(10) | NO | `MEMBER` | `OWNER` / `ADMIN` / `MEMBER` (chk_conversation_members_role) |
| `joined_at` | TIMESTAMP | NO | NOW() | Thời điểm tham gia nhóm |
| `left_at` | TIMESTAMP | YES | - | Thời điểm rời/bị xóa khỏi nhóm; NULL = thành viên đang hoạt động (ACTIVE) |
| `last_read_message_id` | BIGINT | YES | - | FK -> messages(message_id) ON DELETE SET NULL |
| `nickname` | VARCHAR(40) | YES | - | Biệt danh tự đặt của thành viên trong nhóm (cục bộ, tối đa 40 ký tự) |

### 2.9.2. conversation_invites

Quản lý lời mời tham gia nhóm và hàng đợi phê duyệt.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `invite_id` | BIGINT IDENTITY | NO | auto | PK |
| `conversation_id` | BIGINT | NO | - | FK -> conversations CASCADE |
| `inviter_id` | BIGINT | NO | - | FK -> users CASCADE |
| `invitee_id` | BIGINT | NO | - | FK -> users CASCADE |
| `status` | VARCHAR(20) | NO | `PENDING` | `PENDING` / `PENDING_APPROVAL` / `ACCEPTED` / `DECLINED` / `CANCELLED` |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `responded_at` | TIMESTAMP | YES | - | |

### 2.10. messages

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `message_id` | BIGINT IDENTITY | NO | auto | PK |
| `conversation_id` | BIGINT | NO | - | FK -> conversations CASCADE |
| `sender_id` | BIGINT | NO | - | FK -> users |
| `type` | VARCHAR(12) + CHECK | NO | `TEXT` | `TEXT` / `IMAGE` / `FILE` / `PRODUCT_CARD` / `ORDER_CARD` / `SYSTEM` |
| `content` | TEXT | YES | - | Cho phép NULL khi có attachments |
| `product_id` | BIGINT | YES | - | FK -> products SET NULL |
| `order_id` | BIGINT | YES | - | FK -> orders SET NULL |
| `reply_to_message_id` | BIGINT | YES | - | FK -> messages(message_id) ON DELETE SET NULL |
| `is_deleted` | BOOLEAN | NO | FALSE | |
| `sent_at` | TIMESTAMP | NO | NOW() | |
| `read_at` | TIMESTAMP | YES | - | |

### 2.11. message_attachments

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `attachment_id` | BIGINT IDENTITY | NO | auto | PK |
| `message_id` | BIGINT | NO | - | FK -> messages CASCADE |
| `kind` | VARCHAR(10) + CHECK | NO | - | `IMAGE` / `VIDEO` / `PDF` / `AUDIO` / `DOCUMENT` (chk_message_attachments_kind) |
| `url` | TEXT | NO | - | Cloudinary secure delivery URL |
| `storage_key` | VARCHAR(255) | NO | - | Cloudinary public_id |
| `mime_type` | VARCHAR(100) | NO | - | `image/jpeg`, `video/mp4`, `application/pdf`, `audio/webm`, `application/vnd...`, etc. |
| `original_name` | VARCHAR(255) | NO | - | Tên file gốc |
| `size_bytes` | BIGINT | NO | - | Kích thước byte thực tế |
| `duration_ms` | BIGINT | YES | - | Thời lượng phát (ms) cho voice note / audio |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.11.1. message_mentions

Lưu trữ thông tin gắn thẻ người dùng (@mention) có cấu trúc trong tin nhắn nhóm/cộng đồng. Đảm bảo hiển thị ổn định không phụ thuộc vào việc đổi tên hiển thị của người dùng sau này.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `mention_id` | BIGINT IDENTITY | NO | auto | PK |
| `message_id` | BIGINT | NO | - | FK -> messages(message_id) CASCADE |
| `mentioned_user_id` | BIGINT | NO | - | FK -> users(user_id) CASCADE |
| `display_text` | VARCHAR(100) | NO | - | Snapshot chuỗi hiển thị lúc tag (ví dụ `@Trần Thị B`) |
| `start_offset` | INT | NO | - | Vị trí ký tự bắt đầu của token trong `content` |
| `end_offset` | INT | NO | - | Vị trí ký tự kết thúc của token trong `content` |
| `created_at` | TIMESTAMP | NO | NOW() | Thời điểm tạo |

### 2.11.2. message_reactions

Lưu trữ biểu cảm cảm xúc (reaction) của người dùng đối với tin nhắn. Mỗi người dùng chỉ được bày tỏ tối đa 1 biểu cảm trên mỗi tin nhắn.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `reaction_id` | BIGINT IDENTITY | NO | auto | PK |
| `message_id` | BIGINT | NO | - | FK -> messages(message_id) CASCADE |
| `user_id` | BIGINT | NO | - | FK -> users(user_id) CASCADE |
| `reaction_key` | VARCHAR(50) | NO | - | 12 giá trị ASCII: LIKE, HEART, LAUGH, WOW, SAD, ANGRY, PTIT_HEART, PTIT_FIRE, PTIT_LIKE, PTIT_STAR, PTIT_CROWN, PTIT_GRAD |
| `created_at` | TIMESTAMP | NO | NOW() | Thời điểm tạo |

### 2.12. reviews

Đánh giá uy tín người bán dựa trên giao dịch đơn hàng thực tế đã hoàn tất (`COMPLETED`).

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `review_id` | BIGINT IDENTITY | NO | auto | PK |
| `order_id` | BIGINT | NO | - | FK -> orders(order_id) RESTRICT |
| `reviewer_id` | BIGINT | NO | - | FK -> users(user_id) RESTRICT |
| `reviewee_id` | BIGINT | NO | - | FK -> users(user_id) RESTRICT |
| `rating` | SMALLINT | NO | - | CHECK 1..5 |
| `comment` | VARCHAR(1000) | YES | - | Tối đa 1000 ký tự |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

### 2.13. favorites

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `user_id` | BIGINT | NO | - | PK/FK -> users CASCADE |
| `product_id` | BIGINT | NO | - | PK/FK -> products CASCADE |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.14. auctions

Cấu hình và trạng thái đấu giá của một sản phẩm. Mỗi product có tối đa một phiên đấu giá ở trạng thái `SCHEDULED` hoặc `ACTIVE` tại một thời điểm (qua partial unique index `ux_auctions_product_active`), đồng thời cho phép lưu nhiều vòng đấu giá lịch sử (`ENDED`, `CANCELLED`).

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `auction_id` | BIGINT IDENTITY | NO | auto | PK |
| `product_id` | BIGINT | NO | - | FK -> products CASCADE; Index `ix_auctions_product_id` |
| `starting_price` | DECIMAL(12,0) | NO | - | Snapshot giá khởi điểm tại thời điểm tạo auction; CHECK >= 0 |
| `bid_step` | DECIMAL(12,0) | NO | - | Bước giá; CHECK > 0 |
| `starts_at` | TIMESTAMP | NO | NOW() | Thời điểm bắt đầu |
| `ends_at` | TIMESTAMP | NO | - | Thời điểm kết thúc; CHECK `ends_at > starts_at` |
| `status` | VARCHAR(10) + CHECK | NO | `SCHEDULED` | `SCHEDULED` / `ACTIVE` / `ENDED` / `CANCELLED` |
| `winner_id` | BIGINT | YES | - | FK -> users RESTRICT; NULL nếu chưa có/không có người thắng |
| `final_price` | DECIMAL(12,0) | YES | - | Giá thắng được chốt khi kết thúc; CHECK `final_price IS NULL OR final_price >= starting_price` |
| `winner_checkout_deadline` | TIMESTAMP | YES | - | Hạn để người thắng hoàn tất tạo order |
| `created_at` | TIMESTAMP | NO | NOW() | |
| `updated_at` | TIMESTAMP | NO | NOW() | trigger tự cập nhật |

Quy ước:

- Giá khởi điểm được snapshot cố định vào `auctions.starting_price = products.price` khi tạo auction round. Thay đổi `products.price` sau đó không làm thay đổi snapshot này.
- Giá cao nhất hiện tại được lấy từ bid hợp lệ cao nhất trong `auction_bids`.
- PostgreSQL là nguồn dữ liệu chuẩn. Redis/WebSocket chỉ hỗ trợ phân phối sự kiện realtime, không quyết định người thắng.
- Sau khi đã có bid đầu tiên, seller không được thay đổi `products.price`, `products.stock`, `listing_type`, `bid_step`, `starts_at`, `ends_at`.
- Seller chỉ được huỷ đấu giá khi chưa có bid.
- Khi phiên đấu giá kết thúc mà không có giao dịch giữ hàng (hoặc sau khi winner timeout / order bị hủy), seller có thể bắt đầu vòng đấu giá mới (`POST /api/v1/auctions`) hoặc chuyển sang bán giá cố định (`POST /api/v1/auctions/products/{id}/convert-fixed-price`).

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
- Bid đầu tiên phải `> 0` và `>= auction.starting_price`. Nếu `starting_price = 0`, giá đặt tối thiểu là 1 VND.
- Các bid tiếp theo phải `>= giá cao nhất hiện tại + bid_step`.
- Mỗi thao tác bid chạy trong transaction và khoá bản ghi `auctions` tương ứng bằng `FOR UPDATE`.
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

### 2.18. daily_needs

Lưu trữ "Nhu cầu hôm nay" (Daily Student Needs) — các tín hiệu mua bán, trao đổi nhanh trong ngày của sinh viên. Mỗi sinh viên được đăng/chỉnh sửa tối đa 1 nhu cầu cho mỗi ngày dương lịch (theo múi giờ `Asia/Ho_Chi_Minh`). Hiển thị công khai tối đa 10 nhu cầu mới nhất trên Home ticker.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `daily_need_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_id` | BIGINT | NO | - | FK -> users CASCADE |
| `note_date` | DATE | NO | - | Ngày tính theo múi giờ Việt Nam (Asia/Ho_Chi_Minh) |
| `content` | VARCHAR(120) | NO | - | Tối đa 120 ký tự, không rỗng, rút gọn 1 dòng |
| `created_at` | TIMESTAMPTZ | NO | NOW() | |
| `updated_at` | TIMESTAMPTZ | NO | NOW() | |

### 2.18.1. daily_journal_checkins

Lưu trữ sự kiện chứng nhận chuỗi ngày điểm danh bất biến của sinh viên. Bản ghi không bao giờ bị xóa khi người dùng xóa nội dung trong `daily_needs`.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `checkin_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_id` | BIGINT | NO | - | FK -> users(user_id) CASCADE |
| `checkin_date` | DATE | NO | - | Ngày điểm danh theo múi giờ Việt Nam, UNIQUE(user_id, checkin_date) |
| `created_at` | TIMESTAMPTZ | NO | NOW() | Thời điểm ghi nhận |

### 2.19. report_attachments

Lưu trữ ảnh minh chứng đính kèm khiếu nại/báo cáo vi phạm từ người dùng. Tối đa 5 ảnh/báo cáo. Không lưu trữ blob nhị phân trong cơ sở dữ liệu (lưu trên Cloudinary).

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `attachment_id` | BIGINT IDENTITY | NO | auto | PK |
| `report_id` | BIGINT | NO | - | FK -> reports CASCADE |
| `url` | VARCHAR(500) | NO | - | URL Cloudinary nội bộ (không bao giờ lộ ra DTO công khai) |
| `storage_key` | VARCHAR(255) | NO | - | Cloudinary public_id phục vụ xóa/bù trừ và streaming bảo mật |
| `mime_type` | VARCHAR(50) | NO | - | CHECK IN (`image/jpeg`, `image/png`, `image/webp`) |
| `original_name` | VARCHAR(255) | NO | - | Tên tệp gốc do người dùng tải lên |
| `size_bytes` | INTEGER | NO | - | CHECK > 0, tối đa 10MB (10,485,760 bytes) |
| `created_at` | TIMESTAMP | NO | NOW() | |

### 2.20. moderation_actions

Bảng nhật ký kiểm duyệt (Audit Log) ghi nhận các hành động chế tài của Quản trị viên áp dụng lên Người dùng hoặc Tin đăng dựa trên báo cáo vi phạm.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `moderation_action_id` | BIGINT IDENTITY | NO | auto | PK |
| `report_id` | BIGINT | NO | - | FK -> reports CASCADE |
| `admin_id` | BIGINT | NO | - | FK -> users RESTRICT |
| `target_type` | VARCHAR(10) + CHECK | NO | - | `USER` / `PRODUCT` (chk_moderation_actions_target_type) |
| `target_id` | BIGINT | NO | - | polymorphic reference tới users.user_id hoặc products.product_id |
| `action_type` | VARCHAR(20) + CHECK | NO | - | `USER_BAN` / `USER_UNBAN` / `PRODUCT_HIDE` / `PRODUCT_RESTORE` (chk_moderation_actions_action_type) |
| `previous_status` | VARCHAR(20) | NO | - | Trạng thái trước khi chế tài |
| `new_status` | VARCHAR(20) | NO | - | Trạng thái sau khi chế tài |
| `created_at` | TIMESTAMP | NO | NOW() | Thời điểm thực thi chế tài |

### 2.21. user_capability_restrictions

Bảng lưu trữ các lệnh hạn chế quyền có thời hạn áp dụng lên tài khoản người dùng (`BUY` hoặc `SELL`), phát sinh từ quy trình xử lý báo cáo vi phạm (`POST /api/v1/admin/reports/{id}/enforcement`).

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `restriction_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_id` | BIGINT | NO | - | FK -> users(user_id) RESTRICT |
| `source_report_id` | BIGINT | NO | - | FK -> reports(report_id) RESTRICT |
| `imposed_by` | BIGINT | NO | - | FK -> users(user_id) RESTRICT |
| `capability` | VARCHAR(10) | NO | - | CHECK IN ('BUY', 'SELL') |
| `starts_at` | TIMESTAMP | NO | NOW() | Thời điểm bắt đầu hiệu lực |
| `expires_at` | TIMESTAMP | YES | NULL | CHECK (expires_at IS NULL OR expires_at > starts_at) |
| `revoked_at` | TIMESTAMP | YES | NULL | CHECK (revoked_at IS NULL OR revoked_at >= starts_at) |
| `revoked_by` | BIGINT | YES | NULL | FK -> users(user_id) SET NULL |
| `created_at` | TIMESTAMP | NO | NOW() | Thời điểm tạo |

### 2.22. community_moments

Lưu trữ ảnh khoảnh khắc cộng đồng sinh viên PTIT (giao dịch, nhận hàng, kỷ niệm) hiển thị trên Hero Carousel sau khi được Quản trị viên duyệt. Kèm theo một lời nhắn ngắn gọn (1..80 ký tự) hiển thị đè ở góc dưới bên trái ảnh.

**Vòng đời lưu trữ và kiểm soát Hero (Phase 8H-A.2 - Bounded Lifecycle):**
- Trạng thái hoạt động (active domain statuses): Chỉ gồm `PENDING` (chờ duyệt) và `APPROVED` (đang hiển thị trên Hero Carousel).
- Ràng buộc vật lý: `CHECK IN ('PENDING', 'APPROVED', 'REJECTED')` được giữ lại cho tính tương thích ngược vật lý, tầng nghiệp vụ ứng dụng chỉ vận hành `PENDING` và `APPROVED`.
- Hard delete vĩnh viễn:
  - Khi Admin từ chối (`REJECT`): Bản ghi bị xóa vĩnh viễn khỏi DB ngay lập tức và asset Cloudinary được dọn dẹp sau khi commit DB.
  - Khi Admin gỡ khoảnh khắc khỏi Hero (`DELETE`): Bản ghi bị xóa vĩnh viễn khỏi DB và Cloudinary.
  - Khi phê duyệt khoảnh khắc thứ 6 (`APPROVE`): Hệ thống tự động cắt tỉa bản ghi APPROVED cũ nhất theo thứ tự `reviewed_at ASC, moment_id ASC` bằng hard delete và dọn dẹp Cloudinary.
- Giới hạn Hero tối đa: Luôn duy trì tối đa **5 ảnh APPROVED** trên toàn hệ thống, bảo vệ an toàn tương tranh bằng PostgreSQL transactional advisory lock (`hashtext('community_hero_lifecycle')`).
- Client-side touch crop: Ảnh được người dùng cắt chuẩn tỉ lệ Hero chuẩn ngang **16:9** (tối đa 1600x900px, ngưỡng tối thiểu 320x180px) trực tiếp trên trình duyệt trước khi upload.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `moment_id` | BIGINT IDENTITY | NO | auto | PK |
| `uploader_id` | BIGINT | NO | - | FK -> users(user_id) RESTRICT |
| `image_url` | VARCHAR(500) | NO | - | URL ảnh Cloudinary đầy đủ (chuẩn w_1600 f_auto,q_auto) |
| `storage_key` | VARCHAR(255) | NO | - | Cloudinary public_id |
| `mime_type` | VARCHAR(100) | NO | - | JPEG, PNG hoặc WebP |
| `size_bytes` | BIGINT | NO | - | CHECK size_bytes > 0, tối đa 10MB |
| `note` | VARCHAR(80) | YES | NULL | Lời nhắn khoảnh khắc (1..80 ký tự single-line) |
| `status` | VARCHAR(20) | NO | 'PENDING' | CHECK IN ('PENDING', 'APPROVED', 'REJECTED') |
| `reviewed_by` | BIGINT | YES | NULL | FK -> users(user_id) SET NULL |
| `reviewed_at` | TIMESTAMP | YES | NULL | Thời điểm duyệt |
| `created_at` | TIMESTAMP | NO | NOW() | Thời điểm gửi |

### 2.23. site_feedback

Lưu trữ phản hồi, góp ý và báo lỗi của sinh viên về website Chợ PTITers theo mô hình issue board công khai ẩn danh. Mỗi người dùng có thể gửi nhiều feedback theo thời gian (đã loại bỏ `UNIQUE(user_id)`). Feedback là bất biến (immutable) sau khi tạo, người dùng có thể xóa feedback của chính mình (hard delete), quản trị viên có thể xóa bất kỳ feedback nào (hard delete). Không có trạng thái kiểm duyệt (không có PENDING/APPROVED/REJECTED), không có đánh giá sao (rating), không có marquee/featured. Nội dung feedback hiển thị công khai ngay sau khi gửi thành công; danh tính tác giả và các tệp minh chứng (ảnh/video) được bảo mật tuyệt đối, chỉ hiển thị cho quản trị viên và người gửi.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `feedback_id` | BIGINT IDENTITY | NO | auto | PK |
| `user_id` | BIGINT | NO | - | FK -> users CASCADE |
| `content` | VARCHAR(500) | NO | - | 5..500 ký tự (Unicode NFC, plain text) |
| `created_at` | TIMESTAMPTZ | NO | NOW() | |
| `updated_at` | TIMESTAMPTZ | NO | NOW() | |

### 2.24. site_feedback_attachments

Lưu trữ metadata tệp minh chứng hình ảnh (tối đa 3 ảnh JPEG/PNG/WebP, tối đa 10MB/ảnh) hoặc video (tối đa 1 video MP4/WebM/MOV, tối đa 30MB, thời lượng tối đa 60 giây) đính kèm với feedback. Tệp blob thực tế được lưu tại Cloudinary (`student-marketplace/feedback`). Minh chứng là riêng tư, chỉ quản trị viên (và chủ sở hữu) được phép xem/stream an toàn, không hiển thị ra bảng tin công khai. Khi feedback bị xóa, các bản ghi đính kèm sẽ tự động xóa theo (`ON DELETE CASCADE`) và Cloudinary assets được dọn dẹp theo chính sách best-effort sau khi commit database.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `attachment_id` | BIGINT IDENTITY | NO | auto | PK |
| `feedback_id` | BIGINT | NO | - | FK -> site_feedback CASCADE |
| `kind` | VARCHAR(10) | NO | - | CHECK IN ('IMAGE', 'VIDEO') |
| `media_url` | VARCHAR(500) | NO | - | URL Cloudinary gốc an toàn |
| `storage_key` | VARCHAR(255) | NO | - | Public ID trên Cloudinary |
| `mime_type` | VARCHAR(50) | NO | - | MIME type chuẩn hoá |
| `size_bytes` | BIGINT | NO | - | Dung lượng tệp (bytes), CHECK > 0 |
| `duration_ms` | BIGINT | YES | NULL | Thời lượng video tính bằng milliseconds (cho video <= 60000ms) |
| `created_at` | TIMESTAMPTZ | NO | NOW() | |

### 2.25. support_contributions

Lưu trữ sổ cái các khoản đóng góp ủng hộ tài chính (financial support ledger) dành cho người sáng lập và duy trì hệ thống Chợ PTITers, do Quản trị viên (Admin) đối soát và ghi nhận thủ công từ giao dịch ngân hàng thực tế bên ngoài ứng dụng.

**Ngữ nghĩa nghiệp vụ & Bảo vệ quyền riêng tư (Privacy & Immutability):**
- **Xác thực thủ công tuyệt đối (Manual Admin-Verified Only)**: Bản thân bảng `support_contributions` chỉ chứa các khoản đóng góp thực tế đã được Admin đối soát và xác nhận tiền về tài khoản ngân hàng. Sổ cái này tuyệt đối KHÔNG lưu trữ các yêu cầu chờ duyệt (không có cờ PENDING/REJECTED). Lời khai báo từ người dùng được lưu trữ riêng biệt tại bảng staging `support_claims` (`POST /api/v1/feedback/support/claims`). Hệ thống hoàn toàn KHÔNG tích hợp banking API/webhook và không upload ảnh chụp biên lai/OCR.
- **Tính bất biến tài chính (Immutability)**: Không cung cấp API sửa đổi tùy tiện số tiền. Trường hợp ghi nhận nhầm lẫn hoặc trùng lặp, Admin sử dụng thao tác xóa bản ghi sai (`DELETE /api/v1/admin/support-contributions/{id}`) và tạo lại bản ghi mới chính xác.
- **Quyền riêng tư mặc định (`is_public = FALSE`)**: Mọi khoản đóng góp khi tạo mới mặc định ở trạng thái riêng tư (`is_public = FALSE`). Chỉ khi người ủng hộ xác nhận đồng ý xuất hiện công khai trên Bảng tri ân, Admin mới chuyển cờ sang `TRUE` qua endpoint thu hẹp (`PATCH /api/v1/admin/support-contributions/{id}/visibility`).
- **Tổng hợp Bảng tri ân công khai (`GET /api/v1/feedback/support/leaderboard`)**: Chỉ tổng hợp các bản ghi có `is_public = TRUE`. Bản ghi riêng tư hoàn toàn không xuất hiện và không được cộng gộp vào tổng tiền công khai của người dùng. Tuyệt đối không để lộ mã giao dịch (`transaction_ref`), ghi chú admin (`admin_note`), danh tính admin ghi nhận (`recorded_by`), email, số điện thoại hay tài khoản ngân hàng.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `contribution_id` | BIGINT IDENTITY | NO | auto | PK |
| `supporter_id` | BIGINT | NO | - | FK -> users(user_id) ON DELETE RESTRICT |
| `amount_vnd` | BIGINT | NO | - | Số tiền VND nguyên dương, CHECK amount_vnd > 0 |
| `is_public` | BOOLEAN | NO | FALSE | Quyền riêng tư: mặc định FALSE, chỉ hiển thị công khai khi TRUE |
| `received_at` | TIMESTAMPTZ | NO | - | Thời điểm thực tế nhận tiền theo sao kê ngân hàng |
| `recorded_by` | BIGINT | NO | - | FK -> users(user_id) ON DELETE RESTRICT (Admin ghi nhận) |
| `transaction_ref` | VARCHAR(100) | YES | NULL | Mã tham chiếu/đối soát giao dịch ngân hàng nội bộ |
| `admin_note` | VARCHAR(255) | YES | NULL | Ghi chú quản trị nội bộ |
| `created_at` | TIMESTAMPTZ | NO | NOW() | Thời điểm tạo bản ghi hệ thống |

### 2.26. support_claims

Lưu trữ các yêu cầu xác nhận chuyển khoản ủng hộ do người dùng tự khai báo (user support declaration / reconciliation aid). Bảng này đóng vai trò hàng đợi đối soát (staging queue), **KHÔNG** mang giá trị thẩm quyền tài chính (financial truth).

**Ngữ nghĩa nghiệp vụ & Vòng đời đối soát:**
- **Phân định rõ ranh giới**:
  - `support_claims`: Khai báo từ người dùng ("Tôi tin rằng tôi đã chuyển số tiền này"). Trạng thái: `PENDING`, `VERIFIED`, `REJECTED`.
  - `support_contributions`: Sổ cái tài chính có thẩm quyền ("Tiền thực tế đã về tài khoản ngân hàng và được Admin xác minh").
- **Quy trình xác thực nguyên tử**:
  - Khi Admin đối soát thành công: Khóa dòng claim (SELECT FOR UPDATE) -> Tạo 1 bản ghi `support_contributions` với số tiền và thời gian thực nhận -> Cập nhật claim (`status = 'VERIFIED'`, `reviewed_by = admin_id`, `reviewed_at = NOW()`, `contribution_id = created_id`) -> Commit nguyên tử.
  - Idempotency: Không cho phép xác thực lặp lại để chống tạo trùng lặp đóng góp.
- **Quyền riêng tư Bảng tri ân (`wants_public`)**:
  - Mặc định `FALSE`. Khi Admin xác nhận, giá trị `is_public` của khoản đóng góp sẽ lấy theo `claim.wants_public`.
- **Bảng tri ân công khai**: Tuyệt đối **KHÔNG** đọc từ `support_claims`. Chỉ đọc từ `support_contributions` có `is_public = TRUE`.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `claim_id` | BIGINT IDENTITY | NO | auto | PK |
| `supporter_id` | BIGINT | NO | - | FK -> users(user_id) ON DELETE RESTRICT (người khai báo) |
| `claimed_amount_vnd` | BIGINT | NO | - | Số tiền khai báo VND nguyên dương, CHECK > 0 |
| `claimed_transferred_at` | TIMESTAMPTZ | NO | - | Thời gian chuyển tiền do người dùng khai báo |
| `sender_account_name` | VARCHAR(120) | YES | NULL | Tên chủ tài khoản chuyển tiền (bắt buộc nhập từ phía API/UI) |
| `wants_public` | BOOLEAN | NO | FALSE | Nguyện vọng công khai Bảng tri ân (mặc định FALSE) |
| `status` | VARCHAR(20) | NO | 'PENDING' | Trạng thái: PENDING, VERIFIED, REJECTED |
| `reviewed_by` | BIGINT | YES | NULL | FK -> users(user_id) ON DELETE SET NULL (Admin đối soát) |
| `reviewed_at` | TIMESTAMPTZ | YES | NULL | Thời điểm đối soát |
| `contribution_id` | BIGINT | YES | NULL | FK -> support_contributions(contribution_id) ON DELETE SET NULL |
| `rejection_reason` | VARCHAR(255) | YES | NULL | Lý do từ chối nếu không khớp sao kê |
| `created_at` | TIMESTAMPTZ | NO | NOW() | Thời điểm gửi yêu cầu xác nhận |

### 2.27. tutorials

Lưu trữ các video hướng dẫn sử dụng nhanh (Quick-Help Tutorial) định dạng dọc 9:16 do Quản trị viên (Admin) quản lý và tải lên trực tiếp thông qua Cloudinary. Video hướng dẫn được phân loại theo vị trí menu điều hướng thực tế (`feature_key` thuộc 10 mục điều hướng người dùng canonical) và có thể kèm theo một nút hành động điều hướng nhanh (`action_key` - "Làm ngay") đến tính năng tương ứng trên hệ sinh thái Chợ PTITers.

**Ngữ nghĩa nghiệp vụ & Vòng đời quản lý:**
- **Quản lý Admin động (Dynamic CMS)**: Quản trị viên có toàn quyền thêm mới, chỉnh sửa tiêu đề/mô tả, thay thế video 9:16 MP4, bật/tắt xuất bản (`is_published`), sắp xếp thứ tự hiển thị trực quan (`↑ ↓`), và xóa vĩnh viễn (hard delete). Không có chức năng tải lên/quản lý ảnh bìa (poster) tùy biến; ảnh thu nhỏ (thumbnail) được sinh tự động (derived) từ chính video Cloudinary.
- **Quyền riêng tư & Xuất bản**: Khách và sinh viên chỉ có thể xem các video có `is_published = TRUE` thông qua endpoint công khai `GET /api/v1/tutorials`. Các bản ghi nháp (`is_published = FALSE`) chỉ hiển thị trong giao diện Admin (`/admin/tutorials`).
- **Lưu trữ Blob & Metadata**: Tệp video MP4 là tài sản nhị phân duy nhất của Tutorial được lưu trữ trên Cloudinary (`student-marketplace/tutorials/videos`). PostgreSQL chỉ lưu URL và storage key của video. Ảnh thu nhỏ (`thumbnail_url`) là URL phân phối dẫn xuất (derived delivery transformation) từ video frame Cloudinary (thời điểm 1s hoặc 0.5s), không được lưu trữ như một cột database và không tạo thêm asset nhị phân độc lập trên Cloudinary.
- **Dọn dẹp & Bù trừ an toàn (Compensation & Post-commit Cleanup)**:
  - Khi tạo bản ghi mới hoặc thay thế video: nếu commit database thất bại, video mới tải lên Cloudinary được dọn dẹp theo chính sách best-effort.
  - Khi thay thế video hoặc xóa bản ghi: video cũ trên Cloudinary chỉ được dọn dẹp sau khi commit database thành công (post-commit). Lỗi dọn dẹp Cloudinary không làm hủy bỏ kết quả giao dịch database.
- **Thứ tự hiển thị (`sort_order`)**: Hệ thống tự động gán bước số (10, 20, 30...) vào cuối danh sách của nhóm tính năng khi tạo mới, không yêu cầu Admin nhập số thứ tự thủ công.

| Cột | Kiểu | Null | Mặc định | Ghi chú |
|---|---|---:|---|---|
| `tutorial_id` | BIGINT IDENTITY | NO | auto | PK |
| `feature_key` | VARCHAR(40) | NO | - | Khóa điều hướng canonical: HOME, FAVORITES, CREATE_PRODUCT, MY_LISTINGS, BUYER_ORDERS, SELLER_ORDERS, NOTIFICATIONS, MESSAGES, PROFILE, FEEDBACK |
| `title` | VARCHAR(120) | NO | - | Tiêu đề hướng dẫn (1..120 ký tự, trimmed) |
| `description` | VARCHAR(500) | YES | NULL | Mô tả chi tiết hướng dẫn (tối đa 500 ký tự) |
| `video_url` | VARCHAR(500) | NO | - | URL Cloudinary phân phối video (secure_url) |
| `video_storage_key` | VARCHAR(255) | NO | - | Cloudinary public_id của video (bảo mật, không lộ ra DTO công khai) |
| `video_mime_type` | VARCHAR(50) | NO | - | MIME type của video (video/mp4) |
| `video_size_bytes` | BIGINT | NO | - | Dung lượng video (bytes), CHECK video_size_bytes > 0 |
| `duration_ms` | BIGINT | YES | NULL | Thời lượng video (ms), CHECK duration_ms IS NULL OR duration_ms > 0 |
| `action_key` | VARCHAR(50) | YES | NULL | Khóa hành động điều hướng "Làm ngay" theo canonical Action Registry |
| `sort_order` | INTEGER | NO | 0 | Thứ tự hiển thị trong feature group, CHECK sort_order >= 0 |
| `is_published` | BOOLEAN | NO | FALSE | Trạng thái xuất bản công khai (mặc định FALSE - nháp) |
| `created_by` | BIGINT | NO | - | FK -> users(user_id) ON DELETE RESTRICT (Admin tạo) |
| `created_at` | TIMESTAMPTZ | NO | NOW() | Thời điểm tạo |
| `updated_at` | TIMESTAMPTZ | NO | NOW() | Trigger tự động cập nhật thời điểm sửa |

## 3. Khoá và hành động tham chiếu

| Bảng | PK | FK |
|---|---|---|
| `users` | user_id | - |
| `tutorials` | tutorial_id | created_by -> users (RESTRICT) |
| `moderation_actions` | moderation_action_id | report_id -> reports (CASCADE); admin_id -> users (RESTRICT) |
| `community_moments` | moment_id | user_id -> users (CASCADE); reviewed_by -> users (SET NULL) |
| `site_feedback` | feedback_id | user_id -> users (CASCADE) |
| `site_feedback_attachments` | attachment_id | feedback_id -> site_feedback (CASCADE) |
| `support_contributions` | contribution_id | supporter_id -> users (RESTRICT); recorded_by -> users (RESTRICT) |
| `support_claims` | claim_id | supporter_id -> users (RESTRICT); reviewed_by -> users (SET NULL); contribution_id -> support_contributions (SET NULL) |
| `user_auth_identities` | user_auth_identity_id | user_id -> users (CASCADE) |
| `categories` | category_id | - |
| `products` | product_id | seller_id -> users (RESTRICT); category_id -> categories |
| `product_images` | image_id | product_id -> products (CASCADE) |
| `orders` | order_id | buyer_id -> users (RESTRICT); seller_id -> users (RESTRICT) |
| `order_items` | order_item_id | order_id -> orders (CASCADE); product_id -> products (RESTRICT) |
| `order_status_history` | history_id | order_id -> orders (CASCADE); changed_by -> users (SET NULL) |
| `conversations` | conversation_id | user_one_id -> users; user_two_id -> users |
| `conversation_members` | (conversation_id, user_id) | conversation_id -> conversations (CASCADE); user_id -> users (CASCADE); last_read_message_id -> messages (SET NULL) |
| `conversation_invites` | invite_id | conversation_id -> conversations (CASCADE); inviter_id -> users (CASCADE); invitee_id -> users (CASCADE) |
| `messages` | message_id | conversation_id -> conversations (CASCADE); sender_id -> users; product_id -> products (SET NULL); order_id -> orders (SET NULL); reply_to_message_id -> messages (SET NULL) |
| `message_attachments` | attachment_id | message_id -> messages (CASCADE) |
| `message_mentions` | mention_id | message_id -> messages (CASCADE); mentioned_user_id -> users (CASCADE) |
| `reviews` | review_id | order_id -> orders (RESTRICT); reviewer_id -> users (RESTRICT); reviewee_id -> users (RESTRICT) |
| `favorites` | (user_id, product_id) | user_id -> users (CASCADE); product_id -> products (CASCADE) |
| `auctions` | auction_id | product_id -> products (CASCADE); winner_id -> users (RESTRICT) |
| `auction_bids` | bid_id | auction_id -> auctions (CASCADE); bidder_id -> users (RESTRICT) |
| `notifications` | notification_id | user_id -> users (CASCADE) |
| `reports` | report_id | reporter_id -> users (CASCADE); handled_by -> users (SET NULL) |
| `daily_needs` | daily_need_id | user_id -> users (CASCADE) |
| `daily_journal_checkins` | checkin_id | user_id -> users (CASCADE) |
| `report_attachments` | attachment_id | report_id -> reports (CASCADE) |

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
- `message_mentions(message_id, mentioned_user_id)` qua `uq_message_mentions_msg_user`
- `reviews(order_id, reviewer_id)`
- `favorites(user_id, product_id)` qua composite PK
- `auctions(product_id)`
- `daily_needs(user_id, note_date)`

### 4.2. Index thường

- `products(category_id, status, is_deleted, created_at)`
- `products(seller_id, status, created_at)`
- `products(listing_type, status, is_deleted, created_at)`
- GIN full-text index trên `products(title, description)` dùng `to_tsvector`
- `orders(buyer_id, status, created_at)`
- `orders(seller_id, status, created_at)`
- `orders(status, payment_status, auto_cancel_at)`
- `orders(payment_status, receipt_uploaded_at)`
- Partial UNIQUE `ux_orders_auction_id` trên `orders(auction_id) WHERE auction_id IS NOT NULL`
- `order_items(product_id)`
- `conversations(user_one_id, last_message_at)` và `(user_two_id, last_message_at)`
- `conversation_members(user_id, left_at)` (`ix_conversation_members_user_active`)
- `conversation_members(conversation_id)` (`ix_conversation_members_conversation_id`)
- `messages(conversation_id, sent_at)`
- `messages(conversation_id, sender_id, read_at)`
- `message_attachments(message_id)`
- `message_mentions(mentioned_user_id)` (`ix_message_mentions_user_id`)
- `message_mentions(message_id)` (`ix_message_mentions_message_id`)
- `reviews(reviewee_id, created_at DESC, review_id DESC)` để phân trang keyset đánh giá công khai của người bán
- `favorites(product_id)`
- `auctions(product_id)`
- Partial UNIQUE `ux_auctions_product_active` trên `auctions(product_id) WHERE status IN ('SCHEDULED', 'ACTIVE')`
- `auctions(status, ends_at)` để worker tìm phiên cần đóng
- `auctions(status, starts_at)` để worker tìm phiên SCHEDULED cần kích hoạt
- `auctions(status, winner_checkout_deadline)` để worker tìm winner timeout
- `auction_bids(auction_id, amount DESC, created_at ASC, bid_id ASC)` để lấy bid cao nhất và phân trang keyset
- `auction_bids(bidder_id, created_at)` để xem lịch sử bid của user
- `notifications(user_id, is_read, created_at)`
- `daily_needs(note_date, updated_at DESC, daily_need_id DESC)`
- `daily_needs(user_id)`
- `report_attachments(report_id)` (`ix_report_attachments_report_id`)
- `reports(status, created_at DESC, report_id DESC)` (`ix_reports_status_created_desc`) để phân trang keyset hàng đợi kiểm duyệt báo cáo của quản trị viên
- `reports(reporter_id, target_type, target_id)` (`ix_reports_reporter_target`) để kiểm tra báo cáo đang hoạt động trùng lặp và bảo vệ khoá ngoại `reporter_id -> users`
- `community_moments(status, created_at DESC, moment_id DESC)` (`idx_community_moments_admin_queue`)
- `site_feedback(created_at DESC, feedback_id DESC)` (`idx_site_feedback_created_at`) để phân trang keyset bảng tin công khai và danh sách quản trị
- `site_feedback(user_id, created_at DESC, feedback_id DESC)` (`idx_site_feedback_user_created`) để tra cứu lịch sử feedback của người dùng
- `site_feedback_attachments(feedback_id)` (`idx_site_feedback_attachments_feedback_id`)
- `support_contributions(received_at DESC, contribution_id DESC)` (`ix_support_contributions_ledger`) để phân trang keyset sổ cái quản trị
- `support_contributions(is_public, supporter_id)` (`ix_support_contributions_public`) để tổng hợp nhanh Bảng tri ân công khai
- `support_claims(status, created_at DESC, claim_id DESC)` (`ix_support_claims_status_created`) để phân trang keyset hàng đợi đối soát Admin
- `support_claims(supporter_id, created_at DESC, claim_id DESC)` (`ix_support_claims_supporter`) để tra cứu lịch sử yêu cầu của người dùng
- `support_claims(reviewed_by)` (`ix_support_claims_reviewed_by`) bảo vệ khoá ngoại Admin đối soát
- `support_claims(contribution_id)` (`ix_support_claims_contribution_id`) bảo vệ khoá ngoại liên kết đóng góp
- `tutorials(is_published, feature_key, sort_order, tutorial_id)` (`ix_tutorials_pub_feature_sort`) để tối ưu hóa truy vấn danh sách hướng dẫn công khai và sắp xếp danh mục quản trị

## 5. CHECK constraints

- `tutorials.video_size_bytes > 0`
- `tutorials.duration_ms IS NULL OR tutorials.duration_ms > 0`
- `tutorials.sort_order >= 0`
- `orders.buyer_id <> orders.seller_id`
- `orders.payment_status <> 'VERIFYING' OR payment_receipt_url IS NOT NULL`
- `orders.payment_status <> 'PAID' OR paid_confirmed_at IS NOT NULL`
- `community_moments.status IN ('PENDING', 'APPROVED', 'REJECTED')`
- `site_feedback_attachments.kind IN ('IMAGE', 'VIDEO')`
- `site_feedback_attachments.size_bytes > 0`
- `support_contributions.amount_vnd > 0`
- `support_claims.claimed_amount_vnd > 0`
- `support_claims.status IN ('PENDING', 'VERIFIED', 'REJECTED')`
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
- `report_attachments.size_bytes > 0`
- `report_attachments.mime_type IN ('image/jpeg', 'image/png', 'image/webp')`
- `auctions.bid_step > 0`
- `auctions.starting_price >= 0`
- `auctions.ends_at > auctions.starts_at`
- `auctions.status IN ('SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')`
- `auctions.final_price IS NULL OR auctions.final_price >= auctions.starting_price`
- `auctions.status = 'ENDED' OR (auctions.winner_id IS NULL AND auctions.final_price IS NULL AND auctions.winner_checkout_deadline IS NULL)`
- `(auctions.winner_id IS NULL AND auctions.final_price IS NULL AND auctions.winner_checkout_deadline IS NULL) OR (auctions.winner_id IS NOT NULL AND auctions.final_price IS NOT NULL AND auctions.final_price > 0 AND auctions.winner_checkout_deadline IS NOT NULL)`
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

### 7.6. Nhật ký hôm nay (Daily Journal) & Chuỗi ngày (Streak)
 
Tính năng **"Nhật ký hôm nay"** (Daily Journal) tách biệt hai khái niệm miền độc lập:
1. **Nội dung công khai biến đổi (`daily_needs`)**: Người dùng có thể đăng, chỉnh sửa hoặc xóa nội dung nhật ký công khai trong ngày.
2. **Sự kiện tích lũy chuỗi bất biến (`daily_journal_checkins`)**: Sự kiện chứng minh người dùng đã tham gia đăng nhật ký thành công ít nhất một lần trong ngày lịch.
 
#### Cấu trúc bảng `daily_needs` (Nội dung có thể xóa/sửa)
- `daily_need_id` BIGSERIAL PRIMARY KEY
- `user_id` BIGINT NOT NULL REFERENCES `users(user_id)` ON DELETE CASCADE
- `note_date` DATE NOT NULL (Ngày lịch theo múi giờ `Asia/Ho_Chi_Minh`)
- `content` VARCHAR(120) NOT NULL (Nội dung nhật ký công khai, text thuần túy)
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- `updated_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- UNIQUE CONSTRAINT `uq_daily_needs_user_date (user_id, note_date)`
- INDEX `ix_daily_needs_user_id (user_id)`
- INDEX `ix_daily_needs_today_recency (note_date, updated_at, daily_need_id)`

#### Cấu trúc bảng `daily_journal_checkins` (Chứng nhận chuỗi bất biến)
- `checkin_id` BIGSERIAL PRIMARY KEY
- `user_id` BIGINT NOT NULL REFERENCES `users(user_id)` ON DELETE CASCADE
- `checkin_date` DATE NOT NULL (Ngày điểm danh theo múi giờ `Asia/Ho_Chi_Minh`)
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- UNIQUE CONSTRAINT `uq_daily_journal_checkins_user_date (user_id, checkin_date)`
- INDEX `ix_daily_journal_checkins_user_id (user_id)`
 
#### Quy tắc nghiệp vụ & Tính toán Streak
1. **Giao dịch đăng bài nguyên tử (Atomic First Publish)**:
   - Khi đăng bài trong ngày, `daily_needs` và `daily_journal_checkins` được ghi đồng thời trong cùng một transaction.
   - `INSERT INTO daily_journal_checkins ... ON CONFLICT (user_id, checkin_date) DO NOTHING RETURNING checkin_id` đảm bảo tính lũy đẳng (idempotent), an toàn tuyệt đối với request đồng thời (concurrent).
   - Server trả về cờ tạm thời `checkin_created: bool` để frontend chỉ kích hoạt hiệu ứng ngọn lửa bùng cháy (activation animation) đúng 1 lần cho lượt đăng đầu tiên tạo ra check-in mới.
2. **Quy tắc bảo lưu chuỗi khi xóa nội dung (Streak Preservation on Delete)**:
   - Xóa nhật ký trong ngày chỉ xóa dòng trong `daily_needs`.
   - Bảng `daily_journal_checkins` KHÔNG bị xóa.
   - Trạng thái `has_journal_today` trở về `false` (nội dung biến mất khỏi Marquee trang chủ và Direct Chat header).
   - Trạng thái `has_checked_in_today` vẫn là `true`, số ngày chuỗi `streak_count` giữ nguyên, ngọn lửa trang chủ vẫn giữ màu rực sáng.
3. **Đăng lại sau khi xóa (Repost after Delete)**:
   - Tái tạo nội dung `daily_needs`.
   - Tái sử dụng check-in đã có trong ngày (`checkin_created = false`), chuỗi không bị tăng đúp, không kích hoạt lại animation ngọn lửa.
4. **Tính toán chuỗi liên tiếp (Streak)**:
   - Tính toán động, có tính xác định hoàn toàn từ server bằng SQL Recursive CTE dựa trên bảng chuẩn `daily_journal_checkins` qua chỉ mục `(user_id, checkin_date)`:
     - Nếu hôm nay đã check-in (`has_checked_in_today = true`): đếm số ngày liên tục lùi từ `today`.
     - Nếu hôm nay chưa check-in: kiểm tra `yesterday`. Nếu hôm qua có check-in, đếm số ngày liên tục lùi từ `yesterday` (hiển thị ngọn lửa xám). Nếu hôm qua bỏ lỡ, chuỗi = 0.
   - Không giới hạn trần giả định (không có limit 365 ngày).
5. **Giới hạn chuyển đổi dữ liệu lịch sử (Migration Backfill Limitation)**:
   - Migration chuyển giao tất cả dữ liệu lịch sử đang tồn tại trong `daily_needs` sang `daily_journal_checkins`.
   - Các bài đăng đã bị xóa vĩnh viễn trước khi bảng `daily_journal_checkins` được thiết lập không còn dấu vết để khôi phục. Từ thời điểm migration trở đi, mọi hành vi xóa nội dung đều bảo toàn 100% check-in chuỗi.

### 7.7. Bày tỏ cảm xúc tin nhắn Chợ PTITers (Message Reactions)

Bộ cảm xúc chữ ký mang nhận diện Chợ PTITers cho tin nhắn trong Direct và Group Chat.

#### Cấu trúc bảng `message_reactions`
- `reaction_id` BIGSERIAL PRIMARY KEY
- `message_id` BIGINT NOT NULL REFERENCES `messages(message_id)` ON DELETE CASCADE
- `user_id` BIGINT NOT NULL REFERENCES `users(user_id)` ON DELETE CASCADE
- `reaction_key` VARCHAR(32) NOT NULL
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- `updated_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- UNIQUE CONSTRAINT `uq_message_reactions_message_user (message_id, user_id)` (mỗi user tối đa 1 reaction cho mỗi tin nhắn)
- INDEX `ix_message_reactions_user_id (user_id)`
- CHECK CONSTRAINT `chk_message_reactions_key`: 12 giá trị ASCII chuẩn hóa:
  `'THICH', 'HAHA', 'WOW', 'CAM_ON', 'CHOT_DEAL', 'UY_TIN', 'DANG_TOI', 'DOI_CHUT', 'QUAN_TAM', 'HET_TIEN', 'HOC_BAI', 'KHA_NGHI'`

#### Quy tắc nghiệp vụ & Hiệu ứng phụ
1. **Phạm vi hỗ trợ**:
   - `DIRECT`: Người dùng phải là một trong 2 người tham gia canonical (`user_one_id` hoặc `user_two_id`). Không yêu cầu dòng `conversation_members`.
   - `GROUP`: Người dùng phải là thành viên hoạt động (`left_at IS NULL`). Không được reaction tin nhắn gửi trước `joined_at` của mình.
   - `COMMUNITY`: Từ chối hoàn toàn với mã `400 Bad Request`.
2. **Không áp dụng cho tin nhắn hệ thống (`type = 'SYSTEM'`)** hoặc tin nhắn đã xóa.
3. **Zero Side Effects**: Hoạt động reaction là metadata thuần túy. Tuyệt đối không tạo dòng `notifications`, không làm tăng unread counter, không cập nhật `conversations.last_message_at`, không tạo tin nhắn mới.
4. **Hiển thị & Batch Aggregation**: Truy vấn lịch sử tin nhắn gom nhóm reaction theo batch `IN (:message_ids)` với độ phức tạp O(1) query count cho mỗi trang tin nhắn.
5. **Realtime**: Phát sóng sự kiện `MESSAGE_REACTIONS_UPDATED` qua hạ tầng WebSocket cá nhân `/ws/me` hiện có tới các thành viên hợp lệ. Thất bại realtime không rollback giao dịch cơ sở dữ liệu.

### 7.8. Minh chứng báo cáo vi phạm (Report Evidence)

1. **Giới hạn số lượng**: Tối đa 5 ảnh minh chứng cho mỗi báo cáo (`existing_count + new_files <= 5`).
2. **Định dạng & Dung lượng**:
   - Chỉ chấp nhận các định dạng ảnh: JPEG, PNG, WebP (xác thực chữ ký magic bytes).
   - Tuyệt đối không chấp nhận file thực thi, SVG, hoặc các định dạng ngoài chính sách.
   - Dung lượng tối đa: 10MB (10,485,760 bytes) cho mỗi ảnh.
   - Kiểm tra hợp lệ toàn bộ danh sách tệp cục bộ trước khi thực hiện bất kỳ lệnh upload nào lên Cloudinary.
3. **An toàn tương tranh & Giao dịch 2 pha (Race-Safe 2-Phase Upload)**:
   - Pha 1: Tải lên Cloudinary đồng thời theo dõi danh sách `public_id` đã tạo.
   - Pha 2: Mở transaction ghi DB, thực hiện khóa dòng `reports` bằng `SELECT ... FOR UPDATE` (với `populate_existing = true`).
   - Kiểm tra lại dưới lock: báo cáo còn tồn tại, thuộc quyền sở hữu của `reporter_id`, trạng thái là `OPEN` hoặc `REVIEWING`, và tổng số lượng minh chứng không vượt quá 5.
   - Nếu vi phạm (ví dụ: Admin đã giải quyết báo cáo, hoặc request đồng thời khác đã chiếm dung lượng): rollback DB transaction, thực hiện xóa bù trừ (compensation cleanup) tất cả asset vừa tải lên Cloudinary, và trả về mã lỗi 409 Conflict.
4. **Bảo mật & Phân quyền**:
   - Người dùng chỉ được đính kèm minh chứng vào báo cáo do chính mình tạo khi báo cáo còn mở (`OPEN` hoặc `REVIEWING`).
   - Yêu cầu truy cập từ người dùng khác trả về 404 Not Found để không làm lộ sự tồn tại của báo cáo.
   - DTO công khai không bao giờ để lộ Cloudinary raw URL hoặc `storage_key`.
   - Admin xem minh chứng thông qua endpoint streaming bảo mật `GET /admin/reports/{report_id}/evidence/{attachment_id}?variant=thumbnail|full`. Không cho phép client truyền các biến thể transformation tùy ý.

### 7.9. Nhật ký thực thi kiểm duyệt (Moderation Actions Audit Trail)

Bảng `moderation_actions` lưu trữ nhật ký bất biến (immutable audit trail) cho mọi hành động thực thi chế tài (Enforcement Actions) của Quản trị viên đối với người dùng, tin đăng, và giao dịch.

#### Cấu trúc bảng `moderation_actions`
- `moderation_action_id` BIGSERIAL PRIMARY KEY
- `report_id` BIGINT NOT NULL REFERENCES `reports(report_id)` ON DELETE RESTRICT
- `admin_id` BIGINT NOT NULL REFERENCES `users(user_id)` ON DELETE RESTRICT
- `action_type` VARCHAR(50) NOT NULL (`'USER_BAN'`, `'USER_UNBAN'`, `'PRODUCT_HIDE'`, `'PRODUCT_RESTORE'`, `'BUY_RESTRICT'`, `'BUY_RESTORE'`, `'SELL_RESTRICT'`, `'SELL_RESTORE'`)
- `target_type` VARCHAR(20) NOT NULL (`'USER'`, `'PRODUCT'`)
- `target_id` BIGINT NOT NULL
- `previous_status` VARCHAR(50) NOT NULL
- `new_status` VARCHAR(50) NOT NULL
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()
- INDEX `ix_moderation_actions_report_id (report_id)`
- INDEX `ix_moderation_actions_target (target_type, target_id)`
- INDEX `ix_moderation_actions_admin_id (admin_id)`
- INDEX `ix_moderation_actions_created_at (created_at DESC)`

#### Quy tắc nghiệp vụ & Tính toàn vẹn
1. **Tính bất biến (Immutability)**:
   - Bản ghi sau khi được tạo chỉ dùng cho mục đích tra cứu và đối soát, không bao giờ được phép UPDATE hay DELETE trong luồng nghiệp vụ.
   - Không chứa cột `reason` tùy tiện (tránh trùng lặp với lý do báo cáo).
2. **Khóa thứ tự chuẩn hóa (Canonical Lock Order)**:
   - Thứ tự khóa bắt buộc cho mọi luồng thực thi liên quan đến người dùng:
     1. Khóa dòng `reports` (`SELECT ... FOR UPDATE`)
     2. Khóa dòng `users` (`SELECT ... FOR UPDATE`)
   - Thứ tự khóa đồng nhất trên mọi luồng BAN, UNBAN, CAPABILITY_RESTRICT, CAPABILITY_RESTORE giúp giảm thiểu đáng kể rủi ro deadlock cơ sở dữ liệu.
3. **Ràng buộc khóa ngoại an toàn (`ON DELETE RESTRICT`)**:
   - `report_id` và `admin_id` đều sử dụng `ON DELETE RESTRICT` để ngăn việc xóa báo cáo hoặc tài khoản quản trị viên làm mất vết kiểm duyệt.
4. **Cô lập tài khoản bị khóa (Banned Account Isolation)**:
   - Khi tài khoản bị `BANNED`, các tin đăng của người bán tự động bị ẩn khỏi danh sách tìm kiếm công khai thông qua join điều kiện `User.status == 'ACTIVE'`, không làm thay đổi trạng thái gốc `Product.status`.
   - Các hành động tạo đơn mua hàng hoặc đấu giá với người bán bị khóa bị từ chối với lỗi 403 Forbidden.

### 7.10. Chế tài hạn chế quyền tài khoản (Account Capability Restrictions)

Quy tắc nghiệp vụ áp dụng các lệnh hạn chế quyền có thời hạn lên tài khoản người dùng (`BUY` hoặc `SELL`), phát sinh từ quy trình xử lý báo cáo vi phạm (`POST /api/v1/admin/reports/{id}/enforcement`). Chi tiết schema bảng quan hệ xem tại §2.21 `user_capability_restrictions`.

#### Quy tắc nghiệp vụ & Hiệu lực chế tài
1. **Hiệu lực chế tài**:
   - Một restriction được coi là đang có hiệu lực tại thời điểm `T` khi và chỉ khi:
     `starts_at <= T` AND `revoked_at IS NULL` AND (`expires_at IS NULL` OR `expires_at > T`).
2. **Quyền BUY bị hạn chế**:
   - Chặn tạo đơn hàng mua (`POST /api/v1/orders`), chặn đặt bid (`POST /api/v1/auctions/{id}/bids`), chặn checkout thắng đấu giá (`POST /api/v1/auctions/{id}/checkout`).
3. **Quyền SELL bị hạn chế**:
   - Chặn đăng tin mới (`POST /api/v1/products`), chặn kích hoạt phiên đấu giá (`POST /api/v1/auctions`).
   - Tự động hủy nguyên tử các phiên đấu giá `SCHEDULED` hoặc `ACTIVE` của người bán sang `CANCELLED`, bảo lưu bid lịch sử, chuyển `listing_type = 'FIXED_PRICE'`.
   - Ẩn sản phẩm của người bán khỏi danh sách yêu thích `GET /favorites` và `GET /favorites/ids` của người mua (bảo toàn row trong DB).



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
