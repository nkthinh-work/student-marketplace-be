# API CONTRACT — Marketplace C2C Sinh viên

Tài liệu này định nghĩa hợp đồng API chính thức (REST Endpoints, Request/Response DTOs, Authentication, Error Semantics) cho backend `student-marketplace-be` của nền tảng Chợ PTITers.

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

## 2. Authentication & User Management Endpoints

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
  "delivery_area": "Hà Đông, Thanh Xuân, Cầu Giấy",
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
  "delivery_area": "Hà Đông, Thanh Xuân, Cầu Giấy"
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
  "delivery_area": "Hà Đông, Thanh Xuân, Cầu Giấy",
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

### 2.7. `GET /api/v1/users/{user_id}` — Hồ sơ công khai của người dùng

- **Method**: `GET`
- **Path**: `/api/v1/users/{user_id}`
- **Authentication**: Không bắt buộc / Public
- **Business Rule**: Trả về thông tin công khai (tên, avatar, bio, phạm vi giao / nhận hàng, ngày tham gia). Tuyệt đối không để lộ thông tin riêng tư (email, số điện thoại, tài khoản ngân hàng).
- **Response: `200 OK`**:
```json
{
  "user_id": 1,
  "full_name": "Nguyen Van A",
  "avatar_url": "https://lh3.googleusercontent.com/a/.../photo.jpg",
  "bio": "Sinh viên năm 3 CNTT",
  "delivery_area": "Hà Đông, Thanh Xuân, Cầu Giấy",
  "role": "STUDENT",
  "created_at": "2026-08-25T09:40:00"
}
```
- **Error Responses**:
  - `404 Not Found`: Người dùng không tồn tại hoặc tài khoản đã bị khóa/ngừng hoạt động.

---

## 3. Foundation Authorization Roles & Helpers

Backend cung cấp các dependency authorization nền tảng dùng cho các module/phase tiếp theo:
- `get_current_user`: Trích xuất payload từ token và load `User`.
- `get_current_active_user`: Enforce `status == ACTIVE`.
- `require_role(*roles)`: Enforce user có role trong danh sách được cấp phép (ví dụ: `ADMIN`, `STUDENT`).
- `require_admin`: Enforce `role == 'ADMIN'`. Trả về `403 Forbidden` nếu không phải admin.

---

## 4. Categories, Products & Product Images

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
  - `q` (string, optional) — PostgreSQL Full-Text Search (GIN) trên `title` và `description` với cơ chế tiền tố (**prefix matching**) trên token cuối cùng:
    - Chuỗi đầu vào được chuẩn hoá Unicode NFC (`unicodedata.normalize("NFC", ...)`) tại backend.
    - Phân tích cú pháp an toàn qua `plainto_tsquery('simple', :q)` trước khi chuyển token cuối thành tiền tố `:*`, triệt tiêu hoàn toàn nguy cơ lỗi cú pháp khi người dùng nhập ký tự đặc biệt (`:`, `&`, `|`, `!`, `(`, `)`, `"`, `'`, `\`, `+`, `-`, `c++`).
    - Hỗ trợ tìm kiếm thời gian thực khi đang gõ (search-as-you-type): `q=gi` đối sánh các từ bắt đầu bằng `gi` như `giáo`, `giải`; `q="giáo tr"` đối sánh `giáo` AND `tr:*` (như `giáo trình`).
    - Phân biệt rõ: Tìm kiếm tiền tố KHÔNG bao gồm tính năng bỏ dấu (`unaccent`). Ví dụ: `gi` hoặc `giá` tìm thấy `giáo`, nhưng `giao` (không dấu) không tự động tìm thấy `giáo` (thuộc Level-2 unaccent riêng biệt).
    - Chuỗi rỗng hoặc chỉ chứa khoảng trắng giữ nguyên hành vi hiển thị danh sách thông thường không lọc. Chuỗi không chứa lexeme hợp lệ (ví dụ: `: & | !`) trả về danh sách rỗng an toàn (0 bản ghi, HTTP 200).
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
      "view_count": 12,
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
- **Response**: `200 OK`
```json
{
  "items": [
    {
      "product_id": 1,
      "title": "Giáo trình Giải tích 1 PTIT",
      "description": "Sách còn mới 95%",
      "listing_type": "FIXED_PRICE",
      "price": 45000,
      "stock": 1,
      "reserved_stock": 0,
      "available_stock": 1,
      "status": "AVAILABLE",
      "moderation_status": "CLEAR",
      "view_count": 12,
      "thumbnail_url": "https://res.cloudinary.com/.../f_auto,q_auto,w_200/book.jpg",
      "category": {
        "category_id": 1,
        "name": "Giáo trình & Sách",
        "slug": "giao-trinh-sach"
      },
      "auction": null,
      "created_at": "2026-08-26T10:00:00",
      "updated_at": "2026-08-26T10:00:00"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

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

## 5. Favorites (Tin yêu thích)

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
      "view_count": 12,
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

## 6. Đơn hàng và Thanh toán (Orders & Payments)

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

---

## 7. Đấu giá (Auctions)

### 7.1. Bật đấu giá sản phẩm (Enable Auction / New Round)
- **Method**: `POST`
- **Path**: `/api/v1/auctions`
- **Auth**: Bắt buộc (Chỉ Seller sở hữu sản phẩm)
- **Request Body (Immediate Start - MVP Preferred)**:
```json
{
  "product_id": 10,
  "bid_step": 20000,
  "duration_minutes": 180
}
```
*(Hoặc legacy format với `ends_at`)*:
```json
{
  "product_id": 10,
  "bid_step": 20000,
  "starts_at": "2026-08-30T12:00:00Z",
  "ends_at": "2026-08-30T15:00:00Z"
}
```
- **Business Rules**:
  - `product.stock == 1`, `product.reserved_stock == 0`, `product.status == 'AVAILABLE'`.
  - Snapshot cố định `starting_price = product.price` (hỗ trợ `starting_price >= 0`).
  - Chuyển `product.listing_type = 'AUCTION'`.
  - `bid_step > 0`, `duration_minutes > 0`.
  - Tự động bắt đầu ngay: `starts_at = now_utc()`, `ends_at = now_utc() + duration_minutes`, `status = ACTIVE`.
- **Response**: `201 Created` (`AuctionDetailResponse`)

---

### 7.2. Lấy chi tiết phiên đấu giá (Auction Detail)
- **Method**: `GET`
- **Path**: `/api/v1/auctions/{auction_id}`
- **Auth**: Public / Optional Auth
- **Privacy-safe Rules**:
  - Tuyệt đối không để lộ `winner_id` ra client công khai.
  - Sử dụng các cờ ngữ cảnh: `has_winner`, `is_current_user_winner`, `is_current_user_highest_bidder`, `winner_checkout_state` (`NOT_APPLICABLE`, `WAITING`, `ORDER_CREATED`, `EXPIRED`, `NO_BIDS`), `winner_order_id`.
- **Response**: `200 OK`
```json
{
  "auction_id": 1,
  "product_id": 10,
  "status": "ACTIVE",
  "starting_price": 50000,
  "bid_step": 20000,
  "current_price": 70000,
  "highest_bid": 70000,
  "bid_count": 1,
  "minimum_next_bid": 90000,
  "starts_at": "2026-08-30T10:00:00Z",
  "ends_at": "2026-08-30T13:00:00Z",
  "has_winner": false,
  "final_price": null,
  "winner_checkout_deadline": null,
  "is_current_user_winner": false,
  "is_current_user_highest_bidder": true,
  "server_time": "2026-08-30T10:05:00Z",
  "winner_checkout_state": "NOT_APPLICABLE",
  "winner_order_id": null
}
```

---

### 7.3. Lấy phiên đấu giá theo sản phẩm (Get Auction By Product)
- **Method**: `GET`
- **Path**: `/api/v1/auctions/by-product/{product_id}`
- **Auth**: Public / Optional Auth
- **Quy tắc giải quyết vòng đấu giá**:
  - Trả về vòng `SCHEDULED` hoặc `ACTIVE` hiện tại nếu có.
  - Nếu không còn vòng active, trả về vòng mới nhất theo `created_at DESC`.
- **Response**: `200 OK` (`AuctionDetailResponse`)

---

### 7.4. Đặt giá đấu (Place Bid)
- **Method**: `POST`
- **Path**: `/api/v1/auctions/{auction_id}/bids`
- **Auth**: Bắt buộc (User `ACTIVE`)
- **Request Body**:
```json
{
  "amount": 90000
}
```
- **Business Rules**:
  - Khóa row auction `FOR UPDATE`.
  - Yêu cầu `status = 'ACTIVE'`, `now() < ends_at`.
  - Seller không được bid sản phẩm của chính mình.
  - `amount > 0` (tuyệt đối không cho phép 0 VND).
  - Bid đầu tiên: `amount >= auction.starting_price` (khi `starting_price = 0`, `minimum_next_bid = 1`).
  - Các bid tiếp theo: `amount >= highest_bid + bid_step`.
  - Phát sự kiện realtime qua WebSocket `BID_PLACED`.
- **Response**: `201 Created` (`AuctionBidResponse`)
```json
{
  "bid_id": 15,
  "auction_id": 1,
  "bidder_display": "N*** A",
  "amount": 90000,
  "created_at": "2026-08-30T10:06:00Z",
  "is_current_user": true
}
```

---

### 7.5. Lịch sử đặt giá bảo mật danh tính (List Auction Bids)
- **Method**: `GET`
- **Path**: `/api/v1/auctions/{auction_id}/bids`
- **Auth**: Public / Optional Auth
- **Query Params**: `cursor` (string), `limit` (int, 1..50)
- **Keyset Pagination**: `(amount DESC, created_at ASC, bid_id ASC)`
- **Response**: `200 OK` (`AuctionBidCursorPage`)
```json
{
  "items": [
    {
      "bid_id": 15,
      "auction_id": 1,
      "bidder_display": "N*** A",
      "amount": 90000,
      "created_at": "2026-08-30T10:06:00Z",
      "is_current_user": true
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

---

### 7.6. Người bán hủy phiên đấu giá (Cancel Auction)
- **Method**: `POST`
- **Path**: `/api/v1/auctions/{auction_id}/cancel`
- **Auth**: Bắt buộc (Chỉ Seller sở hữu)
- **Business Rules**:
  - Yêu cầu `status IN ('SCHEDULED', 'ACTIVE')`.
  - Yêu cầu `bid_count == 0` (nếu đã có bid, chặn hủy với `400`).
  - Giải phóng listing nếu cần.
- **Response**: `200 OK` (`AuctionDetailResponse`)

---

### 7.7. Người thắng hoàn tất đặt mua (Winner Checkout)
- **Method**: `POST`
- **Path**: `/api/v1/auctions/{auction_id}/checkout`
- **Auth**: Bắt buộc (Chỉ Winner của phiên)
- **Request Body**:
```json
{
  "payment_method": "BANK_TRANSFER",
  "fulfillment_method": "MEETUP",
  "meetup_place": "Cổng trường Học viện",
  "meetup_time": "2026-08-31T15:00:00Z",
  "shipping_address": null,
  "contact_name": "Nguyen Van B",
  "contact_phone": "0987654321",
  "buyer_note": "Giao giờ hành chính"
}
```
- **Business Rules**:
  - Yêu cầu `status = 'ENDED'`, `has_winner = true`, `current_user == winner_id`.
  - Yêu cầu `now() <= winner_checkout_deadline`.
  - Tái sử dụng reservation hiện có (`reserved_stock` giữ nguyên `1`, không tăng lần 2).
  - Tạo Order với `orders.auction_id = auction_id`, `price_at_purchase = final_price`, `quantity = 1`.
  - Thực thi toàn vẹn qua partial unique index `ux_orders_auction_id` (mỗi vòng đấu giá chỉ được tạo tối đa 1 Order duy nhất).
- **Response**: `201 Created` (`OrderDetailResponse`)

---

### 7.8. Chuyển sản phẩm sang bán giá cố định (Convert To Fixed Price)
- **Method**: `POST`
- **Path**: `/api/v1/auctions/products/{product_id}/convert-fixed-price`
- **Auth**: Bắt buộc (Chỉ Seller sở hữu)
- **Business Rules**:
  - Không có phiên đấu giá `SCHEDULED` hoặc `ACTIVE`.
  - `product.reserved_stock == 0` (không có đơn giữ hàng).
  - Chuyển `product.listing_type = 'FIXED_PRICE'`.
- **Response**: `200 OK`
```json
{
  "message": "Product converted to fixed price successfully."
}
```

---

### 7.9. Realtime WebSocket Channel
- **Path**: `/ws/auctions/{auction_id}`
- **Protocol**: WebSocket
- **Heartbeat**: Client gửi chuỗi `"ping"`, server phản hồi `"pong"`.
- **Broadcast Events**:
  - `BID_PLACED`: Kèm `current_price`, `highest_bid`, `bid_count`, `minimum_next_bid`, `server_time`.
  - `AUCTION_STARTED`: Kèm `current_price`, `bid_count`, `server_time`.
  - `AUCTION_ENDED`: Kèm `final_price`, `has_winner`, `server_time`.
  - `AUCTION_CANCELLED`: Kèm `server_time`.

---

## 8. Đánh giá & Uy tín (Reviews & Reputation)

### 8.1. Đánh giá người bán sau khi hoàn tất đơn hàng (Create Order Review)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/review`
- **Auth**: Bắt buộc (Chỉ Buyer của đơn hàng)
- **Request Body**:
```json
{
  "rating": 5,
  "comment": "Người bán thân thiện, nhiệt tình và đúng giờ."
}
```
- **Business Rules**:
  - `order.status` phải là `COMPLETED` (nếu không trả `400 Bad Request`).
  - Chỉ người mua `order.buyer_id == current_user.user_id` mới được quyền đánh giá (Seller gọi trả `403 Forbidden`).
  - Người dùng không liên quan trả `404 Not Found`.
  - Đã có đánh giá trước đó trả `409 Conflict` (bảo vệ kép qua `ux_reviews_order_reviewer`).
  - `rating` bắt buộc từ 1 đến 5 sao. `comment` tối đa 1000 ký tự (chuỗi khoảng trắng tự động chuẩn hóa về `null`).
- **Response**: `201 Created`
```json
{
  "review_id": 1,
  "order_id": 100,
  "reviewer_id": 12,
  "reviewee_id": 45,
  "rating": 5,
  "comment": "Người bán thân thiện, nhiệt tình và đúng giờ.",
  "reviewer_name": "Trần Minh Anh",
  "created_at": "2026-09-01T10:00:00Z",
  "updated_at": "2026-09-01T10:00:00Z"
}
```

---

### 8.2. Lấy thông tin đánh giá của đơn hàng (Get Order Review)
- **Method**: `GET`
- **Path**: `/api/v1/orders/{order_id}/review`
- **Auth**: Bắt buộc (Buyer hoặc Seller của đơn hàng)
- **Business Rules**:
  - Người dùng không liên quan trả `404 Not Found`.
  - Nếu đơn hàng tồn tại và user là người tham gia nhưng người mua chưa đánh giá: trả về `200 OK` với body là `null` (không trả 404).
- **Response**: `200 OK` (hoặc `null`)

---

### 8.3. Chỉnh sửa đánh giá của người mua (Partial Update Order Review)
- **Method**: `PATCH`
- **Path**: `/api/v1/orders/{order_id}/review`
- **Auth**: Bắt buộc (Chỉ Buyer đã tạo đánh giá)
- **Request Body (Partial)**:
```json
{
  "rating": 4,
  "comment": "Cập nhật lại: máy dùng ổn nhưng pin hao nhẹ."
}
```
- **Business Rules**:
  - Chặn body rỗng `{}` trả `422 Unprocessable Entity`.
  - Chặn `{"rating": null}` trả `422 Unprocessable Entity`.
  - `{"comment": null}` xóa nhận xét về `null`.
  - Truyền `rating` giữ nguyên `comment`, truyền `comment` giữ nguyên `rating`.
  - Tự động cập nhật `updated_at` thông qua trigger database `trg_reviews_updated_at`.
- **Response**: `200 OK` (`OrderReviewResponse`)

---

### 8.4. Lấy danh sách đánh giá công khai của người bán (Get Public Seller Reviews)
- **Method**: `GET`
- **Path**: `/api/v1/users/{user_id}/reviews?limit=10&cursor=...`
- **Auth**: Công khai (Public)
- **Query Params**:
  - `limit`: Số lượng mỗi trang (1..50, mặc định 10).
  - `cursor`: Chuỗi Base64 con trỏ keyset pagination (`created_at DESC, review_id DESC`).
- **Privacy Assurance (Zero Leaks)**:
  - Ẩn danh tuyệt đối: Không trả về tên người mua, không trả về `reviewer_display`, không avatar.
  - Không bao giờ trả về `order_id`, `order_code`, `reviewer_id`, `buyer_id`, `product_id`, `email`, `phone`, `address`.
- **Response**: `200 OK`
```json
{
  "items": [
    {
      "rating": 5,
      "comment": "Giao dịch nhanh chóng tại Ký túc xá.",
      "verified_transaction": true,
      "created_at": "2026-09-01T10:00:00Z",
      "updated_at": "2026-09-01T10:00:00Z"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0IjogIi4uLiIsICJyZXZpZXdfaWQiOiAxfQ==",
  "has_more": false
}
```

---

### 8.5. Lịch sử sản phẩm đã bán kèm đánh giá giao dịch ngữ cảnh (Get Sold Products with Contextual Reviews)
- **Method**: `GET`
- **Path**: `/api/v1/users/{user_id}/sold-products`
- **Auth**: Công khai (Public)
- **Response**: `200 OK` (`SoldProductsListResponse`)
```json
{
  "items": [
    {
      "product_id": 101,
      "product_title": "Giáo trình Cấu trúc dữ liệu & Giải thuật",
      "product_image_url": "https://res.cloudinary.com/.../book.jpg",
      "total_sold_quantity": 1,
      "last_sold_at": "2026-09-01T09:30:00Z",
      "rating_average": 5.0,
      "review_count": 1,
      "recent_reviews": [
        {
          "rating": 5,
          "comment": "Sách còn mới, người bán giao đúng hẹn.",
          "created_at": "2026-09-01T10:00:00Z",
          "verified_transaction": true
        }
      ]
    }
  ]
}
```

---

## 9. Tin nhắn & Trò chuyện (Chat & Conversations)

### 9.1. Mở hoặc khởi tạo cuộc trò chuyện (Open / Create Conversation)
- **Method**: `POST`
- **Path**: `/api/v1/conversations`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Request Body**:
  ```json
  {
    "product_id": 101
  }
  ```
- **Business Invariants**:
  - Không cho phép tự chat với sản phẩm của chính mình (`400 Bad Request`).
  - Sản phẩm phải tồn tại và không bị xóa (`404 Not Found`).
  - Canonical 1-to-1 thread giữa 2 user: Gọi nhiều lần với cùng sản phẩm hoặc sản phẩm khác của cùng người bán đều trả về cùng một `conversation_id`.
  - Race-safe (`INSERT ... ON CONFLICT DO NOTHING`).
- **Response**: `200 OK` (`ConversationDetailResponse`)
  ```json
  {
    "conversation_id": 1,
    "other_participant": {
      "user_id": 2,
      "full_name": "Nguyễn Văn Bán",
      "avatar_url": "https://lh3.googleusercontent.com/..."
    },
    "product_context": {
      "product_id": 101,
      "title": "Giáo trình Cấu trúc dữ liệu",
      "price": 45000,
      "status": "AVAILABLE",
      "thumbnail_url": "https://res.cloudinary.com/...",
      "listing_type": "FIXED_PRICE"
    },
    "created_at": "2026-09-02T10:00:00Z"
  }
  ```

---

### 9.2. Lấy danh sách cuộc trò chuyện của tôi (List User Conversations)
- **Method**: `GET`
- **Path**: `/api/v1/conversations?limit=20&cursor=...`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Query Params**:
  - `limit`: 1..50 (mặc định 20)
  - `cursor`: Chuỗi Base64 keyset pagination `(last_message_at DESC, conversation_id DESC)`.
- **Inbox Invariant**: Chỉ trả về các cuộc trò chuyện đã có ít nhất 1 tin nhắn (`last_message_at IS NOT NULL`).
- **Zero N+1 Query Guarantee**: Batch loading người tham gia, tin nhắn mới nhất, unread counts, và contextual products trong đúng 4 câu truy vấn cố định.
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "conversation_id": 1,
        "other_participant": {
          "user_id": 2,
          "full_name": "Nguyễn Văn Bán",
          "avatar_url": "https://lh3.googleusercontent.com/..."
        },
        "product_context": {
          "product_id": 101,
          "title": "Giáo trình Cấu trúc dữ liệu",
          "price": 45000,
          "status": "AVAILABLE",
          "thumbnail_url": "https://res.cloudinary.com/...",
          "listing_type": "FIXED_PRICE"
        },
        "last_message_preview": "Chào bạn, sách còn không ạ?",
        "last_message_at": "2026-09-02T10:05:00Z",
        "unread_count": 0,
        "created_at": "2026-09-02T10:00:00Z"
      }
    ],
    "next_cursor": "eyJsYXN0X21lc3NhZ2VfYXQiOiAiLi4uIiwgImNvbnZlcnNhdGlvbl9pZCI6IDF9",
    "has_more": false
  }
  ```

---

### 9.3. Lấy thông tin chi tiết cuộc trò chuyện (Get Conversation Detail)
- **Method**: `GET`
- **Path**: `/api/v1/conversations/{conversation_id}`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Authorization**: Chỉ người tham gia mới được truy cập; người ngoài nhận `404 Not Found` (không lộ sự tồn tại).
- **Response**: `200 OK` (`ConversationDetailResponse`)

---

### 9.4. Lấy lịch sử tin nhắn trong cuộc trò chuyện (Get Messages)
- **Method**: `GET`
- **Path**: `/api/v1/conversations/{conversation_id}/messages?limit=30&cursor=...`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Query Params**:
  - `limit`: 1..100 (mặc định 30)
  - `cursor`: Chuỗi Base64 keyset pagination `(sent_at DESC, message_id DESC)`.
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "message_id": 12,
        "conversation_id": 1,
        "sender_id": 3,
        "content": "Chào bạn, sách còn không ạ?",
        "product_id": 101,
        "sent_at": "2026-09-02T10:05:00Z",
        "is_mine": true,
        "attachments": [
          {
            "attachment_id": 5,
            "kind": "IMAGE",
            "url": "https://res.cloudinary.com/.../image.jpg",
            "mime_type": "image/jpeg",
            "original_name": "anh_sach.jpg",
            "size_bytes": 124500,
            "duration_ms": null
          }
        ],
        "mentions": [
          {
            "user_id": 2,
            "display_name": "Trần Thị B",
            "display_text": "@Trần Thị B",
            "start_offset": 0,
            "end_offset": 11
          }
        ]
      }
    ],
    "next_cursor": "eyJzZW50X2F0IjogIi4uLiIsICJtZXNzYWdlX2lkIjogMTJ9",
    "has_more": false
  }
  ```

---

### 9.5. Gửi tin nhắn (Send Message)
- **Method**: `POST`
- **Path**: `/api/v1/conversations/{conversation_id}/messages`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Content-Type**: `multipart/form-data`
- **Form Data**:
  - `content`: Tùy chọn, tối đa 2000 ký tự.
  - `product_id`: Tùy chọn, ID sản phẩm ngữ cảnh (chỉ dùng cho `DIRECT`).
  - `voice_duration_ms`: Tùy chọn, thời lượng voice note (ms) khi gửi audio.
  - `mentions`: Tùy chọn, chuỗi JSON serialize của mảng `MessageMentionCreate` (ví dụ: `[{"mentioned_user_id": 2, "display_text": "@Trần Thị B", "start_offset": 0, "end_offset": 11}]`).
    - Hỗ trợ trong các hội thoại `GROUP` và `COMMUNITY`. Bị từ chối với `400 Bad Request` nếu gửi trong `DIRECT`.
    - Tất cả `mentioned_user_id` bắt buộc phải là thành viên đang hoạt động trong nhóm (`left_at IS NULL`). Nếu chứa người dùng không phải thành viên hoạt động -> từ chối với `422 Unprocessable Entity`.
    - Tọa độ `start_offset` và `end_offset` bắt buộc phải thỏa mãn: `0 <= start < end <= len(content)` và `content[start:end] == display_text`. Nếu không khớp -> từ chối với `422 Unprocessable Entity`.
  - `files`: Tùy chọn, từ 0 đến 4 files (hỗ trợ `IMAGE`, `VIDEO`, `PDF`, `AUDIO`, `DOCUMENT`).
- **Validation**:
  - Tin nhắn hợp lệ khi có `content` (không rỗng) HOẶC có ít nhất 1 tệp đính kèm hợp lệ.
  - Giới hạn kích thước và định dạng:
    - Ảnh (`IMAGE`): <= 10MB (`image/jpeg`, `image/png`, `image/webp`).
    - Video (`VIDEO`): <= 50MB (`video/mp4`, `video/webm`).
    - Âm thanh (`AUDIO`): <= 15MB (`audio/webm`, `audio/mpeg`, `audio/wav`, `audio/ogg`, `audio/mp4`, voice note <= 5 phút).
    - Tài liệu (`DOCUMENT` / `PDF`): <= 20MB (`application/pdf`, `.docx`, `.xlsx`, `.pptx`, `.txt`).
  - Kiểm tra Magic Bytes chống file giả mạo (.exe đổi đuôi).
- **Realtime**:
  - Tự động phát sự kiện `MESSAGE_CREATED` qua kênh WebSocket `/ws/me` tới các thành viên đang hoạt động (`left_at IS NULL`) sau khi giao dịch commit thành công.
  - Trong `GROUP`, phát sinh thêm sự kiện realtime độc lập `NOTIFICATION_CREATED` tới từng người dùng được nhắc đến (xem mục 12.7).
- **Response**: `201 Created` (`MessageResponse`)

---

### 9.6. Đánh dấu đã đọc (Mark Conversation Read)
- **Method**: `POST`
- **Path**: `/api/v1/conversations/{conversation_id}/read`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Invariant**: Chỉ cập nhật các tin nhắn được gửi bởi người kia (`sender_id != current_user_id AND read_at IS NULL`).
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "read_count": 2
  }
  ```

---

### 9.7. Danh sách tệp đính kèm đã chia sẻ (Shared Attachments List)
- **Method**: `GET`
- **Path**: `/api/v1/conversations/{conversation_id}/attachments`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Query Params**:
  - `category` (hoặc alias `kind`): `media` (ảnh, video), `audio` (âm thanh, ghi âm), hoặc `file` (tài liệu, PDF). Mặc định `media`.
  - `limit`: 1..100 (mặc định 30).
  - `cursor`: Keyset pagination cursor `(created_at DESC, attachment_id DESC)`.
- **Response**: `200 OK` (`SharedAttachmentListResponse`)
  ```json
  {
    "items": [
      {
        "attachment_id": 15,
        "message_id": 42,
        "sender_id": 3,
        "kind": "DOCUMENT",
        "url": "https://res.cloudinary.com/...",
        "mime_type": "application/pdf",
        "original_name": "De_cuong_mon_hoc.pdf",
        "size_bytes": 1048576,
        "duration_ms": null,
        "created_at": "2026-09-10T08:30:00Z"
      }
    ],
    "next_cursor": "ey...",
    "has_more": false
  }
  ```

---

### 9.8. Thống kê tệp đính kèm chia sẻ (Shared Attachments Summary)
- **Method**: `GET`
- **Path**: `/api/v1/conversations/{conversation_id}/attachments/summary`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Response**: `200 OK` (`SharedAttachmentSummaryResponse`)
  ```json
  {
    "media_count": 12,
    "audio_count": 3,
    "file_count": 5,
    "total_count": 20
  }
  ```

---

### 9.9. Tạo mã tải xuống an toàn 1 lần (Create Attachment Download Ticket)
- **Method**: `POST`
- **Path**: `/api/v1/conversations/{conversation_id}/attachments/{attachment_id}/download-ticket`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Mô tả**: Cấp capability token dùng 1 lần (TTL 60 giây) lưu trữ trên Redis, cho phép trình duyệt kích hoạt luồng tải tệp mà không để lộ Firebase ID Token vào URL query string.
- **Response**: `200 OK` (`AttachmentDownloadTicketResponse`)
  ```json
  {
    "ticket": "a1b2c3d4e5f6...",
    "expires_in": 60,
    "download_url": "/api/v1/conversations/1/attachments/15/download?ticket=a1b2c3d4e5f6..."
  }
  ```

---

### 9.10. Tải tệp đính kèm trực tiếp (Download Attachment Stream)
- **Method**: `GET`
- **Path**: `/api/v1/conversations/{conversation_id}/attachments/{attachment_id}/download`
- **Auth**: Qua query param `?ticket=<ticket>` HOẶC header `Authorization: Bearer <Firebase ID Token>`.
- **Header phản hồi**:
  - `Content-Disposition: attachment; filename="fallback.ext"; filename*=UTF-8''...` (Mã hóa RFC 5987 / RFC 6266 bảo toàn tên file tiếng Việt có dấu).
  - `Cache-Control: private, no-store`.
  - `Content-Type`: MIME type gốc của tệp.
- **Invariants**:
  - Tiêu thụ ticket nguyên tử (atomic GETDEL). Ticket chỉ dùng đúng 1 lần.
  - Tái thẩm định tư cách thành viên active của cuộc trò chuyện (`left_at IS NULL`) lúc tải tệp. Thành viên đã bị xóa khỏi nhóm không thể tải tệp kể cả khi đã lấy ticket trước đó.
  - Chống SSRF: Upstream URL bắt buộc thuộc domain Cloudinary tin cậy (`res.cloudinary.com`).
  - Streaming phân đoạn (chunked 64KB) giới hạn bộ nhớ RAM server.

---

## 10. Nhật ký hôm nay & Chuỗi ngày (Daily Journal & Streak)

Tính năng chia sẻ trạng thái ngắn/nhật ký công khai hàng ngày của sinh viên: mỗi người dùng đăng tối đa 1 dòng trạng thái/ngày dương lịch (múi giờ `Asia/Ho_Chi_Minh`, tối đa 120 ký tự).
Tích hợp:
- Chuỗi ngày đăng liên tiếp (**Streak**) hiển thị trạng thái ngọn lửa trên thẻ Welcome trang chủ.
- Hiển thị tối đa 10 nhật ký mới nhất trên Marquee trang chủ.
- Hiển thị dòng trạng thái nhật ký hôm nay dưới tên người đối thoại trong Header cuộc trò chuyện 1-1 (Direct Chat).

### 10.1. Danh sách nhật ký hôm nay (Home Public Marquee)
- **Method**: `GET`
- **Path**: `/api/v1/daily-needs/today`
- **Auth**: Public (không bắt buộc)
- **Quy tắc**:
  - Trả về tối đa 10 nhật ký mới nhất của ngày hiện tại (múi giờ `Asia/Ho_Chi_Minh`).
  - Sắp xếp: `updated_at DESC, daily_need_id DESC`.
  - Không lộ email, phone, số tài khoản ngân hàng của tác giả (chỉ lộ `user_id`, `full_name`, `avatar_url`).
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "daily_need_id": 1,
        "content": "Cần tìm giáo trình Giải tích 1",
        "note_date": "2026-09-03",
        "created_at": "2026-09-03T08:00:00+07:00",
        "updated_at": "2026-09-03T08:00:00+07:00",
        "author": {
          "user_id": 123,
          "full_name": "Nguyễn Khắc Thịnh",
          "avatar_url": "https://..."
        }
      }
    ]
  }
  ```

