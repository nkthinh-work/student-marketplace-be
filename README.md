# Student Marketplace C2C Backend

This is the FastAPI backend for the **Marketplace C2C Sinh viên** platform. It provides a secure, high-performance API for trading items, managing shopping carts, and processing orders among students.

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
│   ├── modules/             # Business features (auth, products, orders, cart)
│   └── workers/             # Background workers & cron tasks
├── alembic/                 # Alembic migration scripts
├── tests/                   # Pytest automated test suites
├── Dockerfile               # Backend Docker build instructions
├── docker-compose.yml       # Dev and production infrastructure services
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

## 🐳 Docker Deployment & Multi-container Development

You can build and spin up the complete infrastructure (FastAPI, Background Worker (Placeholder), PostgreSQL, and Redis) instantly:

```bash
docker-compose up --build
```

This starts the following services:
- **`postgres`**: Relational database on port `5432`
- **`redis`**: Caching and messaging store on port `6379`
- **`api`**: FastAPI server on port `8000`
- **`worker`**: Background worker/daemon running tasks

To stop the containers:
```bash
docker-compose down
```

---

## 🧪 Testing

To run the automated tests locally:

```bash
pytest
```

---

## 🔌 API Endpoints (Core)

- **`GET /health`**: Health check endpoint verifying application, PostgreSQL database, and Redis connections.
- **`GET /`**: Welcome root.
