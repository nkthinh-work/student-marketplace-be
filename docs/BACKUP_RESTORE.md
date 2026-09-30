# POSTGRESQL BACKUP & RESTORE RUNBOOK — Student Marketplace

Tài liệu vận hành tiêu chuẩn cho việc sao lưu (logical backup), kiểm tra tính toàn vẹn (checksum & manifest) và diễn tập phục hồi (restore drill) cơ sở dữ liệu PostgreSQL cho dự án Student Marketplace.

---

## 1. Mục đích (Purpose)

Cung cấp quy trình an toàn, lặp lại được và đã được kiểm chứng để:
1. Tạo bản sao lưu logic PostgreSQL native (`pg_dump --format=custom`).
2. Tự động kiểm tra tính toàn vẹn dữ liệu lưu trữ (SHA-256 checksum và `pg_restore --list`).
3. Khôi phục thử nghiệm vào một cơ sở dữ liệu cô lập hoàn toàn (`isolated restore target`).
4. Kiểm chứng schema, `alembic_version` và số lượng bản ghi khớp 100% với dữ liệu gốc.
5. Thu dọn an toàn cơ sở dữ liệu tạm sau khi diễn tập thành công.
6. Xác lập ranh giới phục hồi thảm họa rõ ràng giữa PostgreSQL, Redis, Cloudinary và Firebase Auth.

> **Nguyên tắc cốt lõi**: Một bản sao lưu chỉ được coi là đáng tin cậy khi quy trình phục hồi đã được diễn tập thành công trên thực tế (`Restored & Verified`).

---

## 2. Ma trận phạm vi sao lưu (Backup Coverage Matrix)

| Hệ thống | Trạng thái sao lưu | Dữ liệu bao gồm |
| :--- | :--- | :--- |
| **PostgreSQL** | **ĐƯỢC SAO LƯU TOÀN DIỆN** | Toàn bộ 32 bảng nghiệp vụ quan hệ (users, products, categories, product_images, orders, order_items, order_status_history, auctions, auction_bids, reviews, favorites, conversations, conversation_members, conversation_invites, messages, message_attachments, message_reactions, message_mentions, notifications, reports, report_attachments, moderation_actions, user_capability_restrictions, user_auth_identities, daily_needs, daily_journal_checkins, community_moments, site_feedback, site_feedback_attachments, support_contributions, support_claims, tutorials) và bảng hệ thống `alembic_version` (tổng cộng 33 bảng vật lý). |
| **Redis** | **KHÔNG SAO LƯU VÀO DUMP** | Tầng dữ liệu tạm thời/tối ưu hóa (product view buffer, dedupe seen keys, dirty set, Pub/Sub channels, presence, download tickets). Khi phục hồi, khởi tạo Redis mới hoặc làm sạch namespace của ứng dụng. Dữ liệu số lượt xem bền vững được tái cấu trúc từ trường `view_count` trong PostgreSQL. |
| **Cloudinary** | **CHỈ LƯU METADATA & URL** | Chỉ lưu trữ đường dẫn URL, `storage_key`/`public_id`, metadata tệp đính kèm và video tutorial (không lưu trữ metadata poster do ảnh thumbnail được sinh dẫn xuất từ video) trong PostgreSQL. Binary media blobs nằm trên hạ tầng Cloudinary. |
| **Firebase Auth** | **CHỈ LƯU UID MAPPING** | Chỉ lưu `user_auth_identities` (ánh xạ provider UID sang local `user_id`). Tài khoản và thông tin xác thực trên Firebase Authentication do Google quản lý độc lập. |
| **Secrets / Env** | **TUYỆT ĐỐI LOẠI TRỪ** | Tệp `.env`, API keys, service-account JSON và thông tin nhạy cảm KHÔNG ĐƯỢC PHÉP chứa trong tệp dump hoặc manifest. |
| **Source Code** | **KHÔNG ĐÓNG GÓI** | Git là hệ thống lưu trữ và quản lý phiên bản mã nguồn. |

---

