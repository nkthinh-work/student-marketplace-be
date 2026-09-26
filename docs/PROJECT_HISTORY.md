# LỊCH SỬ DỰ ÁN (PROJECT HISTORY) — Marketplace C2C Sinh viên

> Tài liệu này lưu trữ toàn bộ lịch sử triển khai, các giai đoạn đã hoàn thành, nghiệm thu, hoặc các tính năng đã thu hồi/thay thế. Nguồn sự thật cho trạng thái hiện tại ngắn hạn: xem [PROJECT_STATE.md](PROJECT_STATE.md).

---

## 1. Tóm tắt các giai đoạn đã hoàn thành và kiểm chứng

- **Phase 0 (Foundation)**: FastAPI, SQLAlchemy 2.x async, Alembic baseline, PostgreSQL 15+, Redis, Docker Compose (api, worker, postgres, redis), pytest.
- **Phase 1 (Auth + Users)**: Firebase Authentication, user provisioning (`users`, `user_auth_identities`), profile management, avatar upload.
- **Phase 2 (Categories + Products + Images)**: Danh mục phân cấp, sản phẩm đa dạng, quản lý tồn kho (`stock`, `reserved_stock`), Cloudinary image upload, bộ lọc & tìm kiếm, feed responsive.
- **Phase 3 (Favorites)**: Lưu tin quan tâm, danh sách yêu thích, đồng bộ trạng thái realtime/optimistic.
- **Phase 4 (Orders + Payment)**: Quy trình đơn hàng C2C, khóa tồn kho atomic, VietQR ngân hàng (thông tin tài khoản trên `users` và snapshot trên `orders`), lịch sử trạng thái đơn hàng (`order_status_history`), worker tự hủy đơn quá hạn.
- **Phase 5 (Auctions)**: Đấu giá thời gian thực, khóa bản ghi `FOR UPDATE`, quản lý lượt bid (`auction_bids`), xác định người thắng, WebSocket cập nhật realtime, worker quét hết hạn.
- **Phase 6 (Reviews & Reputation)**: Đánh giá uy tín người bán sau khi giao dịch hoàn tất (`COMPLETED`), ràng buộc 1..5 sao, keyset pagination, tổng hợp uy tín người bán không N+1.
- **Phase 7 + 7A + 7C (Chat & Conversations + Groups + Attachments)**: Trò chuyện 1-1 theo ngữ cảnh sản phẩm, nhóm trò chuyện sinh viên, phê duyệt thành viên, mentions (@), hệ thống tệp đính kèm đa định dạng (`IMAGE`, `VIDEO`, `PDF`, `AUDIO`, `DOCUMENT`), tải tệp an toàn qua ticket ngắn hạn RFC 5987.
- **Phase 7.5 (Daily Journal & Streak)**: Nhật ký sinh viên mỗi ngày (tối đa 120 ký tự), tách bạch điểm danh chuỗi bất biến (`daily_journal_checkins`), recursive CTE tính streak, ngọn lửa hoạt họa trang chủ.
- **Phase 8 (Notifications, Reports, Moderation, Capabilities)**: Thông báo realtime, hệ thống báo cáo vi phạm, quy trình kiểm duyệt 2 bước của Admin, chế tài hạn chế quyền tài khoản ngắn hạn.
- **Phase 8H (Community Engagement)**: Khoảnh khắc cộng đồng Hero 16:9 với touch crop và vòng đời bounded; Bảng tin góp ý/báo lỗi website công khai kèm minh chứng và hard delete; Hồ sơ Creator và VietQR ủng hộ.
- **Phase 9A (Worker Hardening)**: Tăng cường tính lũy đẳng, bọc retry lỗi tạm thời PostgreSQL, chống deadlock và giải phóng tồn kho chính xác.
- **Phase 9B (Redis Product View Counter)**: Bộ đếm lượt xem nguyên tử tần suất cao qua Redis Lua, khử trùng lặp 24h, đồng bộ bền vững sang PostgreSQL, hiển thị số lượt xem trên trang chi tiết và thẻ sản phẩm (USER ACCEPTED).
- **Phase 9C-A (Query & Index Audit)**: Kiểm toán 21 họ truy vấn trọng yếu, khắc phục điểm nghẽn bảng `reports` qua 2 chỉ mục chuyên biệt (`c2f84937f5d2`), loại bỏ Seq Scan cưỡng bức, xác thực 0 N+1 (USER ACCEPTED).
- **Đợt Bảo trì (Hygiene Pass)**: Rà soát toàn diện repository, chuẩn hoá quyền sở hữu đơn nhất giữa các tài liệu canonical, dọn dẹp cache/scratch cục bộ, chuẩn hoá rule quản trị (USER ACCEPTED).
- **Phase 9C-B (PostgreSQL Backup & Restore Procedure)**: Quy trình sao lưu logical dump PostgreSQL native (`pg_dump -Fc`), xác thực SHA-256 và manifest, diễn tập phục hồi cô lập trên Docker container, khớp 100% 29 bảng nghiệp vụ và Alembic revision, bảo toàn CSDL nguồn, phân định rõ ranh giới phục hồi Redis / Cloudinary / Firebase (USER ACCEPTED).
- **Phase 9C-C (Production Docker Build & Container Hardening)**: Dockerfile đa tầng (multi-stage) tối ưu `python:3.12-slim`, non-root user `appuser` (UID 10001), dùng chung image `student-marketplace-be:prod` cho API và Worker. Cấu hình `docker-compose.prod.yml` độc lập, loại bỏ source bind mounts và dev reload, giữ PostgreSQL/Redis trong mạng nội bộ, healthchecks chuẩn xác, migration Alembic tường minh, diễn tập production smoke stack cô lập thành công (USER ACCEPTED).
- **Pre-Deployment Hardening — Complete User + Admin Notification Coverage & Support Claims Flow**: Hoàn thiện 100% độ phủ thông báo in-app và realtime cho Admin Inbox và User Lifecycle outcomes, hàng đợi đối soát ủng hộ `support_claims`, neo huy hiệu chuông thông báo Bell trên mobile drawer và header, 786/786 backend tests PASS, frontend build clean (USER ACCEPTED).
- **Pre-Deployment UX Polish — Dynamic Tutorial Overlay & Admin CMS**: Thay thế trang tĩnh `/tutorials` bằng Global Tutorial Overlay modal chuẩn 9:16 portrait (~420px max-width) mở trực tiếp từ menu `Tutorial` (không đổi route, không reload). Trình phát video HTML5 native với tự động chuyển mã `vc_auto` (H.264 `avc1` hỗ trợ Chrome, Safari, mobile), seeking mượt mà, fallback báo lỗi thân thiện. Admin CMS quản lý video/poster trên Cloudinary với I/O non-blocking (offloaded qua `asyncio.to_thread`), API phản hồi tức thì < 0.15s trong lúc upload. 1 bảng nghiệp vụ `tutorials` (migration `1b009a1b9a9f`), 815/815 full backend tests PASS, 29/29 tutorial backend tests PASS, 10/10 tutorial frontend tests PASS, frontend build clean (USER ACCEPTED).
- **Pre-Deployment Amendment — Navigation-Aligned Tutorial & Presentation Media UX**: Đồng bộ kiến trúc thông tin Tutorial với 10 mục điều hướng thực tế. Loại bỏ hoàn toàn lifecycle ảnh bìa (poster) tùy biến; sinh thumbnail tự động từ video Cloudinary qua transformation URL dẫn xuất. Tiện ích cắt ảnh dùng chung (4:3 cho Product Images, 16:9 cho Community Moments; không cắt minh chứng pháp lý). 31/31 backend tests PASS, 12/12 frontend tests PASS, frontend build clean (USER ACCEPTED).
- **Pre-Deployment Acceptance Fix — Product Approval Completion & Inbox/Home UX**: Hoàn thiện toàn diện quy trình kiểm duyệt tin đăng tiền xuất bản (`Product Pre-Publication Approval Completion`), hỗ trợ tin đăng tùy chọn 0 ảnh; dọn dẹp hộp thư thông báo cá nhân bằng cử chỉ vuốt phải trực tiếp trên mobile (`Notification Direct Swipe-Right Delete`); 10 bản ghi nhật ký thật mới nhất kèm marquee hai chiều liên tục (`10 Most Recent Real Journals & Continuous Two-Way Marquee`). 841/841 backend tests PASS, 14/14 frontend acceptance tests PASS, frontend build clean (USER ACCEPTED).
- **Phase 9C-D (Release Candidate Hygiene & Production Data Preparation)**: Vệ sinh toàn diện mã nguồn BE/FE, loại bỏ debug code, chuẩn hóa tiếng Việt giải thích WHY, zero secrets, .gitignore cập nhật `*.dump`. Phân định không gian lưu trữ Cloudinary theo môi trường (`student-marketplace/dev` vs `student-marketplace/prod`) giữ nguyên 100% tài nguyên legacy. Chiến lược CSDL production sạch qua `alembic upgrade head` + nạp 10 danh mục chuẩn tắc `seed_production_reference.py` + CLI bootstrap admin an toàn `promote_admin.py`. Kiểm toán CSDL dev đọc-chỉ (1.375 bản ghi bảo toàn trên 32 bảng ứng dụng, 0 biến đổi dữ liệu). Hoàn tất dọn dẹp Cloudinary sau rà soát thủ công: 50 legacy referenced assets retained, 4 orphan assets deleted, 0 orphan remaining, 0 unknown remaining. 842/842 tests backend PASS, Alembic head `4414f46b5404`, 32 bảng ứng dụng + 1 bảng `alembic_version` = 33 bảng vật lý (USER ACCEPTED / COMPLETED & VERIFIED).
- **Phase 9C-D (GitHub Release & CI Verification)**: Đẩy toàn bộ commit Release Candidate lên nhánh `main` của cả hai repo `student-marketplace-be` và `student-marketplace-fe`. Kiểm chứng thực tế thành công trên giao diện GitHub Actions: Backend CI & Release Gate SUCCESS, Backend Test Suite & Alembic Verification SUCCESS, Production Docker Build & Artifact Hardening Gate SUCCESS; Frontend CI & Build Gate SUCCESS, Frontend Typecheck & Production Build SUCCESS. Cảnh báo Node.js 20 deprecation / GitHub runner chỉ là warning, không làm gián đoạn workflow (COMPLETED & VERIFIED / USER ACCEPTED).

---

## 2. Chi tiết lịch sử triển khai từng Phase

### Phase 9C-D: Xác thực CI & Phát hành GitHub (GitHub Release & CI Verification) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - **A. Phát hành Nhánh Main (GitHub Release Gate)**:
    - Toàn bộ các thay đổi của gói Release Candidate đã được người dùng commit và đẩy lên nhánh `main` cho cả hai repository: `student-marketplace-be` và `student-marketplace-fe`.
  - **B. Kiểm chứng Hệ thống CI Backend (Backend GitHub Actions CI)**:
    - Xác nhận thực tế thành công từ giao diện người dùng GitHub Actions:
      - `Backend CI & Release Gate`: **SUCCESS**.
      - `Backend Test Suite & Alembic Verification`: **SUCCESS** (Toàn bộ 842 tests backend vượt qua, migration Alembic khớp head `4414f46b5404`, 0 schema drift).
      - `Production Docker Build & Artifact Hardening Gate`: **SUCCESS** (Image `student-marketplace-be:prod` build thành công, non-root user `appuser` UID 10001, compose prod config hợp lệ).
  - **C. Kiểm chứng Hệ thống CI Frontend (Frontend GitHub Actions CI)**:
    - Xác nhận thực tế thành công từ giao diện người dùng GitHub Actions:
      - `Frontend CI & Build Gate`: **SUCCESS**.
      - `Frontend Typecheck & Production Build`: **SUCCESS** (Kiểm tra kiểu tĩnh TypeScript và đóng gói Vite sạch, 0 errors, sinh đầy đủ artifact `dist/index.html`).
    - Các thông báo deprecation liên quan đến Node.js 20 hoặc runner từ GitHub Actions chỉ mang tính chất warning, hoàn toàn không làm gián đoạn hoặc thất bại bất kỳ bước nào trong quy trình CI.
  - **D. Nghiệm thu & Chuyển giao**:
    - Trạng thái nghiệm thu: **COMPLETED & VERIFIED / USER ACCEPTED**.
    - Cổng Release Candidate và CI chính thức đóng lại thành công; mở ra nhiệm vụ tiếp theo: **Phase 9C-D Slice 2 — Remote Deployment**.