---

### 10.2. Nhật ký hôm nay của tôi
- **Method**: `GET`
- **Path**: `/api/v1/daily-needs/me/today`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Response**: `200 OK`
  - Nếu đã có nhật ký hôm nay: trả về object `DailyNeedResponse`.
  - Nếu chưa có: trả về `null`.

---

### 10.3. Tóm tắt nhật ký và chuỗi ngày của tôi (Streak Summary)
- **Method**: `GET`
- **Path**: `/api/v1/daily-needs/me/summary`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Quy tắc tính toán**:
  - Tính toán động có tính xác định hoàn toàn từ server bằng SQL Recursive CTE dựa trên bảng `daily_journal_checkins` (múi giờ `Asia/Ho_Chi_Minh`).
  - Không có giới hạn trần giả định (hỗ trợ chuỗi > 365 ngày).
  - Phân biệt tường minh hai trạng thái:
    - `has_journal_today`: nội dung nhật ký hiện tại trong ngày có tồn tại hay không (quản lý hiển thị modal/CTA và nội dung công khai).
    - `has_checked_in_today`: người dùng đã tham gia giữ chuỗi hôm nay hay chưa (quản lý màu sắc ngọn lửa trang chủ).
    - `has_posted_today`: [DEPRECATED] bằng với `has_checked_in_today` nhằm tương thích ngược với client cũ.
- **Response**: `200 OK`
  ```json
  {
    "today_journal": {
      "daily_need_id": 1,
      "content": "Hôm nay cần tìm giáo trình Giải tích",
      "note_date": "2026-09-03",
      "created_at": "2026-09-03T08:00:00+07:00",
      "updated_at": "2026-09-03T08:00:00+07:00",
      "author": {
        "user_id": 123,
        "full_name": "Nguyễn Khắc Thịnh",
        "avatar_url": "https://..."
      },
      "checkin_created": false
    },
    "has_journal_today": true,
    "has_checked_in_today": true,
    "has_posted_today": true,
    "streak_count": 4
  }
  ```

---

### 10.4. Nhật ký hôm nay của người dùng công khai (Direct Chat Status)
- **Method**: `GET`
- **Path**: `/api/v1/daily-needs/users/{user_id}/today`
- **Auth**: Public / Optional
- **Quy tắc**:
  - Dùng riêng cho Header cuộc trò chuyện 1-1 (Direct Chat) để hiển thị dòng trạng thái dưới tên người dùng.
  - Chỉ trả về nhật ký của ngày hôm nay (múi giờ `Asia/Ho_Chi_Minh`). Không trả về nhật ký ngày cũ.
  - Tuyệt đối không để lộ thông tin bảo mật (chỉ gồm `daily_need_id`, `content`, `note_date`, `updated_at`, `author`).
  - Nếu người dùng không có nhật ký hôm nay: trả về `200 OK` với body `null` (không dùng 404).
- **Response**: `200 OK`
  ```json
  {
    "daily_need_id": 1,
    "content": "Đang tìm giáo trình Giải tích để học tối nay",
    "note_date": "2026-09-03",
    "updated_at": "2026-09-03T08:00:00+07:00",
    "author": {
      "user_id": 123,
      "full_name": "Nguyễn Khắc Thịnh",
      "avatar_url": "https://..."
    }
  }
  ```
  *(Hoặc `null` khi chưa đăng hôm nay)*

---

### 10.5. Đăng hoặc cập nhật nhật ký hôm nay (Upsert)
- **Method**: `PUT`
- **Path**: `/api/v1/daily-needs/me/today`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Body**:
  ```json
  {
    "content": "Cần mua giáo trình Giải tích hoặc Spring Boot"
  }
  ```
- **Validation**:
  - Bắt buộc, không được để trống / chỉ có khoảng trắng.
  - Tối đa 120 ký tự.
  - Chuẩn hoá một dòng (loại bỏ xuống dòng).
  - Tự động gán `note_date` theo ngày hiện tại tại Việt Nam (không nhận `note_date` từ client).
- **Hành vi**:
  - Chưa có note hôm nay -> Tạo mới `daily_needs` và đồng thời chèn điểm danh `daily_journal_checkins` trong cùng 1 transaction nguyên tử (`checkin_created = true` -> client kích hoạt animation ngọn lửa).
  - Đã có note hôm nay -> Cập nhật cùng bản ghi `daily_needs` (`checkin_created = false`, không tạo thêm check-in, không kích hoạt animation).
  - Đăng lại sau khi đã xóa note trong ngày -> Tái tạo nội dung `daily_needs` (`checkin_created = false`, check-in đã có được giữ nguyên, không kích hoạt animation).
- **Response**: `200 OK` (`DailyNeedResponse` kèm `checkin_created: bool`)

---