## 3. Các thành phần không thuộc phạm vi Dump (What is NOT Included)

1. **Media Blobs**: Video, audio, hình ảnh sản phẩm, ảnh chụp minh chứng báo cáo/feedback trên Cloudinary.
2. **Firebase User Credentials**: Mật khẩu, danh tính SSO Google/Apple trên Firebase Auth.
3. **Redis InMemory State**: WebSocket pub/sub ephemeral state, cache đếm lượt xem chưa đồng bộ xuống DB.
4. **Environment Secrets**: Các biến môi trường và bí mật cấu hình hạ tầng.

---

## 4. Điều kiện tiên quyết (Prerequisites)

- **Môi trường Docker Compose (Local Dev / VPS)**: Docker và Docker Compose đang chạy với container service `postgres` (PostgreSQL 15+).
- **Môi trường Trực tiếp / External Tunnel (Railway Production)**:
  - Cài đặt công cụ native PostgreSQL client (`psql`, `pg_dump`, `pg_restore`) tương thích phiên bản major với PostgreSQL server.
  - Cài đặt và cấu hình Railway CLI (`@railway/cli`) khi kết nối hạ tầng sản xuất.
- Python 3.10+ trên máy chủ vận hành (sử dụng duy nhất thư viện chuẩn `standard library`, không phát sinh dependency mới).
- Thư mục lưu trữ bản sao lưu có quyền ghi (`backups/`).

---

## 5. Tạo bản sao lưu (Create Backup)

### 5.1. Nguyên tắc kỹ thuật
- Sử dụng công cụ `pg_dump` chính thức với định dạng custom (`-Fc` / `--format=custom`).
- Thiết lập cờ `--no-owner --no-acl` để đảm bảo tính di động cao nhất giữa các môi trường database khác nhau.
- **Cơ chế ghi tệp nguyên tử (Atomic writing)**: Dữ liệu được stream trực tiếp vào tệp tạm thời `<filename>.dump.part`. Chỉ khi tiến trình hoàn tất thành công (exit code 0), tệp mới được đổi tên thành `.dump`. Nếu có lỗi hoặc bị ngắt quãng, tệp `.part` sẽ bị xóa bỏ ngay lập tức.
- **Cổng kiểm tra phiên bản (PostgreSQL Version Gate)**:
  - Trước khi dump, script tự động đối soát phiên bản: `SHOW server_version;` so với `pg_dump --version`.
  - Quy tắc: Phiên bản major của `pg_dump` **bắt buộc phải $\ge$** phiên bản major của PostgreSQL server. Nếu `pg_dump` cũ hơn server, script **từ chối an toàn** và dừng lại với mã lỗi non-zero.
- **Chính sách Snapshot nhất quán & Số lượng dòng (Consistent Snapshot Review)**:
  - Trên cơ sở dữ liệu có lưu lượng ghi đồng thời (concurrent production writes), nếu truy vấn `SELECT count(*)` trên các bảng độc lập với `pg_dump`, số lượng dòng có thể chênh lệch tự nhiên so với transaction snapshot của dump.
  - Do đó, số lượng dòng (`row_counts`) trong manifest mang tính chất **ảnh chụp thông tin (informational snapshot)**.
  - Các cổng kiểm tra cứng phục vụ nghiệm thu bản sao lưu là: `pg_restore` không lỗi, khớp SHA-256, TOC hợp lệ, đủ 100% bảng nghiệp vụ và khớp chính xác `alembic_version`.
- **An toàn bí mật**: Tuyệt đối không đưa mật khẩu cơ sở dữ liệu vào tiến trình CLI (sử dụng biến môi trường `PGPASSWORD` truyền trong subprocess) hay lưu vào manifest.

### 5.2. Lệnh thực hiện

#### A. Chế độ Docker Compose (Mặc định cho Local Development / VPS)
Tạo bản sao lưu tiêu chuẩn:
```bash
python scripts/db_backup.py backup
```