### Phase 9C-D: Vệ sinh Mã nguồn Phát hành & Chuẩn bị Dữ liệu Sản xuất (Release Candidate Hygiene & Production Data Preparation) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - **A. Vệ sinh Toàn diện Repository (BE & FE Code & File Hygiene)**:
    - Triệt tiêu code debug, `console.debug`, chuẩn hóa thông báo lỗi tải ảnh tự nhiên tiếng Việt (`Tải ảnh lên thất bại. Vui lòng thử lại.`).
    - Chuẩn hóa chú thích mã nguồn giải thích lý do/bất biến kỹ thuật bằng tiếng Việt súc tích (giữ nguyên định danh kỹ thuật, không sửa chuỗi hợp đồng runtime API/DB/Enums).
    - Rà soát .gitignore: Bổ sung `*.dump`, `*.dump.part` ngăn chặn rò rỉ bản sao lưu CSDL vào Git; 0 tệp lớn > 500KB được theo dõi; 0 secret rò rỉ trong cả hai repository.
    - Xử lý triệt để các lỗi whitespace cuối file (`git --no-pager diff --check` đạt 0 lỗi `new blank line at EOF` trên cả hai repo).
  - **B. Phân định Không gian Lưu trữ Cloudinary theo Môi trường (dev vs prod)**:
    - Bộ giải quyết tập trung duy nhất qua `get_cloudinary_root_folder()`: `student-marketplace/dev/...` cho môi trường phát triển và `student-marketplace/prod/...` cho môi trường sản xuất.
    - Bảo toàn 100% các tài nguyên legacy hiện có của các bản ghi CSDL cũ (không rename, không di dời).
    - Cấu hình biến môi trường `ENVIRONMENT=development` trong cấu hình và `.env.example`.
  - **C. Kiểm toán và Dọn dẹp Tài nguyên Cloudinary (Cloudinary Cleanup Completion)**:
    - Công cụ `scripts/audit_cloudinary_media.py` quét toàn diện 8 bảng CSDL (`product_images`, `message_attachments`, `report_attachments`, `community_moments`, `site_feedback_attachments`, `tutorials`, `orders`, `users`) trên cả 3 loại tài nguyên (`image`, `video`, `raw`).
    - Kết quả dọn dẹp hoàn tất sau khi rà soát thủ công:
      - 50 tài nguyên legacy đang được CSDL tham chiếu được giữ lại nguyên vẹn (50 legacy referenced assets retained).
      - 4 tài nguyên mồ côi đã được xóa an toàn sau khi rà soát thủ công (4 orphan assets deleted after manual review).
      - 0 tài nguyên mồ côi còn lại (0 orphan remaining).
      - 0 tài nguyên không xác định (0 unknown remaining).
  - **D. Chiến lược Dữ liệu & Công cụ Vận hành CSDL Production**:
    - Cơ chế CSDL Production sạch từ đầu: Khởi tạo schema bằng `alembic upgrade head`; tuyệt đối không sao chép CSDL dev chứa dữ liệu kiểm thử.
    - Idempotent Production Seed Script (`scripts/seed_production_reference.py`): Nạp chính xác 10 danh mục chuẩn tắc, an toàn khi chạy lại nhiều lần, tuyệt đối không nạp dữ liệu giao dịch giả.
    - Quy trình Bootstrap Admin An toàn (`scripts/promote_admin.py`): Thăng cấp tài khoản quản trị viên đầu tiên sau khi đăng nhập qua Firebase Auth, không hardcode mật khẩu, không tạo backdoor.
    - Công cụ Kiểm toán CSDL Dev Đọc-chỉ (`scripts/audit_dev_db.py`): Báo cáo 1.375 bản ghi trên toàn bộ 32 bảng ứng dụng, bảo toàn nguyên vẹn dữ liệu thử nghiệm tại máy dev.
  - **E. Kiểm thử & Cơ sở Dữ liệu**:
    - Toàn bộ **842/842 tests backend** PASS (`pytest tests/ -q` in 115.23s).
    - Frontend Acceptance tests (18 assertions) và Tutorial tests (12 tests) PASS 100%; Frontend build sạch (`tsc -b && vite build` hoàn tất trong 8.31s).
    - Alembic Head: `4414f46b5404`, 0 schema drift (`alembic check` clean, No new upgrade operations detected).
    - CSDL vật lý: 32 bảng ứng dụng + 1 bảng `alembic_version` = 33 bảng vật lý.
    - Trạng thái nghiệm thu: **COMPLETED & VERIFIED / USER ACCEPTED**.

### Pre-Deployment Acceptance Fix: Hoàn thiện Kiểm duyệt Tin đăng, Vuốt Xóa Thông báo & Marquee Nhật ký (Product Approval Completion & Inbox/Home UX) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - **A. Kiểm duyệt Tin đăng Tiền xuất bản & Ảnh tùy chọn (Product Pre-Publication Approval Completion & Optional Images)**:
    - Admin Navigation & Routing: Đăng ký mục `Kiểm duyệt tin đăng` (`/admin/product-approvals`, icon `ClipboardCheck`) hiển thị đầy đủ, rõ ràng trong nhóm `QUẢN TRỊ` trên cả Header Desktop dropdown và Mobile Drawer.
    - Hàng đợi thẩm định: Trang `AdminProductApprovalsPage` sắp xếp `submitted_for_review_at ASC, product_id ASC` (tin gửi trước duyệt trước), phân trang Keyset cursor mượt mà, hỗ trợ chuyển tab `Đã duyệt` và `Đã từ chối`.
    - Modal thẩm định hiển thị chi tiết sản phẩm và tóm tắt an toàn người bán. Khi tin có 0 ảnh hiển thị `Tin đăng này không có ảnh.` không lỗi render. Khóa dòng `SELECT ... FOR UPDATE` chống xung đột đồng thời.
    - Sửa thứ tự ưu tiên nhãn người bán: `moderation_status == 'BLOCKED'` -> `approval_status == 'DRAFT'` -> `approval_status == 'PENDING'` -> `approval_status == 'REJECTED'` -> `approval_status == 'APPROVED'`.
    - Bước 2 đăng tin cho phép gửi duyệt không bắt buộc ảnh (`POST /api/v1/products/{id}/submit-review`), chuyển sang `PENDING` và thông báo Admin.
    - Bảo vệ nội dung đã duyệt: Chỉnh sửa trường nhạy cảm hoặc thêm/xóa ảnh tự động thu hồi phê duyệt (`APPROVED -> DRAFT`). Reorder ảnh hoặc đổi thumbnail giữa các ảnh hiện có bảo lưu trạng thái phê duyệt. Khách mua không thể xem hoặc đặt mua tin chưa duyệt (404 Not Found).
  - **B. Dọn dẹp Hộp thư Thông báo bằng Cử chỉ Vuốt Phải Trực tiếp (Notification Direct Swipe-Right Delete)**:
    - Triển khai `DELETE /api/v1/notifications/{notification_id}` cho user ACTIVE. Xóa cứng bản ghi thông báo của user, trả về 204 No Content, không ảnh hưởng thực thể nghiệp vụ tham chiếu.
    - Cử chỉ vuốt phải trực tiếp trên mobile: Vuốt ngang sang phải đạt ngưỡng (>= 38% chiều rộng và >= 90px) thả tay kích hoạt xóa ngay lập tức không cần chạm lần 2. Thả tay dưới ngưỡng tự động snap back. Cuộn dọc được bảo toàn.
    - Tách lớp thị giác triệt tiêu tràn màu: Lớp nền đỏ z-0 `pointer-events-none` neo chặt bên trái; lớp tiền cảnh z-10 dùng nền 100% OPAQUE. Desktop có icon thùng rác tinh tế; TanStack Query optimistic update giảm `unread_count` tức thì.
  - **C. 10 Bản ghi Nhật ký Thật Mới nhất & Marquee Hai chiều Liên tục (10 Most Recent Real Journals & Continuous Two-Way Marquee)**:
    - Bổ sung `GET /api/v1/daily-needs/recent` (query param `limit` clamp 1..10, mặc định 10, public anonymous) lấy 10 bản ghi thật mới nhất theo `note_date DESC, updated_at DESC, daily_need_id DESC`. Backend tuyệt đối không sinh dữ liệu giả.
    - Presentation pool 10 slots trên frontend: Khi có 1..9 bản ghi thật, tự động dùng round-robin tuần hoàn tạo 10 slots cho 2 hàng marquee chuyển động ngược hướng liên tục mà không sinh fake DB ID. Trạng thái 0 bản ghi hiển thị empty state thân thiện.
  - **D. Kiểm thử & Cơ sở dữ liệu**:
    - 32 bảng nghiệp vụ + 1 bảng `alembic_version` = 33 bảng vật lý. Alembic head `4414f46b5404`, 0 drift.
    - Full Backend Suite: 841/841 PASS. Frontend Acceptance Suite: 14/14 PASS. Frontend Build: PASS.
    - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức (USER ACCEPTED).

### Pre-Deployment Amendment: Đồng bộ Điều hướng Tutorial & Cắt ảnh Trình bày (Navigation-Aligned Tutorial & Presentation Media UX) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - Đồng bộ kiến trúc thông tin Tutorial với 10 mục điều hướng thực tế thuộc 5 nhóm điều hướng người dùng.
  - Loại bỏ hoàn toàn vòng đời ảnh bìa (poster) tùy biến; sinh thumbnail tự động từ video Cloudinary qua transformation URL dẫn xuất.
  - Tiện ích cắt ảnh dùng chung: 4:3 cho Product Images, 16:9 cho Community Moments; bảo toàn nguyên vẹn khung hình gốc cho minh chứng pháp lý (báo cáo, phản hồi, biên nhận chuyển khoản, đính kèm tin nhắn).
  - 31/31 backend tests PASS, 12/12 frontend tests PASS.
  - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức (USER ACCEPTED).

