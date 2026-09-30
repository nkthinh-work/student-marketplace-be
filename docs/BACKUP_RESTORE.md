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
2. Danh mục bảng: Đảm bảo khớp chính xác 100% số lượng bảng nghiệp vụ (`application_table_count`) và tổng số bảng vật lý (`physical_table_count`) được ghi nhận động trong manifest của bản sao lưu.
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

## 14. Chính sách lưu giữ & Lưu trữ từ xa (Phase C Retention & Remote Storage)

Hệ thống triển khai tự động hóa sao lưu và lưu giữ theo mô hình cặp bản sao lưu nguyên tử (Atomic Backup Set) trên Cloudflare R2 (S3-compatible):

### 14.1. Khái niệm Cặp Bản sao lưu Nguyên tử (Atomic Remote Backup Set)
Một bản sao lưu từ xa chỉ được công nhận hợp lệ khi tồn tại đầy đủ cặp đôi tương ứng:
- `<prefix>/<base_name>.dump` (Binary custom dump)
- `<prefix>/<base_name>.dump.manifest.json` (Operational manifest metadata)

Một phiên sao lưu từ xa được coi là **THÀNH CÔNG** khi và chỉ khi:
1. Dump tải lên thành công vào bucket R2.
2. Manifest tải lên thành công vào bucket R2.
3. Cả 2 đối tượng được kiểm chứng tồn tại từ xa qua `head_object`.
4. Kích thước đối tượng trên R2 khớp 100% với kích thước tệp cục bộ (`dump_size_bytes` và `manifest_size_bytes`).

> **Nguyên tắc Chống Thất Thoát (Fail-Closed Safety)**:
> Nếu bất kỳ tệp nào tải thất bại hoặc không vượt qua kiểm tra kích thước: Phiên chạy lập tức bị đánh dấu **THẤT BÀI**, **KHÔNG kích hoạt tiến trình retention**, và **toàn bộ bản sao lưu cũ trên R2 được bảo toàn tuyệt đối**.

### 14.2. Thuật toán Lưu giữ (Rolling Retention: 14 Daily + 4 Weekly)
- **Cửa sổ hàng ngày (Daily Window)**: Giữ lại toàn bộ bản sao lưu trong vòng 14 ngày gần nhất (14 bản ngày).
- **Cửa sổ hàng tuần (Weekly Window)**: Giữ lại 1 bản/tuần (nhóm theo tuần lịch ISO) cho 4 tuần kế tiếp (khoảng thời gian từ 14 đến 42 ngày trước).
- **Thu dọn bản hết hạn (Pruning)**: Toàn bộ bản sao lưu cũ hơn 42 ngày hoặc bản dư thừa trong cùng một tuần lịch cũ hơn 14 ngày sẽ bị thu dọn hoàn chỉnh (xóa đồng thời cả `.dump` và `.manifest.json`).
- **Các chốt chặn an toàn bất biến (Retention Invariants)**:
  1. **Bản sao lưu mới nhất (Newest Verified Pair)**: TUYỆT ĐỐI KHÔNG BAO GIỜ bị xóa trong bất kỳ hoàn cảnh nào.
  2. **Điều kiện kích hoạt**: Retention CHỈ được phép chạy sau khi đã tải và kiểm chứng thành công một bản sao lưu mới trong phiên hiện tại (`newest_verified != None`).
  3. **Ngưỡng tối thiểu**: Nếu tổng số cặp bản sao lưu trên R2 $\le 1$, tuyệt đối không xóa bất kỳ bản nào.
  4. **Tệp mồ côi (Orphan objects)**: Các tệp đơn lẻ thiếu dump hoặc manifest không được coi là backup hợp lệ và không làm ảnh hưởng tới retention các cặp hoàn chỉnh.

### 14.3. Hạ tầng & Tham số Thời gian thực
- **Lưu trữ**: Cloudflare R2 STANDARD storage (`StorageClass: "STANDARD"`). Tính chính xác và an toàn của hệ thống lưu trữ độc lập với chính sách giá của nhà cung cấp. Về mặt vận hành, theo giả định gói miễn phí hiện hành của Cloudflare R2: 10 GB lưu trữ chuẩn và chính sách không thu phí truyền tải dữ liệu tải xuống (zero egress fee policy) phù hợp với quy mô hiện tại của dự án (không mô tả việc tải xuống/khôi phục là vô hạn).
- **RPO (Recovery Point Objective)**: Bản sao lưu tự động hàng ngày bảo đảm RPO $\le$ 24 giờ. Bản sao lưu thủ công trước migration là điểm rollback đã biết (chỉ đạt RPO = 0 khi luồng ghi của ứng dụng được tạm dừng có kiểm soát giữa thời điểm backup và migration).
- **Thời gian thực thi & Headroom**: Thời gian thực thi `pg_dump` đo đạc thực tế trên production Railway là ~27 giây (tuyệt đối không áp dụng giả định dưới 2 giây cho production). Tiến trình container được thiết kế với biên độ an toàn (headroom) từ 60 đến 120 giây.
- **Chi phí**: Tiến trình tiêu thụ tài nguyên tính toán container thông thường của Railway và là phần sử dụng có tính phí theo quy định của nền tảng (billable compute usage). Mức gia tăng tài nguyên này dự kiến là không đáng kể và có thể được bù trừ bởi hạn mức tín dụng sẵn có của gói dịch vụ (không cam kết cố định $0.00).
- **Thuật ngữ bảng CSDL**: Luôn sử dụng `application_table_count` (số bảng nghiệp vụ) và `physical_table_count` (tổng số bảng vật lý) được trích xuất động từ manifest (baseline hiện tại là 32 bảng nghiệp vụ + 1 bảng Alembic = 33 bảng vật lý, nhưng mã nguồn và quy trình đối soát không ràng buộc cứng con số 33).