Tùy chọn chỉ định thư mục lưu trữ và chụp snapshot số lượng bản ghi phục vụ kiểm toán:
```bash
python scripts/db_backup.py backup --output-dir backups --include-row-counts
```

Khi chạy trên stack Production Compose:
```bash
python scripts/db_backup.py backup --compose-file docker-compose.prod.yml
```

#### B. Chế độ Kết nối Trực tiếp (Direct Connection / Railway Production Tunnel)
Khi kết nối tới Railway qua tunnel an toàn:
1. Mở tunnel Railway ở terminal riêng (chế độ tunnel-only, gán cổng cục bộ cố định):
   ```bash
   railway connect postgres --tunnel-only -P 15432
   ```
2. Thiết lập biến môi trường kết nối trong terminal vận hành (không in ra log/chat):
   ```powershell
   # PowerShell
   $env:PGHOST = "127.0.0.1"
   $env:PGPORT = "15432"
   $env:PGUSER = "postgres"
   $env:PGDATABASE = "railway"
   $env:PGPASSWORD = "<MẬT_KHẨU_TỪ_RAILWAY>"
   ```
3. Thực thi sao lưu ở chế độ Direct:
   ```bash
   python scripts/db_backup.py backup --direct --output-dir backups --include-row-counts
   ```
4. Xóa ngay biến môi trường nhạy cảm sau khi hoàn tất:
   ```powershell
   Remove-Item Env:\PGPASSWORD
   ```

Tệp tạo ra gồm cặp đôi hoàn chỉnh:
- `backups/<dbname>_<UTC_TIMESTAMP>.dump`: Binary archive nén.
- `backups/<dbname>_<UTC_TIMESTAMP>.dump.manifest.json`: Siêu dữ liệu vận hành.

---

## 6. Kiểm tra tính toàn vẹn (Verify Backup)

Mọi tệp dump sau khi tạo phải vượt qua bước kiểm tra nghiêm ngặt:
1. Tệp dump và manifest tương ứng tồn tại và dung lượng > 0 bytes.
2. Mã băm SHA-256 tính toán từ tệp dump khớp chính xác 100% với giá trị ghi trong manifest.
3. Đọc thử bảng mục lục (Table of Contents) bằng lệnh `pg_restore --list` thành công mà không phát sinh lỗi.
4. Kiểm tra manifest không chứa bất kỳ trường bí mật (password, token, connection string) nào.

### Lệnh thực hiện
Kiểm tra qua Docker Compose (mặc định):
```bash
python scripts/db_backup.py verify backups/<filename>.dump
```

Kiểm tra bằng công cụ native `pg_restore` trực tiếp trên host:
```bash
python scripts/db_backup.py verify backups/<filename>.dump --direct
```

---

## 7. Diễn tập khôi phục (Restore Drill)

### 7.1. Nguyên tắc an toàn tuyệt đối
- **Bảo vệ database chính / Source DB**: Quy trình khôi phục CẤM TUYỆT ĐỐI việc khôi phục đè hoặc xóa cơ sở dữ liệu nguồn đang hoạt động.
- **Ranh giới cô lập tuyệt đối**: Kịch bản diễn tập lấy mốc kỳ vọng **hoàn toàn từ manifest**; **TUYỆT ĐỐI KHÔNG gửi bất kỳ truy vấn nào vào database nguồn** trong suốt quá trình diễn tập.
- **Kiểm tra tính hợp lệ của tên database**: Tên database đích chỉ được chứa chữ cái, chữ số và dấu gạch dưới (`^[a-zA-Z_][a-zA-Z0-9_]{1,62}$`), ngăn chặn hoàn toàn SQL Injection.
- **Chặn trùng tên**: Nếu tên database đích trùng với database nguồn ghi trong manifest: Kịch bản **TỪ CHỐI THỰC HIỆN** ngay lập tức và trả mã lỗi non-zero.
- Mặc định, quy trình tự sinh tên database cô lập có tiền tố `<source_db>_restore_<TIMESTAMP>`.
- **Đối soát động**: Kiểm tra `alembic_version`, số lượng bảng nghiệp vụ và danh sách bảng khớp với manifest; đối soát số dòng thông tin và tự động dọn dẹp sạch sẽ database tạm thời (`DROP DATABASE ... WITH (FORCE)`).