### Pre-Deployment UX Polish: Hệ thống Hướng dẫn Nhanh Toàn cục & Quản trị CMS (Dynamic Tutorial Overlay & Admin CMS) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - *Thay thế hoàn toàn phiên bản Tutorial v1 tĩnh*: Loại bỏ hoàn toàn các route `/tutorials` và `/tutorials/:slug` cùng dữ liệu mock tĩnh `tutorialsData.ts`.
  - **Điều hướng & Global Tutorial Overlay**:
    - Nhãn menu chuẩn `Tutorial`, đặt ở vị trí cao nhất trên thanh điều hướng (phía trên `Trang chủ`), click mở trực tiếp Global Overlay modal mà không thay đổi URL, không tải lại trang; tự động đóng Mobile Drawer khi kích hoạt.
    - Modal toàn cục chuẩn 9:16 portrait (~420px max-width), nền mờ `backdrop-blur-sm bg-black/60`, hỗ trợ phím Escape, đóng bằng nút ✕ hoặc click backdrop, khóa cuộn trang nền.
    - Chế độ **FEATURE LIST**: Accordion dọc theo 10 nhóm tính năng chuẩn hóa (Context-Aware Route Matching), tự động mở rộng theo ngữ cảnh trang hiện tại, hiển thị danh sách video con kèm ảnh thumbnail và thời lượng.
    - Chế độ **VIDEO MODE**: Trình phát video HTML5 native chuẩn 9:16 portrait (`object-fit: contain`, `playsInline`, `preload="metadata"`, không autoplay, không loop, seeking mượt mà, tự động dừng khi đóng modal hoặc quay lại danh sách). Ràng buộc trực tiếp `src={videoUrl}`, reset lỗi tự động khi đổi URL, fallback báo lỗi thân thiện `Không thể phát video Tutorial này.` kèm nút thử lại.
    - Nút CTA "Làm ngay" theo 10 hành động chuẩn hóa dẫn thẳng đến tính năng thật của hệ thống.
  - **Quản trị CMS Admin (`/admin/tutorials`)**:
    - Bổ sung mục điều hướng `Quản lý Tutorial` trong danh mục `QUẢN TRỊ` của Admin.
    - Quản lý danh sách video theo Feature, nút sắp xếp `↑` `↓` tự động cập nhật bước số `sort_order` (10, 20, 30...) trong CSDL transaction.
    - Modal Thêm mới, Chỉnh sửa, Thay thế video MP4 (tối đa 100 MB), Quản lý ảnh bìa poster (tối đa 10 MB), Bật/tắt xuất bản (`is_published`), Xem thử video (hỗ trợ cả bản nháp), và Xóa vĩnh viễn có xác nhận.
    - Tiêu đề chức năng gọn (`Ảnh bìa`, `Thay thế Video`, `Chỉnh sửa Tutorial`, `Xem thử Video`) kèm phụ đề bọc dòng mềm (`break-words`), chống tràn giao diện cho tiêu đề tối đa 120 ký tự.
    - Nhãn hành động trong dropdown hiển thị tên thân thiện (ví dụ `Mở hồ sơ cá nhân` thay vì kèm route `/profile`).
    - Xem trước video và poster bằng `URL.createObjectURL` với `preload="metadata"`, tự động thu hồi bộ nhớ bằng `URL.revokeObjectURL` khi đổi tệp hoặc unmount/đóng modal.
    - Cập nhật dữ liệu tức thì qua React Query cache invalidation, triệt tiêu 100% reload toàn trang (`location.reload` = 0) và không kích hoạt bootstrap `Đang khởi tạo...`.
  - **Khắc phục Triệt để Acceptance Blockers — Non-blocking Cloudinary I/O & Universal Video Delivery**:
    - **Triệt tiêu nghẽn Event Loop FastAPI (Event-Loop Starvation Fix)**: Đưa toàn bộ các lời gọi đồng bộ I/O của Cloudinary SDK (`upload`, `upload_large`, `destroy`) ra worker thread thông qua `asyncio.to_thread` trong module tích hợp trung tâm `app/integrations/cloudinary.py`. Tách bạch tuyệt đối: DB transaction, validation chạy trên async event loop; Cloudinary network I/O chạy trên worker thread. Các request song song (`GET /api/v1/users/me`, `GET /health`, reload...) phản hồi tức thì (< 0.15s) ngay cả khi đang tải lên video lớn.
    - **Chuẩn hóa Video Delivery Đa nền tảng (Universal Transcoding)**: Bổ sung bộ lọc chuyển mã tự động `vc_auto` vào đường dẫn Cloudinary video URL (`.../video/upload/vc_auto/...mp4`). Khắc phục triệt để lỗi không phát được trên Google Chrome do video quay từ thiết bị iOS/iPhone mặc định lưu codec HEVC (`hvc1`), tự động chuyển mã về chuẩn H.264 (`avc1`) có `Accept-Ranges: bytes` hỗ trợ seeking mượt mà.
    - **Linh hoạt Phương thức Tải lên (Threshold Policy)**: Tệp video <= 20 MB sử dụng API upload video thông thường; tệp > 20 MB sử dụng `upload_large` với chunk size 20 MB. Cả 2 luồng đều chỉ định tường minh `resource_type="video"`.
    - **Cơ chế Bù trừ Vẹn toàn**: Giữ nguyên cơ chế xóa asset mới trên Cloudinary nếu DB transaction thất bại; xóa asset cũ trên Cloudinary sau khi DB transaction commit thành công.
  - **Cơ sở dữ liệu & Migration**:
    - Bổ sung duy nhất 1 bảng nghiệp vụ `tutorials` trong PostgreSQL qua Alembic migration `1b009a1b9a9f_add_tutorials_table.py`.
    - Toàn bộ ràng buộc: `video_size_bytes > 0`, `duration_ms > 0`, `sort_order >= 0`, `poster_all_or_none`, trigger tự cập nhật `updated_at`, composite index `ix_tutorials_pub_feature_sort` trên `(is_published, feature_key, sort_order, tutorial_id)`.
    - Tổng số bảng: 32 bảng nghiệp vụ + 1 bảng `alembic_version` = 33 bảng vật lý. 0 schema drift (`alembic check` clean).
  - **Hệ thống Kiểm thử & Xác thực**:
    - Backend: 29/29 tests PASS trong `tests/test_tutorials.py` bao gồm kiểm thử event loop ticker, kiểm thử gọi API đồng thời trong lúc upload, kiểm thử `resource_type="video"`, kiểm thử định dạng URL delivery `vc_auto`, và từ chối phản hồi provider không hợp lệ.
    - Full Backend: **815/815 PASS** (`pytest tests/ -q` in 145.42s).
    - Frontend: **10/10 PASS** (`node src/features/tutorials/__tests__/tutorials.test.mjs`).
    - Frontend Build: `tsc -b && vite build` PASS (0 errors, 8.82s).
    - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức (USER ACCEPTED).

### Pre-Deployment Hardening: Hoàn thiện Độ phủ Thông báo User + Admin & Hàng đợi Đối soát Ủng hộ (Complete User + Admin Notification Coverage & Support Claims Flow) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - Kiểm toán và hoàn thiện 100% độ phủ thông báo in-app và realtime cho Admin Inbox và User Lifecycle outcomes.
  - Tái sử dụng bảng `notifications` hiện hữu với `type = 'SYSTEM'` và polymorphic `ref_type`, không sửa đổi DB schema, 0 Alembic migration drift.
  - Admin inbox fan-out cho 4 sự kiện hành động mới: Báo cáo vi phạm (`ADMIN_REPORT`), Ảnh cộng đồng (`ADMIN_COMMUNITY`), Phản hồi (`ADMIN_FEEDBACK`), Ủng hộ đối soát (`ADMIN_SUPPORT_CLAIM`) tới toàn bộ active admin (`role = ADMIN` và `status = ACTIVE`).
  - User lifecycle outcomes: Xác nhận ủng hộ với số tiền thực nhận có thẩm quyền (`SUPPORT_CLAIM`), Từ chối ủng hộ trung tính (`SUPPORT_CLAIM`), Duyệt ảnh cộng đồng (`COMMUNITY_MOMENT`), Từ chối ảnh cộng đồng với snapshot trước khi hard delete (`COMMUNITY_REJECTED`), Kết quả báo cáo vi phạm (`REPORT` cho terminal RESOLVED/REJECTED, 0 cho REVIEWING), Giới hạn & khôi phục quyền tài khoản (`ACCOUNT_ACCESS`).
  - Bảo toàn tính nguyên tử giao dịch: Tạo bản ghi thông báo trong cùng DB transaction, phát tán realtime `NOTIFICATION_CREATED` post-commit qua `/ws/me`, lỗi Redis/WebSocket được cô lập hoàn toàn (không rollback dữ liệu nghiệp vụ).
  - Tái cấu trúc neo huy hiệu chuông thông báo (Notification Badge Anchoring): Đưa `Bell` và badge chưa đọc vào wrapper cục bộ `relative inline-flex shrink-0`, badge `absolute` tại góc trên phải icon với `pointer-events: none`, triệt tiêu hoàn toàn lỗi che icon hoặc thế chỗ icon ở Mobile Drawer (`Thông báo`), đồng bộ căn chỉnh hoàn hảo với các mục điều hướng lân cận, không gây dịch chuyển giao diện khi số lượng chưa đọc thay đổi (0, 1..99, 99+).
  - Đơn giản hóa luồng ủng hộ (Support Claims Simplification): Triệt tiêu mã chuyển khoản `PTITERS-{user_id}` khỏi frontend và backend, thu gọn biểu mẫu người dùng thành `claimed_amount_vnd`, `claimed_transferred_at`, `sender_account_name` và `wants_public`, phân tách rành mạch giữa hàng đợi khai báo `support_claims` và sổ cái tài chính chính thức `support_contributions`.
  - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức (USER ACCEPTED).

### Phase 9C-C: Đóng gói Container Sản xuất & Tăng cường Bảo mật (Production Docker Build & Container Hardening) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - Triển khai Dockerfile đa tầng (multi-stage build: builder -> runner) dựa trên `python:3.12-slim`. Toàn bộ dependencies được cài đặt trong `/opt/venv` ở stage builder, stage runner loại bỏ hoàn toàn trình biên dịch và công cụ phát triển, kích thước content chỉ 103MB.
  - Phân quyền runtime phi đặc quyền: Tạo group và user `appuser:appgroup` (UID `10001`, GID `10001`), toàn bộ tiến trình container thực thi dưới non-root user.
  - Dùng chung image ứng dụng: Cả `api` và `worker` chia sẻ cùng image `student-marketplace-be:prod`, phân biệt duy nhất bằng lệnh khởi chạy (`command`).
  - Cấu hình Production Compose độc lập (`docker-compose.prod.yml`):
    - Bao gồm duy nhất 4 dịch vụ cốt lõi: `api`, `worker`, `postgres`, `redis`. Không chứa frontend, reverse proxy hay sidecars.
    - Loại bỏ hoàn toàn source bind mounts (`./app:/app/app`) và cờ dev auto-reload (`--reload`). Mã nguồn và dependencies nằm cố định trong built image.
    - Mạng nội bộ an toàn: PostgreSQL (`5432`) và Redis (`6379`) không publish cổng ra máy chủ host, chỉ giao tiếp nội bộ trong mạng Compose.
    - Cơ chế kiểm tra sức khỏe (Healthchecks) chuẩn xác: `pg_isready` cho Postgres, `redis-cli ping` cho Redis, và lệnh stdlib Python kiểm tra `GET /health` cho API.
    - Phân định di trú CSDL tường minh: Không tự động chạy migration khi API khởi động; quản trị viên thực thi migration chủ động qua `docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head`.
  - Diễn tập thực tế trên Stack Production Cô lập (`sm-prod-smoke`):
    - Khởi tạo stack cô lập hoàn toàn với cổng host API 18000, named volume riêng biệt `sm-prod-smoke_postgres_data`.
    - Di trú thành công toàn bộ 33 revisions lên `c2f84937f5d2 (head)` trên CSDL trống.
    - Xác thực API `/health` trả về `200 {"status":"healthy","database":"up","redis":"up","service":"up"}`.
    - Xác thực Worker liveness ổn định, kết nối Redis/DB chuẩn xác, không gặp crash loop.
    - Kiểm chứng khởi động lại (Restart): API và Worker phục hồi nhanh chóng và duy trì trạng thái healthy; dữ liệu schema CSDL bền vững trên volume.
    - Kiểm chứng dừng duyên dáng (Graceful Shutdown): API và Worker bắt tín hiệu SIGTERM (15) chuẩn xác, đóng kết nối Redis và thoát vòng lặp sạch sẽ.
    - Dọn dẹp sạch sẽ toàn bộ tài nguyên tạm thời của smoke stack.
  - An toàn môi trường phát triển: Môi trường dev (FastAPI port 8000, Frontend port 3000, Dev Tunnel, dev PostgreSQL/Redis containers) không bị gián đoạn hay ảnh hưởng.
  - Tương thích công cụ sao lưu: Mở rộng `scripts/db_backup.py` hỗ trợ cờ tùy chọn `--compose-file docker-compose.prod.yml` tương thích ngược.
  - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức ("Check sau đó tiếp tục phase sau nhé").

### Phase 9C-B: Quy trình Sao lưu & Diễn tập Phục hồi CSDL PostgreSQL (PostgreSQL Backup & Restore Procedure) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - Triển khai công cụ vận hành tiêu chuẩn `scripts/db_backup.py` sử dụng thư viện chuẩn Python (Standard Library only), tương thích môi trường Windows & Linux.
  - Định dạng sao lưu: PostgreSQL native logical custom format (`pg_dump -Fc --no-owner --no-acl`), cơ chế ghi file nguyên tử qua tệp đệm `.part`.
  - Kiểm tra tính toàn vẹn: Tự động tính toán mã băm SHA-256 và kiểm tra bảng mục lục lưu trữ qua `pg_restore --list`. Tạo siêu dữ liệu vận hành `manifest.json` không chứa mật khẩu hay thông tin nhạy cảm.
  - Diễn tập khôi phục cô lập (Restore Drill):
    - Cơ chế an toàn tuyệt đối: Khước từ cứng (hard refusal) nếu tên database đích trùng database nguồn `student_marketplace`; xác thực tên database qua biểu thức chính quy chống SQL injection.
    - Khôi phục thành công vào database tạm thời cô lập `student_marketplace_restore_20260924_042548` trong 1.13 giây.
    - Kiểm chứng khớp 100% bảng `alembic_version` (revision `c2f84937f5d2`), đủ 29/29 bảng nghiệp vụ (+ 1 bảng Alembic = 30 bảng vật lý).
    - Kiểm chứng số lượng bản ghi: Khớp 100% số lượng dòng trên toàn bộ 29 bảng nghiệp vụ giữa CSDL nguồn và CSDL khôi phục.
    - Bảo toàn CSDL nguồn: Database `student_marketplace` không bị tác động hay ghi đè. Database tạm thời được xóa sạch sẽ sau diễn tập.
  - Phân định ranh giới thảm họa: PostgreSQL là nguồn dữ liệu nghiệp vụ chuẩn xác; Redis mang tính tạm thời (khởi tạo mới khi khôi phục); tài nguyên Cloudinary và tài khoản Firebase Auth tuân thủ ranh giới nhà cung cấp bên ngoài.
  - Quyền sở hữu tài liệu: Toàn bộ quy trình vận hành và nhật ký diễn tập chi tiết thuộc sở hữu độc quyền của `BACKUP_RESTORE.md`.
  - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức ("Oke prompt tiếp để clean và phase sau nhé").

