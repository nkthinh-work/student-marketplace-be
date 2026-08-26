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
  "avatar_url": "https://res.cloudinary.com/.../avatar.jpg",
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

### 2.2. Cập nhật hồ sơ Current User

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
  "avatar_url": "https://res.cloudinary.com/.../new_avatar.jpg",
  "bio": "Sinh viên năm cuối CNTT",
  "default_meetup_area": "Căn tin B1"
}
```
*Ghi chú*: Mọi trường đều là optional. Tuyệt đối không cho phép client cập nhật: `user_id`, `email`, `role`, `status`, `created_at`, `updated_at`, `provider_uid`. Nếu gửi các trường ngoài danh mục, request sẽ bị từ chối với `422 Unprocessable Entity`.

#### Response: `200 OK`
Trích xuất `UserResponse` đã được cập nhật:
```json
{
  "user_id": 1,
  "email": "student@university.edu.vn",
  "full_name": "Nguyen Van A (Updated)",
  "phone": "0987654321",
  "avatar_url": "https://res.cloudinary.com/.../new_avatar.jpg",
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

