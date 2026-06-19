# =============================================================================
# Dockerfile — Polymarket BTC 15-Minute Trading Bot
# Multi-stage build: Rust builder + Python runtime
# =============================================================================
# Usage:
#   docker build -t polymarket-btc-bot .
#   docker run --rm -it --env-file .env polymarket-btc-bot
#   docker run --rm -it --env-file .env polymarket-btc-bot --live
#   docker run --rm -it --env-file .env polymarket-btc-bot --test-mode
# =============================================================================

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
# Install Rust toolchain + build nautilus_trader native extensions
FROM python:3.12-slim-bookworm AS builder

LABEL stage=builder

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Install build dependencies (Rust, C compiler, SSL, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain (required by nautilus_trader)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && /root/.cargo/bin/rustup default stable \
    && /root/.cargo/bin/rustup update

ENV PATH="/root/.cargo/bin:${PATH}"

# Copy requirements and build wheels for all packages
WORKDIR /build
COPY requirements.txt .

# Filter out Windows-only packages, then build wheels
# Pre-install build deps for nautilus_trader (poetry-core + cython)
RUN grep -v -E 'pywin32' requirements.txt > reqs.txt \
    && pip install --upgrade pip setuptools wheel \
    && pip install poetry-core==2.3.1 cython==3.2.4 \
    && pip wheel --no-cache-dir --wheel-dir=/wheels -r reqs.txt \
    && ls -lh /wheels/ | head -20


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

LABEL description="Polymarket BTC 15-Minute Trading Bot"
LABEL version="1.0"

# Prevent Python from writing .pyc files and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=42 \
    TZ=UTC

# Install minimal runtime dependencies (only what's needed at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-tools \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built wheels from builder stage
COPY --from=builder /wheels /wheels

# Install from pre-built wheels (preferred) with PyPI fallback
RUN pip install --no-cache-dir --find-links=/wheels \
        nautilus_trader \
        redis \
        python-dotenv \
        loguru \
        prometheus_client \
        eth-account \
        web3 \
        aiohttp \
        pandas \
        numpy \
        httpx \
        requests \
        py-clob-client \
        poly-eip712-structs \
        py-order-utils \
    && rm -rf /wheels /root/.cache/pip

# Create non-root user for security
RUN groupadd -r botuser && useradd -r -g botuser -d /app -s /sbin/nologin botuser

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/grafana

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=botuser:botuser . .

# Remove Windows-specific files
RUN rm -f venv/ 2>/dev/null; true

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Switch to non-root user
USER botuser

# Volumes for persistent data
VOLUME ["/app/data", "/app/logs"]

# Expose ports:
#   3000 - Web Dashboard (REST API + UI)
#   8000 - Prometheus metrics (for Grafana)
EXPOSE 3000 8000

# Default command (can be overridden: --live, --test-mode, --no-grafana)
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "bot.py"]
