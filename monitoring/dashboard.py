"""
Trading Dashboard — Web UI for real-time bot monitoring.
REST API + beautiful dark-themed dashboard on port 3000.

Usage:
    # Standalone (SQLite data only):
    python -m monitoring.dashboard

    # Started automatically by bot.py (full live data):
    python bot.py
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from decimal import Decimal
import threading

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

# ── Data sources (lazy-loaded) ──────────────────────────────────────────────
DB_PATH = project_root / "data" / "trades.db"


def _query_db(sql: str, params: tuple = ()) -> list[dict]:
    """Query SQLite and return list of dicts."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_singletons():
    """Try to load in-memory singletons (only works inside bot process)."""
    perf = risk = exec_eng = None
    try:
        from monitoring.performance_tracker import get_performance_tracker
        perf = get_performance_tracker()
    except Exception:
        pass
    try:
        from execution.risk_engine import get_risk_engine
        risk = get_risk_engine()
    except Exception:
        pass
    try:
        from execution.execution_engine import get_execution_engine
        exec_eng = get_execution_engine()
    except Exception:
        pass
    return perf, risk, exec_eng


_perf, _risk, _exec = _load_singletons()

# ── Bot status (written to by bot.py at runtime) ──────────────────────────
BOT_STATUS = {
    "mode": "simulation",
    "started_at": None,
    "last_trade_at": None,
    "current_price": None,
    "current_market": "",
    "total_ticks": 0,
    "uptime_seconds": 0,
}


def update_bot_status(**kwargs):
    """Called by bot.py to push real-time status into the dashboard."""
    BOT_STATUS.update(kwargs)


# =====================================================================
#  HTTP HANDLER
# =====================================================================