### Phase 9C-A: Rà soát & Tối ưu hóa Truy vấn / Chỉ mục CSDL (Query & Index Audit / Database Performance Hardening) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Mục tiêu & Thực chứng**:
  - Khảo sát toàn diện 21 nhóm truy vấn trọng yếu trên 29 bảng nghiệp vụ (+ 1 bảng metadata `alembic_version` = 30 bảng vật lý); 96 indexes.
  - Xác nhận 100% khớp chỉ mục với phân trang Keyset con trỏ mờ và biểu thức tìm kiếm toàn văn GIN FTS `to_tsvector('simple', ...)`.
  - Khắc phục điểm nghẽn duy nhất trên bảng `reports`: Bổ sung 2 chỉ mục `ix_reports_status_created_desc` và `ix_reports_reporter_target` qua Alembic migration `c2f84937f5d2`, tăng tốc độ truy vấn 72% - 95%, triệt tiêu hoàn toàn forced Seq Scan và Sort trên RAM.
  - Xác thực không phát sinh N+1 truy vấn trên các endpoint danh sách (`selectin`, `selectinload` và batch loading).
  - Chi tiết hồ sơ đo lường và execution plans được lưu giữ độc lập tại `QUERY_INDEX_AUDIT.md`.
  - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức ("Oke ... tiếp phase sau").

### Đợt Bảo trì: Rà soát Repository & Chuẩn hoá Tài liệu Canonical (Repository & Canonical Documentation Hygiene Pass) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Kết quả bảo trì & Vệ sinh mã nguồn**:
  - Thiết lập ma trận sở hữu đơn nhất (One Question -> One Canonical Source) trong `.roo/rules/00-project.md`.
  - Tinh gọn `PROJECT_STATE.md` về bộ nhớ ngắn hạn súc tích (~88 dòng).
  - Khử trùng lặp và đồng bộ cấu trúc 29 bảng nghiệp vụ trong `DB_v7.md` (giải quyết xung đột `community_moments` và chuẩn hoá ràng buộc quyền hạn chế tài khoản).
  - Cập nhật `API_CONTRACT.md` (chuẩn hoá tên miền nghiệp vụ, phản hồi góp ý website và bổ sung `view_count` trong DTOs ví dụ).
  - Đồng bộ `TechStack_v2.md` với cây thư mục ổn định thực tế và lược bỏ thư mục sinh/cục bộ.
  - Dọn dẹp an toàn `.pytest_cache/`, các tệp tạm thời trong `scratch/`, rà soát `.gitignore` và `.dockerignore`.
  - Toàn bộ 738/738 tests backend vượt qua, frontend build sạch, Alembic 0 drift.
  - Nghiệm thu người dùng: Đã được người dùng xác nhận nghiệm thu chính thức ("Oke ... tiếp phase sau").

### Phase 9B: Đếm lượt xem sản phẩm qua Redis & Hiển thị trên thẻ (Redis Product View Counter & Card View Count) [COMPLETED & VERIFIED / USER ACCEPTED]
- **Kiến trúc & Triển khai**:
  - Ghi nhận lượt xem tần suất cao trên Redis với biến đếm số nguyên chính xác (Exact Atomic Integer Counter via Lua script `REGISTER_VIEW_LUA`), không dùng HyperLogLog.
  - Khử trùng lặp 24 giờ (`product:views:seen:{product_id}:{viewer_token}`). Định danh ưu tiên `u:{user_id}` từ verified Firebase token, fallback anonymous UUID `a:{uuid}` (`ptiters-viewer-id`), không lưu IP hay device fingerprint.
  - Loại trừ người bán tự xem và Quản trị viên (`counted = false`). Bảo toàn chính sách quyền riêng tư của sản phẩm (404 Not Found).
  - Đồng bộ định kỳ sang PostgreSQL qua worker: Cập nhật đơn điệu `UPDATE products SET view_count = GREATEST(products.view_count, :count)` bảo toàn `updated_at`, commit DB trước khi conditional ACK trong Redis (`CONDITIONAL_ACK_LUA`), replay-safe và multi-worker safe.
  - Fail-open: Chi tiết sản phẩm vẫn xem được bình thường nếu Redis offline, trả về count từ PostgreSQL.
  - Frontend Product Detail tự động đăng ký lượt xem sau khi tải sản phẩm thành công, hiển thị số lượt xem tiếng Việt chuẩn `Intl.NumberFormat('vi-VN')` (`1.234 lượt xem`), cập nhật cache TanStack Query cục bộ.
  - **Bổ sung Card View Count (Card Amendment)**:
    - Thẻ sản phẩm `ProductCard`, `SellerProductCard`, và `Favorites` card hiển thị số lượt xem với icon con mắt trực quan (`view_count`).
    - Các endpoint danh sách (`GET /api/v1/products`, `GET /api/v1/products/me`, `GET /api/v1/favorites`): Thực hiện đúng 1 lần Redis `MGET` theo lô (`batch_get_views`) cho danh sách IDs, fallback lấy `view_count` từ PostgreSQL nếu Redis offline/lỗi.
    - Bất biến: Card component chỉ đọc dữ liệu, tuyệt đối không gửi `POST /view`. Chỉ có trang chi tiết (`ProductDetailPage`) mới đăng ký lượt xem.
    - Hiển thị thuần túy: Không thay đổi thứ tự sắp xếp sản phẩm (không sắp xếp theo view_count), giữ nguyên thứ tự ưu tiên của Người bán (Đang đấu giá -> Chờ checkout -> Sắp diễn ra -> Mới nhất) và thứ tự mới nhất của Đơn hàng.
- **Bằng chứng Kiểm thử Tự động & Nghiệm thu**:
  - `tests/test_product_view_counter.py`: 26/26 PASSED (bao gồm 7 test mới cho batch MGET, Seller response serialization, Favorite response serialization, zero card POST).
  - `tests/test_worker_hardening.py`: 13/13 PASSED.
  - Full backend suite: 737/737 PASSED in 166.52s.
  - Frontend build: `tsc -b && vite build` PASSED (0 errors in 11.23s).
  - Nghiệm thu người dùng (User Acceptance): Đã được người dùng xác nhận nghiệm thu chính thức ("Oke ... tiếp phase sau"). Giai đoạn chuyển thành COMPLETED & VERIFIED / USER ACCEPTED.

### Phase 7.5: Nhật ký hôm nay & Điểm danh chuỗi bất biến (Daily Journal & Immutable Check-in) [VERIFIED 100%]
- **Database Schema & Alembic Migration (`cc8aeddfcb89_create_daily_journal_checkins_table.py`)**:
  - Tách bạch 2 khái niệm miền: `daily_needs` (nội dung có thể xóa/sửa) và `daily_journal_checkins` (chứng nhận chuỗi bất biến).
  - Bảng `daily_journal_checkins`: `checkin_id BIGINT PRIMARY KEY`, `user_id BIGINT FK -> users(user_id) ON DELETE CASCADE`, `checkin_date DATE NOT NULL`, `created_at TIMESTAMPTZ DEFAULT NOW()`.
  - Ràng buộc: `UNIQUE(user_id, checkin_date)`. Index tối giản: `ix_daily_journal_checkins_user_id`.
  - Backfill dữ liệu lịch sử an toàn từ `daily_needs`. Schema drift check: `alembic check` trả về 0 diff.
- **Backend Services & API Endpoints**:
  - Giao dịch đăng bài nguyên tử: `upsert_user_note` + `record_checkin` thực hiện trong cùng một SQLAlchemy transaction.
  - Cả hai thao tác sử dụng PostgreSQL atomic `ON CONFLICT`, an toàn tuyệt đối với request đồng thời.
  - `record_checkin` trả về boolean `checkin_created` (`True` duy nhất khi chèn bản ghi điểm danh mới).
  - Tính toán chuỗi liên tiếp (Streak): SQL Recursive CTE trực tiếp trên bảng `daily_journal_checkins`.
  - Hợp đồng `GET /api/v1/daily-needs/me/summary`: `has_journal_today`, `has_checked_in_today`, `streak_count`.
  - Xóa nhật ký hôm nay (`DELETE /api/v1/daily-needs/me/today`): chỉ xóa dòng trong `daily_needs`, bảo toàn chuỗi check-in.
- **Frontend Architecture & UX**:
  - `HomePage.tsx`: Ngọn lửa trên thẻ Welcome Card dựa 100% vào `hasCheckedInToday`.
  - `DailyNeedModal.tsx`: Nhắc chuỗi động, giới hạn 120 ký tự.
- **Verification**:
  - `pytest tests/test_daily_needs.py`: 25/25 tests PASSED.
  - `pytest tests/test_conversations.py`: 12/12 tests PASSED.
  - Frontend `npm run build`: 0 errors.

### Phase 7 + 7A + 7C: Trò chuyện & Tệp đính kèm (Chat, Conversations, Groups & Media) [VERIFIED 100%]
- **Database Schema & Alembic Migrations (`ff6a57a76040`, `7a1b2c3d4e5f`, `8c3d4e5f6a7b`, `9f1a2b3c4d5e`, `e58355f24d58`, `e8a9b1c2d3e4`)**:
  - `conversations`: Hỗ trợ cả DIRECT 1-1 và GROUP trò chuyện, `type`, `title`, `avatar_url`, `created_by`, `requires_approval`.
  - `conversation_members`: `role` (`OWNER`, `ADMIN`, `MEMBER`), `status` (`ACTIVE`, `LEFT`, `REMOVED`), `joined_at`, `left_at`.
  - `conversation_invites`: Lời mời tham gia nhóm và hàng đợi phê duyệt.
  - `messages`: `type` (`TEXT`, `IMAGE`, `FILE`, `PRODUCT_CARD`, `ORDER_CARD`, `SYSTEM`), `content`, `product_id`, `order_id`, `is_deleted`.
  - `message_attachments`: `kind IN ('IMAGE', 'VIDEO', 'PDF', 'AUDIO', 'DOCUMENT')`, `duration_ms BIGINT NULL`, `url`, `storage_key`, `mime_type`, `original_name`, `size_bytes`.
  - `message_mentions`: Snapshot lưu trữ @mention trong nhóm.
- **Backend Services & API Endpoints**:
  - Chat 1-1 theo ngữ cảnh sản phẩm, race-safe `INSERT ... ON CONFLICT DO NOTHING`.
  - Quản lý nhóm: tạo nhóm, mời thành viên, phê duyệt yêu cầu, thăng/giáng cấp role, rời nhóm, xóa thành viên.
  - Keyset pagination cho danh sách tin nhắn và danh sách hội thoại, eager loading attachments qua `selectinload` chống N+1.
  - Phân loại tệp tải lên qua Magic Bytes, chống file giả mạo (.exe đổi đuôi .jpg).
  - Tải tệp an toàn qua ticket ngắn hạn (TTL 60s) lưu trữ trên Redis, bảo toàn tên tiếng Việt Unicode theo RFC 5987.
  - Kênh WebSocket `/ws/me` phân phối realtime: `MESSAGE_CREATED`, `CONVERSATION_READ`, `GROUP_MEMBERSHIP_CHANGED`, `GROUP_INVITE_UPDATED`, `PRESENCE_STATE`.
- **Frontend Implementation**:
  - Composer hỗ trợ gõ tiếng Việt Telex/VNI (`event.nativeEvent.isComposing`), đính kèm tệp đa dạng.
  - Xem trước ảnh, video player native, hiển thị file theo họ định dạng trực quan.
  - Phản ứng tức thì khi bị xóa khỏi nhóm: thu hồi quyền truy cập, đẩy về `/messages` an toàn, ngăn chặn vòng lặp retry 403/404.

### Phase 6: Đánh giá & Uy tín (Reviews & Reputation) [VERIFIED 100%]
- **Database Schema & Alembic Migration (`0b6255d0ebcd_create_reviews_table.py`)**:
  - `reviews` table: `review_id BIGINT IDENTITY PK`, `order_id`, `reviewer_id`, `reviewee_id`, `rating SMALLINT (1..5)`, `comment VARCHAR(1000)`, `created_at`, `updated_at`.
  - Check constraints: `chk_reviews_rating`, `chk_reviews_reviewer_not_reviewee`.
  - Unique constraint: `ux_reviews_order_reviewer (order_id, reviewer_id)`.
  - Keyset index: `ix_reviews_reviewee_created_desc`.
- **Backend & Frontend**:
  - Đánh giá chỉ cho phép khi đơn hàng `COMPLETED`, người bán không được tự đánh giá mình.
  - Tích hợp aggregate rating (`rating_average`, `review_count`) vào hồ sơ người bán mà không sinh N+1 query.
  - Bảo mật danh tính: không để lộ thông tin nhạy cảm của người mua trong reviews công khai.
- **Verification**: 12/12 reviews tests PASSED, 239 regression tests PASSED.

### Phase 5: Đấu giá (Auctions) [VERIFIED 100%]
- **Database Schema & Constraints**:
  - `auctions` table: `starting_price`, `bid_step`, `starts_at`, `ends_at`, `status` (`SCHEDULED`, `ACTIVE`, `ENDED`, `CANCELLED`), `winner_id`, `final_price`, `winner_checkout_deadline`.
  - `auction_bids` table: `bid_id`, `auction_id`, `bidder_id`, `amount`, `created_at`.
  - Partial unique index: `ux_auctions_product_active` đảm bảo 1 sản phẩm chỉ có tối đa 1 phiên đấu giá active/scheduled tại 1 thời điểm.