### 7.2. Lệnh thực hiện

#### A. Diễn tập trên Local Docker Compose
Diễn tập tự động (tự tạo DB cô lập trên `postgres` container, kiểm chứng và tự động xóa sau khi thành công):
```bash
python scripts/db_backup.py restore-drill backups/<filename>.dump
```

Nếu muốn giữ lại database đã phục hồi để thanh tra thủ công:
```bash
python scripts/db_backup.py restore-drill backups/<filename>.dump --keep-target
```

Nếu muốn bắt buộc khớp 100% số lượng dòng (dành cho kiểm thử môi trường dev tĩnh):
```bash
python scripts/db_backup.py restore-drill backups/<filename>.dump --strict-row-counts
```

#### B. Diễn tập vào Target CSDL Cô lập Trực tiếp (Direct Isolated Target)
Khi diễn tập bản sao lưu production vào một container PostgreSQL cô lập cùng phiên bản major trên máy local (ví dụ port 15433):
```bash
python scripts/db_backup.py restore-drill backups/<filename>.dump --direct --host 127.0.0.1 --port 15433 --user postgres
```

---

## 8. Trình tự phục hồi thảm họa thực tế (Disaster Recovery Sequence)

Khi cần thực hiện phục hồi cơ sở dữ liệu trong tình huống sự cố thực tế:

```text
[BƯỚC 1] Lấy mã nguồn ứng dụng tương thích và chuẩn bị cấu hình môi trường (.env an toàn).
   │
   ▼
[BƯỚC 2] Khởi tạo cụm PostgreSQL 15+ mới hoặc database đích hoàn toàn mới (ví dụ: `student_marketplace_recovered`).
   │
   ▼
[BƯỚC 3] Kiểm tra tính toàn vẹn của tệp dump bằng `python scripts/db_backup.py verify <file>.dump`.
   │
   ▼
[BƯỚC 4] Nạp dữ liệu vào database đích bằng lệnh `pg_restore --exit-on-error --no-owner --no-acl -d <new_db> <file>.dump`.
   │
   ▼
[BƯỚC 5] Kiểm tra schema, xác nhận `alembic_version` khớp với phiên bản mã nguồn. Nếu mã nguồn mới hơn, chạy `alembic upgrade head`.
   │
   ▼
[BƯỚC 6] Khởi tạo Redis mới hoàn toàn (hoặc thực hiện xóa namespace ứng dụng đã được xác nhận độc lập).
   │
   ▼
[BƯỚC 7] Cập nhật biến môi trường `DATABASE_URL` của API và Worker trỏ sang database đã phục hồi.
   │
   ▼
[BƯỚC 8] Khởi động Backend API và Worker; chạy các truy vấn smoke test kiểm tra xác thực và dữ liệu cốt lõi.
   │
   ▼
[BƯỚC 9] Mở lại lưu lượng mạng (traffic) phục vụ người dùng.
```

---

## 9. Kiểm chứng sau khôi phục (PostgreSQL Validation)

Sau khi phục hồi, cần kiểm tra tối thiểu các tiêu chí kỹ thuật:
1. `alembic_version`: Truy vấn `SELECT version_num FROM alembic_version;` phải trả về đúng revision mong đợi.
2. Danh mục bảng: Đảm bảo đủ 29 bảng nghiệp vụ vật lý của hệ thống.
3. Ràng buộc toàn vẹn: Không có lỗi khóa ngoại hoặc bảng thiếu chỉ mục.
4. Truy vấn khói (Smoke SELECT): Thực hiện truy vấn đọc thử trên các bảng `users`, `products`, `orders`, `auctions`.

---

## 10. Chính sách xử lý Redis sau khôi phục (Redis Reset Policy)