### 10.6. Xóa nhật ký hôm nay
- **Method**: `DELETE`
- **Path**: `/api/v1/daily-needs/me/today`
- **Auth**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Hành vi**: Xóa nội dung nhật ký của ngày hôm nay khỏi bảng `daily_needs` (nội dung biến mất khỏi Marquee trang chủ và Direct Chat header). Bảng `daily_journal_checkins` ĐƯỢC GIỮ NGUYÊN. Chuỗi ngày `streak_count` và ngọn lửa trạng thái (`has_checked_in_today = true`) không bị thu hồi hay chuyển sang màu xám.
- **Response**: `204 No Content`

---

## 11. Group Lifecycle, Approval Settings & SYSTEM Events

### 11.1. Cập nhật cài đặt nhóm & phê duyệt
- **Method**: `PATCH`
- **Path**: `/api/v1/conversations/groups/{conversation_id}`
- **Auth**: Bắt buộc (`OWNER` hoặc `ADMIN` đối với metadata; `requires_approval` CHỈ `OWNER` mới có quyền sửa).
- **Body**:
  ```json
  {
    "title": "Nhóm học tập K20",
    "description": "Trao đổi tài liệu và bài tập",
    "requires_approval": true
  }
  ```
- **Quy tắc phân quyền**:
  - `requires_approval`: Nếu user không phải `OWNER` (kể cả `ADMIN`), trả về `403 Forbidden` (`{"detail": "Only group owner can modify approval settings."}`).
- **Hành vi SYSTEM message**:
  - Thay đổi `title`: Sinh SYSTEM message `"{actor} đã đổi tên nhóm thành \"{title}\"."`
  - Thay đổi `description`: Sinh SYSTEM message `"{actor} đã cập nhật mô tả nhóm."`
  - Trường không thay đổi: Không sinh SYSTEM message thừa.
- **Response**: `200 OK` (`ConversationDetailResponse` có trường `requires_approval: bool`)

---

### 11.2. Danh sách yêu cầu tham gia chờ duyệt
- **Method**: `GET`
- **Path**: `/api/v1/conversations/groups/{conversation_id}/pending-approvals`
- **Auth**: Bắt buộc (`OWNER` ONLY)
- **Quy tắc phân quyền**:
  - Chỉ `OWNER` mới được truy cập. `ADMIN` hoặc `MEMBER` nhận `403 Forbidden` (`{"detail": "Only group owner can view pending approvals."}`).
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "invite_id": 12,
        "conversation_id": 5,
        "invitee_id": 45,
        "invitee_name": "Trần Thị B",
        "invitee_avatar": "https://...",
        "inviter_id": 10,
        "inviter_name": "Nguyễn Văn A",
        "inviter_avatar": "https://...",
        "created_at": "2026-09-05T10:00:00Z"
      }
    ]
  }
  ```

---

### 11.3. Duyệt hoặc từ chối yêu cầu tham gia
- **Method**: `POST`
- **Path**: `/api/v1/conversations/groups/{conversation_id}/pending-approvals/{invite_id}`
- **Auth**: Bắt buộc (`OWNER` ONLY)
- **Quy tắc phân quyền**:
  - Chỉ `OWNER` mới được xử lý. `ADMIN` hoặc `MEMBER` nhận `403 Forbidden` (`{"detail": "Only group owner can approve or reject pending requests."}`).
- **Body**:
  ```json
  {
    "action": "APPROVE" // hoặc "REJECT"
  }
  ```
- **Hành vi**:
  - Khi `APPROVE`:
    - `invite.status` -> `ACCEPTED`.
    - Thêm user vào `conversation_members` với `role='MEMBER'`, `status='ACTIVE'`, `joined_at=now`.
    - Sinh SYSTEM message: `"{invitee} đã tham gia nhóm."`
    - Realtime: `GROUP_MEMBERSHIP_CHANGED` gửi toàn bộ active members.
    - Realtime: `MESSAGE_CREATED` gửi toàn bộ active members (bao gồm thành viên mới).
  - Khi `REJECT`:
    - `invite.status` -> `DECLINED`.
    - KHÔNG tạo membership, KHÔNG sinh SYSTEM message, KHÔNG ghi notifications table.
    - Realtime: gửi event tối giản `GROUP_INVITE_UPDATED` trực tiếp cho `invitee` (`status='DECLINED'`).
- **Response**: `200 OK` (`{"success": true, "status": "ACCEPTED" | "DECLINED"}`)

---

### 11.4. Quy tắc ngữ nghĩa tin nhắn SYSTEM
- **Bắt buộc**: Tin nhắn SYSTEM được lưu bền vững trong DB PostgreSQL (`messages.type = 'SYSTEM'`), trả về đầy đủ trong lịch sử chat, phân trang và timeline realtime.
- **Không gây tác dụng phụ**:
  - KHÔNG tăng `unread_count` của bất kỳ ai.
  - KHÔNG cập nhật `conversations.last_message_at`.
  - KHÔNG trở thành `last_message_preview` trên inbox preview.
  - KHÔNG tạo notification trong bảng `notifications`.
  - KHÔNG gửi push/browser notification.

---

## 12. Thông báo (Notifications)

### 12.1. GET /api/v1/notifications
- **Mô tả**: Lấy danh sách thông báo của người dùng hiện tại (Keyset Cursor Pagination).
- **Auth**: Bắt buộc (`get_current_active_user`)
- **Query Parameters**:
  - `limit`: int (mặc định 20, min 1, max 50)
  - `cursor`: string base64 urlsafe (tùy chọn)
  - `unread_only`: boolean (mặc định false)
- **Response 200 OK**:
  ```json
  {
    "items": [
      {
        "notification_id": 123,
        "type": "NEW_ORDER",
        "title": "Bạn có đơn hàng mới",
        "body": "Đơn ORD-260914-ABCD12 vừa được tạo.",
        "ref_type": "ORDER",
        "ref_id": 456,
        "is_read": false,
        "created_at": "2026-09-14T06:27:41"
      }
    ],
    "next_cursor": "eyJjcmVhdGVkX2F0Ij...",
    "has_more": false
  }
  ```

### 12.2. GET /api/v1/notifications/unread-count
- **Mô tả**: Lấy số lượng thông báo chưa đọc của người dùng hiện tại.
- **Auth**: Bắt buộc (`get_current_active_user`)
- **Response 200 OK**:
  ```json
  {
    "count": 3
  }
  ```

### 12.3. PATCH /api/v1/notifications/read-all
- **Mô tả**: Đánh dấu tất cả thông báo của người dùng hiện tại là đã đọc.
- **Auth**: Bắt buộc (`get_current_active_user`)
- **Thứ tự Route**: Static route `/read-all` được đăng ký trước parameterized `/{notification_id}/read`.
- **Response 204 No Content**

### 12.4. PATCH /api/v1/notifications/{notification_id}/read
- **Mô tả**: Đánh dấu một thông báo là đã đọc (idempotent).
- **Auth**: Bắt buộc (`get_current_active_user`)
- **Lỗi 404 Not Found**: Nếu thông báo không tồn tại hoặc thuộc người dùng khác (non-leaking 404).
- **Response 204 No Content**

### 12.5. Realtime Event: NOTIFICATION_CREATED
- **Kênh phát**: WebSocket cá nhân (`/ws/me`) và Redis pub/sub channel `user:{user_id}:events`.
- **Payload**:
  ```json
  {
    "type": "NOTIFICATION_CREATED",
    "notification": {
      "notification_id": 123,
      "type": "NEW_ORDER",
      "title": "Bạn có đơn hàng mới",
      "body": "Đơn ORD-260914-ABCD12 vừa được tạo.",
      "ref_type": "ORDER",
      "ref_id": 456,
      "is_read": false,
      "created_at": "2026-09-14T06:27:41"
    }
  }
  ```
- **Quy tắc Transaction**:
  - Giao dịch tạo thông báo NEW_ORDER nằm cùng transaction với đơn hàng (`session.flush()` -> tạo snapshot `NotificationResponse` -> commit duy nhất -> phát tán realtime `NOTIFICATION_CREATED` post-commit).
  - Lỗi mạng/Redis không làm rollback đơn hàng hoặc thông báo đã lưu bền vững.

---

### 12.6. Auction Notification Producers (Phase 8B)
Hệ thống thông báo đấu giá gồm 4 loại thông báo được phát sinh tự động trong các giao dịch nghiệp vụ cốt lõi:

1. **AUCTION_BID**:
   - **Người nhận (Recipient)**: Người bán sản phẩm (`auction.product.seller_id`).
   - **Thời điểm kích hoạt**: Khi một người dùng hợp lệ đặt giá vào phiên đấu giá (`place_bid`). Người đặt giá KHÔNG nhận thông báo này.
   - **Metadata**: `ref_type = 'AUCTION'`, `ref_id = auction_id`.
   - **Tiêu đề**: "Lượt đặt giá mới"
   - **Nội dung (Body)**: Chứa tên sản phẩm và số tiền đặt giá được định dạng tiền tệ (`...,... đ`).

2. **AUCTION_OUTBID**:
   - **Người nhận (Recipient)**: Người từng giữ giá cao nhất trước đó (`previous_highest_bidder_id`), CHỈ KHI bị vượt qua bởi một người dùng khác.
   - **Điều kiện loại trừ (Guards)**:
     - Lượt đặt giá đầu tiên (`previous_highest_bid is None`): KHÔNG gửi `AUCTION_OUTBID`.
     - Tự nâng giá (`self-raise`, `previous_highest_bidder_id == current_user_id`): KHÔNG gửi `AUCTION_OUTBID`.
   - **Thời điểm kích hoạt**: Snapshot người giữ giá cao nhất trước đó được lấy bên trong transaction có khóa dòng trước khi chèn bản ghi `AuctionBid` mới.
   - **Metadata**: `ref_type = 'AUCTION'`, `ref_id = auction_id`.
   - **Tiêu đề**: "Bạn đã bị trả giá cao hơn"
   - **Nội dung (Body)**: Chứa tên sản phẩm và mức giá mới cao hơn vừa được đặt.

3. **AUCTION_WON**:
   - **Người nhận (Recipient)**: Người chiến thắng phiên đấu giá (`winner_id`).
   - **Thời điểm kích hoạt**: Khi phiên đấu giá hết hạn và chuyển trạng thái hợp lệ sang `ENDED` (`close_single_auction_if_expired`). Chỉ phát sinh khi có lượt đặt giá hợp lệ.
   - **Metadata**: `ref_type = 'AUCTION'`, `ref_id = auction_id`.
   - **Tiêu đề**: "Chúc mừng! Bạn đã thắng đấu giá"
   - **Nội dung (Body)**: Chứa tên sản phẩm và mức giá chiến thắng cuối cùng.

4. **AUCTION_ENDED**:
   - **Người nhận (Recipient)**: Người bán sản phẩm (`auction.product.seller_id`).
   - **Thời điểm kích hoạt**: Khi phiên đấu giá hết hạn và chuyển trạng thái hợp lệ sang `ENDED` (`close_single_auction_if_expired`).
   - **Metadata**: `ref_type = 'AUCTION'`, `ref_id = auction_id`.
   - **Tiêu đề**: "Phiên đấu giá đã kết thúc"
   - **Nội dung (Body)**:
     - Có người thắng: Chứa tên sản phẩm và giá chốt phiên đấu giá.
     - Không có lượt bid: "Phiên đấu giá [Tên SP] đã kết thúc mà chưa có người thắng."

#### Quy tắc Transaction & Realtime Isolation:
- Tất cả các trường dữ liệu cần thiết (`seller_id`, `product_title`, `bidder_name`, `amount_formatted`, `winner_id`) được phân giải thành các biến nguyên thủy (plain data) trước khi flush/commit để triệt tiêu lỗi async ORM lazy-loading sau commit.
- Chèn notification vào DB -> `session.flush()` -> tạo snapshot DTO `NotificationResponse` bất biến -> duy nhất 1 lần `session.commit()` sở hữu bởi service nghiệp vụ.
- Phát tán realtime được thực hiện **post-commit** độc lập cho từng người nhận (`safe_publish_user_notification`):
  - Lỗi phát tán WebSocket/Redis tới một người nhận KHÔNG được chặn hay làm gián đoạn việc phát tán tới những người nhận khác.
  - Lỗi phát tán broadcast chung của auction KHÔNG làm gián đoạn thông báo riêng cho người bán/người thắng/người bị outbid.
- Tính bất biến/Idempotency của Worker: Phiên đấu giá đã ở trạng thái `ENDED` khi worker sweep quét lại sẽ lập tức bỏ qua (no-op), đảm bảo không bao giờ sinh thông báo trùng lặp.
- Điều hướng Frontend: Khách hàng click vào thông báo loại `ref_type = 'AUCTION'` được điều hướng qua `/auctions/:auctionId`, tự động phân giải `product_id` và điều hướng tới `/products/:productId` với ngữ nghĩa `{ replace: true }`, ngăn chặn triệt để vòng lặp lịch sử trình duyệt khi nhấn nút Back.

---

### 12.7. Group @Mention Notification Producer (Phase 8C)
Thông báo được phát sinh tự động khi người dùng trong một nhóm trò chuyện (`GROUP`) chủ động gắn thẻ (`@mention`) một hoặc nhiều thành viên khác trong nhóm.

1. **NEW_MESSAGE (@mention trong GROUP)**:
   - **Người nhận (Recipient)**: Tập hợp các `mentioned_user_id` phân biệt (distinct) được trích xuất trực tiếp từ các thực thể `MessageMention` đã được server xác thực và lưu bền vững, **loại trừ chính người gửi** (`mentioned_user_id != current_user.user_id`).
   - **Loại thông báo (type)**: `NEW_MESSAGE` (tái sử dụng enum hiện có, không bổ sung migration/enum mới).
   - **Metadata tham chiếu**: `ref_type = 'CONVERSATION'`, `ref_id = conversation_id`.
   - **Tiêu đề**: "Bạn được nhắc đến trong nhóm"
   - **Nội dung (Body)**: `"{sender_name} đã nhắc đến bạn trong {group_title}."`
   - **Trạng thái đọc ban đầu**: `is_read = false`.

2. **Quy tắc Nghiệp vụ và Loại trừ (Guards)**:
   - **Phạm vi nhóm (Group Scope)**: Chỉ áp dụng cho cuộc trò chuyện loại `GROUP`.
   - **DIRECT Chat**: Gửi kèm `mentions` payload bị từ chối `400 Bad Request` ("Tính năng gắn thẻ chỉ khả dụng trong nhóm và cộng đồng."). Không sinh thông báo.
   - **COMMUNITY Chat**: Gửi kèm `mentions` được chấp nhận và lưu `message_mentions`, nhưng KHÔNG phát sinh thông báo (nhằm tránh notification storm/spam trong nhóm cộng đồng toàn trường).
   - **Tin nhắn thường (No Mentions)**: Tin nhắn gửi trong nhóm không kèm structured mentions -> tạo 0 thông báo.
   - **Tin nhắn hệ thống (SYSTEM)**: Tin nhắn hệ thống tạo trong nhóm (đổi tên nhóm, thêm thành viên, v.v.) -> tạo 0 thông báo.
   - **Self-mention**: Người gửi tự tag chính mình (`@sender`) -> bị loại trừ khỏi danh sách nhận thông báo (tạo 0 thông báo cho sender).
   - **Khử trùng lặp người nhận (Deduplication)**: Nếu một thành viên được tag nhiều lần trong cùng 1 tin nhắn (hoặc trùng display text), người đó chỉ nhận duy nhất 1 thông báo. Khử trùng lặp dựa trên `user_id` định danh duy nhất trong CSDL, tuyệt đối không dựa trên chuỗi tên hiển thị.
   - **Bảo toàn danh tính độc lập**: Hai thành viên có cùng tên hiển thị (ví dụ hai bạn cùng tên "Nguyễn Văn Test") được phân định hoàn toàn bởi `user_id` bên trong structured mention payload. Chọn người nào thì chỉ người đó nhận thông báo.
   - **Thành viên không hoạt động**: Gắn thẻ thành viên đã rời nhóm hoặc bị xóa (`left_at IS NOT NULL`) hoặc không thuộc nhóm bị server từ chối ngay lập tức với `422 Unprocessable Entity`.

3. **Tính Nguyên tử của Giao dịch (Transaction Atomicity)**:
   - Việc lưu `Message`, các dòng `MessageMention`, và các dòng `Notification` (`NEW_MESSAGE`) diễn ra trong **MỘT TRANSACTION DUY NHẤT** do service nghiệp vụ sở hữu:
     `self.repo.create_message()` (flush) -> tạo các bản ghi `Notification` -> `self.db.flush()` -> tạo snapshot DTO `NotificationResponse` -> `await self.db.commit()`.
   - Nếu xảy ra lỗi trước hoặc trong khi commit, toàn bộ thay đổi được rollback sạch sẽ: 0 Message, 0 MessageMention, 0 Notification.

4. **Cách ly Thời gian thực (Realtime Isolation)**:
   - Sau khi commit thành công:
     - Bước 1: Thử an toàn phát sự kiện `MESSAGE_CREATED` tới tất cả thành viên đang hoạt động trong nhóm. Lỗi phát tán broadcast chat được bao bọc trong khối `try...except`, không được phép làm gián đoạn việc gửi thông báo.
     - Bước 2: Thử độc lập phát sự kiện `NOTIFICATION_CREATED` tới từng người nhận thông báo (`safe_publish_user_notification`). Lỗi phát tán tới một người nhận KHÔNG ảnh hưởng hay chặn việc phát tán tới những người nhận còn lại.
   - Lỗi WebSocket/Redis chỉ ảnh hưởng đến realtime tức thời, không làm hỏng dữ liệu bền vững trong CSDL.

5. **Điều hướng Frontend (Navigation & Authorization Invariant)**:
   - Khi click vào thông báo `NEW_MESSAGE` trong trang `/notifications`:
     - Kích hoạt đánh dấu đã đọc bất đồng bộ (fire-and-forget, không block điều hướng).
     - Điều hướng ngay lập tức tới `/messages?c={conversation_id}`.
   - Nếu người nhận đã bị kick/rời khỏi nhóm sau thời điểm được tag, khi truy cập vào hội thoại sẽ bị lớp phân quyền chuẩn của Conversation từ chối `404 Not Found` (non-leaking) và tự động đóng/chuyển hướng an toàn mà không rơi vào vòng lặp retry. Thông báo không cấp thêm bất kỳ đặc quyền truy cập nào.

---

### 12.8. Order Status & Lifecycle Notification Producer (Phase 8D)
Thông báo in-app được phát sinh tự động trong các bước chuyển trạng thái quan trọng thuộc vòng đời đơn hàng (`Order`).

1. **Loại thông báo (type)**:
   - Sử dụng thống nhất `ORDER_STATUS` (tái sử dụng enum hiện có, không bổ sung migration/enum mới).
   - `ref_type = 'ORDER'`, `ref_id = order_id`.

2. **Ma trận sự kiện và nội dung (Canonical Event Matrix)**:
   - **Xác nhận đơn hàng (`PENDING -> CONFIRMED`)**:
     - *Tác nhân*: Người bán (`Seller`).
     - *Người nhận*: Người mua (`Buyer`). Người bán nhận 0 thông báo.
     - *Tiêu đề*: "Đơn hàng đã được xác nhận"
     - *Nội dung*: `"Đơn {order_code} đã được người bán xác nhận."`
   - **Tải lên biên nhận thanh toán (`UNPAID -> VERIFYING`)**:
     - *Tác nhân*: Người mua (`Buyer`).
     - *Người nhận*: Người bán (`Seller`). Người mua nhận 0 thông báo.
     - *Tiêu đề*: "Người mua đã gửi biên nhận"
     - *Nội dung*: `"Đơn {order_code} đang chờ bạn kiểm tra thanh toán."`
   - **Xác nhận thanh toán (`VERIFYING/UNPAID -> PAID`)**:
     - *Tác nhân*: Người bán (`Seller`).
     - *Người nhận*: Người mua (`Buyer`). Người bán nhận 0 thông báo.
     - *Tiêu đề*: "Thanh toán đã được xác nhận"
     - *Nội dung*: `"Thanh toán cho đơn {order_code} đã được người bán xác nhận."`
   - **Bắt đầu giao hàng (`CONFIRMED -> DELIVERING`, áp dụng hình thức SHIPPING)**:
     - *Tác nhân*: Người bán (`Seller`).
     - *Người nhận*: Người mua (`Buyer`). Người bán nhận 0 thông báo.
     - *Tiêu đề*: "Đơn hàng đang được giao"
     - *Nội dung*: `"Đơn {order_code} đã bắt đầu được giao đến bạn."`
   - **Hoàn tất đơn hàng (`CONFIRMED/DELIVERING -> COMPLETED`)**:
     - *Tác nhân*: Người mua hoặc Người bán.
     - *Người nhận*: Bên còn lại (non-actor). Tác nhân nhận 0 thông báo.
     - *Tiêu đề*: "Đơn hàng đã hoàn tất"
     - *Nội dung*: `"Đơn {order_code} đã được hoàn tất."`
   - **Hủy đơn hàng thủ công (`valid status -> CANCELLED`)**:
     - *Tác nhân*: Người mua hoặc Người bán.
     - *Người nhận*: Bên còn lại (non-actor). Tác nhân nhận 0 thông báo.
     - *Tiêu đề*: "Đơn hàng đã bị hủy"
     - *Nội dung*: `"Người mua đã hủy đơn {order_code}."` hoặc `"Người bán đã hủy đơn {order_code}."`
     - *Bảo mật*: Lý do hủy (`cancel_reason`) không bị leak vào tiêu đề/nội dung thông báo in-app.
   - **Hệ thống tự động hủy đơn quá hạn (`PENDING -> CANCELLED`)**:
     - *Tác nhân*: Hệ thống (`SYSTEM` background worker sweep).
     - *Người nhận*: **Cả Người mua VÀ Người bán** trong cùng 1 transaction.
     - *Tiêu đề*: "Đơn hàng đã tự động hủy"
     - *Nội dung*: `"Đơn {order_code} đã tự động hủy do quá thời gian xác nhận."`
   - **Cập nhật điều khoản giao dịch (`update_transaction_terms`)**:
     - *Tác nhân*: Người bán (`Seller`).
     - *Người nhận*: Người mua (`Buyer`).
     - *Tiêu đề*: "Điều khoản đơn hàng đã được cập nhật"
     - *Nội dung*: `"Người bán đã cập nhật thông tin giao dịch của đơn {order_code}."`
     - *Quy tắc phát hiện thay đổi*: So sánh bộ giá trị lưu trữ canonical trước và sau khi cập nhật: `(payment_method, fulfillment_method, meetup_place, meetup_time, shipping_address, shipping_expected_at, payment_note)`. Nếu không có thay đổi thực chất (no-op PATCH), tạo 0 thông báo.

3. **Bảo toàn ngữ nghĩa API & Xử lý trùng lặp**:
   - Các hành vi idempotency hoặc lỗi validation có sẵn của API được bảo toàn tuyệt đối:
     - Lặp lại `confirm_order`: Giữ nguyên lỗi `400 Bad Request`, tạo 0 thông báo mới.
     - Lặp lại `confirm_payment`: Giữ nguyên phản hồi idempotent, tạo 0 thông báo mới.
     - Lặp lại `cancel_order`: Giữ nguyên phản hồi idempotent, tạo 0 thông báo mới.
     - Lặp lại `complete_order`: Giữ nguyên lỗi `400 Bad Request`, tạo 0 thông báo mới.
     - Quét lại auto-cancel đối với đơn đã hủy: Trả về `False`, tạo 0 thông báo mới.

4. **Tính nguyên tử và cô lập Realtime**:
   - Toàn bộ thao tác cập nhật đơn hàng + lịch sử trạng thái + tạo bản ghi thông báo được thực hiện trong **MỘT TRANSACTION DUY NHẤT**: `flush()` -> tạo snapshot DTO `NotificationResponse` -> `commit()`.
   - Lỗi phát tán WebSocket (`publish_order_updated` hoặc `NOTIFICATION_CREATED`) không làm rollback dữ liệu CSDL đã commit.
   - Khi phát tán cho nhiều người nhận (SYSTEM auto-cancel), việc gửi realtime được cô lập độc lập cho từng người nhận qua `safe_publish_user_notification`, lỗi của một người nhận không ảnh hưởng đến người nhận còn lại.

5. **Frontend Navigation**:
   - `NotificationItem` đã tích hợp xử lý loại `ORDER_STATUS`, hiển thị icon xe hàng (`Truck`), click vào sẽ điều hướng đến route chi tiết đơn hàng `/orders/{ref_id}`.

---

### 12.9. Group Invitation Notification Producer
Thông báo in-app bền vững được phát sinh tự động khi một thành viên nhóm mời thành viên mới tham gia cuộc trò chuyện loại `GROUP`.

1. **Loại thông báo (type)**:
   - Sử dụng thống nhất `SYSTEM` (tái sử dụng enum hiện có, không bổ sung migration/enum mới).
   - `ref_type = 'GROUP_INVITE'`, `ref_id = invite_id` (định danh có cấu trúc, không phụ thuộc substring matching).

2. **Người nhận & Nội dung (Recipient & Copy)**:
   - **Người nhận (Recipient)**: Người được mời (`invite.invitee_id`). Người mời (`inviter`) nhận 0 thông báo.
   - **Tiêu đề**: "Bạn có lời mời tham gia nhóm"
   - **Nội dung (Body)**: `"{inviter_display_name} đã mời bạn tham gia {group_title}."`
   - **Bảo mật**: Không chứa email, số điện thoại, token hay thông tin riêng tư.
   - **Trạng thái đọc ban đầu**: `is_read = false`.

3. **Tính nguyên tử của Giao dịch (Transaction Atomicity)**:
   - Việc tạo bản ghi `ConversationInvite` và bản ghi `Notification` (`SYSTEM`) diễn ra trong **CÙNG MỘT TRANSACTION POSTGRESQL** do Service sở hữu:
     `repo.create_invites()` (flush) -> `NotificationRepository.create()` (flush) -> snapshot DTO `NotificationResponse` -> `await self.db.commit()`.
   - Nếu xảy ra lỗi trước hoặc trong khi commit: rollback toàn bộ, đảm bảo 0 invite và 0 notification được lưu.

4. **Xử lý trùng lặp & Chuyển trạng thái**:
   - Yêu cầu mời trùng lặp bị từ chối/bỏ qua -> tạo 0 bản ghi thông báo mới.
   - Chấp nhận (`ACCEPT`) hoặc từ chối (`DECLINE`) lời mời -> cập nhật trạng thái lời mời, KHÔNG sinh thêm thông báo loại "Bạn có lời mời tham gia nhóm".
   - Tin nhắn dòng thời gian hệ thống trong nhóm (`Message.type == 'SYSTEM'`) -> tạo 0 thông báo in-app (không làm ô nhiễm Bell hay unread count).

5. **Phân phối Realtime (Post-Commit Delivery)**:
   - Sau khi commit thành công vào PostgreSQL, hệ thống phát tán song song độc lập:
     - `GROUP_INVITE_CREATED` tới người được mời để cập nhật số lượng badge tab Lời mời trong Tin nhắn.
     - `NOTIFICATION_CREATED` tới người được mời qua WebSocket private `/ws/me` để cập nhật chuông thông báo (Bell badge count) và danh sách thông báo.
   - Lỗi phát tán WebSocket/Redis của một sự kiện không ảnh hưởng hoặc chặn sự kiện còn lại; không làm rollback dữ liệu CSDL đã commit.

6. **Điều hướng Frontend (Navigation)**:
   - Khi người dùng click vào thông báo có `type === 'SYSTEM'` và `ref_type === 'GROUP_INVITE'`:
     - Kích hoạt đánh dấu đã đọc bất đồng bộ (không block điều hướng).
     - Điều hướng ngay lập tức tới `/messages?tab=invites` (chọn sẵn tab Lời mời trong Tin nhắn).
     - Không cấp quyền truy cập cuộc trò chuyện nếu người dùng chưa bấm Chấp nhận lời mời.

---

## Group Self-Nickname API Contract (Biệt danh trong nhóm)

### Endpoint: Cập nhật hoặc xóa biệt danh bản thân trong nhóm

- **Method**: `PATCH`
- **Path**: `/api/v1/conversations/groups/{conversation_id}/me/nickname`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`
- **Scope**: Self-scoped chỉ cho chính người dùng hiện tại; không nhận bất kỳ tham số `user_id` hay `member_id` nào. Chủ nhóm (`OWNER`) và Quản trị viên (`ADMIN`) không có quyền đổi biệt danh của thành viên khác.

