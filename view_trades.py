"""
View simulation/paper trades from SQLite database.
Usage:
    python view_trades.py              # last 20 trades
    python view_trades.py --all        # all trades
    python view_trades.py --limit 50   # last 50 trades
    python view_trades.py --stats      # summary stats only
    python view_trades.py --outcome WIN   # filter by outcome
"""
import argparse
import sys
from datetime import datetime

from monitoring.trade_db import get_trades, get_stats


def show_stats():
    s = get_stats()
    wins = s["wins"] or 0
    losses = s["losses"] or 0
    pending = s["pending"] or 0
    total = s["total_trades"] or 0
    volume = s["total_volume"] or 0.0
    avg_price = s["avg_price"]

    print("=" * 60)
    print("  TRADING STATISTICS")
    print("=" * 60)
    print(f"  Total trades : {total}")
    print(f"  Wins         : {wins}")
    print(f"  Losses       : {losses}")
    print(f"  Pending      : {pending}")
    closed = wins + losses
    if closed:
        print(f"  Win rate     : {wins / closed * 100:.1f}%")
    print(f"  Total volume : ${volume:.2f}")
    print(f"  Avg price    : ${avg_price:.4f}" if avg_price else "  Avg price    : N/A")
    print()


def show_trades(limit=20, direction=None, outcome=None):
    trades = get_trades(limit=limit, direction=direction, outcome=outcome)

    if not trades:
        print("No trades found.")
        return

    print("=" * 130)
    print(f"{'ID':<5} {'Time (UTC)':<20} {'Dir':<6} {'Size':<8} {'Price':<10} {'Score':<7} {'Conf':<8} {'Outcome':<10} {'Market'}")
    print("=" * 130)
    for t in trades:
        ts = t["timestamp"][:19] if t.get("timestamp") else "-"
        slug = t.get("market_slug", "")[-40:] if t.get("market_slug") else "-"
        price = t.get("price", 0) or 0
        size = t.get("size_usd", 0) or 0
        score = t.get("signal_score", 0) or 0
        conf = t.get("signal_confidence", 0) or 0
        print(
            f"{t.get('id', '?'):<5} {ts:<20} {t.get('direction', '?'):<6} "
            f"${size:<5.2f} ${price:<7.4f} "
            f"{score:<7.1f} {conf:.0%}    "
            f"{t.get('outcome', '?'):<10} {slug}"
        )
    print("=" * 130)
    total = len(trades)
    wins = sum(1 for t in trades if t.get("outcome") == "WIN")
    losses = sum(1 for t in trades if t.get("outcome") == "LOSS")
    closed = wins + losses
    if closed:
        print(f"  Displayed: {total} trades | {wins}W / {losses}L ({wins/closed*100:.1f}%)")
    else:
        print(f"  Displayed: {total} trades")


def main():
    parser = argparse.ArgumentParser(description="View paper trades from SQLite database")
    parser.add_argument("--limit", type=int, default=20, help="Number of trades to show")
    parser.add_argument("--all", action="store_true", help="Show all trades")
    parser.add_argument("--stats", action="store_true", help="Show summary stats only")
    parser.add_argument("--outcome", choices=["WIN", "LOSS", "PENDING"], help="Filter by outcome")
    parser.add_argument("--direction", choices=["LONG", "SHORT"], help="Filter by direction")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    limit = 999999 if args.all else args.limit
    show_trades(limit=limit, direction=args.direction, outcome=args.outcome)


if __name__ == "__main__":
    main()
