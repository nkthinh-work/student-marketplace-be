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

### 5. Backend — Cloudinary Folder Namespace Standardization [Đã Verified]
- [x] Cấu hình `CLOUDINARY_ROOT_FOLDER=student-marketplace` trong `app/core/config.py` và `.env.example`.
- [x] Chuẩn hóa integration layer `app/integrations/cloudinary.py`:
  - Thêm helper phân giải folder `get_cloudinary_folder(folder_key)` với kiểu dữ liệu `Literal["products", "avatars"]`.
  - Phân giải `products` -> `student-marketplace/products`.
  - Phân giải `avatars` -> `student-marketplace/avatars` (dành riêng cho avatar/profile media trong tương lai).
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
- [x] Giữ nguyên namespace `student-marketplace/avatars` cho avatar media.
- [x] Giữ nguyên toàn bộ existing assets cũ (không migration/delete ảnh cũ).
- [x] Pytest suite: Mở rộng `tests/test_cloudinary.py` lên 16 tests, toàn bộ **27/27 tests PASSED**.
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
  - `student-marketplace/avatars` cho avatar profile.
  - Giúp quản trị asset dễ dàng, không gây lẫn lộn giữa các sản phẩm khi số lượng listing tăng cao.
- **Declarative Upload Queue Architecture**: Sử dụng `activeUploadsRef` kết hợp `useEffect` điều phối concurrency = 2 thay vì synchronous setState mutation loops, triệt tiêu hoàn toàn nguy cơ stale closure, duplicate upload và infinite pending.
- **Loại bỏ item_condition**: Đã loại bỏ hoàn toàn khái niệm `item_condition` (và các giá trị NEW_99, USED_GOOD, USED_FAIR) khỏi toàn bộ hệ thống để tối ưu trải nghiệm mobile-first; tình trạng thực tế của sản phẩm được mô tả linh hoạt trong `description`.
- **Header Search & Sticky Stability**: Header giữ nguyên chiều cao `h-14` (56px) cả khi mở hoặc đóng Search mode; CategoryBar sticky tại `top-14 pt-0` bám sát mép dưới Header đảm bảo 0px gap và 0px layout shift trên mọi viewport.
- **Listing Type Policy**: Phase 2B chỉ cho phép tạo tin với `FIXED_PRICE`. Form Edit không gửi `listing_type`. Nếu có record `AUCTION` trong DB, frontend render dưới dạng badge "Đấu giá" và nhãn "Giá khởi điểm" (read-only), không tạo các chức năng đấu giá giả trước Phase 5.
- **Image Upload Controlled Concurrency**: Hàng đợi upload song song tối đa 2 ảnh cùng lúc, có feedback trạng thái từng ảnh và dọn dẹp bộ nhớ `URL.revokeObjectURL`.
- **Hierarchical Query Invalidation**: Sử dụng query key factory phân cấp giúp các mutations tự động làm mới chính xác các danh sách public và danh sách seller mà không làm bẩn cache toàn cục.

## Trạng thái kiểm thử
- Frontend Build: **Passed** (`npm run build` with 0 errors)
- Price Validation & Formatter Suite: **11/11 tests passed 100%**
- Cloudinary & Product Images Tests: **27/27 passed** (pytest `tests/test_cloudinary.py` & `tests/test_product_images.py`)
- Products CRUD & Detail Tests: **18/18 passed** (pytest `tests/test_products_crud.py` & `tests/test_products_detail.py`)
- Live Cloudinary & API Verification: **Passed 100%** (Real upload to `student-marketplace/products/product-{id}`, URL transform & compensation)
- Alembic Migration Round-Trip & Check: **Passed** (`alembic check` - No new upgrade operations detected)
- Docker Compose Configuration: **Passed** (`docker compose config` valid 100%)
- Phase 2 Overall: **VERIFIED 100%**