#### Request Body
```json
{
  "nickname": "Mít"
}
```
- `nickname`: `Optional[str]` (tối đa 40 ký tự).
- Chuỗi rỗng (`""`), chỉ chứa khoảng trắng (`"   "`), hoặc `null`: Xóa biệt danh (đưa trường `nickname` về `NULL` trong cơ sở dữ liệu).
- Ký tự bị từ chối (`400 Bad Request`): Chứa ký tự xuống dòng (`\r`, `\n`), khoảng tab (`\t`), hoặc ký tự điều khiển ASCII/Unicode C0/C1.
- Ký tự được hỗ trợ: Chữ cái, khoảng trắng đơn/kép, tiếng Việt có dấu, emoji, ký tự Unicode chuẩn.

#### Response: `200 OK`
Trả về DTO `ConversationMemberResponse`:
```json
{
  "user_id": 101,
  "full_name": "Nguyễn Khắc Thịnh",
  "avatar_url": "https://...",
  "role": "MEMBER",
  "joined_at": "2026-09-15T08:00:00Z",
  "nickname": "Mít",
  "is_online": false
}
```

#### Realtime Event
- Event type: `GROUP_MEMBERSHIP_CHANGED`
- Action: `NICKNAME_UPDATED`
- Payload:
```json
{
  "type": "GROUP_MEMBERSHIP_CHANGED",
  "conversation_id": 12,
  "action": "NICKNAME_UPDATED"
}
```
- Client Handling: Tự động invalidate query `['conversations', convId, 'members']`. Không bao giờ trigger thu hồi quyền truy cập (`handleConversationAccessRevoked`) hay điều hướng rời khỏi nhóm.

#### Tác dụng phụ (Side Effects)
- Tạo 0 tin nhắn hệ thống (`SYSTEM`).
- Tạo 0 dòng thông báo (`notifications`).
- Tăng 0 số đếm chưa đọc (`unread_count`).
- Không làm thay đổi `users.full_name` (danh tính gốc luôn được bảo toàn).

---

## 18. Chợ PTITers Signature Message Reactions

Cho phép người dùng bày tỏ cảm xúc trên tin nhắn bằng bộ reaction mang nhận diện Chợ PTITers trong cuộc trò chuyện 1-1 (DIRECT) và nhóm (GROUP).

### 18.1. Đặt / Đổi cảm xúc tin nhắn (PUT)

- **Method**: `PUT`
- **Path**: `/api/v1/conversations/{conversation_id}/messages/{message_id}/reaction`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE`
- **Phạm vi áp dụng**: `DIRECT` và `GROUP` (từ chối `COMMUNITY` với `400 Bad Request`).

#### Quyền truy cập:
- **DIRECT**: Người dùng phải là một trong 2 người tham gia canonical (`user_one_id` hoặc `user_two_id`). Không yêu cầu dòng `conversation_members`.
- **GROUP**: Người dùng phải là thành viên hoạt động (`left_at IS NULL`). Tin nhắn không được gửi trước thời điểm `joined_at` của thành viên.
- Tin nhắn phải thuộc đúng `conversation_id`, chưa bị xóa (`is_deleted = False`), và không phải tin nhắn hệ thống (`type != 'SYSTEM'`).
- Mọi trường hợp vi phạm quyền truy cập hoặc tin nhắn không thuộc cuộc trò chuyện trả về `404 Not Found` (không làm rò rỉ sự tồn tại của tin nhắn ngoại lai).

#### Request Body
```json
{
  "reaction_key": "THICH"
}
```
- `reaction_key`: Bắt buộc. Một trong 12 mã ASCII:
  `'THICH'`, `'HAHA'`, `'WOW'`, `'CAM_ON'`, `'CHOT_DEAL'`, `'UY_TIN'`, `'DANG_TOI'`, `'DOI_CHUT'`, `'QUAN_TAM'`, `'HET_TIEN'`, `'HOC_BAI'`, `'KHA_NGHI'`.
- Giá trị không hợp lệ trả về `422 Unprocessable Entity`.

#### Response: `200 OK`
Trả về DTO `MessageReactionSummaryResponse`:
```json
{
  "message_id": 456,
  "reactions": [
    {
      "reaction_key": "THICH",
      "count": 2
    },
    {
      "reaction_key": "CHOT_DEAL",
      "count": 1
    }
  ],
  "my_reaction": "THICH"
}
```

---

### 18.2. Gỡ bỏ cảm xúc tin nhắn (DELETE)

- **Method**: `DELETE`
- **Path**: `/api/v1/conversations/{conversation_id}/messages/{message_id}/reaction`
- **Authentication**: Bắt buộc
- **Tính lũy đẳng (Idempotent)**: Nếu người dùng chưa từng reaction tin nhắn này, API vẫn trả về `200 OK` với danh sách tổng hợp hiện thời và `my_reaction: null`.

#### Response: `200 OK`
Trả về DTO `MessageReactionSummaryResponse`:
```json
{
  "message_id": 456,
  "reactions": [
    {
      "reaction_key": "THICH",
      "count": 1
    }
  ],
  "my_reaction": null
}
```

---

### 18.3. Hợp đồng Realtime (`MESSAGE_REACTIONS_UPDATED`)

Được gửi qua hạ tầng private WebSocket `/ws/me` hiện có tới tất cả thành viên hợp lệ của cuộc trò chuyện (best-effort, không chặn hay rollback giao dịch cơ sở dữ liệu).

#### Payload Contract
```json
{
  "type": "MESSAGE_REACTIONS_UPDATED",
  "conversation_id": 123,
  "message_id": 456,
  "reactions": [
    {
      "reaction_key": "THICH",
      "count": 2
    },
    {
      "reaction_key": "CHOT_DEAL",
      "count": 1
    }
  ],
  "actor_user_id": 42,
  "actor_reaction": "THICH"
}
```
Khi gỡ bỏ cảm xúc: `actor_reaction: null`.

- Tuyệt đối không chứa danh sách danh tính reactor, email, nickname, hay profile private data.
- Phía Frontend áp dụng snapshot tạm thời để tối ưu độ trễ, sau đó invalidate query active messages list để đồng bộ trạng thái canonical từ PostgreSQL/REST (chống lỗi sự kiện đến sai thứ tự out-of-order).

---

## 19. Phase 8E — NEW_REVIEW Notifications

Tài liệu này định nghĩa hợp đồng phát sinh và nhận thông báo khi người mua (Buyer) tạo đánh giá (Review) cho đơn hàng đã hoàn tất (`COMPLETED`).

### 19.1. Producer & Quyền hạn phát sinh
- **Trigger**: Tạo thành công một đánh giá mới qua endpoint `POST /api/v1/orders/{order_id}/review`.
- **Actor**: Người mua (Buyer/reviewer).
- **Recipient**: Người bán (Seller/reviewee) được suy xuất trực tiếp từ đơn hàng chuẩn (`review.reviewee_id == order.seller_id`).
- **Self-action guard**: Người mua tuyệt đối không nhận thông báo tự thân từ hành động của chính mình.
- **Tính nguyên tử (Atomicity)**: Bản ghi `Review` và bản ghi `Notification` được thêm và commit trong cùng một transaction PostgreSQL. Nếu transaction gặp lỗi hoặc bị rollback, cả hai đều không được lưu.

### 19.2. Notification Schema & Copy Contract
- **type**: `NEW_REVIEW` (tái sử dụng enum và check constraint có sẵn trong CSDL; không tạo enum mới hay chạy migration rỗng).
- **ref_type**: `"ORDER"`
- **ref_id**: `order_id` (BIGINT)
- **title**: `"Bạn có đánh giá mới"`
- **body**: `"Đơn {order_code} vừa nhận được đánh giá {rating} sao."` (sử dụng giá trị `review.rating` đã được lưu chuẩn; ví dụ: `"Đơn ORD-ABC123 vừa nhận được đánh giá 5 sao."`).
- **Bảo mật quyền riêng tư (Privacy-Safe)**:
  - Tuyệt đối không đưa nội dung nhận xét tùy ý (`comment`) của người mua vào `Notification.body`.
  - Tuyệt đối không đưa email, số điện thoại, địa chỉ, hay Firebase UID của người mua vào thông báo.
  - Thông báo chỉ đóng vai trò chỉ dấu điều hướng (navigation cue).

### 19.3. Điều hướng & Ngữ cảnh Frontend
- **Destination**: `/orders/:orderId`
- **Navigation flow**: Khi người dùng nhấn vào thông báo `NEW_REVIEW` trong danh sách:
  - Nếu thông báo chưa đọc (`is_read == false`), trigger mutation đánh dấu đã đọc bất đồng bộ (không chặn điều hướng).
  - Điều hướng ngay lập tức đến `/orders/:orderId`.
- **Hiển thị ngữ cảnh**: Trang `OrderDetailPage` đã hỗ trợ đầy đủ hiển thị ngữ cảnh đánh giá cho đơn hàng `COMPLETED`: hiển thị sao (`StarRating`), nhãn cảm xúc, ngày đánh giá, nhận xét chi tiết và huy hiệu cộng điểm uy tín cho người bán.

### 19.4. Bất biến nghiệp vụ (Business Invariants)
- **POST duy nhất**: Chỉ tạo thông báo `NEW_REVIEW` khi tạo mới review thành công lần đầu.
- **PATCH Review**: Chỉnh sửa đánh giá (sửa sao, sửa comment, hoặc cả hai qua `PATCH /api/v1/orders/{order_id}/review`) tuyệt đối **KHÔNG** tạo thêm thông báo `NEW_REVIEW`.
- **GET / List Review**: Các thao tác đọc đánh giá không bao giờ tạo thông báo.
- **Duplicate POST**: Yêu cầu tạo trùng lặp bị từ chối với HTTP `409 Conflict` (bởi tiền kiểm tra logic hoặc backstop ràng buộc duy nhất `ux_reviews_order_reviewer`) và không phát sinh thêm thông báo nào.
- **Invalid Request**: Các yêu cầu đánh giá không hợp lệ (đơn chưa `COMPLETED`, người bán tự đánh giá, người ngoài đơn hàng, số sao ngoài khoảng 1-5) đều bị từ chối và tạo chính xác 0 thông báo.
- **Không hồi tố (No Historical Backfill)**: Tính năng chỉ áp dụng cho các đánh giá tạo mới kể từ thời điểm triển khai; không quét CSDL để tạo thông báo cho các review cũ trong lịch sử.
- **Giữ nguyên thuật ngữ & uy tín**: Không thay đổi thuật toán tính điểm uy tín người bán, không bổ sung cột tổng hợp dư thừa.

### 19.5. Phân phối Realtime (`NOTIFICATION_CREATED`)
- Sau khi transaction commit thành công vào PostgreSQL, hệ thống phát tán sự kiện `NOTIFICATION_CREATED` tới người bán (`reviewee_id`) qua hạ tầng WebSocket private `/ws/me`.
- **Payload Contract**:
```json
{
  "type": "NOTIFICATION_CREATED",
  "notification": {
    "notification_id": 1234,
    "user_id": 56,
    "type": "NEW_REVIEW",
    "title": "Bạn có đánh giá mới",
    "body": "Đơn ORD-ABC123 vừa nhận được đánh giá 5 sao.",
    "ref_type": "ORDER",
    "ref_id": 789,
    "is_read": false,
    "created_at": "2026-09-15T13:30:00"
  }
}
```
- **Cơ chế Best-effort**: Việc phát tán realtime qua Redis/WebSocket nếu gặp lỗi mạng hay gián đoạn kết nối sẽ không làm rollback dữ liệu đánh giá và thông báo đã commit, đồng thời API trả về HTTP `201 Created` bình thường.
- Phía Frontend: Hook `usePrivateRealtime` tự động bắt sự kiện `NOTIFICATION_CREATED` và invalidate query cache `NOTIFICATION_QUERY_KEYS.all`, giúp cập nhật tức thời chuông thông báo (Bell badge count) và danh sách thông báo mà không cần tải lại trang.

---

## 20. Phase 8F — Reports (Báo cáo vi phạm)

Tài liệu này định nghĩa hợp đồng API chính thức cho phân hệ tiếp nhận Báo cáo vi phạm (Reports) của người dùng đối với Người dùng (`USER`), Sản phẩm (`PRODUCT`) và Đơn hàng (`ORDER`).

### 20.1. Endpoint: Tạo báo cáo vi phạm

- **Method**: `POST`
- **Path**: `/api/v1/reports`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`)
- **Status Requirement**: `ACTIVE` (User `BANNED` hoặc `INACTIVE` bị từ chối với HTTP `403 Forbidden`).

