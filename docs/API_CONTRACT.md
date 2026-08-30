# API CONTRACT — Phase 1: Auth & Users

Tài liệu này định nghĩa API contract chính thức cho backend `student-marketplace-be` tại **Phase 1 — Auth + Users**.

---

## 1. Cơ chế xác thực (Authentication)

- **Authority**: Firebase Authentication.
- **Header xác thực**:
  ```http
  Authorization: Bearer <FIREBASE_ID_TOKEN>
  ```
- **Xử lý token**:
  - Backend giải mã và xác thực chữ ký của Firebase ID Token qua Firebase Admin SDK.
  - Sau khi xác thực thành công, backend trích xuất `uid` (Firebase UID).
  - Backend map `uid` sang bảng `user_auth_identities` để lấy `users.user_id` nội bộ.
  - Tuyệt đối không chấp nhận `uid`, `user_id`, hay `role` do client tự gửi trong body / header / query param để chứng minh danh tính.

### First-login Provisioning (Đăng nhập lần đầu)
- Nếu Firebase UID chưa tồn tại trong `user_auth_identities`:
  - Hệ thống tự động tạo bản ghi `users` với `role='STUDENT'`, `status='ACTIVE'`, `email` và `full_name` từ token.
  - Hệ thống tạo bản ghi `user_auth_identities` liên kết với `user_id`.
  - Toàn bộ quá trình thực hiện nguyên tử (**atomic transaction**).

### Xử lý trạng thái tài khoản (`users.status`)
- `ACTIVE`: Được phép truy cập tất cả các authenticated endpoints.
- `BANNED`: Bị từ chối với HTTP `403 Forbidden` (`{"detail": "User account is banned."}`).
- `INACTIVE`: Bị từ chối với HTTP `403 Forbidden` (`{"detail": "User account is inactive."}`).

---

## 2. Danh sách Endpoints Phase 1

### 2.1. Lấy thông tin Current User

- **Method**: `GET`
- **Path**: `/api/v1/users/me`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`

#### Request
- Headers:
  ```http
  Authorization: Bearer <FIREBASE_ID_TOKEN>
  ```
- Body: Không có.

#### Response: `200 OK`
```json
{
  "user_id": 1,
  "email": "student@university.edu.vn",
  "full_name": "Nguyen Van A",
  "phone": "0912345678",
  "avatar_url": "https://lh3.googleusercontent.com/a/.../photo.jpg",
  "bio": "Sinh viên năm 3 CNTT",
  "default_meetup_area": "Sảnh A, Toà H1, ĐHBK",
  "role": "STUDENT",
  "status": "ACTIVE",
  "last_active_at": "2026-08-25T09:50:00",
  "created_at": "2026-08-25T09:40:00",
  "updated_at": "2026-08-25T09:50:00"
}
```

#### Error Responses
- `401 Unauthorized`:
  - Token bị thiếu: `{"detail": "Missing or invalid Authorization header."}`
  - Token không hợp lệ / hết hạn: `{"detail": "Firebase token has expired."}` hoặc `{"detail": "Invalid Firebase token."}`
- `403 Forbidden`:
  - Tài khoản bị khoá: `{"detail": "User account is banned."}`
  - Tài khoản không hoạt động: `{"detail": "User account is inactive."}`
- `503 Service Unavailable`:
  - Firebase Admin SDK chưa được cấu hình credentials.

---

### 2.2. `PATCH /api/v1/users/me` — Cập nhật thông tin cá nhân

- **Method**: `PATCH`
- **Path**: `/api/v1/users/me`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`

#### Request
- Headers:
  ```http
  Authorization: Bearer <FIREBASE_ID_TOKEN>
  Content-Type: application/json
  ```
