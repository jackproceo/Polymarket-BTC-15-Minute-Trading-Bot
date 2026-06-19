#!/usr/bin/env bash
# =============================================================================
# entrypoint.sh — Polymarket BTC 15-Minute Trading Bot
# =============================================================================
# Handles:
#   1. Wait for Redis to be ready
#   2. Create data/logs directories if missing
#   3. Apply any runtime configuration fixes
#   4. Execute bot with passed arguments
# =============================================================================

set -euo pipefail

# ── Colors for output ────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── Configuration ────────────────────────────────────────────────────────────
REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_TIMEOUT="${REDIS_TIMEOUT:-30}"  # seconds to wait for Redis
DATA_DIR="/app/data"
LOGS_DIR="/app/logs"

# ── Helper functions ─────────────────────────────────────────────────────────
log_info()  { echo -e "${GREEN}[ENTRYPOINT]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[ENTRYPOINT]${NC} $1"; }
log_error() { echo -e "${RED}[ENTRYPOINT]${NC} $1"; }
log_step()  { echo -e "${BLUE}[ENTRYPOINT]${NC} $1"; }

# ── 1. Wait for Redis ────────────────────────────────────────────────────────
wait_for_redis() {
    log_step "Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT} ..."

    local counter=0
    until redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping 2>/dev/null | grep -q "PONG"; do
        counter=$((counter + 1))
        if [ $counter -ge "${REDIS_TIMEOUT}" ]; then
            log_warn "Redis not available after ${REDIS_TIMEOUT}s — continuing without Redis."
            log_warn "Mode switching via redis_control.py will NOT work."
            return 1
        fi
        sleep 1
    done

    log_info "Redis is ready at ${REDIS_HOST}:${REDIS_PORT}"
    return 0
}

# ── 2. Ensure directories exist ──────────────────────────────────────────────
ensure_dirs() {
    log_step "Ensuring data directories exist..."

    mkdir -p "${DATA_DIR}" "${LOGS_DIR}"

    # Ensure writable by botuser (if running as non-root)
    if [ "$(id -u)" -eq 0 ]; then
        chown -R botuser:botuser "${DATA_DIR}" "${LOGS_DIR}" 2>/dev/null || true
    fi

    log_info "Directories ready: ${DATA_DIR}, ${LOGS_DIR}"
}

# ── 3. Print system info ─────────────────────────────────────────────────────
print_info() {
    echo ""
    echo "================================================"
    echo " Polymarket BTC 15-Minute Trading Bot"
    echo "================================================"
    echo " Python : $(python --version 2>&1)"
    echo " Host   : $(hostname 2>/dev/null || echo 'unknown')"
    echo " Date   : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo " Mode   : $([ "${SIMULATION_MODE:-1}" = "1" ] && echo "SIMULATION" || echo "LIVE")"
    echo " Redis  : ${REDIS_HOST}:${REDIS_PORT}"
    echo " Args   : $*"
    echo "================================================"
    echo ""
}

# ── 4. Warn if running as root ───────────────────────────────────────────────
check_user() {
    if [ "$(id -u)" -eq 0 ]; then
        log_warn "Running as ROOT. Consider using 'docker run --user 1000:1000' for better security."
    fi
}

# ── 5. Check for critical env vars ───────────────────────────────────────────
check_env() {
    local missing=0

    if [ -z "${POLYMARKET_FUNDER:-}" ]; then
        log_warn "POLYMARKET_FUNDER not set — simulation mode only."
    fi

    # In live mode, validate critical credentials
    if [ "${LIVE_MODE:-0}" = "1" ] || [ "${#}" -gt 0 ] && [[ "$*" == *"--live"* ]]; then
        if [ -z "${POLYMARKET_PK:-}" ]; then
            log_error "POLYMARKET_PK is required for live trading!"
            missing=1
        fi
        if [ -z "${POLYMARKET_API_KEY:-}" ]; then
            log_error "POLYMARKET_API_KEY is required for live trading!"
            missing=1
        fi
        if [ -z "${POLYMARKET_API_SECRET:-}" ]; then
            log_error "POLYMARKET_API_SECRET is required for live trading!"
            missing=1
        fi
        if [ -z "${POLYMARKET_PASSPHRASE:-}" ]; then
            log_error "POLYMARKET_PASSPHRASE is required for live trading!"
            missing=1
        fi
        if [ -z "${POLYMARKET_FUNDER:-}" ]; then
            log_error "POLYMARKET_FUNDER is required for live trading!"
            missing=1
        fi

        if [ "${missing}" -eq 1 ]; then
            log_error "Missing required environment variables for live trading."
            log_error "Set them in your .env file or pass them via -e flags."
            exit 1
        fi
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
    print_info "$@"
    check_user
    ensure_dirs
    wait_for_redis || true   # Non-fatal — bot can run without Redis
    check_env "$@"

    log_info "Starting bot..."
    echo ""

    # If running as root, drop to botuser via Python setuid
    if [ "$(id -u)" -eq 0 ]; then
        exec python3 -c "
import os, sys, pwd
uid = pwd.getpwnam('botuser').pw_uid
gid = pwd.getpwnam('botuser').pw_gid
os.setgid(gid)
os.setuid(uid)
os.execvp('python3', ['python3', '/app/bot.py'] + sys.argv[1:])
" "$@"
    fi

    # Execute the bot with all passed arguments
    exec python bot.py "$@"
}

main "$@"