#### Headers
```http
Authorization: Bearer <FIREBASE_ID_TOKEN>
Content-Type: application/json
```

#### Request Body (`ReportCreateRequest`)
Cấu hình schema: `extra = "forbid"` (từ chối mọi trường lạ ngoài hợp đồng).

```json
{
  "target_type": "PRODUCT",
  "target_id": 123,
  "reason": "FAKE_ITEM",
  "description": "Sách photo vi phạm bản quyền"
}
```

- **`target_type`**: Enum chuỗi, bắt buộc. Giá trị hợp lệ: `USER`, `PRODUCT`, `ORDER`.
- **`target_id`**: Số nguyên (`BIGINT`), bắt buộc (`gt=0`). ID của đối tượng bị báo cáo.
- **`reason`**: Enum chuỗi, bắt buộc. Giá trị hợp lệ: `SCAM`, `FAKE_ITEM`, `SPAM`, `INAPPROPRIATE`, `NO_SHOW`, `OTHER`.
- **`description`**: Chuỗi văn bản, tuỳ chọn (trừ khi `reason="OTHER"`). Tối đa 1000 ký tự. Tự động trim khoảng trắng hai đầu; nếu chỉ gồm khoảng trắng sẽ chuẩn hoá về `null`.

#### Ma trận lý do báo cáo theo đối tượng (`REPORT_REASON_MATRIX`)

| Loại đối tượng (`target_type`) | Các lý do hợp lệ (`reason`) |
|---|---|
| `USER` | `SCAM`, `SPAM`, `INAPPROPRIATE`, `OTHER` |
| `PRODUCT` | `SCAM`, `FAKE_ITEM`, `SPAM`, `INAPPROPRIATE`, `OTHER` |
| `ORDER` | `SCAM`, `FAKE_ITEM`, `SPAM`, `INAPPROPRIATE`, `NO_SHOW`, `OTHER` |

#### Response: `201 Created` (`ReportResponse`)
Bảo mật quyền riêng tư: Tuyệt đối không trả về `reporter_id`, `handled_by`, hay `handled_at`.

```json
{
  "report_id": 1,
  "target_type": "PRODUCT",
  "target_id": 123,
  "reason": "FAKE_ITEM",
  "description": "Sách photo vi phạm bản quyền",
  "status": "OPEN",
  "created_at": "2026-09-15T20:35:00"
}
```

### 20.2. Ma trận mã lỗi xác định (Deterministic Error Matrix)

| HTTP Status | Trường hợp phát sinh | Chi tiết phản hồi |
|---|---|---|
| `401 Unauthorized` | Không có token hoặc token không hợp lệ | `{"detail": "Missing or invalid Authorization header."}` |
| `403 Forbidden` | Tài khoản người gửi báo cáo bị `BANNED` hoặc `INACTIVE` | `{"detail": "User account is banned."}` / `{"detail": "User account is inactive."}` |
| `400 Bad Request` | Tự báo cáo chính mình (`target_type="USER"`, `target_id=reporter_id`) | `{"detail": "Không thể tự báo cáo chính mình."}` |
| `400 Bad Request` | Tự báo cáo sản phẩm của mình (`target_type="PRODUCT"`, `seller_id=reporter_id`) | `{"detail": "Không thể báo cáo sản phẩm của chính mình."}` |
| `404 Not Found` | Đối tượng `USER` không tồn tại hoặc không ở trạng thái `ACTIVE` (tái sử dụng quy tắc hồ sơ công khai) | `{"detail": "Không tìm thấy người dùng."}` |
| `404 Not Found` | Đối tượng `PRODUCT` không tồn tại, đã soft-deleted (`is_deleted=True`), hoặc ở trạng thái `HIDDEN` đối với người ngoài | `{"detail": "Product not found."}` |
| `404 Not Found` | Đối tượng `ORDER` không tồn tại, hoặc người gửi báo cáo không phải Người mua/Người bán của đơn hàng (chống lộ thông tin tồn tại) | `{"detail": "Không tìm thấy đơn hàng."}` |
| `409 Conflict` | Đã tồn tại một báo cáo đang hoạt động (`OPEN` hoặc `REVIEWING`) của chính reporter đối với cùng đối tượng | `{"detail": "Bạn đã gửi báo cáo cho đối tượng này và đang được xử lý."}` |
| `422 Unprocessable Entity` | Sai enum `target_type`, sai enum `reason`, lý do không thuộc ma trận đối tượng, `reason="OTHER"` nhưng thiếu mô tả chi tiết, mô tả dài > 1000 ký tự, hoặc chứa trường thừa | Lỗi xác thực cấu trúc dữ liệu Pydantic tiêu chuẩn |

### 20.3. Cơ chế chống trùng lặp & Mức độ đảm bảo tương tranh (Concurrency Semantics)
- **Kiểm tra trùng lặp tuần tự (Sequential active duplicate prevention)**: `VERIFIED`. Hệ thống từ chối `409 Conflict` nếu người dùng gửi thêm báo cáo khi báo cáo cũ đang ở trạng thái `OPEN` hoặc `REVIEWING`.
- **Cho phép báo cáo lại**: Nếu báo cáo trước đó đã được xử lý xong (`RESOLVED` hoặc `REJECTED`), người dùng được phép tạo báo cáo mới cho đối tượng đó.
- **Tính duy nhất khi gửi đồng thời (Concurrent identical-submit uniqueness)**: `NOT STRICTLY GUARANTEED BY CURRENT DB SCHEMA`. Do schema CSDL `DB_v7` không đặt ràng buộc UNIQUE trên bảng `reports` (để hỗ trợ báo cáo lại sau khi resolved/rejected), hai yêu cầu gửi cùng mili-giây có thể lọt qua kiểm tra tầng service.

### 20.4. Bất biến nghiệp vụ & An toàn bảo mật (Invariants & Safety)
- **Không thay đổi trạng thái miền (No Domain State Mutation)**: Việc tạo báo cáo chỉ đóng vai trò ghi nhận tín hiệu kiểm duyệt; tuyệt đối KHÔNG tự ý thay đổi `User.status`, `Product.status`, `Product.is_deleted`, `stock`, `reserved_stock`, `Order.status`, hay `payment_status`.
- **Không phát sinh thông báo hoặc realtime (Zero Notification / Zero Realtime)**: Báo cáo vi phạm không tạo bản ghi `notifications` và không phát tán WebSocket/Redis tới bất kỳ ai.
- **Server-owned fields**: Các trường `reporter_id` (lấy từ token xác thực), `status` (mặc định `OPEN`), `handled_by` (luôn `NULL`), `handled_at` (luôn `NULL`), và `created_at` (luôn gán bởi server) được bảo vệ tuyệt đối và không nhận từ client.

---

## 21. Phase 8G-A — Admin Report Queue & Resolution (Hàng đợi & Xử lý báo cáo vi phạm)

Tài liệu này định nghĩa hợp đồng API dành cho Quản trị viên (ADMIN) để xem danh sách hàng đợi báo cáo vi phạm, xem chi tiết và giải quyết trạng thái kiểm duyệt (`status`).

### 21.1. Quyền hạn truy cập (Authorization)
- **Authority**: Tái sử dụng dependency chuẩn `require_admin`.
- **Enforcement**: Yêu cầu tài khoản có `role == 'ADMIN'` và `status == 'ACTIVE'`.
- Người dùng có `role == 'STUDENT'` bị từ chối với HTTP `403 Forbidden` (`{"detail": "Operation not permitted for your user role."}`).
- Chưa xác thực bị từ chối với HTTP `401 Unauthorized`.

### 21.2. Endpoint: Danh sách hàng đợi báo cáo (`GET /api/v1/admin/reports`)

- **Method**: `GET`
- **Path**: `/api/v1/admin/reports`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)

#### Query Parameters:
- `status` (chuỗi enum, tuỳ chọn): `OPEN`, `REVIEWING`, `RESOLVED`, `REJECTED`.
- `target_type` (chuỗi enum, tuỳ chọn): `USER`, `PRODUCT`, `ORDER`.
- `cursor` (chuỗi base64 opaque, tuỳ chọn): Con trỏ phân trang keyset `(created_at, report_id)`.
- `limit` (số nguyên, tuỳ chọn, mặc định 20, min 1, max 50): Số lượng bản ghi trên một trang.

#### Sắp xếp & Phân trang:
- **Thứ tự mặc định**: `created_at DESC`, tie-break bằng `report_id DESC`.
- **Keyset cursor**: Tuyệt đối không dùng offset pagination. Con trỏ mã hoá an toàn dạng base64 chuỗi `ISO|ID`. Con trỏ sai định dạng trả về `422 Unprocessable Content`.

#### Batch Target Resolution (Chống N+1 Query):
- Hệ thống gom nhóm `target_id` theo loại đối tượng (`USER`, `PRODUCT`, `ORDER`) và thực hiện truy vấn hàng loạt (batch queries in O(1) query count), không thực hiện một truy vấn riêng cho mỗi báo cáo.

#### Response: `200 OK` (`AdminReportListResponse`)
```json
{
  "items": [
    {
      "report_id": 1,
      "reporter_id": 10,
      "reporter": {
        "user_id": 10,
        "full_name": "Nguyễn Văn A",
        "avatar_url": "https://..."
      },
      "target_type": "PRODUCT",
      "target_id": 123,
      "target_available": true,
      "target_summary": {
        "product_id": 123,
        "title": "Giáo trình Mạng",
        "seller": {
          "user_id": 20,
          "full_name": "Lê B"
        },
        "status": "AVAILABLE",
        "is_deleted": false
      },
      "reason": "FAKE_ITEM",
      "description": "Nội dung vi phạm",
      "status": "OPEN",
      "handled_by": null,
      "handler": null,
      "handled_at": null,
      "created_at": "2026-09-17T02:00:00"
    }
  ],
  "next_cursor": "MjAyNi0wOS0xN1QwMjowMDowMHwxf...",
  "has_more": false
}
```

*Lưu ý bảo mật riêng tư*: `ReporterSummary` chỉ chứa `user_id`, `full_name`, `avatar_url`. Tuyệt đối không để lộ `email`, số điện thoại, tài khoản ngân hàng hay danh tính Firebase.

### 21.3. Endpoint: Xem chi tiết báo cáo (`GET /api/v1/admin/reports/{report_id}`)

- **Method**: `GET`
- **Path**: `/api/v1/admin/reports/{report_id}`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)

#### Response: `200 OK` (`AdminReportResponse`)
- Trả về đối tượng báo cáo kèm tóm tắt đối tượng `target_summary` và chỉ dấu `target_available`.
- **Target survival invariant**: Nếu đối tượng bị báo cáo đã bị xóa (`is_deleted=True` hoặc không còn trong DB), tài khoản bị khóa (`BANNED`), hoặc tin bị ẩn (`HIDDEN`), báo cáo bền vững vẫn trả về `200 OK` với `target_available: false` (nếu không còn dòng trong DB) hoặc `target_available: true` kèm trạng thái thực tế (`is_deleted: true` hoặc `status: BANNED/HIDDEN`). Tuyệt đối không trả về 404 cho báo cáo vì đối tượng thay đổi.

### 21.4. Endpoint: Cập nhật trạng thái xử lý (`PATCH /api/v1/admin/reports/{report_id}/status`)

- **Method**: `PATCH`
- **Path**: `/api/v1/admin/reports/{report_id}/status`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)

#### Request Body (`AdminReportStatusUpdateRequest`)
Schema cấu hình `extra = "forbid"`, cấm nhận `handled_by` hay `handled_at` từ client (trả về `422` nếu gửi kèm).
```json
{
  "status": "REVIEWING"
}
```

#### Ma trận chuyển trạng thái hợp lệ (State Machine):
- `OPEN` → `REVIEWING`: Gán `handled_by = current_admin.user_id`, `handled_at = NULL`.
- `OPEN` → `RESOLVED`: Gán `handled_by = current_admin.user_id`, `handled_at = server_time (naive UTC)`.
- `OPEN` → `REJECTED`: Gán `handled_by = current_admin.user_id`, `handled_at = server_time (naive UTC)`.
- `REVIEWING` → `RESOLVED`: Gán `handled_by = current_admin.user_id`, `handled_at = server_time (naive UTC)`.
- `REVIEWING` → `REJECTED`: Gán `handled_by = current_admin.user_id`, `handled_at = server_time (naive UTC)`.
- Trạng thái kết thúc: `RESOLVED` và `REJECTED` là bất biến (terminal), không cho phép chuyển tiếp về bất kỳ trạng thái nào khác.
- Chuyển trạng thái trùng lặp (`OPEN` → `OPEN`, `REVIEWING` → `REVIEWING`) hoặc chuyển trạng thái không hợp lệ bị từ chối với HTTP `409 Conflict`.

#### Concurrency & Row-Locking:
- Giao dịch thực hiện khoá bản ghi `reports` qua cú pháp `SELECT ... FOR UPDATE`.
- Bên trong giao dịch: khoá bản ghi → đọc trạng thái thực tế → kiểm tra hợp lệ → cập nhật `status`, `handled_by`, `handled_at` → commit.
- Nếu hai quản trị viên cùng thao tác trên một báo cáo, thao tác thứ hai sau khi chờ giải phóng khoá sẽ quan sát trạng thái kết thúc và nhận mã lỗi có kiểm soát `409 Conflict`.

