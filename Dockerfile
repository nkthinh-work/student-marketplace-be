FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 1. Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 3. Tạo user không có quyền root
RUN adduser --disabled-password --gecos "" appuser

# 4. Copy application code và phân quyền
COPY . .
RUN chown -R appuser:appuser /app

# 5. Chuyển sang user an toàn
USER appuser

EXPOSE 8000

# Lệnh khởi chạy mặc định
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]