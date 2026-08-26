# TRẠNG THÁI DỰ ÁN — Backend & Frontend

## Giai đoạn hiện tại
Phase 2 — Categories + Products + Images + Search + Filters (Đã hoàn thành refactor loại bỏ hoàn toàn `item_condition`)

## Công việc hiện tại
Phase 2 (Backend 2A + Frontend 2B) hoàn thành và VERIFIED 100%. Sẵn sàng bước sang Phase 3 (Favorites).

## Trạng thái
- Phase 0: Verified
- Phase 1 (Backend + Frontend): Verified
- Phase 2A (Backend Categories + Products + Images): Verified
- Phase 2B (Frontend Categories + Products + Images + Search + Filters): Verified
- **Cross-Layer Refactor (Remove Product Item Condition)**: **VERIFIED 100%**
- **Phase 2 Overall**: **VERIFIED**

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

## Quyết định thiết kế quan trọng
- **Loại bỏ item_condition**: Đã loại bỏ hoàn toàn khái niệm `item_condition` (và các giá trị NEW_99, USED_GOOD, USED_FAIR) khỏi toàn bộ hệ thống để tối ưu trải nghiệm mobile-first; tình trạng thực tế của sản phẩm được mô tả linh hoạt trong `description`.
- **Header Search & Sticky Stability**: Header giữ nguyên chiều cao `h-14` (56px) cả khi mở hoặc đóng Search mode; CategoryBar sticky tại `top-14 pt-0` bám sát mép dưới Header đảm bảo 0px gap và 0px layout shift trên mọi viewport.
- **Listing Type Policy**: Phase 2B chỉ cho phép tạo tin với `FIXED_PRICE`. Form Edit không gửi `listing_type`. Nếu có record `AUCTION` trong DB, frontend render dưới dạng badge "Đấu giá" và nhãn "Giá khởi điểm" (read-only), không tạo các chức năng đấu giá giả trước Phase 5.
- **Image Upload Controlled Concurrency**: Hàng đợi upload song song tối đa 2 ảnh cùng lúc, có feedback trạng thái từng ảnh và dọn dẹp bộ nhớ `URL.revokeObjectURL`.
- **Hierarchical Query Invalidation**: Sử dụng query key factory phân cấp giúp các mutations tự động làm mới chính xác các danh sách public và danh sách seller mà không làm bẩn cache toàn cục.

## Trạng thái kiểm thử
- Frontend Build: **Passed** (`npm run build` with 0 errors)
- Backend Tests: **54/54 passed** (pytest in 9.96s)
- Alembic Migration Round-Trip & Check: **Passed** (`alembic check` - No new upgrade operations detected)
- Active Reference Scan: **Clean (0 stale active references)**
- Phase 2 Overall: **VERIFIED 100%**