#### Phạm vi hiệu ứng (Scope Boundaries):
- `RESOLVED` chỉ biểu thị "Quản trị viên đã xử lý xong khiếu nại/báo cáo này".
- Tuyệt đối KHÔNG tự ý khoá tài khoản User, ẩn Product, huỷ Order, hay thay đổi dữ liệu miền trong Phase 8G-A.
- Tạo chính xác 0 dòng `Notification` và 0 sự kiện realtime WebSocket.

---

## 22. Phase 8G-A.1 — Report Moderation UX Polish & Image Evidence (Minh chứng ảnh báo cáo)

Tài liệu này định nghĩa hợp đồng API cho việc đính kèm minh chứng hình ảnh vào báo cáo vi phạm, tối ưu DTO hàng đợi/chi tiết, và cơ chế phân phối ảnh an toàn (authenticated secure streaming) cho quản trị viên.

### 22.1. Endpoint: Tải lên minh chứng báo cáo (`POST /api/v1/reports/{report_id}/evidence`)

- **Method**: `POST`
- **Path**: `/api/v1/reports/{report_id}/evidence`
- **Authentication**: Bắt buộc (Bearer JWT)
- **Content-Type**: `multipart/form-data`

#### Form Parameters:
- `files`: Danh sách tệp hình ảnh và video đính kèm (multipart file list).

#### Quy tắc xác thực & Giới hạn:
1. **Bảo mật danh tính & Riêng tư (Non-leaking 404)**:
   - Nếu báo cáo không tồn tại HOẶC `report.reporter_id != current_user.user_id`: trả về `404 Not Found` (`{"detail": "Báo cáo không tồn tại."}`).
   - Tuyệt đối không trả về `403 Forbidden` nhằm tránh làm lộ sự tồn tại của báo cáo người khác tạo.
2. **Trạng thái hợp lệ**:
   - Báo cáo phải ở trạng thái `OPEN` hoặc `REVIEWING`.
   - Báo cáo đã kết thúc (`RESOLVED` hoặc `REJECTED`) bị từ chối với HTTP `409 Conflict` (`{"detail": "Không thể thêm ảnh minh chứng cho báo cáo đã ở trạng thái kết thúc '{status}'."}`).
3. **Giới hạn số lượng (Evidence Invariants)**:
   - **Ảnh**: Tối đa **5 ảnh** trên mỗi báo cáo. Vượt quá trả về HTTP `409 Conflict` (nếu đã có) hoặc `422 Unprocessable Content` (nếu gửi > 5 trong request).
   - **Video**: Tối đa **1 video** trên mỗi báo cáo. Vượt quá trả về HTTP `409 Conflict` (nếu đã có video) hoặc `422 Unprocessable Content` (nếu gửi > 1 video).
4. **Định dạng & Dung lượng (Evidence Media Policy)**:
   - **Ảnh (Images)**:
     - Tối đa: 5 ảnh
     - Dung lượng tối đa: 10 MB (10,485,760 bytes) mỗi ảnh
     - Định dạng cho phép: JPEG (`image/jpeg`), PNG (`image/png`), WebP (`image/webp`)
   - **Video**:
     - Tối đa: 1 video
     - Dung lượng tối đa: 30 MB (31,457,280 bytes)
     - Thời lượng tối đa: 60 giây (xác thực từ metadata Cloudinary có thẩm quyền)
     - Định dạng cho phép: MP4 (`video/mp4`), WebM (`video/webm`), QuickTime MOV (`video/quicktime`)
   - Xác thực chữ ký nhị phân (magic bytes header) trước khi upload lên Cloudinary. Tệp sai định dạng hoặc vượt dung lượng bị từ chối ngay với `422 Unprocessable Content` mà không kích hoạt bất kỳ lệnh tải lên Cloudinary nào.
   - Nếu video tải lên có thời lượng > 60 giây theo Cloudinary metadata: backend hủy/xóa ngay tài nguyên trên Cloudinary (compensation cleanup) và trả về `422 Unprocessable Content` (`{"detail": "Video chỉ được dài tối đa 60 giây."}`).

#### Quy trình tương tranh an toàn & Bù trừ (Race-Safe 2-Phase Upload):
1. **Phase 1 (External Upload)**: Tải các tệp hợp lệ lên Cloudinary theo đúng `resource_type` (`image` hoặc `video`), lưu trữ danh sách `(public_id, resource_type)` đã tạo. Không giữ khóa dòng database trong suốt thời gian kết nối mạng Cloudinary.
2. **Phase 2 (Locked DB Persistence)**: Mở transaction ghi DB, thực hiện khóa dòng `Report` qua `SELECT ... FOR UPDATE` (với `populate_existing=True`).
3. **Re-check under lock**: Xác minh báo cáo vẫn tồn tại, thuộc quyền sở hữu, chưa bị đóng (`OPEN`/`REVIEWING`), tổng số ảnh <= 5 và tổng số video <= 1.
4. **Compensation Cleanup**: Nếu re-check thất bại hoặc commit DB gặp lỗi:
   - Rollback DB transaction (0 dòng `report_attachments` được lưu).
   - Thực hiện xóa bù trừ (best-effort delete) toàn bộ asset Cloudinary vừa tạo trong request đó qua `destroy_asset(pid, resource_type=resource_type)`.
   - Trả về mã lỗi 409 Conflict tương ứng.

#### Response: `201 Created` (`ReportEvidenceUploadResponse`)
```json
{
  "report_id": 1,
  "attachments": [
    {
      "attachment_id": 10,
      "original_name": "bang_chung_1.mp4",
      "mime_type": "video/mp4",
      "media_type": "VIDEO",
      "size_bytes": 15485760,
      "created_at": "2026-09-20T03:30:00"
    }
  ]
}
```
*Lưu ý bảo mật*: DTO tuyệt đối không bao giờ để lộ Cloudinary raw URL hoặc `storage_key`.

---

### 22.2. Tách biệt DTO Hàng đợi & Chi tiết (Compact Queue vs Detail DTO)

#### 1. Hàng đợi kiểm duyệt (`GET /api/v1/admin/reports`):
- Trả về `AdminReportResponse` chỉ chứa trường số lượng tổng: `evidence_count: int = 0` (tổng ảnh + video).
- Không nhúng mảng `evidence` metadata vào danh sách hàng đợi nhằm giữ payload nhỏ gọn và tối ưu tốc độ mạng di động.
- Tính toán số lượng minh chứng bằng truy vấn gộp đơn (`batch_count_attachments` qua `GROUP BY report_id`), đảm bảo $O(1)$ query count cho toàn trang (không có N+1 query).

#### 2. Chi tiết báo cáo (`GET /api/v1/admin/reports/{report_id}` & `PATCH /api/v1/admin/reports/{report_id}/status`):
- Trả về `AdminReportDetailResponse` kế thừa `AdminReportResponse` và bổ sung danh sách metadata minh chứng (kèm trường `media_type`: `"IMAGE"` | `"VIDEO"`):
```json
{
  "report_id": 1,
  "reporter_id": 10,
  "reporter": {
    "user_id": 10,
    "full_name": "Nguyễn Văn A",
    "avatar_url": "https://..."
  },
  "target_type": "PRODUCT",
  "target_id": 123,
  "target_available": true,
  "target_summary": { ... },
  "reason": "FAKE_ITEM",
  "description": "Mô tả chi tiết",
  "status": "OPEN",
  "handled_by": null,
  "handler": null,
  "handled_at": null,
  "created_at": "2026-09-17T02:00:00",
  "evidence_count": 2,
  "evidence": [
    {
      "attachment_id": 10,
      "original_name": "bang_chung_1.jpg",
      "mime_type": "image/jpeg",
      "media_type": "IMAGE",
      "size_bytes": 1048576,
      "created_at": "2026-09-17T03:30:00"
    },
    {
      "attachment_id": 11,
      "original_name": "bang_chung_2.mp4",
      "mime_type": "video/mp4",
      "media_type": "VIDEO",
      "size_bytes": 12524288,
      "created_at": "2026-09-20T03:30:00"
    }
  ]
}
```

---

### 22.3. Endpoint: Phân phối minh chứng bảo mật (`GET /api/v1/admin/reports/{report_id}/evidence/{attachment_id}`)

