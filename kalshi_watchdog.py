"""Kalshi Watchdog — runs independently of Jarvis web server.
Analyzes bot strategy and scans markets on a schedule.
Set up as a Windows Task Scheduler job to run even when Jarvis is closed.

Usage:
  python kalshi_watchdog.py          # Run once
  python kalshi_watchdog.py --loop   # Run every 2 hours
"""

import sys
import os
import json
import datetime
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent / ".env")

import httpx
import anthropic

KALSHI_BOT_URL = os.getenv("KALSHI_BOT_URL", "https://web-production-c8a5b.up.railway.app")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
REPORTS_DIR = Path(__file__).parent / "data" / "kalshi_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def bot_get(endpoint):
    try:
        resp = httpx.get(f"{KALSHI_BOT_URL}{endpoint}", timeout=15)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def get_live_scores():
    scores = {}
    for sport, path in [("mlb", "baseball/mlb"), ("nba", "basketball/nba"), ("nhl", "hockey/nhl")]:
        try:
            resp = httpx.get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard", timeout=8)
            for e in resp.json().get("events", [])[:5]:
                name = e.get("shortName", "")
                status = e.get("status", {}).get("type", {}).get("shortDetail", "")
                comps = e.get("competitions", [{}])[0].get("competitors", [])
                score = " - ".join(f"{c.get('team', {}).get('abbreviation', '?')} {c.get('score', '0')}" for c in comps)
                scores[name] = f"{score} ({status})"
        except Exception:
            pass
    return scores


def run_analysis():
    print(f"[{datetime.datetime.now().strftime('%I:%M %p')}] Running Kalshi analysis...")

    # Pull all data
    portfolio = bot_get("/api/portfolio")
    status = bot_get("/api/bot/status")
    trades = bot_get("/api/bot/trades?limit=30")
    signals = bot_get("/api/bot/signals")
    warnings = bot_get("/api/bot/warnings")
    scores = get_live_scores()

    signal_list = signals.get("signals", [])
    trade_list = trades.get("trades", [])
    warning_list = warnings.get("warnings", [])
    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else []

    # Skip reasons
    skip_reasons = {}
    for s in signal_list:
        reason = s.get("skip_reason", "acted")
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    prompt = f"""You are a quantitative trading advisor for a Kalshi prediction market bot.
Give specific, actionable analysis. Be direct.

## Bot Status
- Running: {status.get('running', '?')}
- Balance: ${portfolio.get('balance', 0):.2f} | Portfolio: ${portfolio.get('portfolio_value', 0):.2f}
- Positions: {portfolio.get('position_count', 0)} | Consecutive losses: {status.get('consecutive_losses', 0)}
- Scans: {status.get('scan_count', 0)} | Trades today: {status.get('trades_today', 0)}
- Warnings: {warning_list}

## Signal Skip Reasons (last 50)
{json.dumps(skip_reasons, indent=2)}

## Top Signals
{json.dumps(signal_list[:10], indent=2, default=str)}

## Current Positions
{json.dumps([dict(ticker=p.get('ticker',''), side=p.get('side',''), price=p.get('avg_price',0), pnl=p.get('upnl',0)) for p in positions], indent=2)}

## Live Scores
{json.dumps(scores, indent=2) if scores else 'No live games'}

## Provide:
1. STRATEGY REVIEW: What's working, what's failing, why the losing streak
2. TOP 3 OPPORTUNITIES: Best signals to act on with reasoning
3. POSITION REVIEW: Hold/exit recommendations for each position
4. BOT IMPROVEMENTS: 3 specific changes to improve profitability
5. RISK ASSESSMENT: Current risk level and what to watch

Keep under 400 words. Use US dollars."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = resp.content[0].text
    except Exception as e:
        analysis = f"Analysis failed: {e}"

    # Save report
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report = f"=== KALSHI WATCHDOG REPORT — {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')} ===\n\n"
    report += analysis
    report += f"\n\n---\nBot balance: ${portfolio.get('balance', 0):.2f} | "
    report += f"Positions: {portfolio.get('position_count', 0)} | "
    report += f"Losses streak: {status.get('consecutive_losses', 0)}\n"

    report_path = REPORTS_DIR / f"watchdog_{timestamp}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"  Report saved: {report_path.name}")
    print(f"  Balance: ${portfolio.get('balance', 0):.2f} | Positions: {portfolio.get('position_count', 0)}")

    return report


if __name__ == "__main__":
    if "--loop" in sys.argv:
        print("Kalshi Watchdog started — running every 2 hours. Press Ctrl+C to stop.")
        while True:
            try:
                run_analysis()
                print(f"  Next run at {(datetime.datetime.now() + datetime.timedelta(hours=2)).strftime('%I:%M %p')}")
                time.sleep(7200)  # 2 hours
            except KeyboardInterrupt:
                print("\nWatchdog stopped.")
                break
            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(300)  # Retry in 5 min on error
    else:
        run_analysis()
        print("Done. Run with --loop for continuous monitoring.")