- Trạng thái trên Redis mang tính chất tạm thời (ephemeral), tối ưu hóa trải nghiệm thời gian thực và giảm tải truy vấn.
- **Nguyên tắc an toàn**: Không khôi phục dump Redis cũ vào hệ thống đã khôi phục cơ sở dữ liệu PostgreSQL.
- **Khuyến nghị vận hành**: Bắt đầu với một Redis hoàn toàn mới hoặc dọn dẹp các khóa thuộc namespace ứng dụng trước khi chuyển đổi traffic.
- **Hệ quả chấp nhận được**:
  - Trạng thái online/presence và Pub/Sub của người dùng được thiết lập lại từ đầu.
  - Bộ đệm khử trùng lặp lượt xem trong 24 giờ (`product:views:seen:*`) được làm mới.
  - Các lượt xem sản phẩm phát sinh trong vài giây trước khi có sự cố (chưa kịp flush xuống DB) có thể bị thất thoát nhỏ. Bộ đếm lượt xem trên PostgreSQL tiếp tục làm mốc tối thiểu (`durable floor`) bảo đảm tính đơn điệu tăng dần.

---

## 11. Ranh giới phục hồi Cloudinary (Cloudinary Limitation)

- PostgreSQL chỉ lưu trữ siêu dữ liệu và đường dẫn URL của hình ảnh/video/tài liệu đính kèm.
- **Giới hạn 1**: Khôi phục cơ sở dữ liệu KHÔNG THỂ tái tạo tệp nhị phân trên Cloudinary nếu tệp đó đã bị xóa trên dịch vụ của bên thứ ba.
- **Giới hạn 2**: Nếu khôi phục cơ sở dữ liệu về một mốc thời gian cũ hơn, các tệp tải lên Cloudinary sau thời điểm sao lưu sẽ trở thành tệp mồ côi (`orphaned assets`).
- **Hành động vận hành tương lai**: Định kỳ đối soát hoặc kết hợp chính sách sao lưu/retention của tài khoản Cloudinary với lịch sao lưu cơ sở dữ liệu.

---

## 12. Ranh giới phục hồi Firebase Auth (Firebase Limitation)

- Cơ sở dữ liệu lưu trữ bảng `user_auth_identities` gồm các định danh duy nhất (`provider_uid`, `email`) được ánh xạ tới tài khoản sinh viên nội bộ.
- Việc phục hồi cơ sở dữ liệu giả định Project Firebase Authentication gốc vẫn hoạt động bình thường, giúp người dùng đăng nhập bằng Google/Email và tiếp tục truy cập dữ liệu cũ liền mạch.
- Nếu Project Firebase bị xóa hoặc cấu hình sai, cần quy trình phục hồi/xuất tài khoản người dùng độc lập ở tầng hạ tầng Firebase, nằm ngoài phạm vi bản sao lưu PostgreSQL.

---

## 13. Xử lý bí mật và an toàn thông tin (Secret Handling)

1. Tệp `.env`, API keys và credentials tuyệt đối không được gộp vào tệp sao lưu.
2. Thư mục `backups/` đã được khai báo loại trừ triệt để trong cả `.gitignore` và `.dockerignore`.
3. **Cảnh báo Terminal Railway CLI**: Lệnh `railway connect postgres --tunnel-only -P 15432` sẽ in thông tin đăng nhập trực tiếp ra console của người vận hành:
   - Tuyệt đối **KHÔNG copy/paste** output console này vào chat AI, issue trackers, pull requests hay tệp tài liệu.
   - Khi thiết lập biến môi trường `$env:PGPASSWORD` hoặc `export PGPASSWORD`, phải xóa ngay lập tức sau khi hoàn tất lệnh (`Remove-Item Env:\PGPASSWORD` hoặc `unset PGPASSWORD`).
   - Xóa sạch buffer terminal sau phiên làm việc (`Clear-Host` hoặc `clear`).