- **Method**: `GET`
- **Path**: `/api/v1/admin/reports/{report_id}/evidence/{attachment_id}`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`, hỗ trợ `Authorization: Bearer <token>` hoặc `?token=<token>` query param cho HTML5 media tag).
- **Query Parameters**:
  - `variant`: `Literal["thumbnail", "full"]` (mặc định: `thumbnail` cho ảnh).
  - `token`: Optional JWT token cho các trường hợp trình duyệt yêu cầu media stream trực tiếp qua thẻ `<video>`/`<img>`.

#### Cơ chế bảo vệ SSRF, HTTP Range & Secure Streaming:
- Backend xác thực quyền `ADMIN` và kiểm tra attachment thuộc đúng `report_id` tương ứng (trả về 404 nếu không khớp).
- Tệp Video: Hỗ trợ chuẩn HTTP Range requests (`Accept-Ranges: bytes`, `Content-Range`, mã trạng thái `206 Partial Content`). Chuyển tiếp dải byte an toàn từ upstream mà không buffer toàn bộ tệp 30MB vào bộ nhớ máy chủ. Stream chunk bounded 64KB.
- Tệp Ảnh: Giữ nguyên cơ chế thumbnail transform và full-image streaming.
- Kiểm tra tính tin cậy của URL lưu trữ Cloudinary:
  - Scheme bắt buộc là `https`.
  - Hostname bắt buộc là `res.cloudinary.com`.
  - Đường dẫn tài nguyên bắt buộc thuộc namespace cloud name của dự án.
- Không nhận URL từ client; chỉ sinh URL từ `storage_key` nội bộ trong CSDL.
- Sử dụng HTTP streaming client với timeout kết nối 10 giây và timeout đọc 20 giây.
- Header phản hồi:
  - `Content-Type`: Lấy từ `attachment.mime_type` chuẩn hóa trong CSDL.
  - Không kèm theo bất kỳ credential hay token nhạy cảm nào trong URL.

---

## 23. Phase 8G-B1 — Admin User Account Enforcement & Moderation Semantics

### 23.1. Moderation Semantics & Workflow Layer
- **Trạng thái CSDL**: Giữ nguyên enum DB `OPEN`, `REVIEWING`, `RESOLVED`, `REJECTED` (không sửa đổi enum DB).
- **Tầng trừu tượng tiến trình (Workflow Abstraction)**:
  - `workflow_state`: `'OPEN' | 'REVIEWING' | 'COMPLETED'`
  - `conclusion`: `'SUPPORTED' | 'INSUFFICIENT_EVIDENCE' | null`
    - Báo cáo `RESOLVED` ánh xạ sang `conclusion = 'SUPPORTED'`.
    - Báo cáo `REJECTED` ánh xạ sang `conclusion = 'INSUFFICIENT_EVIDENCE'`.
    - Báo cáo `OPEN`, `REVIEWING` có `conclusion = null`.
- **Bộ lọc hàng đợi mở rộng (`GET /api/v1/admin/reports`)**:
  - Hỗ trợ tham số `workflow: Optional[ReportWorkflowState]` (`OPEN`, `REVIEWING`, `COMPLETED`).
  - Hỗ trợ tham số `conclusion: Optional[ReportConclusion]` (`SUPPORTED`, `INSUFFICIENT_EVIDENCE`).
  - Xác thực kết hợp: Từ chối với mã lỗi `422 Unprocessable Content` nếu truyền `conclusion` khi `workflow` khác `COMPLETED` (hoặc khi `status` khác `RESOLVED`/`REJECTED`).

### 23.2. Endpoint: Thực thi chế tài tài khoản (`POST /api/v1/admin/reports/{report_id}/enforce`)
- **Method**: `POST`
- **Path**: `/api/v1/admin/reports/{report_id}/enforce`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)
- **Request Body** (`AdminEnforcementRequest`):
  ```json
  {
    "action": "USER_BAN"
  }
  ```
  Giá trị hợp lệ: `'USER_BAN'`, `'USER_UNBAN'`.
- **Hành vi**:
  - `USER_BAN`:
    - Chuyển `User.status = 'BANNED'`.
    - Tự động đánh dấu `Report.status = 'RESOLVED'` (nếu báo cáo chưa kết thúc).
    - Ghi nhận `ModerationAction(action_type='USER_BAN')`.
    - Thu hồi truy cập realtime: ngắt kết nối WebSocket `/ws/me` với close code 1008, phát thông điệp Redis `_DISCONNECT` / `ACCOUNT_ACCESS_REVOKED`.
  - `USER_UNBAN`:
    - Chuyển `User.status = 'ACTIVE'`.
    - Giữ nguyên trạng thái báo cáo.
    - Ghi nhận `ModerationAction(action_type='USER_UNBAN')`.
- **Thứ tự khóa bắt buộc (Canonical Lock Order)**:
  1. `Report FOR UPDATE`
  2. `User FOR UPDATE`
  Giảm thiểu triệt để nguy cơ deadlock trên toàn bộ luồng BAN và UNBAN tương tranh.
- **Quy tắc an toàn**:
  - Báo cáo mục tiêu phải là loại `USER` (400 Bad Request nếu không phải).
  - Không cho phép tự khóa chính mình (400 Bad Request).
  - Không cho phép khóa tài khoản có vai trò `ADMIN` (403 Forbidden).
  - Tính lũy đẳng & phát hiện xung đột: 409 Conflict nếu user đã ở trạng thái mục tiêu, hoặc báo cáo đã ở trạng thái kết thúc khi thực hiện USER_BAN.
- **Response**: `200 OK` (`AdminReportDetailResponse`).

### 23.3. Endpoint: Kiểm tra quyền truy cập tài khoản (`GET /api/v1/users/me/access-status`)
- **Method**: `GET`
- **Path**: `/api/v1/users/me/access-status`
- **Authentication**: Bắt buộc (Bearer JWT qua `get_current_user`, không chặn tài khoản `BANNED` hoặc `INACTIVE`).
- **Response**: `200 OK` (`UserAccessStatusResponse`)
  ```json
  {
    "user_id": 123,
    "status": "ACTIVE",
    "role": "STUDENT"
  }
  ```
- **Mục đích**: Cung cấp endpoint cho trang `/account-restricted` và client kiểm tra trạng thái hoạt động thực tế thời gian thực mà không bị chặn 403.

---

## 24. Phase 8G-B2 — Admin Product Enforcement & Simplified Moderation UX

### 24.1. Product Moderation Semantics & Separation of Concerns
- **Trạng thái kinh doanh (`Product.status`)**: Thuộc quyền sở hữu của người bán (`AVAILABLE`, `HIDDEN`, `SOLD_OUT`). Không bị ghi đè hay thay đổi khi Quản trị viên can thiệp kiểm duyệt.
- **Trạng thái kiểm duyệt (`Product.moderation_status`)**: Thuộc thẩm quyền của nền tảng (`CLEAR`, `BLOCKED`).
  - `CLEAR`: Tin đăng hợp lệ, tuân thủ chính sách cộng đồng.
  - `BLOCKED`: Tin đăng bị Quản trị viên ẩn do vi phạm chính sách marketplace.
- **Strict Typing trên DTO phản hồi**:
  - `ProductDetailResponse`, `SellerProductResponse`, và `ProductTargetSummary` sử dụng trường bắt buộc `moderation_status: ProductModerationStatus`. Tuyệt đối không dùng `str = "CLEAR"` làm giá trị mặc định để tránh che giấu lỗi mapper.

### 24.2. Bộ lọc hàng đợi Quản trị viên (`queue_state`)
- **Tham số truy vấn**: `GET /api/v1/admin/reports?queue_state=NEEDS_ACTION|COMPLETED`
  - `NEEDS_ACTION`: Lọc các báo cáo có `status IN (OPEN, REVIEWING)`.
  - `COMPLETED`: Lọc các báo cáo có `status IN (RESOLVED, REJECTED)`.
- **Quy tắc bất biến**: `NEEDS_ACTION` là một bộ lọc truy vấn danh sách (Query Filter), **KHÔNG** phải là một trạng thái luồng xử lý đơn lẻ của một báo cáo. Trường `workflow_state` của từng báo cáo chỉ có thể là `OPEN`, `REVIEWING`, hoặc `COMPLETED`. DTO không bao giờ trả về `workflow_state = NEEDS_ACTION`.
- Không cho phép kết hợp `queue_state` đồng thời với các tham số cũ (`status`, `workflow`, `conclusion`) — trả về `422 Unprocessable Content`.

### 24.3. Endpoint: Thực thi chế tài tin đăng (`POST /api/v1/admin/reports/{report_id}/enforcement`)
- **Method**: `POST`
- **Path**: `/api/v1/admin/reports/{report_id}/enforcement` (hỗ trợ alias `/enforce`)
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)
- **Request Body** (`AdminEnforcementRequest`):
  ```json
  {
    "action": "PRODUCT_HIDE"
  }
  ```
  Hành động hỗ trợ: `'USER_BAN'`, `'USER_UNBAN'`, `'PRODUCT_HIDE'`, `'PRODUCT_RESTORE'`.
- **Thứ tự khóa nguyên tử (Canonical Lock Order)**:
  1. `Report FOR UPDATE`
  2. `Product FOR UPDATE` (kể cả tin đã soft-delete để kiểm tra an toàn)
  3. `Auction FOR UPDATE` (nếu có phiên `SCHEDULED` hoặc `ACTIVE` liên kết với tin)
- **Hành vi `PRODUCT_HIDE`**:
  - Đặt `Product.moderation_status = 'BLOCKED'`.
  - Nếu tồn tại phiên đấu giá `SCHEDULED` hoặc `ACTIVE`:
    - Chuyển `Auction.status = 'CANCELLED'`.
    - Đặt `winner_id = NULL`, `final_price = NULL`, `winner_checkout_deadline = NULL`.
    - Chuyển `Product.listing_type = 'FIXED_PRICE'`.
    - Bảo lưu toàn bộ các lượt đặt giá (`AuctionBid`) làm dữ liệu lịch sử bất biến.
  - Thêm bản ghi audit `ModerationAction(action_type='PRODUCT_HIDE')`.
  - Đánh dấu `Report.status = 'RESOLVED'`, cập nhật `handled_by` và `handled_at`.
  - Thực hiện trong **một commit CSDL duy nhất**.
  - **Sau khi commit thành công**: Phân phối sự kiện realtime `AUCTION_CANCELLED` qua kênh WebSocket của phiên đấu giá (best-effort).
- **Hành vi `PRODUCT_RESTORE`**:
  - Chỉ cho phép khôi phục nếu báo cáo hiện tại chính là nguồn tạo ra lệnh `PRODUCT_HIDE` đang có hiệu lực.
  - Đặt `Product.moderation_status = 'CLEAR'`.
  - Thêm bản ghi audit `ModerationAction(action_type='PRODUCT_RESTORE')`.
  - **Bảo toàn tính bất biến**: Tuyệt đối không phục hồi bất kỳ phiên đấu giá nào đã bị hủy (`CANCELLED -> ACTIVE` bị nghiêm cấm). Người bán có thể tạo vòng đấu giá mới nếu sản phẩm đủ điều kiện thông thường.
- **Quy tắc phân định nghiệp vụ**:
  - Quyết định báo cáo đơn thuần ("Ghi nhận vi phạm" / "Bỏ qua báo cáo") được điều hướng qua `PATCH /admin/reports/{id}/status` (`RESOLVED` / `REJECTED`).
  - Endpoint `/enforcement` chỉ dùng cho hành vi chế tài thực thể mục tiêu (`USER_BAN`, `USER_UNBAN`, `PRODUCT_HIDE`, `PRODUCT_RESTORE`).

### 24.4. Cổng kiểm duyệt khám phá công khai & Thương mại
- **Khám phá công khai**: Mọi truy vấn công khai (`GET /api/v1/products`, tìm kiếm FTS, lọc danh mục, trang người bán công khai) đều lọc `moderation_status == 'CLEAR'`.
- **Chi tiết sản phẩm (`GET /api/v1/products/{id}`)**:
  - Người mua / khách vãng lai: Nhận `404 Not Found` đối với tin đăng `BLOCKED`.
  - Người bán sở hữu tin: Nhận `200 OK` với thông tin chi tiết kèm `moderation_status = 'BLOCKED'` để theo dõi và quản lý.
- **Danh sách tin của người bán (`GET /api/v1/products/me`)**: Vẫn hiển thị các tin `BLOCKED` với nhãn `Đã bị quản trị viên ẩn`. Người bán không thể sửa `moderation_status` thông qua các endpoint cập nhật sản phẩm.
- **Yêu thích (`Favorites`)**:
  - Danh sách tin yêu thích (`GET /api/v1/favorites`) và danh sách ID yêu thích (`GET /api/v1/favorites/ids`) loại trừ các tin `BLOCKED`. Bản ghi `Favorite` trong CSDL được bảo lưu. Khi sản phẩm được gỡ ẩn (`PRODUCT_RESTORE`), tin đăng tự động xuất hiện lại trong danh sách yêu thích.
- **Chặn giao dịch mới**:
  - Đặt hàng trực tiếp (`POST /api/v1/orders`): Từ chối với `404 Not Found` nếu sản phẩm bị `BLOCKED`.
  - Tạo đấu giá (`POST /api/v1/auctions`): Từ chối với `400 Bad Request`.
  - Đặt giá (`POST /api/v1/auctions/{id}/bids`): Từ chối với `400 Bad Request`.
  - Thanh toán thắng đấu giá (`POST /api/v1/auctions/{id}/checkout`): Từ chối với `400 Bad Request`.
- **Bảo toàn đơn hàng đã tạo**: Các đơn hàng trực tiếp hoặc phiên đấu giá đã kết thúc trước khi tin đăng bị ẩn vẫn giữ nguyên tính hợp lệ kinh doanh và không bị hủy.

---

## 25. Pre-B3 — Message Reply & Price Input Hardening

### 25.1. Message Reply API (`POST /api/v1/conversations/{id}/messages`)
- **Method**: `POST`
- **Path**: `/api/v1/conversations/{conversation_id}/messages`
- **Content-Type**: `multipart/form-data` hoặc `application/json`
- **Payload additions**:
  - `reply_to_message_id`: `int | None` (tùy chọn) — ID của tin nhắn được trả lời.
- **Quy tắc an toàn bảo mật & toàn vẹn dữ liệu (Privacy-Safe & Integrity Rules)**:
  1. **Bảo mật quyền riêng tư giữa các cuộc trò chuyện (Cross-Conversation Privacy)**:
     - Nếu `reply_to_message_id` không tồn tại HOẶC tồn tại nhưng thuộc về một cuộc hội thoại khác / không thể truy cập bởi người gửi hiện tại:
     - **BẮT BUỘC** trả về cùng mã lỗi HTTP `404 Not Found` với thông điệp chung:
       ```json
       {
         "detail": "Tin nhắn được trả lời không tồn tại hoặc không thể truy cập."
       }
       ```
     - Tuyệt đối không phân biệt giữa "tin nhắn không tồn tại" và "tin nhắn thuộc hội thoại khác" để triệt tiêu hoàn toàn nguy cơ rò rỉ sự tồn tại của message ID riêng tư của người dùng khác.
  2. **Chặn trả lời tin nhắn hệ thống (SYSTEM Message)**:
     - Trả về HTTP `400 Bad Request` (`{"detail": "Không thể trả lời tin nhắn hệ thống."}`) vì tin nhắn hệ thống đã hiển thị công khai trong hội thoại và không có ngữ cảnh phản hồi hội thoại thông thường.
  3. **Chặn tạo mới reply vào tin nhắn đã bị xóa (`is_deleted = True`)**:
     - Trả về HTTP `400 Bad Request` (`{"detail": "Không thể trả lời tin nhắn đã bị xóa."}`).
  4. **Tombstone an toàn khi tin nhắn gốc bị xóa về sau**:
     - Nếu tin nhắn A được reply bởi tin nhắn B, sau đó A bị xóa (`is_deleted = True`), tin nhắn B vẫn giữ nguyên tính hợp lệ và trường `reply_to` hiển thị tombstone an toàn:
       ```json
       {
         "preview": "Tin nhắn không còn khả dụng"
       }
       ```
     - Tuyệt đối không để lộ nội dung gốc của tin nhắn đã xóa.

### 25.2. Reply DTO & Query Efficiency
- **DTO phản hồi (`MessageResponse`)**:
  - Bổ sung trường `reply_to: ReplyMessageSummary | null`.
  - Cấu trúc `ReplyMessageSummary`:
    ```json
    {
      "message_id": 123,
      "sender_id": 45,
      "sender_name": "Nguyen Van A",
      "message_type": "TEXT",
      "preview": "Nội dung tin nhắn trích dẫn (tối đa 120 ký tự)..."
    }
    ```
- **Builder tập trung (Single Source of Truth)**:
  - Hàm `build_reply_summary(message: Message) -> ReplyMessageSummary | None` chuẩn hóa logic tạo preview:
    - Tin nhắn đã xóa (`is_deleted = True`): `"Tin nhắn không còn khả dụng"`.
    - `TEXT`: Cắt tối đa 120 ký tự, chuẩn hóa khoảng trắng an toàn unicode.
    - Media / Cards: Sử dụng chuỗi mô tả đại diện an toàn không phát sinh query phụ (`IMAGE` -> `"Hình ảnh"`, `FILE` -> `"Tệp đính kèm"`, `PRODUCT_CARD` -> `"Sản phẩm"`, `ORDER_CARD` -> `"Đơn hàng"`, `AUDIO` -> `"Tin nhắn thoại"`, `VIDEO` -> `"Video"`).
- **Chống N+1 Query (Query Efficiency)**:
  - Repository nạp tin nhắn theo trang với eager loading tường minh: `selectinload(Message.reply_to).selectinload(Message.sender)`.
  - Không phát sinh query phụ cho từng reply attachments/cards/products.
- **Realtime WebSocket Semantics**:
  - Giữ nguyên kiến trúc thông báo nhẹ (`MESSAGE_CREATED` event) kích hoạt refetch REST để đồng bộ hóa `MessageResponse` có cấu trúc quote đầy đủ. Không nhân đôi cấu trúc DTO sang WebSocket payload.

### 25.3. Product Price Hardening
- **Authoritative Backend Validation**:
  - Áp dụng trên cả `ProductCreate` và `ProductUpdate` schemas qua validator chuẩn hóa `validate_product_price`:
    - Kiểu dữ liệu: Số nguyên VND (`int`).
    - Miền giá trị hợp lệ: `0 <= price <= 50_000_000`.
    - Chặn số âm, số thập phân lẻ, và giá vượt quá 50 triệu VND (HTTP `422 Unprocessable Content`).
- **Frontend Lexical Input Hardening**:
  - Không cho phép nhập các ký tự khoa học `e`, `E`, `+`, `-`, hoặc dấu chấm thập phân `.`, phẩy `,` trên các trường nhập giá sản phẩm và bộ lọc.
  - Từ chối toàn bộ chuỗi dán (paste) không hợp lệ, không tự ý sanitize biến đổi giá trị sai lệch (ví dụ `1e18` tuyệt đối không bị chuyển đổi thành `118`, `10.5` không bị chuyển đổi thành `105`).

---

## 26. Phase 8G-B3 — Moderation Workflow, Subject History & Capability Restrictions

### 26.1. Subject Report History API (`GET /api/v1/admin/users/{user_id}/report-history`)
- **Method**: `GET`
- **Path**: `/api/v1/admin/users/{user_id}/report-history`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)
- **Query Parameters**:
  - `cursor`: `int | None` — Cursor phân trang theo `report_id` giảm dần.
  - `limit`: `int` (mặc định 5, tối đa 20).
  - `exclude_report_id`: `int | None` — ID báo cáo hiện tại để loại trừ khỏi lịch sử đối soát.
- **Response** (`SubjectReportHistoryResponse`):
  ```json
  {
    "items": [
      {
        "report_id": 105,
        "target_type": "PRODUCT",
        "reason": "SCAM",
        "description": "Nghi vấn lừa đảo cọc",
        "status": "RESOLVED",
        "conclusion": "SUPPORTED",
        "evidence_count": 2,
        "created_at": "2026-09-20T10:00:00Z",
        "enforcement_action": {
          "moderation_action_id": 42,
          "action_type": "PRODUCT_HIDE",
          "created_at": "2026-09-20T10:15:00Z"
        }
      }
    ],
    "total_count": 3,
    "next_cursor": null,
    "has_more": false
  }
  ```
- **Bảo mật**: Chỉ bao gồm các báo cáo liên quan đến đối tượng `user_id` (trực tiếp mục tiêu USER, hoặc sở hữu PRODUCT bị báo cáo, hoặc là người bán/người mua trong ORDER bị báo cáo).

### 26.2. User Access & Capability Status API (`GET /api/v1/users/me/access-status`)
- **Method**: `GET`
- **Path**: `/api/v1/users/me/access-status`
- **Authentication**: Bắt buộc Firebase Auth (hỗ trợ cả người dùng bị `BANNED`).
- **Response** (`UserAccessStatusResponse`):
  ```json
  {
    "user_id": 123,
    "status": "ACTIVE",
    "role": "STUDENT",
    "can_buy": true,
    "can_sell": false,
    "active_restrictions": [
      {
        "capability": "SELL",
        "expires_at": "2026-10-21T02:00:00Z"
      }
    ]
  }
  ```

### 26.3. Capability Enforcement & Reversal API (`POST /api/v1/admin/reports/{report_id}/enforcement`)
- **Method**: `POST`
- **Path**: `/api/v1/admin/reports/{report_id}/enforcement`
- **Authentication**: Bắt buộc (`role == 'ADMIN'`)
- **Actions hỗ trợ**:
  - `CAPABILITY_RESTRICT`:
    ```json
    {
      "action": "CAPABILITY_RESTRICT",
      "capabilities": ["BUY", "SELL"],
      "duration_days": 3
    }
    ```
    - `duration_days` (bắt buộc): Chỉ chấp nhận đúng 4 giá trị số nguyên: `1`, `3`, `7`, hoặc `14` ngày.
    - `duration_days = null` hoặc bị bỏ trống: Không hợp lệ (HTTP `422 Unprocessable Entity`). Mọi lệnh chế tài mới bắt buộc có thời hạn hữu hạn (finite-only). Lưu ý: database vật lý giữ `expires_at` nullable thuần túy để tương thích ngược đọc/thu hồi dữ liệu lịch sử cũ (legacy NULL compatibility), không phải hợp đồng tạo mới.
    - Thời điểm hết hạn `expires_at` được server tính toán độc lập: `starts_at (server time) + duration_days`. Client không gửi `expires_at`.
    - Hạn chế `SELL`: Tự động hủy nguyên tử các phiên đấu giá `ACTIVE`/`SCHEDULED` sang `CANCELLED`, chuyển `listing_type = FIXED_PRICE`, bảo lưu toàn bộ lượt bid.
  - `CAPABILITY_RESTORE`:
    ```json
    {
      "action": "CAPABILITY_RESTORE",
      "capabilities": ["BUY"]
    }
    ```
    - Thu hồi các dòng restriction có nguồn gốc từ báo cáo này.
- **Mã lỗi chuẩn hóa khi bị giới hạn quyền**:
  - HTTP `403 Forbidden`:
    ```json
    {
      "detail": {
        "code": "BUY_RESTRICTED",
        "message": "Tài khoản của bạn đang bị giới hạn quyền mua hàng."
      }
    }
    ```
  - HTTP `403 Forbidden`:
    ```json
    {
      "detail": {
        "code": "SELL_RESTRICTED",
        "message": "Tài khoản của bạn đang bị giới hạn quyền bán hàng."
      }
    }
    ```

---

## 13. Khoảnh khắc Cộng đồng (Community Moments)

Phân hệ đăng tải ảnh khoảnh khắc sinh viên di động (Mobile-first Community Moments) xoay vòng trên Hero trang chủ và quy trình kiểm duyệt trực tiếp bởi Admin.

### 13.1. Gửi ảnh khoảnh khắc cộng đồng (Student Moment Submission)

- **Method**: `POST`
- **Path**: `/api/v1/community-moments`
- **Authentication**: Bắt buộc (`Bearer <Firebase ID Token>`), tài khoản phải có trạng thái `ACTIVE`.
- **Content-Type**: `multipart/form-data`
- **Quy tắc Payload**:
  - Đúng **1 file ảnh duy nhất** trong form-data field `file`: Ảnh đã được cắt chuẩn tỉ lệ khung hình Hero **16:9** (tối đa 1600x900px, ngưỡng tối thiểu 320x180px) trên trình duyệt trước khi upload.
  - Định dạng: Chỉ chấp nhận `image/jpeg`, `image/png`, `image/webp` (xác thực magic-byte authoritative từ backend).
  - Dung lượng: Tối đa 10MB (10,485,760 bytes).
  - Trường `note`: Chuỗi ký tự lời nhắn khoảnh khắc (bắt buộc, 1..80 ký tự, single-line plain text, NFC normalized).
- **Ràng buộc Anti-Spam**:
  - Mỗi người dùng chỉ được có **tối đa 1 ảnh** ở trạng thái `PENDING`.
  - Kiểm tra và thực thi qua partial UNIQUE index: `uq_community_moments_user_pending`.

#### Response: `201 Created`
```json
{
  "moment_id": 42,
  "status": "PENDING",
  "message": "Khoảnh khắc của bạn đã được gửi và đang chờ quản trị viên duyệt."
}
```

#### Error Responses:
- `400 Bad Request` (`INVALID_IMAGE`): File rỗng, không phải ảnh JPEG/PNG/WebP hợp lệ, hoặc giả mạo extension.
- `401 Unauthorized`: Chưa đăng nhập hoặc token không hợp lệ.
- `403 Forbidden`: Người dùng bị `BANNED` hoặc `INACTIVE`.
- `409 Conflict` (`COMMUNITY_MOMENT_PENDING`): Người dùng đã có 1 ảnh đang ở trạng thái chờ duyệt.
  ```json
  {
    "detail": {
      "code": "COMMUNITY_MOMENT_PENDING",
      "message": "Bạn đang có 1 khoảnh khắc chờ duyệt. Vui lòng đợi quản trị viên xử lý trước khi gửi ảnh mới."
    }
  }
  ```
- `413 Request Entity Too Large` (`FILE_TOO_LARGE`): File vượt quá dung lượng tối đa 10MB.
- `422 Unprocessable Content`: Lời nhắn bị thiếu, rỗng, chứa ký tự xuống dòng, hoặc vượt quá 80 ký tự.

---

### 13.2. Lấy danh sách ảnh Hero công khai (Public Hero Moments)

- **Method**: `GET`
- **Path**: `/api/v1/community-moments/hero`
- **Authentication**: Không (Public Endpoint).
- **Quy tắc Nghiệp vụ**:
  - Trả về tối đa **5 ảnh** có trạng thái `APPROVED`.
  - Thứ tự: Sắp xếp theo `reviewed_at DESC, moment_id DESC` (ảnh vừa được duyệt mới nhất đứng đầu).
  - Bảo mật danh tính: Tuyệt đối không để lộ `uploader_id`, `storage_key`, `reviewed_by`.
  - URL ảnh: Đã qua bộ chuyển đổi responsive của Cloudinary chuẩn Hero (`f_auto,q_auto,w_1600`).
  - Khi hệ thống có 0 ảnh duyệt: Trả về danh sách rỗng `{"items": []}`. Frontend hiển thị banner CSS thương hiệu thuần 16:9 (không dùng ảnh tĩnh fallback).

#### Response: `200 OK`
```json
{
  "items": [
    {
      "moment_id": 42,
      "image_url": "https://res.cloudinary.com/ptit/image/upload/f_auto,q_auto,w_1600/student-marketplace/community-moments/abc123xyz.webp",
      "note": "Nhận được sách trước giờ lên lớp 😆",
      "approved_at": "2026-09-21T10:30:00"
    }
  ]
}
```

---

### 13.3. Danh sách hàng đợi duyệt của Admin (Admin Moderation Queue)

- **Method**: `GET`
- **Path**: `/api/v1/admin/community-moments`
- **Authentication**: Bắt buộc (`ADMIN` role).
- **Query Parameters**:
  - `status` (tùy chọn, chuỗi): `PENDING` | `APPROVED` (Mặc định: `PENDING`). Quản trị viên chỉ quản lý 2 hàng đợi: Chờ duyệt (`PENDING`) và Đang hiển thị (`APPROVED`).
  - `cursor` (tùy chọn, chuỗi): Con trỏ keyset pagination mã hóa Base64URL.
  - `limit` (tùy chọn, số nguyên): Mặc định `20`, tối đa `50`.

#### Response: `200 OK`
```json
{
  "items": [
    {
      "moment_id": 42,
      "image_url": "https://res.cloudinary.com/ptit/image/upload/f_auto,q_auto,w_1600/student-marketplace/community-moments/abc123xyz.webp",
      "storage_key": "student-marketplace/community-moments/abc123xyz",
      "mime_type": "image/webp",
      "size_bytes": 1420500,
      "status": "PENDING",
      "uploader": {
        "user_id": 15,
        "full_name": "Nguyễn Văn Sinh Viên",
        "email": "sv@ptit.edu.vn",
        "avatar_url": "https://..."
      },
      "reviewed_by": null,
      "reviewed_at": null,
      "created_at": "2026-09-21T09:15:00",
      "updated_at": "2026-09-21T09:15:00"
    }
  ],
  "next_cursor": "MjAyNi0wOS0yMVQwOToxNTowMC4wMDB8NDI=",
  "has_more": false
}
```

---

### 13.4. Chi tiết khoảnh khắc cho Admin (Admin Moment Detail)

- **Method**: `GET`
- **Path**: `/api/v1/admin/community-moments/{id}`
- **Authentication**: Bắt buộc (`ADMIN` role).
- **Response**: `200 OK` trả về chi tiết `AdminCommunityMomentItem` đầy đủ.

---

### 13.5. Phê duyệt khoảnh khắc (Admin Approve Moment)

- **Method**: `POST`
- **Path**: `/api/v1/admin/community-moments/{id}/approve`
- **Authentication**: Bắt buộc (`ADMIN` role).
- **Quy tắc Nghiệp vụ (Phase 8H-A.2 Bounded Hero Lifecycle)**:
  - Khóa toàn cục bằng PostgreSQL transactional advisory lock (`COMMUNITY_HERO_LOCK_NAMESPACE = "community_hero_lifecycle"`).
  - Khóa dòng PENDING bằng `SELECT ... FOR UPDATE`.
  - Chuyển `status` thành `APPROVED`, ghi nhận `reviewed_by = admin.user_id`, `reviewed_at = NOW()`.
  - Kiểm tra số lượng APPROVED hiện tại: Nếu vượt quá **5 ảnh**, hệ thống tự động cắt tỉa (prune) các bản ghi APPROVED cũ nhất (`reviewed_at ASC, moment_id ASC`) bằng cơ chế **Hard Delete** khỏi DB.
  - Commit DB transaction.
  - Dọn dẹp Cloudinary: Sau commit thành công, gọi `destroy_image` dọn dẹp các ảnh vừa bị prune (best-effort, không rollback DB nếu Cloudinary lỗi).

#### Response: `200 OK`
```json
{
  "moment_id": 42,
  "status": "APPROVED",
  "reviewed_by": 1,
  "reviewed_at": "2026-09-21T10:30:00"
}
```

---

### 13.6. Từ chối khoảnh khắc (Admin Reject Moment — Hard Delete)

- **Method**: `POST`
- **Path**: `/api/v1/admin/community-moments/{id}/reject`
- **Authentication**: Bắt buộc (`ADMIN` role).
- **Quy tắc Nghiệp vụ (Phase 8H-A.2 Bounded Lifecycle)**:
  - Khóa dòng PENDING bằng `SELECT ... FOR UPDATE`.
  - Thực hiện **Hard Delete**: Xóa bản ghi `community_moments` vĩnh viễn khỏi database.
  - Commit DB transaction (giải phóng slot PENDING cho sinh viên ngay lập tức).
  - Sau commit thành công, gọi `destroy_image(storage_key)` dọn dẹp asset trên Cloudinary theo cơ chế best-effort.
  - Không lưu trữ bản ghi `REJECTED` trong cơ sở dữ liệu.

#### Response: `200 OK`
```json
{
  "moment_id": 42,
  "status": "REJECTED",
  "message": "Đã từ chối và xóa khoảnh khắc thành công."
}
```

---

### 13.7. Gỡ khoảnh khắc khỏi Hero (Admin Delete Approved Moment — Hard Delete)

- **Method**: `DELETE`
- **Path**: `/api/v1/admin/community-moments/{id}`
- **Authentication**: Bắt buộc (`ADMIN` role).
- **Quy tắc Nghiệp vụ (Phase 8H-A.2)**:
  - Khóa toàn cục bằng PostgreSQL transactional advisory lock (`COMMUNITY_HERO_LOCK_NAMESPACE`).
  - Khóa dòng APPROVED bằng `SELECT ... FOR UPDATE`.
  - Thực hiện **Hard Delete**: Xóa bản ghi `community_moments` vĩnh viễn khỏi database.
  - Commit DB transaction.
  - Sau commit thành công, gọi `destroy_image(storage_key)` dọn dẹp asset trên Cloudinary theo cơ chế best-effort.

#### Response: `200 OK`
```json
{
  "moment_id": 42,
  "status": "DELETED",
  "message": "Đã gỡ khoảnh khắc khỏi Hero và xóa dữ liệu thành công."
}
```

---

## 14. Phản hồi website & Ủng hộ Chợ PTITers (Site Feedback & VietQR Support)

Tính năng thu thập phản hồi, góp ý và báo lỗi của sinh viên cho website Chợ PTITers theo mô hình issue board công khai ẩn danh, kèm minh chứng riêng tư (ảnh/video) và chức năng xóa vĩnh viễn (hard delete) cho cả tác giả và quản trị viên.

### 14.1. Gửi phản hồi / góp ý mới (Submit Feedback)
- **Method**: `POST`
- **Path**: `/api/v1/feedback`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Content-Type**: `multipart/form-data`
- **Form Data**:
  - `content`: string (bắt buộc, 5..500 ký tự, chuẩn hoá Unicode NFC, plain text, không chấp nhận ký tự điều khiển ngoại trừ xuống dòng).
  - `images`: file[] (tùy chọn, tối đa 3 ảnh JPEG, PNG, WebP, tối đa 10MB/ảnh).
  - `video`: file (tùy chọn, tối đa 1 video MP4, WebM, MOV, tối đa 30MB, thời lượng tối đa 60 giây).
- **Quy tắc nghiệp vụ**:
  - 1 người dùng có thể gửi **nhiều phản hồi** theo thời gian (không giới hạn 1 user = 1 feedback, không upsert).
  - Feedback là bất biến (immutable) sau khi tạo thành công.
  - Phản hồi xuất hiện ngay trên bảng tin công khai sau khi tạo thành công (không có bước tiền kiểm duyệt, không có PENDING/APPROVED/REJECTED, không có sao đánh giá).
  - Tệp minh chứng được tải lên Cloudinary có cơ chế bồi hoàn (compensation cleanup) nếu upload lỗi hoặc lưu DB thất bại.
- **Response**: `201 Created`
  ```json
  {
    "feedback_id": 1,
    "content": "Không thể bấm đặt giá khi bàn phím đang mở.",
    "created_at": "2026-09-21T21:04:00Z",
    "attachments": [
      {
        "attachment_id": 1,
        "kind": "IMAGE",
        "mime_type": "image/jpeg",
        "size_bytes": 102400,
        "duration_ms": null
      }
    ]
  }
  ```

---

### 14.2. Bảng tin phản hồi cộng đồng công khai (Public Community Feed)
- **Method**: `GET`
- **Path**: `/api/v1/feedback`
- **Auth**: Public (không bắt buộc)
- **Query Params**:
  - `limit`: Số lượng mỗi trang (1..50, mặc định 20).
  - `cursor`: Keyset pagination `created_at DESC, feedback_id DESC`.
- **Quy tắc bảo mật danh tính (Anonymity)**:
  - Chỉ trả về: `feedback_id`, `content`, `created_at`.
  - Tuyệt đối **KHÔNG** trả về: `user_id`, `full_name`, `avatar_url`, `email`, `phone`, thông tin xác thực, số lượng đính kèm, URL ảnh/video, `storage_key`, hay dữ liệu quản trị.
  - Tự động loại trừ phản hồi của người dùng bị khóa/không hoạt động (`BANNED`/`INACTIVE`).
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "feedback_id": 1,
        "content": "Không thể bấm đặt giá khi bàn phím đang mở.",
        "created_at": "2026-09-21T21:04:00Z"
      }
    ],
    "next_cursor": "MjAyNi0wOS0yMVQyMTowNDowMHwxfA==",
    "has_more": false
  }
  ```