- **Backend & Realtime**:
  - Khóa bản ghi `auctions` bằng `FOR UPDATE` trong transaction khi đặt bid chống race condition.
  - Không cho phép seller tự bid sản phẩm của chính mình.
  - Worker quét tự động kích hoạt phiên khi đến `starts_at` và chốt người thắng khi quá `ends_at`.
  - Winner checkout: tạo đơn hàng theo giá thắng và deadline quy định.
- **Verification**: 25/25 auction tests PASSED, WebSocket stress tests PASSED.

### Phase 4, 4A & Follow-ups: Đơn hàng & Thanh toán (Orders & Payment) [VERIFIED 100%]
- **Database Schema & Flow**:
  - `orders`, `order_items`, `order_status_history`, thông tin tài khoản ngân hàng nhận tiền tích hợp trực tiếp trên `users` và snapshot trên `orders` (không sử dụng bảng riêng `bank_accounts`, xem `DB_v7.md`).
  - Giữ tồn kho nguyên tử (`reserved_stock`) khi đặt hàng, giải phóng khi hủy đơn.
  - Hỗ trợ thanh toán VietQR với tài khoản ngân hàng xác thực, tiền mặt khi nhận hàng (Cash on Delivery/Meetup).
  - Worker tự động hủy đơn khi quá hạn thanh toán/xác nhận.

### Phase 0, 1, 2, 3: Nền tảng, Xác thực, Sản phẩm & Yêu thích [VERIFIED 100%]
- Kiến trúc FastAPI + SQLAlchemy 2 async + PostgreSQL 15 + Alembic.
- Firebase Auth integration và role-based access control.
- Danh mục sản phẩm đa cấp, quản lý hình ảnh sản phẩm qua Cloudinary.
- Tính năng Favorites lưu tin yêu thích, đồng bộ tức thì.

---

## 3. Lịch sử các đợt ổn định & Bugfix trước Phase 8 (Pre-Phase-8 Passes)

### Pre-Phase-8 Pass 1: Polish giao diện SYSTEM message & Điều hướng trang cá nhân [VERIFIED 100%]
- Refine giao diện tin nhắn hệ thống nhóm sang tông màu Burgundy/Gold/Cream nhẹ nhàng.
- Khắc phục lỗi rò rỉ label `"generic"` khi quay lại từ hồ sơ công khai sang trang cá nhân (`getSafeBackAction` trong `navigation.ts`).

### Pre-Phase-8 Pass 2: Thu hồi quyền truy cập Realtime khi bị gỡ khỏi nhóm [VERIFIED 100%]
- Phát tán sự kiện `GROUP_MEMBERSHIP_CHANGED` với `action="REMOVED"` tới thành viên bị gỡ bỏ sau khi DB transaction commit.
- Frontend hủy in-flight queries, xóa cache cuộc trò chuyện, điều hướng an toàn về `/messages`.
- Chặn vòng lặp retry vô tận khi gặp 403/404 (`isAccessRevokedError`).

### Pre-Phase-8 Pass 3: Đồng bộ số lượng tệp đính kèm Realtime [VERIFIED 100%]
- Cập nhật tức thì bộ đếm summary (`media_count`, `audio_count`, `file_count`) ngay khi gửi tệp thành công qua optimistic delta kết hợp PostgreSQL reconciliation.
- Ngăn chặn double-count trên self-echo bằng so sánh `sender_id`.

### Pre-Phase-8 Pass 4: Tải tệp tin cậy & Nút tải video trên di động [VERIFIED 100%]
- Triển khai streaming endpoint RFC 5987 / RFC 6266 bảo toàn tên tiếng Việt Unicode và phần mở rộng gốc.
- Cơ chế Capability Download Ticket (TTL 60s) lưu hash trên Redis, dùng 1 lần (GETDEL), kiểm tra lại quyền thành viên hiện tại khi tiêu thụ ticket.
- Bổ sung nút "Tải xuống" rõ ràng cho video trên giao diện web/mobile.

### Pre-Phase-8 Pass 5: Hoàn thiện hiển thị icon tệp & Nút tải ảnh từ Chat [VERIFIED 100%]
- Tách bạch `fileVisuals.ts` và component `FileTypeIcon.tsx`. Phân loại màu sắc và badge sắc nét theo từng họ tệp (PDF, Word, Excel, PowerPoint, Archive, Code, Generic).
- Tích hợp nút "Tải xuống" trực tiếp trên modal xem trước ảnh trong bong bóng chat, tái sử dụng luồng download ticket an toàn.

---

## 4. Phase 8F — Báo cáo vi phạm (Reports) & Tiền đề Phase 8G [VERIFIED 100%]

### Phase 8F: Báo cáo vi phạm (User-Facing Reports)
- **Database Schema**: Tạo bảng `reports` theo đúng `DB_v7.md` §2.17 (migration `dee714fefa43`).
- **Backend Domain**:
  - Khai báo canonical enums `ReportTargetType`, `ReportReason`, `ReportStatus`.
  - Ma trận lý do duy nhất `REPORT_REASON_MATRIX` cho USER, PRODUCT, ORDER.
  - Tái sử dụng canonical access rules cho từng loại đối tượng.
  - Kiểm tra trùng lặp báo cáo `OPEN` hoặc `REVIEWING` (409 Conflict).
  - Phản hồi privacy-safe loại bỏ hoàn toàn `reporter_id`, `handled_by`, `handled_at`.
  - Bất biến: Không thay đổi trạng thái miền, không tạo thông báo hay realtime.
- **Frontend Integration**:
  - Giao diện `ReportModal.tsx` tích hợp trên `ProductDetailPage`, `PublicProfilePage`, `OrderDetailPage`.
  - Toast thông báo phản hồi "Đã gửi báo cáo. Ban quản trị sẽ xem xét.".

### Group Invite Notifications & Prefix FTS Polish
- **Group Invite Notification**: Sắp xếp giao dịch nguyên tử khi mời thành viên nhóm (`POST /api/v1/conversations/{id}/invites`), tạo bản ghi `notifications` loại `SYSTEM` (`ref_type="GROUP_INVITE"`), phát realtime `GROUP_INVITE_CREATED` và `NOTIFICATION_CREATED`.
- **Community Logo & Direct Purchase Price Wrap**: Avatar nhóm COMMUNITY hiển thị logo chữ "P" chuẩn thương hiệu; chuẩn hóa hiển thị giá `formatVND` kèm `whitespace-nowrap` trên màn hình hẹp (360px - 430px).
- **PostgreSQL Prefix FTS & Debounce Search**: Chuẩn hóa Unicode NFC, phân tích lexeme an toàn tránh lỗi cú pháp tsquery syntax error; Frontend debounce 300ms hỗ trợ gõ tiếng Việt có dấu IME an toàn.

---

## 5. Phase 8G — Kiểm duyệt báo cáo vi phạm, Quyền hạn tài khoản & Đơn hàng (Admin Moderation & Capabilities) [VERIFIED 100%]

### Phase 8G-B1: Admin User Enforcement
- Khóa (`USER_BAN`) và Mở khóa (`USER_UNBAN`) tài khoản người dùng từ báo cáo vi phạm.
- Cô lập sản phẩm của người dùng bị khóa khỏi feed công khai và danh sách yêu thích, chặn tạo đơn hàng và tham gia đấu giá.
- Kiểm tra tính hợp lệ trạng thái đối tượng, bảo vệ tài khoản Quản trị viên khỏi chế tài kiểm duyệt.

### Phase 8G-B2: Admin Product Enforcement & Simplified Moderation UX
- Phân tách rành mạch trạng thái kinh doanh (`Product.status`) và trạng thái kiểm duyệt (`Product.moderation_status`: `CLEAR`, `BLOCKED`).
- Ẩn tin đăng vi phạm (`PRODUCT_HIDE`) và Hồi sinh tin (`PRODUCT_RESTORE`). Tự động hủy nguyên tử phiên đấu giá `ACTIVE`/`SCHEDULED` của tin vi phạm sang `CANCELLED`, chuyển `listing_type = FIXED_PRICE`, bảo lưu toàn bộ lượt bid lịch sử.
- Đơn giản hóa UX hàng đợi kiểm duyệt: 3 tab ("Tất cả", "Cần xử lý", "Đã xử lý"), loại bỏ các badge kết luận thừa.

### Phase 8G-B3 & Post-Implementation Polish: Clean Moderation Workflow + Subject Report History + Order Enforcement + Capability Restrictions
- **Clean Two-Step Moderation Workflow**:
  - Bước 1 (Xem xét & Đánh giá): Quản trị viên chọn [ Bỏ qua ] (`status = REJECTED`) hoặc [ Ghi nhận vi phạm ] (chuyển sang bước chọn chế tài trên UI cục bộ, không biến đổi trạng thái báo cáo trong CSDL).
  - Bước 2 (Thực thi chế tài): Tin đăng chỉ hiển thị [ Ẩn tin đăng ]; Người dùng & Đơn hàng hiển thị [ Hạn chế quyền... ] và [ Khóa tài khoản ].
  - Nút Back điều hướng: Duy nhất một nút điều hướng "← Quay lại xem xét" bên phải tiêu đề "CHỌN BIỆN PHÁP XỬ LÝ", đã loại bỏ hoàn toàn nút "Quay lại" trùng lặp ở góc dưới bên trái.
  - Phân tách rành mạch với nút "Quay lại báo cáo trước" của ngăn xếp modal lịch sử (`reportStack`).
- **Subject Report History & Modal Stacking**:
  - Endpoint `GET /api/v1/admin/users/{user_id}/report-history` hỗ trợ phân trang cursor, exclude current report ID, giới hạn số lượng an toàn.
  - `SubjectReportHistoryCard` hiển thị tối đa 3 báo cáo trước đây kèm số lượng minh chứng và kết quả chế tài; nhấp vào báo cáo lịch sử đẩy vào stack (`reportStack`) với nút "Quay lại báo cáo trước", không làm thay đổi tab bộ lọc hàng đợi bên dưới.
- **Account Capability Restrictions (Hạn chế quyền tài khoản sinh viên)**:
  - Bảng `user_capability_restrictions` (22 bảng CSDL, migration `820160377ff1`).
  - Chính sách thời hạn mới: Cho phép đúng 4 mức thời hạn sinh viên ngắn hạn thân thiện: `1 ngày`, `3 ngày` (mặc định), `7 ngày`, `14 ngày`.
  - Loại bỏ hoàn toàn tùy chọn 30 ngày, 90 ngày và "Không thời hạn" (`null`) đối với mọi lệnh tạo mới.
  - Backend xác thực nghiêm ngặt (`duration_days` bắt buộc thuộc `(1, 3, 7, 14)` cho `CAPABILITY_RESTRICT`), cấm `null` hoặc bỏ trống (422). Server tự động tính `expires_at = starts_at + duration_days`.
  - Giữ tương thích ngược với các bản ghi `expires_at IS NULL` cũ nếu có trong CSDL (đọc/kiểm tra hiệu lực/thu hồi bình thường, không sửa đổi cấu trúc CSDL).
  - Quyền Mua (`BUY`): Chặn tạo đơn hàng, chặn đặt giá đấu, chặn checkout thắng cuộc.
  - Quyền Bán (`SELL`): Chặn đăng tin, chặn tạo đấu giá; tự động hủy phiên đấu giá active/scheduled, chuyển fixed price, ẩn tin khỏi favorites người mua.
  - Thu hồi (`CAPABILITY_RESTORE`): Khôi phục quyền từ báo cáo gốc, sản phẩm tự động hiển thị trở lại.
- **Default Admin Queue State**:
  - Truy cập `/admin/reports` mặc định vào tab "Cần xử lý" (`queue_state=NEEDS_ACTION`) ngay từ lần render đầu tiên, không nhấp nháy "Tất cả".
  - Yêu cầu API gửi chính xác `queue_state=NEEDS_ACTION`.
  - Tôn trọng điều hướng lịch sử trình duyệt, lựa chọn tab rõ ràng (`Tất cả`, `Đã xử lý`).
  - Đóng modal hoặc duyệt ngăn xếp lịch sử không làm mất trạng thái hàng đợi đang chọn.
  - Khi hàng đợi không có báo cáo cần xử lý, hiển thị trạng thái rỗng "Không có báo cáo nào cần xử lý." thay vì tự động chuyển sang Tất cả.

---

## 6. Phase 8H — Tương tác Cộng đồng (Community Engagement)