- Body (`UserUpdate`):
```json
{
  "full_name": "Nguyen Van A (Updated)",
  "phone": "0987654321",
  "bio": "Sinh viên năm cuối CNTT",
  "default_meetup_area": "Căn tin B1"
}
```
*Ghi chú*: Mọi trường đều là optional. `avatar_url` được quản lý và đồng bộ tự động từ tài khoản Google/Firebase của người dùng khi đăng nhập, không được phép chỉnh sửa qua endpoint này. Tuyệt đối không cho phép client cập nhật: `avatar_url`, `user_id`, `email`, `role`, `status`, `created_at`, `updated_at`, `provider_uid`. Nếu client gửi `avatar_url` hoặc các trường ngoài danh mục cho phép, request sẽ bị từ chối với `422 Unprocessable Entity`.

#### Response: `200 OK`
Trích xuất `UserResponse` đã được cập nhật:
```json
{
  "user_id": 1,
  "email": "student@university.edu.vn",
  "full_name": "Nguyen Van A (Updated)",
  "phone": "0987654321",
  "avatar_url": "https://lh3.googleusercontent.com/a/.../photo.jpg",
  "bio": "Sinh viên năm cuối CNTT",
  "default_meetup_area": "Căn tin B1",
  "role": "STUDENT",
  "status": "ACTIVE",
  "last_active_at": "2026-08-25T09:50:00",
  "created_at": "2026-08-25T09:40:00",
  "updated_at": "2026-08-25T09:55:00"
}
```

#### Error Responses
- `401 Unauthorized`: Lỗi xác thực token.
- `403 Forbidden`: Tài khoản BANNED hoặc INACTIVE.
- `422 Unprocessable Entity`: Body validation failed (ví dụ: `phone` quá 20 ký tự, `full_name` trống, gửi trường không được phép).

---

### 2.3. `GET /api/v1/users/banks` — Danh sách ngân hàng Việt Nam hỗ trợ (VietQR/NAPAS)

- **Method**: `GET`
- **Path**: `/api/v1/users/banks`
- **Authentication**: Không bắt buộc / Public
- **Response: `200 OK`**:
```json
[
  {
    "bin": "970422",
    "code": "MB",
    "short_name": "MBBank",
    "name": "Ngân hàng TMCP Quân đội"
  },
  {
    "bin": "970436",
    "code": "VCB",
    "short_name": "Vietcombank",
    "name": "Ngân hàng TMCP Ngoại thương Việt Nam"
  }
]
```

---

### 2.4. `GET /api/v1/users/me/bank-account` — Lấy thông tin tài khoản nhận tiền

- **Method**: `GET`
- **Path**: `/api/v1/users/me/bank-account`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`
- **Response: `200 OK`**:
  - Khi đã cấu hình:
    ```json
    {
      "bank_bin": "970422",
      "bank_code": "MB",
      "bank_name": "Ngân hàng TMCP Quân đội",
      "bank_short_name": "MBBank",
      "account_number": "0123456789",
      "account_name": "NGUYEN VAN A"
    }
    ```
  - Khi chưa cấu hình: trả về JSON `null` với HTTP `200 OK`.

---

### 2.5. `PUT /api/v1/users/me/bank-account` — Thiết lập / Cập nhật tài khoản nhận tiền

- **Method**: `PUT`
- **Path**: `/api/v1/users/me/bank-account`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`
- **Request Body**:
```json
{
  "bank_bin": "970422",
  "account_number": "0123456789",
  "account_name": "NGUYEN VAN A"
}
```
- **Validation**:
  - `bank_bin`: Nhận mã BIN chuẩn (VD: `970422`) hoặc Code ngân hàng (VD: `MB`). Backend tự động chuẩn hóa sang canonical BIN.
  - `account_number`: 4 - 30 ký tự alphanumeric, không chứa khoảng trắng hoặc ký tự đặc biệt.
  - `account_name`: 2 - 100 ký tự.
- **Response: `200 OK`** (`BankAccountResponse`).

---

### 2.6. `DELETE /api/v1/users/me/bank-account` — Xóa tài khoản nhận tiền