class DashboardHandler(BaseHTTPRequestHandler):
    """Serves REST API + dashboard HTML."""

    # Suppress default logging (we log selectively)
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str, indent=2).encode())

    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _send_error(self, status: int, msg: str):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        try:
            if path == "/" or path == "":
                return self._serve_dashboard()
            elif path == "/api/stats":
                return self._api_stats()
            elif path == "/api/trades":
                return self._api_trades(params)
            elif path == "/api/performance":
                return self._api_performance()
            elif path == "/api/risk":
                return self._api_risk()
            elif path == "/api/positions":
                return self._api_positions()
            elif path == "/api/status":
                return self._api_status()
            else:
                self._send_error(404, "Not found")
        except Exception as e:
            logger.error(f"Dashboard API error: {e}\n{traceback.format_exc()}")
            self._send_error(500, str(e))

    # ── API Handlers ──────────────────────────────────────────────────────

    def _api_stats(self):
        """Aggregated trade statistics from SQLite."""
        rows = _query_db("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 500")
        total = len(rows)
        wins = sum(1 for r in rows if r.get("outcome") == "WIN")
        losses = sum(1 for r in rows if r.get("outcome") == "LOSS")
        pending = sum(1 for r in rows if r.get("outcome") == "PENDING")
        closed = wins + losses
        win_rate = wins / closed * 100 if closed else 0
        total_volume = sum(r.get("size_usd", 0) for r in rows)
        total_pnl = 0
        # Estimate PnL from outcomes (very rough)
        for r in rows:
            if r.get("outcome") == "WIN":
                total_pnl += r.get("size_usd", 0) * 0.20  # ~20% win
            elif r.get("outcome") == "LOSS":
                total_pnl -= r.get("size_usd", 0) * 0.30  # ~30% loss

        self._send_json({
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "win_rate": round(win_rate, 1),
            "total_volume": round(total_volume, 2),
            "estimated_pnl": round(total_pnl, 2),
            "avg_price": round(sum(r.get("price", 0) for r in rows) / total, 4) if total else 0,
        })

    def _api_trades(self, params):
        """Recent paper trades."""
        limit = int(params.get("limit", [50])[0])
        rows = _query_db(
            "SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        self._send_json(rows)

    def _api_performance(self):
        """Performance metrics from singleton (or SQLite fallback)."""
        if _perf is not None:
            # Live data from in-memory singleton
            metrics = _perf.calculate_metrics()
            equity = _perf.get_equity_curve()
            daily = _perf.get_daily_pnl(30)
            dist = _perf.get_win_loss_distribution()
            self._send_json({
                "source": "live",
                "total_pnl": float(metrics.total_pnl),
                "roi": metrics.roi * 100,
                "win_rate": metrics.win_rate * 100,
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown": metrics.max_drawdown * 100,
                "total_trades": metrics.total_trades,
                "current_capital": float(_perf.current_capital),
                "avg_signal_score": metrics.avg_signal_score,
                "avg_signal_confidence": metrics.avg_signal_confidence,
                "equity_curve": equity,
                "daily_pnl": daily,
                "distribution": dist,
            })
        else:
            # Fallback: estimate from SQLite
            rows = _query_db("SELECT * FROM paper_trades ORDER BY id ASC")
            total = len(rows)
            wins = sum(1 for r in rows if r.get("outcome") == "WIN")
            losses = sum(1 for r in rows if r.get("outcome") == "LOSS")
            win_rate = wins / (wins + losses) * 100 if (wins + losses) else 0
            capital = 1000.0 - (losses * 0.30) + (wins * 0.20)

            # Build equity curve from sequential trades
            equity = [{"timestamp": "start", "equity": 1000.0}]
            running = 1000.0
            for r in rows:
                if r.get("outcome") == "WIN":
                    running += r.get("size_usd", 1) * 0.20
                elif r.get("outcome") == "LOSS":
                    running -= r.get("size_usd", 1) * 0.30
                equity.append({"timestamp": r.get("timestamp", ""), "equity": round(running, 2)})

            self._send_json({
                "source": "sqlite",
                "total_pnl": round(capital - 1000.0, 2),
                "roi": round((capital - 1000.0) / 1000.0 * 100, 2),
                "win_rate": round(win_rate, 1),
                "sharpe_ratio": 0,
                "max_drawdown": 0,
                "total_trades": total,
                "current_capital": round(capital, 2),
                "avg_signal_score": 0,
                "avg_signal_confidence": 0,
                "equity_curve": equity,
                "daily_pnl": [],
                "distribution": {
                    "total_trades": total,
                    "wins": {"count": wins},
                    "losses": {"count": losses},
                },
            })

    def _api_risk(self):
        """Risk summary from singleton (or SQLite fallback)."""
        if _risk is not None:
            data = _risk.get_risk_summary()
            # Convert Decimals to floats
            data = json.loads(json.dumps(data, default=str))
            data["source"] = "live"
        else:
            # Estimate from SQLite
            rows = _query_db("SELECT COUNT(*) as cnt, SUM(size_usd) as vol FROM paper_trades")
            r = rows[0] if rows else {}
            data = {
                "source": "sqlite",
                "positions": {"count": 0, "max_allowed": 5},
                "exposure": {"current": 0, "max_allowed": 10.0, "utilization_pct": 0},
                "pnl": {"daily": 0, "unrealized": 0, "daily_limit": 5.0},
                "balance": {"current": 1000.0, "peak": 1000.0, "drawdown_pct": 0, "max_drawdown_pct": 15},
                "daily_stats": {"trades": r.get("cnt", 0) if r else 0, "pnl": 0},
                "alerts": 0,
            }
        self._send_json(data)

    def _api_positions(self):
        """Open positions from execution engine singleton."""
        if _exec is not None:
            positions = _exec.get_open_positions()
            # Convert Decimals
            positions = json.loads(json.dumps(positions, default=str))
            self._send_json({"source": "live", "positions": positions, "count": len(positions)})
        else:
            self._send_json({"source": "sqlite", "positions": [], "count": 0})

    def _api_status(self):
        """Bot runtime status."""
        if BOT_STATUS["started_at"]:
            uptime = (datetime.now(timezone.utc) - BOT_STATUS["started_at"]).total_seconds()
            BOT_STATUS["uptime_seconds"] = round(uptime)
        self._send_json(BOT_STATUS)

    # ── Dashboard HTML ────────────────────────────────────────────────────

    def _serve_dashboard(self):
        self._send_html(DASHBOARD_HTML)


# =====================================================================
#  FRONTEND — Beautiful dark-themed dashboard
# =====================================================================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Polymarket Trading Bot — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  /* ── Reset & base ────────────────────────────────────────── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg-primary: #0b0e14;
    --bg-secondary: #131820;
    --bg-card: #1a212e;
    --bg-card-hover: #1f2838;
    --border: #2a3446;
    --text-primary: #e4e8ef;
    --text-secondary: #8892a6;
    --text-muted: #5a6478;
    --green: #22c55e;
    --green-bg: rgba(34,197,94,0.12);
    --red: #ef4444;
    --red-bg: rgba(239,68,68,0.12);
    --yellow: #eab308;
    --yellow-bg: rgba(234,179,8,0.12);
    --blue: #3b82f6;
    --blue-bg: rgba(59,130,246,0.12);
    --purple: #a855f7;
    --radius: 12px;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  html { font-size: 14px; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 20px;
    min-height: 100vh;
  }
  a { color: var(--blue); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* ── Layout ─────────────────────────────────────────────── */
  .container { max-width: 1400px; margin: 0 auto; }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 20px;
    flex-wrap: wrap;
    gap: 12px;
  }
  .header-left { display: flex; align-items: center; gap: 16px; }
  .header-left h1 {
    font-size: 1.25rem;
    font-weight: 700;
    background: linear-gradient(135deg, var(--blue), var(--purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: .8rem;
    font-weight: 600;
  }
  .status-badge.sim { background: var(--yellow-bg); color: var(--yellow); }
  .status-badge.live { background: var(--red-bg); color: var(--red); }
  .status-badge .dot {
    width: 8px; height: 8px; border-radius: 50%;
    animation: pulse 2s infinite;
  }
  .status-badge.sim .dot { background: var(--yellow); }
  .status-badge.live .dot { background: var(--red); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .header-right { display: flex; align-items: center; gap: 20px; color: var(--text-secondary); font-size: .85rem; }
  .header-right span { display: flex; align-items: center; gap: 6px; }
  .header-right .label { color: var(--text-muted); }

  /* ── Dashboard Grid ─────────────────────────────────────── */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }

  /* Cards */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
    transition: border-color .2s, background .2s;
    box-shadow: var(--shadow);
  }
  .card:hover { border-color: var(--blue); background: var(--bg-card-hover); }
  .card .label { font-size: .75rem; text-transform: uppercase; letter-spacing: .5px; color: var(--text-muted); margin-bottom: 4px; }
  .card .value { font-size: 1.4rem; font-weight: 700; }
  .card .sub { font-size: .8rem; color: var(--text-secondary); margin-top: 2px; }
  .card .value.green { color: var(--green); }
  .card .value.red { color: var(--red); }
  .card .value.yellow { color: var(--yellow); }
  .card .value.blue { color: var(--blue); }

  /* ── Charts ─────────────────────────────────────────────── */
  .chart-row {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 12px;
    margin-bottom: 20px;
  }
  .chart-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
    box-shadow: var(--shadow);
  }
  .chart-card .chart-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 12px;
  }
  .chart-card .chart-title { font-size: .9rem; font-weight: 600; color: var(--text-secondary); }
  .chart-card canvas { max-height: 280px; max-width: 100%; }

  /* ── Tables ─────────────────────────────────────────────── */
  .table-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
  }
  .table-card .table-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 12px;
  }
  .table-card .table-title { font-size: .9rem; font-weight: 600; color: var(--text-secondary); }
  .table-card .table-count { font-size: .8rem; color: var(--text-muted); }

  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th {
    text-align: left;
    padding: 10px 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    font-size: .7rem;
    letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  td {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  tr:hover td { background: rgba(59,130,246,0.04); }
  tr:last-child td { border-bottom: none; }
  .tag {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: .75rem;
    font-weight: 600;
  }
  .tag.win { background: var(--green-bg); color: var(--green); }
  .tag.loss { background: var(--red-bg); color: var(--red); }
  .tag.pending { background: var(--yellow-bg); color: var(--yellow); }
  .tag.long { background: var(--blue-bg); color: var(--blue); }
  .tag.short { background: var(--purple); color: #fff; opacity: .85; }
  .mono { font-family: 'SF Mono', 'Fira Code', monospace; }

  /* ── Responsive ─────────────────────────────────────────── */
  @media (max-width: 900px) {
    .chart-row { grid-template-columns: 1fr; }
    body { padding: 12px; }
    .header { flex-direction: column; align-items: stretch; }
    .header-right { flex-wrap: wrap; }
  }

  /* ── Refresh indicator ──────────────────────────────────── */
  .refresh-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 0; color: var(--text-muted); font-size: .75rem;
  }
  .refresh-bar .spinner {
    width: 10px; height: 10px; border-radius: 50%;
    border: 2px solid var(--border);
    border-top-color: var(--blue);
    animation: spin 1s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Empty state ────────────────────────────────────────── */
  .empty { text-align: center; padding: 40px 20px; color: var(--text-muted); }
  .empty .icon { font-size: 2.5rem; margin-bottom: 8px; }
  .empty p { font-size: .9rem; }
</style>
</head>
<body>
<div class="container">
  <!-- Header -->
  <div class="header" id="header">
    <div class="header-left">
      <h1>☰ Polymarket BTC Bot</h1>
      <span class="status-badge sim" id="modeBadge"><span class="dot"></span>SIMULATION</span>
      <span class="status-badge" id="dataSourceBadge" style="background:var(--blue-bg);color:var(--blue);font-size:.7rem">LIVE</span>
    </div>
    <div class="header-right">
      <span><span class="label">Market</span> <span id="currentMarket">—</span></span>
      <span><span class="label">Price</span> <span id="currentPrice" class="mono">—</span></span>
      <span><span class="label">Uptime</span> <span id="uptime">—</span></span>
      <span><span class="label">Ticks</span> <span id="totalTicks">0</span></span>
    </div>
  </div>

  <!-- Summary Cards -->
  <div class="grid" id="summaryCards">
    <div class="card"><div class="label">Total P&amp;L</div><div class="value" id="totalPnl">—</div><div class="sub" id="pnlSub">—</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value blue" id="winRate">—</div><div class="sub" id="winRateSub">— closed trades</div></div>
    <div class="card"><div class="label">Total Trades</div><div class="value" id="totalTrades">—</div><div class="sub" id="tradesSub">—</div></div>
    <div class="card"><div class="label">Current Capital</div><div class="value" id="currentCapital">—</div><div class="sub" id="capitalSub">—</div></div>
    <div class="card"><div class="label">Total Volume</div><div class="value" id="totalVolume">—</div><div class="sub">lifetime traded</div></div>
    <div class="card"><div class="label">ROI</div><div class="value" id="roi">—</div><div class="sub" id="roiSub">return on capital</div></div>
  </div>

  <!-- Charts -->
  <div class="chart-row">
    <div class="chart-card">
      <div class="chart-header"><span class="chart-title">Equity Curve</span><span class="chart-title" style="font-size:.7rem;color:var(--text-muted)" id="equityLabel">—</span></div>
      <canvas id="equityChart"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-header"><span class="chart-title">Daily P&amp;L (30d)</span></div>
      <canvas id="dailyPnlChart"></canvas>
    </div>
  </div>

  <!-- Positions + Trades side by side on wide screens -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px" id="tablesGrid">
    <!-- Open Positions -->
    <div class="table-card">
      <div class="table-header"><span class="table-title">Open Positions</span><span class="table-count" id="positionsCount">0</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>Dir</th><th>Size</th><th>Entry</th><th>SL</th><th>TP</th><th>Age</th></tr></thead>
          <tbody id="positionsBody"><tr><td colspan="7" class="empty"><div class="icon">📭</div><p>No open positions</p></td></tr></tbody>
        </table>
      </div>
    </div>
    <!-- Recent Trades -->
    <div class="table-card">
      <div class="table-header"><span class="table-title">Recent Trades</span><span class="table-count" id="tradesCount">0</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Dir</th><th>Size</th><th>Price</th><th>Score</th><th>Conf</th><th>Outcome</th><th>Market</th></tr></thead>
          <tbody id="tradesBody"><tr><td colspan="8" class="empty"><div class="icon">📊</div><p>No trades yet — start the bot!</p></td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Risk Panel -->
  <div class="table-card">
    <div class="table-header"><span class="table-title">Risk Dashboard</span><span class="table-count" id="riskAlerts">0 alerts</span></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px" id="riskPanel">
      <div class="card"><div class="label">Exposure</div><div class="value blue" id="riskExposure">$0.00</div><div class="sub" id="riskExposurePct">0% of limit</div></div>
      <div class="card"><div class="label">Daily P&amp;L</div><div class="value" id="riskDailyPnl">$0.00</div><div class="sub" id="riskDailyLimit">Limit: $5.00</div></div>
      <div class="card"><div class="label">Drawdown</div><div class="value" id="riskDrawdown">0%</div><div class="sub" id="riskDrawdownMax">Max: 15%</div></div>
      <div class="card"><div class="label">Open Positions</div><div class="value" id="riskOpenPositions">0</div><div class="sub" id="riskMaxPositions">Max: 5</div></div>
      <div class="card"><div class="label">Balance</div><div class="value" id="riskBalance">$1,000</div><div class="sub" id="riskPeak">Peak: $1,000</div></div>
    </div>
  </div>

  <!-- Refresh bar -->
  <div class="refresh-bar">
    <div class="spinner"></div>
    <span>Auto-refreshing every <strong>10s</strong></span>
    <span style="margin-left:auto" id="lastRefresh">—</span>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────
let equityChart = null;
let dailyPnlChart = null;
const REFRESH_MS = 10000;

// ── Helpers ──────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }
function setText(id, val) { const el = $(id); if (el) el.textContent = val; }
function fmtPrice(v) { return '$' + Number(v).toLocaleString(undefined, {minimumFractionDigits:2,maximumFractionDigits:4}); }
function fmtPct(v) { return Number(v).toFixed(1) + '%'; }
function fmtTime(iso) { if (!iso || iso === 'start') return '—'; try { return new Date(iso).toLocaleTimeString(); } catch { return iso; } }

// ── Fetch ────────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ── Update summary cards ─────────────────────────────────────
function updateStats(data) {
  setText('totalTrades', data.total_trades);
  setText('tradesSub', data.wins + 'W / ' + data.losses + 'L / ' + data.pending + 'P');
  setText('totalVolume', fmtPrice(data.total_volume));
  setText('winRate', fmtPct(data.win_rate));
  setText('winRateSub', (data.wins + data.losses) + ' closed trades');
}

// ── Update performance ───────────────────────────────────────
function updatePerformance(data) {
  const pnl = data.total_pnl || 0;
  const el = $('totalPnl');
  el.textContent = (pnl >= 0 ? '+' : '') + fmtPrice(pnl);
  el.className = 'value ' + (pnl >= 0 ? 'green' : 'red');
  setText('pnlSub', (data.total_trades || 0) + ' trades settled');

  setText('currentCapital', fmtPrice(data.current_capital || 1000));
  setText('capitalSub', 'starting $1,000');

  const roi = data.roi || 0;
  const roiEl = $('roi');
  roiEl.textContent = (roi >= 0 ? '+' : '') + roi.toFixed(2) + '%';
  roiEl.className = 'value ' + (roi >= 0 ? 'green' : 'red');
  setText('roiSub', 'return on capital');

  // Equity curve
  const eq = data.equity_curve || [];
  if (eq.length > 0) {
    const labels = eq.map(p => fmtTime(p.timestamp));
    const values = eq.map(p => p.equity);
    setText('equityLabel', eq.length + ' points · final: ' + fmtPrice(values[values.length-1]));
    if (equityChart) { equityChart.data.labels = labels; equityChart.data.datasets[0].data = values; equityChart.update(); }
  }

  // Daily PnL
  const daily = data.daily_pnl || [];
  if (daily.length > 0 && dailyPnlChart) {
    const dl = daily.map(p => p.date ? p.date.slice(5) : '');
    const dv = daily.map(p => p.pnl || 0);
    dailyPnlChart.data.labels = dl;
    dailyPnlChart.data.datasets[0].data = dv;
    dailyPnlChart.update();
  }

  // Distribution
  if (data.distribution) {
    const d = data.distribution;
    const t = d.total_trades || 0;
    const w = (d.wins && d.wins.count) || 0;
    const l = (d.losses && d.losses.count) || 0;
    setText('tradesSub', w + 'W / ' + l + 'L' + (t > w+l ? ' / ' + (t-w-l) + 'P' : ''));
  }
}

// ── Update positions table ───────────────────────────────────
function updatePositions(data) {
  const tbody = $('positionsBody');
  const positions = data.positions || [];
  setText('positionsCount', positions.length + ' open');

  if (positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty"><div class="icon">📭</div><p>No open positions</p></td></tr>';
    return;
  }

  tbody.innerHTML = positions.map(p => {
    const dir = (p.direction || '').toLowerCase();
    const age = p.entry_time ? Math.floor((Date.now() - new Date(p.entry_time).getTime()) / 1000) + 's' : '—';
    return `<tr>
      <td class="mono">${(p.position_id || '').slice(-10)}</td>
      <td><span class="tag ${dir}">${(p.direction || '—').toUpperCase()}</span></td>
      <td class="mono">${fmtPrice(p.size || p.current_size || 0)}</td>
      <td class="mono">${fmtPrice(p.entry_price || 0)}</td>
      <td class="mono">${p.stop_loss ? fmtPrice(p.stop_loss) : '—'}</td>
      <td class="mono">${p.take_profit ? fmtPrice(p.take_profit) : '—'}</td>
      <td>${age}</td>
    </tr>`;
  }).join('');
}

// ── Update trades table ──────────────────────────────────────
function updateTrades(trades) {
  const tbody = $('tradesBody');
  setText('tradesCount', trades.length + ' recent');

  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty"><div class="icon">📊</div><p>No trades yet — start the bot!</p></td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const dir = (t.direction || '').toLowerCase();
    const outcome = (t.outcome || 'PENDING').toLowerCase();
    return `<tr>
      <td style="color:var(--text-muted)">${fmtTime(t.timestamp)}</td>
      <td><span class="tag ${dir}">${(t.direction || '—').toUpperCase()}</span></td>
      <td class="mono">${fmtPrice(t.size_usd || 0)}</td>
      <td class="mono">${fmtPrice(t.price || 0)}</td>
      <td class="mono">${(t.signal_score || 0).toFixed(1)}</td>
      <td class="mono">${((t.signal_confidence || 0)*100).toFixed(0)}%</td>
      <td><span class="tag ${outcome}">${t.outcome || 'PENDING'}</span></td>
      <td style="color:var(--text-muted);font-size:.75rem">${(t.market_slug || '').slice(-30)}</td>
    </tr>`;
  }).join('');
}

// ── Update risk panel ────────────────────────────────────────
function updateRisk(data) {
  const exp = data.exposure || {};
  const pnl = data.pnl || {};
  const bal = data.balance || {};
  const pos = data.positions || {};
  const ds = data.daily_stats || {};

  setText('riskExposure', fmtPrice(exp.current || 0));
  setText('riskExposurePct', (exp.utilization_pct || 0).toFixed(1) + '% of limit');

  const dailyPnl = pnl.daily || 0;
  const dailyEl = $('riskDailyPnl');
  dailyEl.textContent = (dailyPnl >= 0 ? '+' : '') + fmtPrice(dailyPnl);
  dailyEl.className = 'value ' + (dailyPnl >= 0 ? 'green' : 'red');
  setText('riskDailyLimit', 'Limit: ' + fmtPrice(pnl.daily_limit || 5));

  const dd = bal.drawdown_pct || 0;
  const ddEl = $('riskDrawdown');
  ddEl.textContent = dd.toFixed(2) + '%';
  ddEl.className = 'value ' + (dd > 5 ? 'red' : dd > 2 ? 'yellow' : 'blue');
  setText('riskDrawdownMax', 'Max: ' + (bal.max_drawdown_pct || 15).toFixed(0) + '%');

  setText('riskOpenPositions', pos.count || 0);
  setText('riskMaxPositions', 'Max: ' + (pos.max_allowed || 5));

  setText('riskBalance', fmtPrice(bal.current || 1000));
  setText('riskPeak', 'Peak: ' + fmtPrice(bal.peak || 1000));

  setText('riskAlerts', (data.alerts || 0) + ' alerts (1h)');
}

// ── Update status bar ────────────────────────────────────────
function updateStatus(data) {
  const badge = $('modeBadge');
  const mode = (data.mode || 'simulation').toLowerCase();
  badge.className = 'status-badge ' + (mode === 'live' ? 'live' : 'sim');
  badge.innerHTML = '<span class="dot"></span>' + mode.toUpperCase();

  // Data source
  const srcBadge = $('dataSourceBadge');
  if (data.mode === 'live' || data.mode === 'simulation') {
    srcBadge.style.display = 'inline-flex';
  }

  setText('currentMarket', data.current_market || '—');
  const price = data.current_price;
  if (price) setText('currentPrice', fmtPrice(price));

  const uptime = data.uptime_seconds || 0;
  const h = Math.floor(uptime / 3600);
  const m = Math.floor((uptime % 3600) / 60);
  const s = uptime % 60;
  setText('uptime', h + 'h ' + m + 'm ' + s + 's');
  setText('totalTicks', data.total_ticks || 0);
}

// ── Full refresh ─────────────────────────────────────────────
async function refresh() {
  try {
    const [stats, perf, risk, positions, trades, status] = await Promise.all([
      fetchJSON('/api/stats'),
      fetchJSON('/api/performance'),
      fetchJSON('/api/risk'),
      fetchJSON('/api/positions'),
      fetchJSON('/api/trades?limit=30'),
      fetchJSON('/api/status'),
    ]);

    updateStats(stats);
    updatePerformance(perf);
    updateRisk(risk);
    updatePositions(positions);
    updateTrades(trades);
    updateStatus(status);

    setText('lastRefresh', new Date().toLocaleTimeString());
  } catch (e) {
    console.error('Refresh failed:', e);
    setText('lastRefresh', '⚠ Error: ' + e.message);
  }
}

// ── Init charts ──────────────────────────────────────────────
function initCharts() {
  const commonOpts = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(15,23,42,0.9)',
        titleColor: '#e4e8ef',
        bodyColor: '#8892a6',
        borderColor: '#2a3446',
        borderWidth: 1,
        cornerRadius: 8,
      }
    },
    scales: {
      x: {
        ticks: { color: '#5a6478', maxTicksLimit: 10, font: { size: 10 } },
        grid: { color: 'rgba(42,52,70,0.3)' },
      },
      y: {
        ticks: { color: '#5a6478', font: { size: 10 } },
        grid: { color: 'rgba(42,52,70,0.3)' },
      }
    }
  };

  const ctx1 = document.getElementById('equityChart').getContext('2d');
  equityChart = new Chart(ctx1, {
    type: 'line',
    data: { labels: [], datasets: [{
      label: 'Equity',
      data: [],
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
      pointHoverRadius: 5,
      borderWidth: 2,
    }]},
    options: {
      ...commonOpts,
      plugins: { ...commonOpts.plugins },
      scales: {
        x: { ...commonOpts.scales.x, display: true },
        y: { ...commonOpts.scales.y, beginAtZero: false },
      }
    }
  });

  const ctx2 = document.getElementById('dailyPnlChart').getContext('2d');
  dailyPnlChart = new Chart(ctx2, {
    type: 'bar',
    data: { labels: [], datasets: [{
      label: 'Daily P&L',
      data: [],
      backgroundColor: [],
      borderRadius: 4,
      borderSkipped: false,
    }]},
    options: {
      ...commonOpts,
      plugins: { ...commonOpts.plugins },
      scales: {
        x: { ...commonOpts.scales.x, display: true },
        y: { ...commonOpts.scales.y, beginAtZero: true },
      }
    }
  });

  // Fix bar colors on update
  const origUpdate = dailyPnlChart.update;
  dailyPnlChart.update = function() {
    const colors = this.data.datasets[0].data.map(v => v >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)');
    this.data.datasets[0].backgroundColor = colors;
    return origUpdate.call(this, arguments);
  };
}