### Phase 8H-A: Khoảnh khắc Sinh viên trên Hero (Community Hero Moments) [VERIFIED 100%]
- **Mục tiêu sản phẩm**:
  - Trải nghiệm gửi ảnh khoảnh khắc sinh viên di động (Mobile-first Community Moments) trực tiếp từ Hero carousel.
  - Phê duyệt trực tiếp bởi Admin người thật (không dùng AI, không chấm điểm tự động).
  - Tự động xoay vòng trên Hero trang chủ (tối đa 5 ảnh đã duyệt mới nhất), backfill các vị trí còn lại bằng ảnh Hero tĩnh mặc định.
  - Chống spam: Mỗi người dùng chỉ được có tối đa 1 ảnh ở trạng thái `PENDING`.
- **Database Schema & Alembic Migration (`41154769d8c9_create_community_moments_table.py`)**:
  - Bảng `community_moments` (23 bảng CSDL, baseline head `820160377ff1` -> `41154769d8c9`).
  - Cột: `moment_id BIGSERIAL PK`, `uploader_id INT FK -> users`, `image_url VARCHAR(1000)`, `storage_key VARCHAR(255)`, `mime_type VARCHAR(50)`, `size_bytes INT`, `status VARCHAR(20) DEFAULT 'PENDING'`, `reviewed_by INT FK -> users NULL`, `reviewed_at TIMESTAMP NULL`, `created_at`, `updated_at`.
  - Check constraint: `chk_community_moments_status IN ('PENDING', 'APPROVED', 'REJECTED')`.
  - Partial UNIQUE index: `uq_community_moments_user_pending UNIQUE (uploader_id) WHERE (status = 'PENDING')`.
  - Indexes: `idx_community_moments_hero (reviewed_at DESC, moment_id DESC) WHERE (status = 'APPROVED')`, `idx_community_moments_admin_status_created (status, created_at DESC, moment_id DESC)`, `idx_community_moments_uploader (uploader_id)`.
  - Tuyệt đối không có trường văn bản (`caption`, `note`, `title`, `description`).
  - Round-trip migration verify: `downgrade -1` -> `upgrade head` -> `alembic check` clean 0 drift.
- **Backend Services & API Endpoints**:
  - Tái sử dụng bộ kiểm thực magic bytes tập trung `validate_image_bytes` (JPEG, PNG, WebP, max 10MB, chống file thực thi/giả mạo).
  - Tích hợp Cloudinary: Lưu trữ tại thư mục `student-marketplace/community-moments/`, bọc xóa bù trừ `best-effort compensation cleanup` nếu insert CSDL thất bại.
  - Ánh xạ lỗi chính xác: Chỉ lỗi vi phạm duy nhất `uq_community_moments_user_pending` mới map sang 409 `COMMUNITY_MOMENT_PENDING`. Các lỗi khác rollback sạch sẽ và trả lỗi phù hợp.
  - Endpoint `POST /api/v1/community-moments`: Nhận form-data `file`, kiểm tra quyền sinh viên `ACTIVE`, upload Cloudinary, insert CSDL.
  - Endpoint `GET /api/v1/community-moments/hero`: Công khai, giới hạn 5 ảnh `APPROVED` mới nhất, bảo mật danh tính (không lộ `uploader_id`, `storage_key`, `reviewed_by`), URL qua biến đổi Cloudinary `f_auto,q_auto,w_1200`.
  - Endpoints Admin (`/api/v1/admin/community-moments`): Yêu cầu role `ADMIN`, phân trang keyset theo cursor Base64URL, chi tiết, duyệt (`/approve`) và từ chối (`/reject`) với khóa hàng `FOR UPDATE`.
- **Frontend Architecture & Mobile UX**:
  - `HeroCarousel.tsx`: Tích hợp query `usePublicHeroMoments`, hợp nhất tối đa 5 slide khoảnh khắc và slide tĩnh. Cơ chế clamping an toàn `activeIndex` khi danh sách slide thay đổi, ngăn ngừa màn hình trắng hoặc lỗi timer closure.
  - Nút chụp ảnh / Camera icon: Đặt tại góc dưới-phải của Hero, kích thước touch target đạt chuẩn di động >= 44x44 CSS px (`w-11 h-11`), không chồng lấn nút điều hướng (mũi tên), chấm phân trang (pagination dots) hay tiêu đề chữ.
  - Xử lý xác thực: Người dùng chưa đăng nhập chạm vào camera sẽ kích hoạt luồng đăng nhập chuẩn (`#auth-card`), không tự tạo modal đăng nhập phụ.
  - `CommunityUploadModal.tsx`: Chọn ảnh, xem trước, hiển thị dung lượng/kích thước, tự giải phóng Object URL (`revokeObjectURL`), xử lý lỗi 409 bằng Toast thông báo thân thiện.
  - Trang quản trị `/admin/community-moments`: Hàng đợi 3 tab ("Chờ duyệt", "Đã duyệt", "Đã từ chối"), phân trang keyset, modal xem ảnh lớn, duyệt và từ chối một chiều.
  - TanStack Query: Invalidate đồng thời `communityMomentKeys.adminAll()` và `communityMomentKeys.hero()` ngay khi Admin duyệt, giúp tab người dùng lập tức thấy ảnh mới khi quay lại Trang chủ.
  - Header: Thêm link "Ảnh cộng đồng" trong menu QUẢN TRỊ cho tài khoản ADMIN.
- **Verification**:
  - `tests/test_community_moments.py`: 13/13 tests PASSED.
  - Full backend test suite: 689/689 tests PASSED, 0 failed in 111.66s.
  - Frontend build: `npm run build` PASSED (0 errors, 9.25s).
  - Database schema: 23 tables, Alembic head `41154769d8c9`, 0 drift.

### Phase 8H-A.1: Bổ sung Lời nhắn Khoảnh khắc Hero (Community Hero Note Amendment) [VERIFIED 100%]
- **Mục tiêu sản phẩm**:
  - Bổ sung trường lời nhắn ngắn gọn (`note`) gắn liền với mỗi ảnh khoảnh khắc sinh viên mới được gửi lên.
  - Hiển thị lời nhắn tinh tế ở góc dưới bên trái của slide Hero, bảo toàn layout di động (360px - 430px) và không che khuất cụm điều hướng (mũi tên), phân trang (dots) hay nút camera.
  - Duyệt song song ảnh và lời nhắn: Admin nhìn thấy cả hai khi duyệt.
  - Tương thích ngược: Cho phép `note = NULL` với các ảnh đã duyệt trong quá khứ mà không chèn chữ giả.
- **Database Schema**:
  - Cột `community_moments.note VARCHAR(80) NULL` qua migration `baf84a486cb8`.
- **Backend & Validation**:
  - `validate_community_note`: Bắt buộc với lượt gửi mới, độ dài 1..80 ký tự, chuẩn hóa Unicode NFC, cấm ký tự điều khiển xuống dòng (CR/LF), cấm toàn khoảng trắng.
  - Serializer công khai trả về `note` cho Hero carousel và admin detail.
- **Frontend & Responsive Design**:
  - `CommunityUploadModal.tsx`: Input 1 dòng, counter `X / 80`, chặn phím Enter, cỡ chữ mobile >= 16px chống iOS zoom.
  - `HeroCarousel.tsx`: Overlay đè `bg-black/50 backdrop-blur-xs border border-white/15 px-2.5 py-1 rounded-lg text-xs sm:text-sm text-white drop-shadow-md truncate`, độ rộng tính toán chính xác `max-w-[calc(50%-24px)]` đảm bảo không bao giờ chạm đến dots ở giữa hay camera ở bên phải.

### Phase 8H-B: Phản hồi website (Site Feedback), Marquee nổi bật, Profile Người sáng lập & VietQR Ủng hộ [VERIFIED 100%]
- **Mục tiêu sản phẩm**:
  - Kênh thu thập phản hồi, đóng góp ý kiến chính thống của sinh viên cho nền tảng Chợ PTITers.
  - Marquee hiển thị tối đa 10 Feedback nổi bật mới nhất được Admin tuyển chọn.
  - Thẻ giới thiệu Người phát triển Chợ PTITers (Nguyễn Khắc Thịnh) liên kết với trang cá nhân công khai (`/users/:id`).
  - Thẻ thông tin ủng hộ duy trì máy chủ qua mã VietQR an toàn với thông điệp "Quan trọng là tấm lòng 💛".
