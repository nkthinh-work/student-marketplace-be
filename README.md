# Student Marketplace C2C Backend

This is the FastAPI backend for the **Marketplace C2C Sinh viên** platform. It provides a secure, high-performance API for direct C2C purchases, real-time auctions, campus messaging, and student community interactions.

## 📖 Canonical Documentation

- **Agent Governance & Rules**: [00-project.md](../.roo/rules/00-project.md)
- **Architecture & Roadmap**: [TechStack_v2.md](docs/TechStack_v2.md)
- **Database Schema**: [DB_v7.md](docs/DB_v7.md)
- **API Contract**: [API_CONTRACT.md](docs/API_CONTRACT.md)
- **Current Project State**: [PROJECT_STATE.md](docs/PROJECT_STATE.md)
- **Project History**: [PROJECT_HISTORY.md](docs/PROJECT_HISTORY.md)
- **Query & Index Audit**: [QUERY_INDEX_AUDIT.md](docs/QUERY_INDEX_AUDIT.md)
- **Backup & Restore Operations**: [BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md)

## 🚀 Tech Stack

- **Python 3.12**
- **FastAPI** (Uvicorn server)
- **SQLAlchemy 2.x async** (with **asyncpg**)
- **PostgreSQL 15+**
- **Redis 7** (Caching, sessions, view counters)
- **Alembic** (Database migration management)
- **Pydantic v2** (Validation & settings)
- **Firebase Admin SDK** (Authentication authority verification)
- **Cloudinary SDK** (Media upload/storage)
- **pytest** (Testing framework)

---

## 🛠️ Project Structure

```text
student-marketplace-be/
├── app/
│   ├── main.py              # Application entrypoint
│   ├── core/                # System config, logging, database, Redis setup
│   ├── db/                  # Database base models
│   ├── integrations/        # Firebase & Cloudinary integrations
│   ├── modules/             # Business domain modules (auth, products, orders, auctions, etc.)
│   └── workers/             # Background workers & cron tasks
├── alembic/                 # Alembic migration scripts
├── docs/                    # Canonical project documentation
├── scripts/                 # Standard operational tools (db_backup.py)
├── tests/                   # Pytest automated test suites
├── Dockerfile               # Production multi-stage Docker build
├── docker-compose.yml       # Development Compose (bind mount, hot-reload, public DB/Redis ports)
├── docker-compose.prod.yml  # Production Compose (no bind mounts, internal DB/Redis, non-root, healthchecks)
├── .env.example             # Configuration placeholder
├── alembic.ini              # Alembic config
└── README.md                # This file
```

---

## ⚙️ Local Setup

### Prerequisites

- **Python 3.12** installed locally.
- **Docker** and **Docker Compose** installed.

### 1. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your configuration:

```bash
cp .env.example .env
```

Ensure you set a strong value for `POSTGRES_PASSWORD` and configure other secrets.

### 2. Standard Local Virtual Environment Setup

1. Create a Python virtual environment:
   ```bash
   python -m venv .venv
   ```

2. Activate the virtual environment:
   - On Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source .venv/bin/activate
     ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the development server:
   ```bash
   uvicorn app.main:app --reload
   ```
   The API will be accessible at `http://localhost:8000`. Documentation will be available at `http://localhost:8000/docs`.

---

## 🐳 Development Docker Stack

You can run the development infrastructure services with source bind mounts and hot-reloading:

```bash
docker compose up -d
```

This starts:
- **`postgres`**: Database exposed on port `5432`
- **`redis`**: Cache exposed on port `6379`
- **`api`**: FastAPI server on port `8000` (`--reload` enabled)
- **`worker`**: Background worker process

To stop development containers:
```bash
docker compose down
```

---

## 🚀 Production Docker

Cấu hình Production Compose (`docker-compose.prod.yml`) được thiết kế đóng gói độc lập, bảo mật và loại bỏ hoàn toàn các giả định môi trường phát triển:
- **Không bind mount mã nguồn**: Mã nguồn và dependencies nằm cố định trong image (`student-marketplace-be:prod`).
- **Không reload**: Uvicorn chạy ở chế độ production chuẩn.
- **Cổng nội bộ an toàn**: PostgreSQL (`5432`) và Redis (`6379`) không publish ra mạng ngoài, chỉ giao tiếp nội bộ trong mạng Compose.
- **Non-root user**: API và Worker thực thi dưới user `appuser` (UID `10001`).
- **Healthchecks chuẩn xác**: Kiểm tra kết nối định kỳ cho Postgres, Redis và API `/health`.
- **Dùng chung image**: Cả `api` và `worker` chia sẻ cùng một image ứng dụng, chỉ khác câu lệnh khởi chạy.

### Trình tự Triển khai Sản xuất (Production Sequence)

1. **Xác thực cấu hình**:
   ```bash
   docker compose -f docker-compose.prod.yml config
   ```
2. **Sao lưu cơ sở dữ liệu** (nếu nâng cấp phiên bản có sẵn):
   ```bash
   python scripts/db_backup.py backup --compose-file docker-compose.prod.yml
   ```
   Chi tiết quy trình xem tại [BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).
3. **Build image production**:
   ```bash
   docker compose -f docker-compose.prod.yml build
   ```
4. **Khởi động cơ sở dữ liệu & bộ nhớ đệm**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d postgres redis
   ```
5. **Chạy migration CSDL tường minh**:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
   ```
6. **Khởi động API và Background Worker**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d api worker
   ```
7. **Kiểm tra trạng thái và sức khỏe**:
   ```bash
   docker compose -f docker-compose.prod.yml ps
   ```
8. **Xác thực endpoint kiểm tra sức khỏe**:
   ```bash
   curl http://localhost:8000/health
   ```
9. **Dừng hệ thống production khi cần**:
   ```bash
   docker compose -f docker-compose.prod.yml down
   ```

---

## 🔄 Continuous Integration & Release Gates

Dự án sử dụng GitHub Actions workflow (`.github/workflows/ci.yml`) để bảo vệ chất lượng mã nguồn trên mỗi commit / pull request:
- **`test`**: Kiểm thử trên môi trường cô lập tạm thời (PostgreSQL 15 + Redis 7), chạy `alembic upgrade head`, xác thực `alembic check` 0 drift, và thực thi toàn bộ test suite (`pytest tests/ -q`).
- **`docker-release-gate`**: Xác thực cú pháp `docker-compose.prod.yml`, build image `student-marketplace-be:prod`, kiểm tra non-root user (`appuser`), kiểm tra dependencies (`pip check`) và kiểm toán ranh giới tệp tin loại trừ secrets/tests/docs.

---

## 🔌 API Endpoints (Core)

- **`GET /health`**: Health check endpoint verifying application, PostgreSQL database, and Redis connections.
- **`GET /`**: Welcome root.