// ── Start ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  refresh();
  setInterval(refresh, REFRESH_MS);
});
</script>
</body>
</html>"""


# =====================================================================
#  SERVER
# =====================================================================

class DashboardServer:
    """Manages the dashboard HTTP server lifecycle."""

    def __init__(self, host: str = "0.0.0.0", port: int = 3000):
        self.host = host
        self.port = port
        self._server = None
        self._thread = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def start(self):
        """Start the dashboard server in a daemon thread."""
        if self._server:
            logger.warning("Dashboard server already running")
            return

        self._server = HTTPServer((self.host, self.port), DashboardHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        logger.info(f"✓ Trading dashboard started at {self.url}")
        logger.info(f"  Dashboard UI: {self.url}")
        logger.info(f"  API:          {self.url}/api/status")

    def stop(self):
        """Stop the dashboard server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("Dashboard server stopped")


# Singleton
_instance = None


def get_dashboard(port: int = 3000) -> DashboardServer:
    """Get or create the dashboard server singleton."""
    global _instance
    if _instance is None:
        _instance = DashboardServer(port=port)
    return _instance


# ── Standalone entry point ─────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot Dashboard")
    parser.add_argument("--port", type=int, default=3000, help="Port to serve on (default: 3000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <level>{message}</level>")

    server = get_dashboard(port=args.port)
    server._server = HTTPServer((args.host, args.port), DashboardHandler)

    logger.info(f"{'='*50}")
    logger.info(f"  POLYMARKET TRADING BOT DASHBOARD")
    logger.info(f"{'='*50}")
    logger.info(f"  Dashboard UI: http://localhost:{args.port}")
    logger.info(f"  API:          http://localhost:{args.port}/api/status")
    logger.info(f"{'='*50}")
    logger.info(f"  Press Ctrl+C to stop")
    logger.info(f"{'='*50}")

    try:
        server._server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        server._server.server_close()
