FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies if required for binary wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy source tree
COPY . .

# Create volume mount target for data artifacts
RUN mkdir -p /app/data

# Default command runs dry-run simulation
ENTRYPOINT ["python", "-m", "solana_block_order_lab.cli"]
CMD ["dry-run"]