### 14.4. Cấu hình Biến Tham chiếu Chuẩn tắc trên Railway (Canonical Railway Variables)
Tiến trình container sao lưu trên Railway nhận thông tin kết nối CSDL chuẩn tắc từ service PostgreSQL nội bộ:
```text
PGHOST=${{Postgres.PGHOST}}
PGPORT=${{Postgres.PGPORT}}
PGUSER=${{Postgres.PGUSER}}
PGPASSWORD=${{Postgres.PGPASSWORD}}
PGDATABASE=${{Postgres.PGDATABASE}}
```
*(Ghi chú: Không ưu tiên `Postgres.RAILWAY_PRIVATE_DOMAIN` thay cho `Postgres.PGHOST`).*

Các biến cấu hình lưu trữ R2 độc lập:
```text
R2_BUCKET_NAME=choptiters-backups
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<access_key_id>
R2_SECRET_ACCESS_KEY=<secret_access_key>
R2_PREFIX=backups/
```


---

## 15. Danh sách kiểm tra phục hồi (Recovery Checklist)

- [ ] Bản sao lưu có SHA-256 trùng khớp với manifest.
- [ ] Database nguồn hiện tại được bảo vệ nguyên vẹn, không bị tác động.
- [ ] Database đích được tạo trên môi trường cô lập hoặc cluster mới.
- [ ] `pg_restore` thực thi thành công không phát sinh cảnh báo lỗi cấu trúc.
- [ ] Bảng `alembic_version` được kiểm tra và khớp với revision của mã nguồn.
- [ ] Khớp số lượng bảng nghiệp vụ (`application_table_count`) và tổng số bảng vật lý (`physical_table_count`) đối soát động từ manifest.
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

---

## 17. Hướng dẫn Vận hành Sao lưu Đám mây & Khôi phục Ngoại vi (Phase C Runbook)

### 17.1. Cấu trúc Công cụ Vận hành
- `scripts/db_backup.py`: Trọng tâm xử lý logic cốt lõi (tạo dump, verify, isolated restore drill).
- `scripts/db_backup_remote.py`: Trọng tâm xử lý kết nối Cloudflare R2, tải cặp tệp nguyên tử, xác thực remote và áp dụng chính sách retention.
- `Dockerfile.backup`: Container runner độc lập (`postgres:18-alpine` + `python3` + `boto3`), chạy tác vụ sao lưu ngắn hạn (`short-lived cron`) theo lịch trình.

### 17.2. Lệnh Vận hành CLI từ xa

#### A. Chạy toàn bộ chu trình tự động (Pipeline)
Thực thi tuần tự: dump direct -> verify -> upload R2 -> confirm -> prune retention:
```bash
python scripts/db_backup_remote.py run-pipeline --output-dir backups --cleanup-local
```

#### B. Tải thủ công một cặp bản sao lưu lên R2
Khi người vận hành muốn đẩy một bản sao lưu cục bộ đã kiểm chứng lên R2:
```bash
python scripts/db_backup_remote.py upload-pair backups/railway_20261001T200000Z.dump --apply-retention
```

#### C. Liệt kê danh sách các cặp bản sao lưu trên R2
Kiểm tra các bản sao lưu hợp lệ đang được lưu trữ an toàn:
```bash
python scripts/db_backup_remote.py list-pairs
```

#### D. Diễn tập Phục hồi Ngoại vi (Off-Platform Disaster Recovery Drill)
1. Tải cặp bản sao lưu mới nhất từ Cloudflare R2 về thư mục cục bộ (sử dụng AWS CLI hoặc giao diện Cloudflare Dashboard):
   ```bash
   aws s3 cp s3://choptiters-backups/backups/railway_LATEST.dump ./backups/ --endpoint-url $R2_ENDPOINT_URL
   aws s3 cp s3://choptiters-backups/backups/railway_LATEST.dump.manifest.json ./backups/ --endpoint-url $R2_ENDPOINT_URL
   ```
2. Thực hiện kiểm chứng tính toàn vẹn:
   ```bash
   python scripts/db_backup.py verify backups/railway_LATEST.dump --direct
   ```
3. Diễn tập khôi phục vào database cô lập:
   ```bash
   python scripts/db_backup.py restore-drill backups/railway_LATEST.dump --direct --host 127.0.0.1 --port 15432 --user postgres
   ```