- **Method**: `DELETE`
- **Path**: `/api/v1/users/me/bank-account`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`
- **Business Rule**: Xóa thông tin tài khoản ngân hàng khỏi hồ sơ cá nhân. Không ảnh hưởng đến các đơn hàng đã xác nhận snapshot trước đó.
- **Response: `204 No Content`**.

---

## 3. Foundation Authorization Roles & Helpers

Backend cung cấp các dependency authorization nền tảng dùng cho các module/phase tiếp theo:
- `get_current_user`: Trích xuất payload từ token và load `User`.
- `get_current_active_user`: Enforce `status == ACTIVE`.
- `require_role(*roles)`: Enforce user có role trong danh sách được cấp phép (ví dụ: `ADMIN`, `STUDENT`).
- `require_admin`: Enforce `role == 'ADMIN'`. Trả về `403 Forbidden` nếu không phải admin.

---

## 4. Phase 2 Endpoints: Categories, Products & Product Images

### 4.1. Categories Endpoints

#### 4.1.1. Lấy danh sách danh mục active
- **Method**: `GET`
- **Path**: `/api/v1/categories`
- **Auth**: Public (Anonymous)
- **Response**: `200 OK`
```json
[
  {
    "category_id": 1,
    "name": "Giáo trình & Sách",
    "slug": "giao-trinh-sach"
  }
]
```

#### 4.1.2. Lấy chi tiết danh mục
- **Method**: `GET`
- **Path**: `/api/v1/categories/{category_id}`
- **Auth**: Public (Anonymous)
- **Response**: `200 OK` (hoặc `404 Not Found` nếu không tồn tại hoặc đã bị xóa mềm).

---

### 4.2. Products — Public Discovery Endpoints

#### 4.2.1. Danh sách sản phẩm public (Keyset Cursor Pagination & Full-Text Search)
- **Method**: `GET`
- **Path**: `/api/v1/products`
- **Auth**: Public
- **Query Parameters**:
  - `category_id` (int, optional)
  - `listing_type` (`FIXED_PRICE` | `AUCTION`, optional)
  - `min_price` (Decimal >= 0, optional)
  - `max_price` (Decimal >= 0, optional)
  - `q` (string, optional) — PostgreSQL GIN search trên `title` và `description`
  - `limit` (int, 1-50, default 20)
  - `cursor` (string Base64 opaque, optional)
- **Response**: `200 OK`
```json
{
  "items": [
    {
      "product_id": 1,
      "title": "Giáo trình Giải tích 1 PTIT",
      "price": 45000,
      "listing_type": "FIXED_PRICE",
      "status": "AVAILABLE",
      "available_stock": 1,
      "thumbnail_url": "https://res.cloudinary.com/.../f_auto,q_auto,w_200/book.jpg",
      "category": {
        "category_id": 1,
        "name": "Giáo trình & Sách",
        "slug": "giao-trinh-sach"
      },
      "seller": {
        "user_id": 10,
        "full_name": "Nguyen Van A",
        "avatar_url": "https://res.cloudinary.com/.../avatar.jpg"
      },
      "created_at": "2026-08-26T10:00:00"
    }
  ],
  "next_cursor": "MjAyNi0wOC0yNlQxMDowMDowMHwx",
  "has_more": true
}
```
*Ghi chú*: Chỉ trả về các sản phẩm `is_deleted = False` và `status = 'AVAILABLE'`. Không hiển thị `reserved_stock` ra public.

#### 4.2.2. Chi tiết sản phẩm
- **Method**: `GET`
- **Path**: `/api/v1/products/{product_id}`
- **Auth**: Public (Optional Bearer token).
- **Semantics**:
  - Nếu sản phẩm `is_deleted = True`: Trả về `404 Not Found`.
  - Nếu sản phẩm `status = 'HIDDEN'`: Trả về `404 Not Found` cho public/buyer; trả về `200 OK` nếu request được thực hiện bởi chính chủ sở hữu (`seller_id == current_user.user_id`).
- **Response**: `200 OK`
```json
{
  "product_id": 1,
  "title": "Giáo trình Giải tích 1 PTIT",
  "description": "Sách còn mới 95%, không rách bìa",
  "listing_type": "FIXED_PRICE",
  "price": 45000,
  "available_stock": 1,
  "status": "AVAILABLE",
  "view_count": 12,
  "images": [
    {
      "image_id": 1,
      "product_id": 1,
      "image_url": "https://res.cloudinary.com/.../raw_image.jpg",
      "detail_url": "https://res.cloudinary.com/.../f_auto,q_auto,w_800/raw_image.jpg",
      "sort_order": 0,
      "is_thumbnail": true
    }
  ],
  "category": {
    "category_id": 1,
    "name": "Giáo trình & Sách",
    "slug": "giao-trinh-sach"
  },
  "seller": {
    "user_id": 10,
    "full_name": "Nguyen Van A",
    "avatar_url": "https://res.cloudinary.com/.../avatar.jpg",
    "default_meetup_area": "Sảnh A1 PTIT",
    "created_at": "2026-08-20T08:00:00"
  },
  "created_at": "2026-08-26T10:00:00",
  "updated_at": "2026-08-26T10:00:00"
}
```

---

### 4.3. Products — Seller Management Endpoints

#### 4.3.1. Danh sách sản phẩm của người bán
- **Method**: `GET`
- **Path**: `/api/v1/products/me`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Query Parameters**:
  - `status` (`AVAILABLE` | `HIDDEN` | `SOLD_OUT`, optional)
  - `limit` (int, 1-50, default 20)
  - `cursor` (string Base64 opaque, optional)
- **Response**: `200 OK` (Trả về `stock`, `reserved_stock`, `available_stock`).

#### 4.3.2. Đăng tin bán sản phẩm mới
- **Method**: `POST`
- **Path**: `/api/v1/products`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Request Body** (`ProductCreate` - `extra = "forbid"`):
```json
{
  "category_id": 1,
  "title": "Giáo trình Giải tích 1 PTIT",
  "description": "Sách còn mới 95%",
  "listing_type": "FIXED_PRICE",
  "price": 45000,
  "stock": 1
}
```
*Ghi chú*: Inject các protected fields (`seller_id`, `reserved_stock`, `view_count`, `is_deleted`, `status`) sẽ bị từ chối với HTTP `422`.

#### 4.3.3. Cập nhật thông tin tin đăng
- **Method**: `PATCH`
- **Path**: `/api/v1/products/{product_id}`
- **Auth**: Bắt buộc (Chính chủ sở hữu hoặc ADMIN)
- **Request Body** (`ProductUpdate` - `extra = "forbid"`):
```json
{
  "title": "Giáo trình Giải tích 1 PTIT (Đã bọc bìa)",
  "price": 40000,
  "status": "HIDDEN"
}
```
*Ghi chú*: Trạng thái `status` chỉ được phép chuyển đổi giữa `AVAILABLE <-> HIDDEN`. Cố tình gán `SOLD_OUT` hoặc các trường protected sẽ nhận HTTP `422`.

#### 4.3.4. Xóa mềm tin đăng
- **Method**: `DELETE`
- **Path**: `/api/v1/products/{product_id}`
- **Auth**: Bắt buộc (Chính chủ sở hữu hoặc ADMIN)
- **Response**: `204 No Content` (Gán `is_deleted = True`).

---

### 4.4. Product Images Endpoints (Owner Only)

#### 4.4.1. Upload ảnh sản phẩm
- **Method**: `POST`
- **Path**: `/api/v1/products/{product_id}/images/upload`
- **Auth**: Bắt buộc (Owner only)
- **Content-Type**: `multipart/form-data` (`file: UploadFile`)
- **Response**: `201 Created` (`ProductImageResponse`)
- **Compensation**: Nếu lưu DB thất bại sau khi upload Cloudinary thành công, service tự động trigger best-effort cleanup xóa asset Cloudinary để tránh rác storage.

#### 4.4.2. Xóa ảnh sản phẩm
- **Method**: `DELETE`
- **Path**: `/api/v1/products/{product_id}/images/{image_id}`
- **Auth**: Bắt buộc (Owner only)
- **Response**: `204 No Content`
- **Thumbnail Auto-Promotion**: Nếu ảnh bị xóa là thumbnail, ảnh kế tiếp theo thứ tự `(sort_order ASC, image_id ASC)` sẽ tự động được promote làm thumbnail mới.

#### 4.4.3. Đặt ảnh làm thumbnail chính
- **Method**: `PATCH`
- **Path**: `/api/v1/products/{product_id}/images/{image_id}/thumbnail`
- **Auth**: Bắt buộc (Owner only)
- **Response**: `200 OK` (Atomic transaction đảm bảo duy nhất 1 thumbnail).

#### 4.4.4. Sắp xếp lại thứ tự ảnh
- **Method**: `PUT`
- **Path**: `/api/v1/products/{product_id}/images/reorder`
- **Auth**: Bắt buộc (Owner only)
- **Request Body**:
```json
{
  "images": [
    { "image_id": 1, "sort_order": 0 },
    { "image_id": 2, "sort_order": 1 }
  ]
}
```
- **Response**: `200 OK` (Validate toàn bộ image_id thuộc đúng product_id, trả 404 nếu có cross-product image).

---

## 5. Phase 3 Endpoints: Favorites (Tin yêu thích)

Tất cả các endpoints trong mục này yêu cầu người dùng xác thực hợp lệ (`Bearer <Firebase ID Token>`) và có trạng thái tài khoản `ACTIVE`. Danh tính `user_id` luôn được phân giải nội bộ qua token đã verify, tuyệt đối không nhận từ client.

### 5.1. Lưu sản phẩm yêu thích (Favorite)
- **Method**: `POST`
- **Path**: `/api/v1/favorites/{product_id}`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Semantics**:
  - Thêm sản phẩm vào danh sách yêu thích của người dùng hiện tại.
  - Cho phép người bán lưu sản phẩm của chính mình.
  - Thao tác có tính **nguyên tử và lũy đẳng (idempotent)**: Gọi nhiều lần với cùng một `product_id` vẫn trả về thành công, không tạo trùng bản ghi nhờ composite PK `(user_id, product_id)` và `INSERT ... ON CONFLICT DO NOTHING`.
  - Chỉ cho phép lưu sản phẩm khi `status = 'AVAILABLE'` và `is_deleted = False`.
- **Response**: `204 No Content`
- **Error Responses**:
  - `401 Unauthorized`: Token thiếu hoặc không hợp lệ.
  - `403 Forbidden`: Tài khoản `BANNED` hoặc `INACTIVE`.
  - `404 Not Found`: Sản phẩm không tồn tại, đã bị ẩn (`HIDDEN`), đã bán hết (`SOLD_OUT`), hoặc đã bị xóa mềm (`is_deleted = True`).
  - `422 Unprocessable Entity`: `product_id` không đúng định dạng integer.

---

### 5.2. Bỏ lưu sản phẩm yêu thích (Unfavorite)
- **Method**: `DELETE`
- **Path**: `/api/v1/favorites/{product_id}`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Semantics**:
  - Xóa sản phẩm khỏi danh sách yêu thích của người dùng hiện tại.
  - Thao tác có tính **lũy đẳng (idempotent)**: Xóa một sản phẩm chưa từng lưu hoặc đã bị xóa trước đó vẫn trả về `204 No Content`.
  - Vẫn cho phép bỏ lưu ngay cả khi sản phẩm sau đó đã chuyển sang `HIDDEN`, `SOLD_OUT`, hoặc bị xóa mềm nhằm dọn dẹp dữ liệu lưu cũ của người dùng.
- **Response**: `204 No Content`
- **Error Responses**:
  - `401 Unauthorized`: Token thiếu hoặc không hợp lệ.
  - `403 Forbidden`: Tài khoản `BANNED` hoặc `INACTIVE`.

---

### 5.3. Lấy danh sách ID sản phẩm đã lưu (Lightweight Set Lookup)
- **Method**: `GET`
- **Path**: `/api/v1/favorites/ids`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Semantics**:
  - Trả về mảng `product_ids` của tất cả sản phẩm đang khả dụng (`status = 'AVAILABLE'` và `is_deleted = False`) mà người dùng hiện tại đã lưu.
  - Endpoint siêu nhẹ phục vụ việc dựng `Set<number>` phía client để kiểm tra trạng thái tim của `ProductCard` với độ phức tạp $O(1)$, triệt tiêu hoàn toàn vấn đề N+1 API calls và không làm bẩn public `ProductSummaryResponse` DTO.
- **Response**: `200 OK`
```json
{
  "product_ids": [1, 5, 23]
}
```

---

### 5.4. Lấy danh sách sản phẩm yêu thích (Keyset Cursor Pagination)
- **Method**: `GET`
- **Path**: `/api/v1/favorites`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Query Parameters**:
  - `limit` (int, 1-50, default 20)
  - `cursor` (string Base64 opaque, optional) — Phân trang dựa trên `(favorites.created_at, favorites.product_id)` theo thứ tự vừa lưu gần nhất (`DESC`).
- **Visibility Policy**: Chỉ trả về các sản phẩm đang hiển thị bình thường (`status = 'AVAILABLE'` và `is_deleted = False`). Các sản phẩm `HIDDEN`, `SOLD_OUT`, hoặc `is_deleted = True` bị loại trừ khỏi response.
- **Response**: `200 OK`
```json
{
  "items": [
    {
      "product_id": 1,
      "title": "Giáo trình Giải tích 1 PTIT",
      "price": 45000,
      "listing_type": "FIXED_PRICE",
      "status": "AVAILABLE",
      "available_stock": 1,
      "thumbnail_url": "https://res.cloudinary.com/.../f_auto,q_auto,w_200/book.jpg",
      "category": {
        "category_id": 1,
        "name": "Giáo trình & Sách",
        "slug": "giao-trinh-sach"
      },
      "seller": {
        "user_id": 10,
        "full_name": "Nguyen Van A",
        "avatar_url": "https://res.cloudinary.com/.../avatar.jpg"
      },
      "created_at": "2026-08-26T10:00:00",
      "favorited_at": "2026-08-28T15:30:00"
    }
  ],
  "next_cursor": "MjAyNi0wOC0yOFQxNTozMDowMHwx",
  "has_more": false
}
```

---

## 6. ĐƠN HÀNG VÀ THANH TOÁN (ORDERS & PAYMENT — PHASE 4)

### 6.1. Đặt mua trực tiếp sản phẩm (Direct Buy)
- **Method**: `POST`
- **Path**: `/api/v1/orders`
- **Auth**: Bắt buộc (`ACTIVE` user, không được tự mua sản phẩm của chính mình)
- **Request Body**:
```json
{
  "product_id": 1,
  "quantity": 1,
  "payment_method": "CASH_ON_MEETUP",
  "fulfillment_method": "MEETUP",
  "meetup_place": "Cổng trường PTIT Hà Đông",
  "meetup_time": "17:00 ngày mai",
  "shipping_address": null,
  "contact_name": "Nguyen Van B",
  "contact_phone": "0987654321",
  "buyer_note": "Gặp ở gần canteen nhé"
}
```
- **Business Rules**:
  - `product.status` phải là `AVAILABLE`, `is_deleted = False`, `listing_type = 'FIXED_PRICE'`.
  - Khóa dòng sản phẩm bằng `SELECT ... FOR UPDATE`, kiểm tra `available_stock = stock - reserved_stock >= quantity`.
  - Tăng `reserved_stock += quantity`.
  - Đơn có `total_amount = 0` (miễn phí) được tự động đánh dấu `payment_status = 'PAID'` và gán `paid_confirmed_at`.
- **Response**: `201 Created` (`OrderDetailResponse`)

---

### 6.2. Lấy danh sách đơn mua của tôi (List Buying Orders)
- **Method**: `GET`
- **Path**: `/api/v1/orders/me/buying`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Query Parameters**:
  - `status` (OrderStatus enum, optional)
  - `limit` (int 1-50, default 20)
  - `cursor` (string Base64 opaque, optional) — Phân trang cursor theo `(created_at, order_id) DESC`
- **Response**: `200 OK` (`OrderCursorPage`)

---

### 6.3. Lấy danh sách đơn bán của tôi (List Selling Orders)
- **Method**: `GET`
- **Path**: `/api/v1/orders/me/selling`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Query Parameters**:
  - `status` (OrderStatus enum, optional)
  - `limit` (int 1-50, default 20)
  - `cursor` (string Base64 opaque, optional)
- **Response**: `200 OK` (`OrderCursorPage`)

---

### 6.4. Xem chi tiết đơn hàng (Get Order Detail)
- **Method**: `GET`
- **Path**: `/api/v1/orders/{order_id}`
- **Auth**: Bắt buộc (Chỉ Buyer, Seller của đơn hoặc ADMIN có quyền xem; người ngoài trả về `404 Not Found`)
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.5. Người bán xác nhận đơn hàng (Seller Confirm Order)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/confirm`
- **Auth**: Bắt buộc (Chỉ Seller của đơn)
- **Request Body**:
```json
{
  "payment_note": "MB Bank - STK: 0123456789 - NGUYEN VAN A - ND: ORD-2026-XXXX"
}
```
- **Business Rules**:
  - Đơn phải ở trạng thái `PENDING`.
  - Nếu `payment_method = 'BANK_TRANSFER'`, yêu cầu người bán phải đã thiết lập tài khoản nhận tiền trong Hồ sơ cá nhân để snapshot thông tin VietQR vào đơn hàng.
  - Chuyển `status -> 'CONFIRMED'`, gán `confirmed_at = now()`, hủy `auto_cancel_at = None`.
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.6. Người bán điều chỉnh điều khoản giao dịch (Update Order Transaction Terms)
- **Method**: `PATCH`
- **Path**: `/api/v1/orders/{order_id}/transaction-terms`
- **Auth**: Bắt buộc (Chỉ Seller của đơn sở hữu; người khác trả về `404 Not Found`)
- **Request Body**:
```json
{
  "fulfillment_method": "SHIPPING",
  "payment_method": "BANK_TRANSFER",
  "meetup_place": null,
  "meetup_time": null,
  "shipping_address": "KTX B2 Phòng 304 PTIT",
  "payment_note": "Chuyển tiền xong shop ship ngay trong ngày"
}
```
- **Business Rules**:
  - Đơn phải ở trạng thái `PENDING` hoặc `CONFIRMED` (từ chối `400` khi đơn đã vào `DELIVERING`, `COMPLETED`, `CANCELLED`).
  - Khóa dòng đơn hàng `SELECT ... FOR UPDATE` tránh tranh chấp đồng thời.
  - **Fulfillment**: Hỗ trợ chuyển đổi giữa `MEETUP` và `SHIPPING`. Khi chuyển sang `MEETUP`, yêu cầu có `meetup_place` và xóa sạch `shipping_address`. Khi chuyển sang `SHIPPING`, yêu cầu có `shipping_address` và xóa sạch `meetup_place`, `meetup_time`.
  - **Payment**:
    - Với đơn có phí: Cho phép chuyển đổi giữa `CASH_ON_MEETUP` và `BANK_TRANSFER` khi `payment_status = 'UNPAID'`.
    - Chặn đổi phương thức thanh toán (`400`) khi `payment_status` là `VERIFYING` hoặc `PAID`.
    - Chuyển từ `CASH` sang `BANK_TRANSFER`: Kiểm tra tài khoản nhận tiền của người bán, nếu đơn đã `CONFIRMED` thì snapshot thông tin ngân hàng ngay lập tức.
    - Chuyển từ `BANK_TRANSFER` sang `CASH`: Xóa sạch snapshot thông tin ngân hàng của đơn hàng.
    - Thay đổi chỉ hình thức giao nhận không làm thay đổi snapshot ngân hàng hiện có.
  - **Đơn miễn phí (`total_amount = 0`)**: Cho phép đổi hình thức giao nhận `MEETUP <-> SHIPPING`, không áp dụng phương thức thanh toán.
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.7. Người mua tải lên biên nhận thanh toán (Buyer Upload Receipt)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/receipt`
- **Auth**: Bắt buộc (Chỉ Buyer của đơn)
- **Content-Type**: `multipart/form-data`
- **Body Form Data**: `file` (Image JPEG/PNG/WEBP, max 5MB)
- **Business Rules**:
  - Đơn phải ở trạng thái `CONFIRMED` (từ chối `400` nếu còn `PENDING`).
  - `payment_method` phải là `BANK_TRANSFER`.
  - Tải ảnh lên Cloudinary scoped folder `student-marketplace/orders/order-{order_id}/payment-receipt`.
  - Cập nhật `payment_receipt_url`, `receipt_uploaded_at = now()`, chuyển `payment_status -> 'VERIFYING'`.
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.8. Người bán xác nhận đã nhận tiền (Seller Confirm Payment)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/confirm-payment`
- **Auth**: Bắt buộc (Chỉ Seller của đơn)
- **Business Rules**:
  - Đơn phải ở trạng thái `CONFIRMED` (hoặc `DELIVERING` đối với `SHIPPING + CASH_ON_MEETUP`) và `payment_status != 'PAID'`.
  - Với `BANK_TRANSFER`: yêu cầu `payment_status = 'VERIFYING'` và `payment_receipt_url IS NOT NULL`.
  - Với `CASH_ON_MEETUP`: yêu cầu `payment_status = 'UNPAID'`.
  - Cập nhật `payment_status -> 'PAID'`, gán `paid_confirmed_at = now()`.
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.9. Người bán bắt đầu giao hàng (Mark Delivering)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/deliver`
- **Auth**: Bắt buộc (Chỉ Seller của đơn)
- **Business Rules**:
  - Chỉ áp dụng cho đơn `fulfillment_method = 'SHIPPING'` (từ chối `400` nếu là `MEETUP`).
  - Yêu cầu `status = 'CONFIRMED'`.
  - Nếu `payment_method = 'BANK_TRANSFER'`, yêu cầu bắt buộc `payment_status = 'PAID'` trước khi giao.
  - Nếu `payment_method = 'CASH_ON_MEETUP'`, cho phép chuyển sang `DELIVERING` khi `payment_status = 'UNPAID'`.
  - Chuyển `status -> 'DELIVERING'`.
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.9. Hoàn tất đơn hàng (Complete Order)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/complete`
- **Auth**: Bắt buộc (Buyer hoặc Seller của đơn)
- **Business Rules**:
  - Yêu cầu `payment_status = 'PAID'`.
  - Đơn `MEETUP`: yêu cầu `status = 'CONFIRMED'`.
  - Đơn `SHIPPING`: yêu cầu `status = 'DELIVERING'`.
  - Khóa dòng sản phẩm `FOR UPDATE`, trừ thực tế tồn kho `stock -= quantity`, `reserved_stock -= quantity`.
  - Nếu `stock == 0`: chuyển sản phẩm sang `status = 'SOLD_OUT'` và tự động xóa sạch các bản ghi yêu thích liên quan (`DELETE FROM favorites WHERE product_id = :product_id`).
  - Chuyển đơn sang `status = 'COMPLETED'`, gán `completed_at = now()`.
- **Response**: `200 OK` (`OrderDetailResponse`)

---

### 6.10. Hủy đơn hàng (Cancel Order)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/cancel`
- **Auth**: Bắt buộc (Buyer hoặc Seller của đơn, hoặc Worker hệ thống)
- **Request Body**:
```json
{
  "cancel_reason": "Người mua đổi ý không muốn mua nữa"
}
```
- **Business Rules**:
  - Cho phép hủy khi `status = 'PENDING'`.
  - Cho phép hủy khi `status = 'CONFIRMED'` nếu `payment_status = 'UNPAID'` hoặc nếu là đơn miễn phí `total_amount = 0`.
  - Chặn hủy khi đơn đã vào `DELIVERING` hoặc `COMPLETED`.
  - Chặn hủy khi đơn có phí đã ở trạng thái `PAID` (cần qua quy trình hoàn tiền riêng).
  - Khóa dòng sản phẩm `FOR UPDATE`, giải phóng tồn kho giữ `reserved_stock -= quantity`.
  - Chuyển đơn sang `status = 'CANCELLED'`, ghi nhận `cancelled_by`, `cancel_reason`, `cancelled_at = now()`.
- **Response**: `200 OK` (`OrderDetailResponse`)