- **Database Schema & Migration (`baf84a486cb8`)**:
  - Bảng `site_feedback` (24 bảng CSDL):
    - `feedback_id BIGSERIAL PK`
    - `user_id BIGINT NOT NULL UNIQUE FK -> users(user_id) ON DELETE CASCADE`
    - `rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5)`
    - `content VARCHAR(300) NOT NULL`
    - `status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'))`
    - `is_featured BOOLEAN NOT NULL DEFAULT FALSE`
    - `featured_at TIMESTAMPTZ NULL`
    - `reviewed_by BIGINT NULL FK -> users(user_id) ON DELETE SET NULL`
    - `reviewed_at TIMESTAMPTZ NULL`
    - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
    - `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
  - Indexes:
    - `uq_site_feedback_user_id UNIQUE (user_id)` (1 user = 1 feedback duy nhất).
    - `idx_site_feedback_admin_status_updated (status, updated_at DESC, feedback_id DESC)` (Ưu tiên hàng đợi duyệt theo phiên bản chỉnh sửa mới nhất).
    - `idx_site_feedback_featured (featured_at DESC, feedback_id DESC) WHERE status = 'APPROVED' AND is_featured = TRUE` (Chỉ index các feedback đủ điều kiện marquee).
- **Backend & Race-Safe Architecture**:
  - Atomic Upsert: Khi người dùng gửi feedback mới hoặc chỉnh sửa, tự động đưa về `status = PENDING`, `is_featured = FALSE`, `featured_at = NULL`, `reviewed_by = NULL`, `reviewed_at = NULL`, và cập nhật server `updated_at`.
  - Stale-Review Concurrency Protection: Yêu cầu Admin gửi kèm `expected_updated_at`. Khóa dòng `SELECT ... FOR UPDATE`, so sánh với `updated_at` hiện tại trong DB. Nếu lệch, trả về `409 Conflict` mã `FEEDBACK_CHANGED`. Admin bắt buộc phải xem lại nội dung người dùng mới sửa trước khi quyết định duyệt/từ chối.
  - VietQR Builder tập trung: Chuẩn hóa tham số mã hóa an toàn, không hardcode số tiền, thông điệp "Quan trọng là tấm lòng 💛" là UI copy, URL ảnh VietQR an toàn không phơi bày API tài khoản ngân hàng thô.
  - Cấu hình Creator an toàn: Biến `COMMUNITY_CREATOR_USER_ID` (mặc định `None`), không hardcode ID 10 hay tên tác giả trong code, fallback mượt mà nếu chưa cấu hình.
- **Frontend & UI/UX**:
  - Thứ tự trang `/feedback` chuẩn mobile-first: (1) Form gửi feedback, (2) Marquee feedback nổi bật, (3) Thẻ người phát triển, (4) Thẻ VietQR ủng hộ.
  - Marquee: Web Animations API mượt mà, tạm dừng khi hover chuột trên thiết bị có chuột (`(hover: hover) and (pointer: fine)`), không bị kẹt đứng trên màn hình cảm ứng, hỗ trợ `prefers-reduced-motion: reduce` với danh sách cuộn ngang tĩnh.
  - Thẻ người phát triển: Dữ liệu động hoàn toàn từ backend (`support.creator.full_name`, `avatar_url`), link sang trang `/users/:id`.
  - Thẻ VietQR: Hiển thị mã QR rõ nét, modal phóng to xem toàn màn hình.
  - Trang quản trị `/admin/feedback`: Thẻ hàng đợi gọn gàng trên mobile (`line-clamp-2`), mặc định tab "Chờ duyệt", mở `AdminFeedbackDetailModal` xem toàn bộ nội dung, duyệt/từ chối chống race stale-review, đưa lên/gỡ khỏi marquee.
  - Menu: Thêm link "Feedback" trong menu TÀI KHOẢN và link "Duyệt Feedback" trong menu QUẢN TRỊ.
- **Verification**:
  - `tests/test_community_moments.py`: 13/13 tests PASSED.
  - `tests/test_feedback.py`: 11/11 tests PASSED (bao gồm stale admin approval 409 test và concurrent edit race test).
  - `tests/test_worker_hardening.py` (Phase 9A): 13/13 tests PASSED.
  - Full backend test suite: 700/700 tests PASSED, 0 failed in 173.21s.
  - Frontend build: `npm run build` PASSED (0 errors, 12.16s).
  - Database schema: 24 tables, Alembic head `baf84a486cb8`, 0 drift.

### Phase 8H-B.1: Tái thiết kế Feedback Website (Public Issue Feedback + Private Evidence + Hard Delete + Fixed VietQR) [VERIFIED 100%]
- **Chuyển đổi triết lý sản phẩm (Product Policy Redesign)**:
  - Loại bỏ hoàn toàn mô hình review/rating: bỏ số sao (1..5 rating), bỏ quy trình tiền kiểm duyệt của Admin (`PENDING`/`APPROVED`/`REJECTED`), bỏ cờ nổi bật (`is_featured`), bỏ marquee chuyển động.
  - Thiết kế mới: Bảng góp ý & báo lỗi cộng đồng công khai (issue/feedback board). Feedback hiển thị công khai ngay sau khi gửi thành công.
  - Hỗ trợ nhiều Feedback trên mỗi người dùng: Đã loại bỏ ràng buộc `UNIQUE(user_id)`. Mỗi lần gửi là một bản ghi độc lập, không có cơ chế update/upsert đè lên feedback cũ.
  - Tính bất biến (Immutable): Feedback không cho phép chỉnh sửa sau khi gửi để bảo toàn tính toàn vẹn của lịch sử và minh chứng.
  - Xóa vĩnh viễn (Hard Delete): Tác giả có quyền xóa feedback của mình (`DELETE /api/v1/feedback/{id}`). Quản trị viên có quyền xóa bất kỳ feedback nào (`DELETE /api/v1/admin/feedback/{id}`).
  - Xóa cascade DB (`site_feedback_attachments` tự động xóa) và dọn dẹp Cloudinary best-effort sau khi commit DB thành công. An toàn khi xóa đồng thời.
- **Minh chứng riêng tư (Private Evidence Attachments)**:
  - Tạo bảng `site_feedback_attachments`: `attachment_id`, `feedback_id`, `kind` (`IMAGE` / `VIDEO`), `media_url`, `storage_key`, `mime_type`, `size_bytes`, `duration_ms`, `created_at`.
  - Giới hạn: Tối đa 3 ảnh (JPEG, PNG, WebP <= 10MB/ảnh) và tối đa 1 video (MP4, WebM, MOV <= 30MB, thời lượng <= 60 giây).
  - Kiểm tra nghiêm ngặt: Magic bytes, MIME type, dung lượng tệp, thời lượng video từ metadata server-side Cloudinary, cơ chế bồi hoàn (compensation cleanup) khi upload lỗi.
  - Bảo mật danh tính công khai: Bảng tin công khai chỉ trả về `feedback_id`, `content`, `created_at`. Tuyệt đối không lộ danh tính tác giả, số lượng đính kèm hay URL minh chứng.
  - Quản trị viên xem đầy đủ danh tính và minh chứng: Hỗ trợ streaming video an toàn với HTTP Range 206 để tua mượt mà.
- **Tài khoản Creator & VietQR cố định**:
  - Khảo sát và xác minh tài khoản từ email `thinhconngua@gmail.com`: Khớp chính xác `user_id = 10`, vai trò `ADMIN`, trạng thái `ACTIVE`, provider `FIREBASE`.
  - Thiết lập cấu hình nội bộ cố định `COMMUNITY_CREATOR_USER_ID = 10`. Tuyệt đối không để lộ email ra API công khai.
  - Dừng sinh VietQR động ở runtime: Sử dụng tài sản ảnh tĩnh cố định `student-marketplace-fe/public/support/nguyen-khac-thinh-vietqr.png`.
  - Thẻ người phát triển hiển thị tên từ DB, vai trò cố định "Người phát triển Chợ PTITers", link sang hồ sơ `/users/10`. Thẻ ủng hộ hiển thị thông điệp "Quan trọng là tấm lòng 💛".
- **Verification**:
  - `alembic check`: 0 drift (Revision `eeb83ca4d13e`). Downgrade -1 và upgrade head roundtrip PASS.
  - `tests/test_feedback.py`: 14/14 tests PASSED.
  - `tests/test_worker_hardening.py` (Phase 9A): 13/13 tests PASSED (bảo toàn 100%).
  - `tests/test_report_evidence.py` & `test_admin_reports.py`: 50/50 tests PASSED.
  - Full backend test suite: 703/703 tests PASSED in 139.84s (0:02:19).
  - Frontend build: `npm run build` PASSED (0 errors, 23.07s).

### Post-8H-B.1: Ổn định Điều hướng Mobile & UI Quản trị / Feedback (Mobile Admin & Feedback Stabilization) [VERIFIED 100%]
- **Khắc phục lỗi trạng thái active trên Mobile Navigation Drawer (`Header.tsx`)**:
  - Loại bỏ các class highlight cố định trên mục "Đăng tin bán" (`/products/new`) và nhóm menu "Quản trị" (`/admin/...`).
  - Áp dụng khớp route chính xác theo `location.pathname`: "Đăng tin bán" chỉ active duy nhất khi ở `/products/new`; mỗi mục trong Quản trị (`/admin/reports`, `/admin/community-moments`, `/admin/feedback`) chỉ active khi đang duyệt đúng route tương ứng; khi ở bất kỳ trang quản trị nào, "Đăng tin bán" luôn ở trạng thái inactive.
  - Thêm thuộc tính semantic `aria-current="page"` trên mục active. Đồng bộ style nhãn tiêu đề các nhóm (TIN ĐĂNG, GIAO DỊCH, LIÊN LẠC, TÀI KHOẢN, QUẢN TRỊ) dạng chữ mờ `text-brand-text-muted`.
- **Thống nhất nhận diện Header Quản trị (`AdminPageHeader.tsx`)**:
  - Tạo component dùng chung `AdminPageHeader` cho 3 trang Quản trị (Kiểm duyệt báo cáo, Ảnh cộng đồng, Feedback người dùng).
  - Chuẩn hóa khung icon tile kích thước `h-10 w-10`, bo tròn `rounded-xl`, nền nhẹ `bg-brand-soft-pink/80 border border-brand-burgundy/15 text-brand-burgundy shadow-2xs`, kích thước glyph `h-5 w-5`.
  - Chuẩn hóa phân cấp chữ: Tiêu đề `text-lg sm:text-xl font-bold text-brand-text`, phụ đề `text-xs sm:text-sm text-brand-text-muted`.
- **Tinh chỉnh Typography trang Feedback (`FeedbackPage.tsx`)**:
  - Gỡ bỏ hoàn toàn badge chữ hoa trang trí `"GÓP Ý & BÁO LỖI"`.
  - Giữ vững thông điệp chính: *"Bọn mình nhận gạch đá để xây chợ vững chắc hơn"* với font chuẩn ứng dụng `font-bold text-xl sm:text-2xl text-brand-text`.
  - Chuyển đổi các tiêu đề phân mục sang sentence case: "Mọi người đang góp ý", "Feedback của bạn".
- **Khắc phục lỗi không tải được ảnh minh chứng Feedback trong modal Admin (`AdminFeedbackDetailModal.tsx`)**:
  - Xử lý nguyên nhân thẻ `<img>` native không gửi `Authorization` header dẫn đến lỗi 401: Bổ sung hàm `getAdminFeedbackEvidenceBlob` trong `src/features/feedback/api.ts` tải dữ liệu ảnh nhị phân dạng Blob qua `apiClient` có kèm Bearer token, chuyển thành `URL.createObjectURL(blob)` và giải phóng bộ nhớ `URL.revokeObjectURL(blob)` khi unmount/đóng modal.
  - Bổ sung modal phóng to ảnh gốc (Image Lightbox) kèm nút đóng và phím tắt Escape.
  - Chuẩn hóa backend `stream_feedback_evidence` sử dụng dependency dùng chung `get_admin_for_evidence`, hỗ trợ xác thực cả qua Bearer header lẫn query param `?token=` phục vụ stream video HTTP Range 206 native.
- **Verification**:
  - `tests/test_feedback.py`: 15/15 tests PASSED (bổ sung test xác thực stream qua Bearer và `?token=`).
  - `tests/test_report_evidence.py` & `test_admin_reports.py`: 50/50 tests PASSED.
  - `tests/test_worker_hardening.py` (Phase 9A): 13/13 tests PASSED (bảo toàn 100%).
  - Full backend test suite: 704/704 tests PASSED in 127.99s (0:02:07).
  - Frontend build (`npm run build`): PASSED 0 errors in 5.75s.
  - Alembic check: `eeb83ca4d13e` clean 0 drift (29 tables).

### Phase 8H-A.2: Vòng đời Bounded Hero & Touch Crop Mobile-First (Community Hero Bounded Lifecycle + Touch Crop) [VERIFIED 100%]
- **Vòng đời Giới hạn & Xóa Vĩnh viễn (Bounded Lifecycle & Hard Delete)**:
  - Giới hạn cứng tối đa 5 khoảnh khắc `APPROVED` trên Hero Carousel toàn hệ thống.
  - Bảo vệ bất biến đồng thời bằng PostgreSQL transactional advisory lock (`COMMUNITY_HERO_LOCK_NAMESPACE = "community_hero_lifecycle"`).
  - Phê duyệt bản ghi thứ 6 (`approve_moment`): Tự động cắt tỉa (prune) các bản ghi APPROVED cũ nhất (`reviewed_at ASC, moment_id ASC`) bằng Hard Delete khỏi cơ sở dữ liệu và dọn dẹp asset Cloudinary sau khi commit DB thành công.
  - Từ chối duyệt (`POST /api/v1/admin/community-moments/{id}/reject`): Thực hiện Hard Delete khỏi DB ngay lập tức, dọn dẹp asset Cloudinary post-commit, trả về `CommunityMomentActionResponse` (`status: "REJECTED"`), giải phóng slot PENDING cho sinh viên.
  - Quản trị viên gỡ khỏi Hero (`DELETE /api/v1/admin/community-moments/{id}`): Khóa advisory lock, Hard Delete khỏi DB, dọn dẹp Cloudinary post-commit, trả về `CommunityMomentActionResponse` (`status: "DELETED"`).
  - Không lưu trữ dữ liệu lịch sử Hero (no historical hero archive). Ràng buộc vật lý `chk_community_moments_status IN ('PENDING', 'APPROVED', 'REJECTED')` được giữ lại cho tính tương thích ngược, tầng nghiệp vụ ứng dụng chỉ vận hành 2 trạng thái `PENDING` và `APPROVED`.
- **Client-Side Touch Crop Mobile-First (Không Thanh Zoom)**:
  - Tỉ lệ Hero chuẩn hóa: Khóa cố định tỉ lệ `7:3` (`21/9`) đồng nhất trên mọi breakpoint, loại bỏ `max-h-72` gây méo khung.
  - Kích thước xuất ảnh canvas: Chuẩn `1400x600px` (ngưỡng tối thiểu `350x150px`), tuân thủ chính sách downscale không nội suy phóng đại (no-upscale), nền trắng đục chống lỗi kênh alpha.
  - Mobile touch UX: Kéo 1 ngón tay để dịch chuyển khung hình, chụm 2 ngón tay (pinch-to-zoom) để phóng to/thu nhỏ, chuột kéo và lăn con trỏ (wheel) trên desktop.
  - Tuyệt đối không có thanh trượt zoom (slider/range input) hay các nút +/- zoom.
  - Văn bản hướng dẫn súc tích: *"Kéo ảnh để chọn vùng hiển thị • Chụm 2 ngón tay để thu phóng"*.
  - Viewport an toàn: Không can thiệp `user-scalable=no` tại meta tag toàn trang.
  - Vòng đời bộ nhớ Object URL: Quản lý nghiêm ngặt qua state machine `PICK` -> `CROP` -> `PREVIEW`, chỉ upload duy nhất tệp đã cắt `croppedFile`, giải phóng bộ nhớ `URL.revokeObjectURL` đầy đủ khi unmount, đóng modal hoặc submit thành công.
- **Loại bỏ Hoàn toàn Ảnh Tĩnh Hero Cũ (Legacy Photo Cleanup)**:
  - Khảo sát 0-reference audit: Xóa bỏ `src/data/heroSlides.ts` và thư mục ảnh tĩnh `public/images/hero/` (`slide1.jpg`, `slide2.jpg`, `slide3.jpg`).
  - Khi hệ thống có 0 ảnh duyệt: Hero hiển thị fallback card thương hiệu thuần CSS sinh động, không tải ảnh tĩnh dự phòng.
  - Khi có 1 ảnh duyệt: Khóa điều hướng dots, mũi tên và dừng autoplay.
- **Dọn dẹp & Tối ưu Cloudinary**:
  - URL Hero responsive nâng cấp lên `w_1400` (`f_auto,q_auto,w_1400`).
  - Chính sách dọn dẹp Cloudinary: Best-effort sau khi DB transaction commit thành công. Lỗi dọn dẹp Cloudinary được log cảnh báo và không rollback DB.
  - Minh chứng Reports, Orders, Products, Conversations media retention giữ nguyên vẹn 100%.
- **Verification**:
  - `tests/test_community_moments.py`: 20/20 tests PASSED (bao gồm 7 test mới kiểm tra upload đơn, reject hard delete, auto prune thứ 6, admin delete, concurrency lock, isolation).
  - `tests/test_feedback.py`: 15/15 tests PASSED.
  - `tests/test_worker_hardening.py` (Phase 9A): 13/13 tests PASSED.
  - Full backend test suite: 711/711 tests PASSED in 123.34s (0:02:03).
  - Frontend build (`npm run build`): PASSED 0 errors in 7.30s.
  - Alembic check: `eeb83ca4d13e` clean 0 drift (29 application tables).

### Post-8H-A.2: Tinh chỉnh Hero 16:9, Hướng dẫn Tải ảnh & Hiển thị Lời nhắn (Post-8H-A.2 — Hero 16:9 + Upload Guidance + Note Rendering Polish) [VERIFIED 100%]
- **Chuyển đổi Tỉ lệ Hero sang Chuẩn Ngang 16:9 (Canonical Landscape 16:9)**:
  - Đồng bộ hoá toàn diện tỉ lệ khung hình Hero: Khóa cố định `16:9` đồng nhất trên mọi điểm chạm: Home Hero container (`aspect-video`), CSS-only branded fallback card (`aspect-video`), viewport cropper (`aspect={16/9}`), khung xem trước (`aspect-video`), và tệp xuất canvas.
  - Loại bỏ hoàn toàn các hằng số và class cũ `21/9`, `7:3`, `aspect-[21/9]`.
  - Kích thước xuất ảnh canvas: Nâng cấp chuẩn tối đa lên `1600x900px` (ngưỡng tối thiểu `320x180px`), giữ vững chính sách downscale không phóng đại (no-upscale), kích thước luôn chia hết cho 16 và 9 để đảm bảo tỉ lệ nguyên vẹn.
  - Tối ưu Cloudinary: Endpoint trả về URL `w_1600` (`f_auto,q_auto,w_1600`). Xác nhận Cloudinary không thực hiện thêm bước cắt xén thứ hai nào (no second crop).
- **Trải nghiệm Tải ảnh Thân thiện & Hướng dẫn Rõ ràng (Student-Friendly Upload UX)**:
  - Tiêu đề modal: *"Chia sẻ ảnh lên Hero"*.
  - Hướng dẫn mục đích xuất hiện nổi bật nhưng tinh tế: *"Ảnh sẽ xuất hiện trên banner Trang chủ sau khi được duyệt. Nên chọn ảnh ngang tỷ lệ 16:9 để hiển thị đẹp nhất."*
  - Hộp chọn ảnh: Tiêu đề *"Chọn ảnh khoảnh khắc"*, phụ đề *"Ưu tiên ảnh ngang 16:9 để hiển thị đẹp trên banner Trang chủ."*, nút *"Chọn ảnh"*.
  - Màn hình cắt ảnh: Tiêu đề *"Chọn vùng hiển thị"*, hướng dẫn cử chỉ *"Kéo ảnh để chọn vùng hiển thị • Chụm 2 ngón tay để thu phóng"* kèm dòng ghi chú *"Khung hiển thị cố định 16:9."*. Không có thanh trượt zoom hay nút +/-.
  - Màn hình xem trước: Dòng giải thích *"Ảnh sẽ hiển thị theo khung 16:9 này sau khi được duyệt."*, hỗ trợ nút `[ Cắt lại ]` và `[ Chọn ảnh khác ]`.
  - Nút gửi duyệt: *"Gửi ảnh chờ duyệt"*, kèm ghi chú hỗ trợ *"Quản trị viên sẽ kiểm tra ảnh trước khi hiển thị trên Trang chủ."*.
- **Sửa Lỗi Hiển thị Lời nhắn (Note Display Bug Fix)**:
  - Khắc phục triệt để lỗi lời nhắn bị tự động bao bọc trong dấu ngoặc kép `"{slide.note}"` trên Hero Carousel, modal chi tiết Admin, và danh sách hàng đợi Admin.
  - Hiển thị chính xác chuỗi ký tự người dùng đã nhập: Input `haha` -> Output hiển thị đúng `haha`.
  - Không bọc dấu ngoặc kép (`"`, `“ ”`, `' '`), không tự động viết hoa (no forced capitalization), không can thiệp biến đổi chữ thường/hoa, bảo toàn trọn vẹn ký tự Unicode/emoji.
  - Bố cục lời nhắn trên khung 16:9 cao hơn: Vị trí góc dưới-trái với độ rộng giới hạn an toàn (`max-w-[calc(50%-16px)]` khi có >1 slide), đảm bảo không bao giờ chồng lấn lên dots điều hướng ở giữa hoặc nút chụp ảnh ở góc phải.