---

### 14.3. Danh sách phản hồi của chính người dùng (Get My Feedbacks)
- **Method**: `GET`
- **Path**: `/api/v1/feedback/me`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Query Params**:
  - `limit`: Số lượng mỗi trang (1..50, mặc định 20).
  - `cursor`: Keyset pagination `created_at DESC, feedback_id DESC`.
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "feedback_id": 1,
        "content": "Không thể bấm đặt giá khi bàn phím đang mở.",
        "created_at": "2026-09-21T21:04:00Z",
        "attachments": [
          {
            "attachment_id": 1,
            "kind": "IMAGE",
            "mime_type": "image/jpeg",
            "size_bytes": 102400,
            "duration_ms": null
          }
        ]
      }
    ],
    "next_cursor": null,
    "has_more": false
  }
  ```

---

### 14.4. Người dùng xóa phản hồi của chính mình (Delete My Feedback)
- **Method**: `DELETE`
- **Path**: `/api/v1/feedback/{feedback_id}`
- **Auth**: Bắt buộc (`ACTIVE` user)
- **Quy tắc nghiệp vụ**:
  - Chỉ chủ sở hữu (`user_id == feedback.user_id`) mới được phép xóa.
  - Nếu không phải chủ sở hữu hoặc phản hồi không tồn tại: Trả về `404 Not Found` (privacy-safe, không làm lộ thông tin phản hồi của người khác).
  - Cơ chế Hard Delete: Khóa dòng FOR UPDATE, thu thập `storage_key`, xóa bản ghi `site_feedback` (tự động xóa cascade các dòng `site_feedback_attachments`), commit DB, sau đó dọn dẹp Cloudinary media theo chính sách best-effort. Lỗi dọn dẹp Cloudinary được ghi log và không rollback DB.
- **Response**: `204 No Content`

---

### 14.5. Thông tin người phát triển & Hỗ trợ VietQR (Creator Support Info)
- **Method**: `GET`
- **Path**: `/api/v1/feedback/support`
- **Auth**: Public (không bắt buộc)
- **Quy tắc**:
  - Đọc tài khoản creator qua cấu hình nội bộ cố định `COMMUNITY_CREATOR_USER_ID = 10` (tài khoản verified `thinhconngua@gmail.com`).
  - Trả về thông tin an toàn: `user_id`, `full_name`, `avatar_url`, `profile_path = "/users/10"`. Tuyệt đối không để lộ email.
  - Mã VietQR là tài sản ảnh tĩnh cố định (`/support/nguyen-khac-thinh-vietqr.png`), không sinh động qua API bên thứ ba ở runtime. Thông điệp hỗ trợ: `"Quan trọng là tấm lòng 💛"`.
- **Response**: `200 OK`
  ```json
  {
    "creator": {
      "user_id": 10,
      "full_name": "Nguyễn Khắc Thịnh - Admin1",
      "avatar_url": "https://...",
      "title": "Người phát triển Chợ PTITers"
    },
    "profile_path": "/users/10",
    "fixed_qr_url": "/support/nguyen-khac-thinh-vietqr.png",
    "support_message": "Quan trọng là tấm lòng 💛"
  }
  ```

---

### 14.6. Danh sách Feedback dành cho Quản trị viên (Admin Feedback List)
- **Method**: `GET`
- **Path**: `/api/v1/admin/feedback`
- **Auth**: Bắt buộc (`ADMIN` role)
- **Query Params**:
  - `limit`: Số lượng mỗi trang (1..50, mặc định 20).
  - `cursor`: Keyset pagination `created_at DESC, feedback_id DESC`.
- **Quy tắc**:
  - Không phân chia tab kiểm duyệt (không có PENDING/APPROVED/REJECTED).
  - Sắp xếp mới nhất trước (`created_at DESC, feedback_id DESC`).
  - Trả về danh tính người gửi an toàn (`user_id`, `full_name`, `avatar_url`), nội dung, thời gian và số lượng tệp minh chứng (`image_count`, `video_count`).
- **Response**: `200 OK`
  ```json
  {
    "items": [
      {
        "feedback_id": 1,
        "sender": {
          "user_id": 15,
          "full_name": "Nguyễn Văn Sinh Viên",
          "avatar_url": "https://..."
        },
        "content": "Không thể bấm đặt giá khi bàn phím đang mở.",
        "created_at": "2026-09-21T21:04:00Z",
        "image_count": 2,
        "video_count": 1
      }
    ],
    "next_cursor": null,
    "has_more": false
  }
  ```

---

### 14.7. Chi tiết Feedback cho Quản trị viên (Admin Feedback Detail)
- **Method**: `GET`
- **Path**: `/api/v1/admin/feedback/{feedback_id}`
- **Auth**: Bắt buộc (`ADMIN` role)
- **Quy tắc**:
  - Trả về toàn bộ nội dung, người gửi, và danh sách minh chứng kèm URL stream an toàn qua backend proxy (`stream_url`).
  - Không để lộ trực tiếp storage key bí mật hay URL gốc của Cloudinary ra ngoài payload.
- **Response**: `200 OK`
  ```json
  {
    "feedback_id": 1,
    "sender": {
      "user_id": 15,
      "full_name": "Nguyễn Văn Sinh Viên",
      "avatar_url": "https://..."
    },
    "content": "Không thể bấm đặt giá khi bàn phím đang mở.",
    "created_at": "2026-09-21T21:04:00Z",
    "attachments": [
      {
        "attachment_id": 1,
        "kind": "IMAGE",
        "mime_type": "image/jpeg",
        "size_bytes": 102400,
        "duration_ms": null,
        "stream_url": "/api/v1/admin/feedback/1/evidence/1"
      }
    ]
  }
  ```

---

### 14.8. Quản trị viên xóa phản hồi (Admin Delete Feedback)
- **Method**: `DELETE`
- **Path**: `/api/v1/admin/feedback/{feedback_id}`
- **Auth**: Bắt buộc (`ADMIN` role)
- **Quy tắc**:
  - Dùng để dọn dẹp spam, nội dung vi phạm, hoặc các lỗi đã khắc phục không còn giá trị lưu trữ.
  - Cơ chế Hard Delete: Khóa dòng FOR UPDATE, xóa `site_feedback` (tự động xóa cascade các dòng attachments), commit DB, dọn dẹp media Cloudinary best-effort.
  - An toàn khi xóa đồng thời (User và Admin cùng xóa): Một bên xóa thành công trả về 204, bên còn lại nhận 404 có kiểm soát.
- **Response**: `204 No Content`

---

### 14.9. Stream minh chứng phản hồi an toàn (Stream Feedback Evidence)
- **Method**: `GET`
- **Path**: `/api/v1/admin/feedback/{feedback_id}/evidence/{attachment_id}`
- **Auth**: Bắt buộc (`ADMIN` role)
- **Header hỗ trợ**: `Range` (hỗ trợ HTTP 206 Partial Content cho video seeking)
- **Response**: `200 OK` hoặc `206 Partial Content` (Streaming response kèm các header `Content-Type`, `Content-Range`, `Content-Length`, `Accept-Ranges: bytes`).

---

## 15. Đếm lượt xem sản phẩm (Product View Counter)

### 15.1. Ghi nhận lượt xem sản phẩm (Register Product View)
- **Method**: `POST`
- **Path**: `/api/v1/products/{product_id}/view`
- **Authentication**: Không bắt buộc (Optional). Hỗ trợ cả người dùng đã đăng nhập và khách vãng lai (anonymous).
- **Quy tắc đếm & Khử trùng lặp (Deduplication)**:
  - Cửa sổ khử trùng lặp: **24 giờ** cho mỗi định danh người xem trên từng sản phẩm.
  - Người dùng đăng nhập: Sử dụng `users.user_id` xác thực từ Firebase token (`u:{user_id}`). Không chấp nhận ID do client tự khai báo.
  - Khách vãng lai: Sử dụng UUID ẩn danh từ request body (`a:{uuid}`) phục vụ mục đích dedupe duy nhất. Không lưu trữ hay đối chiếu địa chỉ IP, User-Agent hoặc dấu vân tay thiết bị.
  - Định danh đăng nhập luôn có độ ưu tiên cao nhất, bỏ qua anonymous UUID nếu có token hợp lệ.
  - **Loại trừ**:
    - Người bán xem sản phẩm của chính mình: Không tăng biến đếm (`counted: false`).
    - Quản trị viên (ADMIN) xem sản phẩm: Không tăng biến đếm (`counted: false`).
  - **Bảo toàn quyền riêng tư**: Sản phẩm ở trạng thái ẩn (`HIDDEN`), bị khóa vi phạm (`BLOCKED`), đã xóa mềm (`is_deleted = true`), hoặc người bán bị hạn chế bán hàng tuân theo đúng chính sách hiển thị của trang chi tiết (trả về `404 Not Found`, không rò rỉ sự tồn tại của sản phẩm).
  - **Khả năng chịu lỗi (Fail-open)**: Nếu Redis gặp sự cố hoặc ngoại tuyến, endpoint trả về HTTP 200 với giá trị `view_count` bền vững từ PostgreSQL và `counted: false`, không làm gián đoạn trải nghiệm duyệt hàng của người dùng.

#### Request
- Headers:
  ```http
  Authorization: Bearer <FIREBASE_ID_TOKEN> (tùy chọn)
  Content-Type: application/json
  ```
- Body:
  ```json
  {
    "anonymous_viewer_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
  ```
  *(Trường `anonymous_viewer_id` có thể bỏ trống nếu đã đăng nhập hoặc không có định danh)*

#### Response: `200 OK`
- Lượt xem hợp lệ mới (được tính):
  ```json
  {
    "view_count": 123,
    "counted": true
  }
  ```
- Lượt xem trùng lặp trong 24h hoặc người bán / Admin:
  ```json
  {
    "view_count": 123,
    "counted": false
  }
  ```