4. **Kiểm tra Secret trong Manifest**: Hàm `assert_manifest_clean_of_secrets()` tự động quét toàn bộ khóa và giá trị trong manifest JSON để ngăn chặn hoàn toàn việc rò rỉ credential lên đĩa.
5. Bản sao lưu chứa dữ liệu cá nhân sinh viên và giao dịch mua bán, do đó tệp `.dump` phải được quản lý với quyền truy cập hạn chế tối đa trên máy chủ, không được đặt trong thư mục public web hay chia sẻ công khai.

---

## 14. Định hướng lưu trữ & lưu giữ (Retention Considerations)

- Hiện tại hệ thống đã hoàn thiện công cụ vận hành (`Procedure Implemented`). Lịch trình tự động (`Scheduled Automation`) sẽ được kích hoạt tại các pha hạ tầng triển khai tiếp theo khi môi trường cloud được xác định.
- **Khuyến nghị lưu giữ**:
  - Sao lưu bắt buộc ngay trước mỗi lần triển khai migration cấu trúc dữ liệu (`Pre-migration backup`).
  - Giữ lại tối thiểu 7 bản sao lưu ngày gần nhất và 4 bản sao lưu tuần trên bộ lưu trữ bảo mật độc lập ngoài máy chủ chính.
  - Kịch bản vận hành mặc định không tự động xóa bất kỳ bản sao lưu cũ nào để tránh rủi ro mất mát dữ liệu do cấu hình nhầm.

---

## 15. Danh sách kiểm tra phục hồi (Recovery Checklist)

- [ ] Bản sao lưu có SHA-256 trùng khớp với manifest.
- [ ] Database nguồn hiện tại được bảo vệ nguyên vẹn, không bị tác động.
- [ ] Database đích được tạo trên môi trường cô lập hoặc cluster mới.
- [ ] `pg_restore` thực thi thành công không phát sinh cảnh báo lỗi cấu trúc.
- [ ] Bảng `alembic_version` được kiểm tra và khớp với revision của mã nguồn.
- [ ] Số lượng bảng vật lý đạt đủ 33 (32 bảng ứng dụng + 1 bảng Alembic).
- [ ] Redis được khởi tạo mới hoặc làm sạch an toàn trước khi kết nối ứng dụng.
- [ ] Biến môi trường kết nối đã được kiểm tra tính chính xác.
- [ ] Chạy các truy vấn SELECT kiểm tra danh tính và đơn hàng mẫu.
- [ ] Kích hoạt lại lưu lượng truy cập ứng dụng.

---

## 16. Bằng chứng diễn tập kiểm chứng thực tế (Tested Evidence)

Bản sao lưu và diễn tập thực tế gần nhất ghi nhận trên hệ thống (Phase B Preparation Readiness):

- **Thời gian diễn tập (UTC)**: `2026-09-30T14:25:32Z`
- **Tệp sao lưu**: `student_marketplace_20260930T142532Z.dump` (Dung lượng: `163,496` bytes)
- **Mã băm SHA-256**: `3df94b5554e50b2f30fcd685ba736aa4066b06dc01485310c55638205bc267ff`
- **Manifest**: `student_marketplace_20260930T142532Z.dump.manifest.json` (TOC: 329 entries)
- **Phiên bản PostgreSQL Server**: `15.19 (Alpine Linux 64-bit)`
- **Phiên bản pg_dump Client**: `15 (khớp phiên bản server)`
- **Alembic Revision**: `f1a2b3c4d5e6` (Head)
- **Số bảng ứng dụng**: 32/32 bảng
- **Số bảng vật lý**: 33 bảng
- **Tên database diễn tập cô lập**: `student_marketplace_restore_20260930_142559`
- **Thời gian khôi phục (Restore Elapsed)**: `1.71 giây`
- **Kiểm chứng khớp số lượng bản ghi**: 100% khớp tuyệt đối trên toàn bộ 32 bảng nghiệp vụ
- **Bảo toàn dữ liệu nguồn**: Database nguồn không bị truy vấn hay tác động trong suốt quá trình drill.
- **Thu dọn tài nguyên**: Database cô lập tạm thời đã được `DROP DATABASE ... WITH (FORCE)` an toàn.