- **Verification**:
  - `tests/test_community_moments.py`: 20/20 tests PASSED.
  - `tests/test_feedback.py`: 15/15 tests PASSED.
  - Full backend test suite: 711/711 tests PASSED.
  - Frontend production build (`npm run build`): PASSED 0 errors in 13.38s.
  - Alembic check: `eeb83ca4d13e` clean 0 drift (29 tables).

---

## 7. Phase 9 — Triển khai Sản xuất & Tối ưu hóa (Production Readiness & Optimization)

### Phase 9A: Đồng bộ hóa Worker & Tăng cường Idempotency / Retry (Worker Synchronization + Retry / Idempotency Hardening) [VERIFIED 100%]
- **Worker Concurrency & Source Audit**:
  - Khảo sát toàn diện 4 tác vụ định kỳ của Worker (`order_auto_cancel.py`): (1) `run_auto_cancel_sweep` (hủy đơn PENDING quá hạn), (2) `run_auction_scheduled_sweep` (kích hoạt/hết hạn phiên SCHEDULED), (3) `run_auction_close_sweep` (đóng phiên ACTIVE, chọn người thắng, giữ hàng), (4) `run_winner_timeout_sweep` (giải phóng tồn kho giữ hàng khi quá hạn checkout người thắng).
  - Khắc phục triệt để lỗi quét lặp vô hạn `get_expired_winner_auctions`: Join `Product` lọc `reserved_stock > 0` và `~exists(Order)` để loại bỏ hoàn toàn các phiên đấu giá đã giải phóng tồn kho hoặc đã tạo đơn hàng khỏi hàng đợi quét của worker.
  - Khắc phục lỗi khởi tạo thiếu mapper trong tiến trình worker độc lập bằng cách import đầy đủ các ORM models (`users`, `categories`, `products`, `orders`, `auctions`, `notifications`) tại entrypoint.
- **Tính Bất biến & Khóa hàng CSDL (Idempotency & Row Locking)**:
  - Khóa bản ghi theo thứ bậc nhất quán tuyệt đối chống deadlock: `Auction FOR UPDATE` -> `Product FOR UPDATE`; `Order FOR UPDATE` -> `Product FOR UPDATE`.
  - Phân tách rành mạch kết quả xử lý: `CHANGED` (có chuyển dịch trạng thái) vs `NO_OP` (bản ghi đã được xử lý bởi worker khác/người dùng).
  - Mọi thao tác lặp lại đều là NO_OP: không tạo thêm lịch sử trạng thái thừa (`order_status_history`), không tạo thông báo người dùng thừa (`Notification`), không phát lại sự kiện realtime.
  - Cuộc đua checkout người thắng vs worker timeout (`test_winner_checkout_vs_timeout_race`): Luôn cho ra kết quả tuần tự hóa nhất quán, không bao giờ xuất hiện đơn hàng với tồn kho bị giải phóng hoặc tồn kho âm.
  - Cuộc đua kiểm duyệt vs worker (`test_auction_moderation_race_no_resurrection`): Phiên đấu giá bị hủy do kiểm duyệt (`CANCELLED`) tuyệt đối không bị worker hồi sinh sang `ACTIVE` hay `ENDED`.
- **Chính sách Retry có Bọc kiểm soát (Transient Retry Policy)**:
  - Module `app/workers/retry.py` phân loại lỗi: Chỉ retry các lỗi tạm thời PostgreSQL (serialization failure `40001`, deadlock `40P01`, mất kết nối mạng `OperationalError`).
  - Lỗi miền nghiệp vụ (`HTTPException`, `ValueError`, `IntegrityError`) thất bại ngay lập tức, không retry mù quáng.
  - Bọc retry giới hạn: tối đa 3 lần (`WORKER_MAX_RETRIES = 3`), backoff lũy thừa (`WORKER_RETRY_BACKOFF_SECONDS = 0.5s`).
  - Giao dịch CSDL luôn được rollback trước khi sleep backoff, retry mở một session mới tinh sạch, tuyệt đối không giữ khóa/connection trong thời gian sleep.
- **Cách ly thất bại & Khởi động / Tắt mượt mà (Failure Isolation & Graceful Shutdown)**:
  - Một dòng bản ghi hỏng/lỗi không làm ngắt chu trình quét của toàn batch; ghi nhận số lượng `failed`, `changed`, `no_op` qua class `SweepResult`.
  - Mất kết nối CSDL toàn cục: Worker tự động backoff 5s, không quay vòng ngốn CPU (busy-loop).
  - Tắt mượt mà (SIGINT/SIGTERM): Hoàn tất chu kỳ hiện tại, đóng Redis connection và engine pool sạch sẽ.
- **Verification**:
  - `tests/test_worker_hardening.py`: 13/13 concurrency & hardening tests PASSED.
  - Focused regressions (orders, auctions, notifications, capabilities, moderation): 135/135 tests PASSED.
  - Full backend suite: 676/676 tests PASSED in 179s.
  - Alembic check: `820160377ff1` clean 0 drift.
  - Worker smoke test (`smoke_worker.py`): 2 chu kỳ chạy thực tế PASS, giải phóng tồn kho chính xác, NO_OP chu kỳ sau, thoát mượt mà.
  - Frontend build (`npm run build`): PASS 0 errors in 12s.

---

### Global Light/Dark Theme System [ROLLED BACK — REPLACED BY LIGHT-ONLY RESTORATION]

> **Ghi chú lịch sử**: Tính năng Dark Mode đã được triển khai đầy đủ và kiểm thử trước đây, tuy nhiên sau đó đã được thu hồi toàn diện (rolled back) theo định hướng sản phẩm. Toàn bộ frontend hiện hoạt động ở chế độ sáng duy nhất (Light-only) để đảm bảo tính nhất quán tối đa về thương hiệu.

- **Kiến trúc CSS Semantic Tokens & Nhận diện Thương hiệu PTITers** (Đã thu hồi):
  - Hệ thống biến CSS custom properties ngữ nghĩa cấp `:root` và `.dark`.
  - Tích hợp Tailwind CSS v4 `@theme`, ánh xạ token thương hiệu.
- **Khởi tạo Chống Nhấp nháy Trước Lần Vẽ Đầu** (Đã gỡ bỏ):
  - Script nội tuyến trong `<head>` của `student-marketplace-fe/index.html` nhận diện `ptiters-theme` hoặc `prefers-color-scheme`.
- **Nút Chuyển đổi Giao diện Tiện lợi** (Đã gỡ bỏ):
  - Thành phần `ThemeToggle.tsx` trên desktop header và mobile drawer.
- **Lưu trữ Cục bộ & Đồng bộ Đa Tab** (Đã gỡ bỏ):
  - Quản lý trạng thái qua `ThemeContext.tsx` với khóa `ptiters-theme`.

---

### Light-Only UI Restoration [COMPLETED & VERIFIED / USER ACCEPTED]
- **Thu hồi toàn diện Dark Mode và chuẩn hoá chế độ sáng duy nhất**:
  - Gỡ bỏ hoàn toàn `ThemeContext.tsx`, `ThemeToggle.tsx`, script khởi tạo theme trong `index.html` và phím tắt chuyển đổi theme.
  - Loại bỏ toàn bộ token `.dark` khỏi `src/index.css`, khôi phục bộ màu thương hiệu Light-only ấm áp (kem ấm `#FFF8F0`, trắng ấm `#FFFCF7`, chữ nâu sẫm `#2D1B14`, đỏ burgundy `#722F37`, hồng nhẹ `#F5E6E0`).
  - Gỡ bỏ thuộc tính `color-scheme: dark` và cố định `color-scheme: light` cùng thẻ meta `<meta name="theme-color" content="#722F37">`.
  - Bảo toàn 100% logic kinh doanh, luồng authentication, các biểu mẫu và giao diện tương tác.
- **Bằng chứng Kiểm chứng**:
  - Frontend production build: `npm run build` (`tsc -b && vite build`) PASS 0 errors.
  - Zero reference audit: Tìm kiếm toàn diện không còn dấu vết của `ThemeContext`, `ThemeToggle`, `ptiters-theme` trong mã nguồn hoạt động.

