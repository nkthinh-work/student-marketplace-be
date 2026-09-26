# ==============================================================================
# Multi-stage Production Dockerfile for Student Marketplace Backend
# Python 3.12-slim base, non-root user, lean runtime context
# ==============================================================================

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime image
FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Tạo group và user appuser không có đặc quyền root
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/sh -d /app appuser

# Copy virtualenv từ stage builder
COPY --from=builder /opt/venv /opt/venv

# Copy các thành phần tối thiểu cho runtime và migration
COPY alembic.ini .
COPY alembic/ ./alembic
COPY app/ ./app
COPY scripts/ ./scripts

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Lệnh khởi chạy mặc định (không --reload cho production)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]