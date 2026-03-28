"""Kalshi Strategy Advisor — AI-powered analysis, optimization, and autonomous bot control.

Jarvis has full knowledge of how the bot works and can:
1. Analyze performance and identify what's working/failing
2. Scan markets for opportunities
3. CHANGE bot config at runtime (edge thresholds, bet sizing, strategies, etc.)
4. Run autonomously in the background to optimize the bot
"""

import json
import datetime
import threading
from pathlib import Path

import anthropic
import httpx

from jarvis.config import ANTHROPIC_API_KEY, KALSHI_BOT_URL
from jarvis.tools.base import Tool, registry

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "kalshi_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

_monitor_running = False
_monitor_thread = None

# ─── Complete bot knowledge for Jarvis ───
BOT_KNOWLEDGE = """
## HOW THE KALSHI BOT WORKS

The bot runs on Railway as a Flask app. It scans Kalshi prediction markets every 5 minutes
(2 min during live sports), evaluates signals from multiple strategies, and places small bets
when it finds an edge.

### STRATEGIES (6 signal sources)
1. **weather** — compares Open-Meteo forecasts vs Kalshi weather market prices
2. **polymarket** — cross-references Polymarket prices vs Kalshi (arbitrage-style)
3. **news_sentiment** — Google News headline sentiment analysis, shifts fair value +/-10%
4. **fred** — Federal Reserve economic data (CPI, jobs, GDP, fed rate)
5. **sports_odds** — historical stats for NBA, NFL, MLB, NHL, UCL
6. **correlated_arb** — finds pricing inconsistencies between related markets (e.g. P(above 3%) >= P(above 3.5%))

### SIGNAL SCORING (EV Score)
- Base EV = edge × payout_ratio
- Sweet spot bonus: +30% for 25-60% win probability
- Liquidity multiplier: 0.8-1.3x based on volume
- Spread penalty: 1% per cent of bid/ask spread
- Time multiplier: +50% for <4h to close, -60% for 30+ days out
- Multi-source bonus: +25% when 2+ strategies agree
- Source reliability weights: sports_odds=1.4x, fred=1.3x, weather=1.2x, polymarket=1.0x, news=0.9x

### POSITION SIZING (Kelly Criterion)
- Dynamic fraction = 0.15 × (edge/0.08)^mult × source_mult × time_mult × drawdown_mult
- Drawdown protection: scales down 15% per consecutive loss (min 0.25x)
- Hard cap: min(kelly × balance, max_bet_pct × balance, max_bet_dollars)

### SAFETY CIRCUIT BREAKERS (cannot be overridden)
- Max $2.00 per trade absolute
- Never buy contracts <10 cents or >85 cents
- Max 20 contracts per order
- Never risk >15% of portfolio on one trade
- Daily loss limit pauses all trading

### EXIT RULES
- Stop-loss: down >35% and worsening, or >50% hard stop
- Take-profit: up >50% but reversing, or >80% lock half
- Dead position: sell if worth <3 cents and cost >10 cents

### TUNABLE PARAMETERS (what Jarvis can change via /api/bot/config)
- min_edge: minimum edge to trigger a bet (default 5%, range 1-20%)
- max_edge: reject signals above this as model error (default 12%, range 5-30%)
- min_bet_cents: minimum bet size (default 5)
- max_bet_dollars: max per trade (default $1.50, range $0.05-$5.00)
- max_bet_pct: max bet as % of balance (default 8%)
- max_positions: max open positions (default 15, range 1-30)
- daily_loss_limit_cents: pause trading if daily loss exceeds (default 800 = $8)
- interval_seconds: scan frequency (default 300s, range 60-3600)
- min_volume_24h: skip markets with less volume (default 200)
- max_spread_cents: skip wide spreads (default 15)
- min_win_prob / max_win_prob: probability bounds (default 40-75%)
- multi_source_boost: EV bonus for multi-source agreement (default 0.25)
- max_series_positions / max_region_positions: correlation limits (default 2 each)
- min_poly_return: minimum Polymarket ROI (default 3%)
"""


def _bot_get(endpoint: str) -> dict | list | str:
    try:
        resp = httpx.get(f"{KALSHI_BOT_URL}{endpoint}", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return f"API error: {e}"


def _bot_post(endpoint: str, data: dict) -> dict | str:
    try:
        resp = httpx.post(
            f"{KALSHI_BOT_URL}{endpoint}",
            json=data,
            timeout=15,
        )
        return resp.json()
    except Exception as e:
        return f"API error: {e}"


def _get_all_bot_data() -> dict:
    data = {}
    for key, ep in [
        ("portfolio", "/api/portfolio"),
        ("status", "/api/bot/status"),
        ("trades", "/api/bot/trades?limit=30"),
        ("signals", "/api/bot/signals"),
        ("warnings", "/api/bot/warnings"),
        ("config", "/api/bot/config"),
        ("performance", "/api/bot/performance/daily"),
    ]:
        result = _bot_get(ep)
        data[key] = result if isinstance(result, dict) else {"raw": result}
    return data


def _get_live_scores() -> dict:
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


def analyze_kalshi_strategy(**kwargs) -> str:
    """Deep analysis of bot strategy with full knowledge of how the bot works."""
    data = _get_all_bot_data()

    status = data.get("status", {})
    portfolio = data.get("portfolio", {})
    trades = data.get("trades", {}).get("trades", [])
    signals = data.get("signals", {}).get("signals", [])
    warnings = data.get("warnings", {}).get("warnings", [])
    config = data.get("config", {}).get("config", {})
    performance = data.get("performance", {}).get("daily_pnl", [])

    skip_reasons = {}
    for s in signals:
        reason = s.get("skip_reason", "acted")
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    strategies = {}
    for t in trades:
        strat = t.get("strategy", "unknown")
        if strat not in strategies:
            strategies[strat] = {"count": 0, "total_edge": 0, "sources": []}
        strategies[strat]["count"] += 1
        strategies[strat]["total_edge"] += t.get("edge", 0)

    prompt = f"""You are JARVIS, an AI quantitative trading advisor with FULL knowledge of how the Kalshi bot works.

{BOT_KNOWLEDGE}

## CURRENT STATE
- Balance: ${portfolio.get('balance', 0):.2f} | Portfolio: ${portfolio.get('portfolio_value', 0):.2f}
- Positions: {portfolio.get('position_count', 0)} | Consecutive losses: {status.get('consecutive_losses', 0)}
- Scans: {status.get('scan_count', 0)} | Trades today: {status.get('trades_today', 0)} | Exits: {status.get('exits_today', 0)}
- Warnings: {warnings}

## CURRENT CONFIG
{json.dumps(config, indent=2) if config else 'Config endpoint not available yet'}

## STRATEGY PERFORMANCE
{json.dumps(strategies, indent=2)}

## SIGNAL SKIP REASONS (last 50)
{json.dumps(skip_reasons, indent=2)}

## RECENT TRADES
{json.dumps(trades[:8], indent=2, default=str)}

## DAILY P&L
{json.dumps(performance[-7:], indent=2) if performance else 'No data'}

## YOUR ANALYSIS (be specific, use your knowledge of the bot internals):
1. Which strategies are profitable vs bleeding money?
2. Are the skip filters (markets_disagree, edge_too_high, etc.) helping or costing money?
3. What specific config changes would improve profitability? Reference exact parameter names and values.
4. What's the optimal min_edge given the current hit rate?
5. Should bet sizing change? Is Kelly fraction too aggressive for the loss streak?
6. Any strategies that should be weighted differently?

Keep under 350 words. Use US dollars. Be direct — this is about making money."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = resp.content[0].text

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        (REPORTS_DIR / f"strategy_{timestamp}.txt").write_text(analysis, encoding="utf-8")
        return analysis
    except Exception as e:
        return f"Analysis failed: {e}"


def scan_kalshi_markets(**kwargs) -> str:
    """Scan for high-value opportunities with full bot knowledge."""
    signals = _bot_get("/api/bot/signals")
    if isinstance(signals, str):
        return signals

    signal_list = signals.get("signals", [])
    portfolio = _bot_get("/api/portfolio")
    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else []
    scores = _get_live_scores()

    news_context = ""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.news("Kalshi prediction markets sports betting odds", max_results=5))
            news_context = "\n".join(f"- {r.get('title', '')}" for r in results)
    except Exception:
        news_context = "News unavailable"

    prompt = f"""You are JARVIS scanning for profitable Kalshi opportunities.

{BOT_KNOWLEDGE}

## CURRENT SIGNALS (bot evaluated these)
{json.dumps(signal_list[:15], indent=2, default=str)}

## CURRENT POSITIONS
{json.dumps([dict(ticker=p.get('ticker',''), side=p.get('side',''), price=p.get('avg_price',0)) for p in positions], indent=2)}

## LIVE SCORES
{json.dumps(scores, indent=2) if scores else 'No live games'}

## NEWS
{news_context}

Find the TOP 3 best opportunities. For each:
1. What the bet is (explain the ticker in plain English)
2. Why it's profitable (edge, news, live score context)
3. Recommended side and confidence
4. Risk factors

Also: any current positions to EXIT immediately?
Under 250 words. US dollars."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        return f"Scan failed: {e}"


def optimize_bot(**kwargs) -> str:
    """Analyze the bot AND apply config changes to improve it. The big one."""
    data = _get_all_bot_data()

    status = data.get("status", {})
    portfolio = data.get("portfolio", {})
    trades = data.get("trades", {}).get("trades", [])
    signals = data.get("signals", {}).get("signals", [])
    warnings = data.get("warnings", {}).get("warnings", [])
    config = data.get("config", {}).get("config", {})

    skip_reasons = {}
    for s in signals:
        reason = s.get("skip_reason", "acted")
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    prompt = f"""You are JARVIS. You have full control of a Kalshi prediction market bot.
Your SOLE goal is to make it more profitable.

{BOT_KNOWLEDGE}

## CURRENT CONFIG
{json.dumps(config, indent=2) if config else 'Not available — deploy config endpoint first'}

## BOT STATE
- Balance: ${portfolio.get('balance', 0):.2f} | Positions: {portfolio.get('position_count', 0)}
- Consecutive losses: {status.get('consecutive_losses', 0)}
- Warnings: {warnings}

## SIGNAL SKIPS
{json.dumps(skip_reasons, indent=2)}

## TRADES (last 10)
{json.dumps(trades[:10], indent=2, default=str)}

## YOUR TASK
Based on your analysis, output a JSON object with EXACTLY the config changes to make.
Only include parameters you want to CHANGE. Use these exact keys:
min_edge, max_edge, min_bet_cents, max_bet_dollars, max_bet_pct, max_positions,
daily_loss_limit_cents, interval_seconds, min_volume_24h, max_spread_cents,
min_win_prob, max_win_prob, multi_source_boost, max_series_positions, min_poly_return

IMPORTANT: Output ONLY valid JSON wrapped in ```json blocks. Then a brief explanation (3-4 sentences) of WHY.

Example:
```json
{{"min_edge": 0.06, "max_bet_dollars": 1.00, "interval_seconds": 180}}
```
Explanation: Raising min_edge to filter out weak signals...
"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = resp.content[0].text

        # Parse the JSON config changes
        import re
        json_match = re.search(r'```json\s*(\{[^`]+\})\s*```', response_text)
        if not json_match:
            # Try bare JSON
            json_match = re.search(r'(\{[^}]+\})', response_text)

        if json_match:
            changes = json.loads(json_match.group(1))

            # Apply changes via bot API
            result = _bot_post("/api/bot/config", changes)

            # Save report
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            report = f"=== JARVIS OPTIMIZATION {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')} ===\n\n"
            report += f"Changes applied: {json.dumps(changes, indent=2)}\n\n"
            report += f"API response: {json.dumps(result, indent=2, default=str)}\n\n"
            report += f"Reasoning:\n{response_text}\n"
            (REPORTS_DIR / f"optimization_{timestamp}.txt").write_text(report, encoding="utf-8")

            if isinstance(result, dict) and result.get("ok"):
                updated = result.get("updated", {})
                changes_desc = ", ".join(f"{k}: {v['old']}→{v['new']}" for k, v in updated.items())
                # Extract explanation after the JSON block
                explanation = response_text.split("```")[-1].strip() if "```" in response_text else ""
                return f"Bot optimized. Changes: {changes_desc}. {explanation}"
            else:
                return f"Analysis complete but config endpoint not available yet. Recommended changes: {json.dumps(changes)}. Deploy the bot update first, then I can apply these. {response_text}"
        else:
            return f"Analysis: {response_text}"

    except Exception as e:
        return f"Optimization failed: {e}"


def adjust_bot_config(changes: str = "", **kwargs) -> str:
    """Manually adjust a specific bot config parameter."""
    if not changes:
        # Show current config
        config = _bot_get("/api/bot/config")
        if isinstance(config, dict) and config.get("ok"):
            lines = ["Current bot config:"]
            for k, v in config.get("config", {}).items():
                lines.append(f"  {k}: {v}")
            return "\n".join(lines)
        return f"Could not read config: {config}"

    try:
        params = json.loads(changes)
    except json.JSONDecodeError:
        # Try key=value format
        params = {}
        for part in changes.split(","):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                try:
                    params[k.strip()] = float(v.strip()) if "." in v else int(v.strip())
                except ValueError:
                    params[k.strip()] = v.strip()

    if not params:
        return "Provide changes as JSON or key=value pairs. Example: min_edge=0.06, max_bet_dollars=1.00"

    result = _bot_post("/api/bot/config", params)
    if isinstance(result, dict) and result.get("ok"):
        updated = result.get("updated", {})
        return "Config updated: " + ", ".join(f"{k}: {v['old']}→{v['new']}" for k, v in updated.items())
    return f"Config update result: {result}"


def _run_background_monitor():
    """Background loop — analyzes and optimizes every 2 hours."""
    global _monitor_running
    import time

    while _monitor_running:
        try:
            # Full optimization cycle
            result = optimize_bot()

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            report = f"=== AUTO-OPTIMIZE {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')} ===\n\n"
            report += result + "\n"
            (REPORTS_DIR / f"auto_{timestamp}.txt").write_text(report, encoding="utf-8")
        except Exception:
            pass

        for _ in range(240):  # 2 hours in 30s chunks
            if not _monitor_running:
                break
            time.sleep(30)


def start_kalshi_monitor(**kwargs) -> str:
    global _monitor_running, _monitor_thread
    if _monitor_running:
        return "Already monitoring and optimizing. I'll keep tuning the bot every 2 hours."

    _monitor_running = True
    _monitor_thread = threading.Thread(target=_run_background_monitor, daemon=True)
    _monitor_thread.start()

    # Run first optimization immediately
    try:
        result = optimize_bot()
        return f"Monitoring and auto-optimization started. First optimization done:\n\n{result}\n\nI'll keep tuning every 2 hours."
    except Exception:
        return "Monitoring started. I'll analyze and optimize the bot every 2 hours."


def stop_kalshi_monitor(**kwargs) -> str:
    global _monitor_running
    _monitor_running = False
    return "Monitoring stopped. Bot config stays as-is until you tell me otherwise."


def get_latest_report(**kwargs) -> str:
    reports = sorted(REPORTS_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return "No reports yet. Ask me to analyze or optimize your bot."

    latest = reports[0]
    content = latest.read_text(encoding="utf-8")
    age = datetime.datetime.now() - datetime.datetime.fromtimestamp(latest.stat().st_mtime)
    hours = age.total_seconds() / 3600
    age_str = f"{int(age.total_seconds() / 60)} minutes ago" if hours < 1 else f"{hours:.1f} hours ago"

    return f"[Report from {age_str}]\n\n{content}"


# ─── Register Tools ───

registry.register(Tool(
    name="analyze_kalshi_strategy",
    description="Deep analysis of Kalshi bot performance with full knowledge of bot internals. Use for 'analyze my bot', 'how's the bot doing', 'what should we change'.",
    parameters={"type": "object", "properties": {}},
    handler=analyze_kalshi_strategy,
))

registry.register(Tool(
    name="scan_kalshi_markets",
    description="Scan for best Kalshi opportunities right now. Cross-references signals, live scores, news. Use for 'find me good bets', 'what markets look profitable'.",
    parameters={"type": "object", "properties": {}},
    handler=scan_kalshi_markets,
))

registry.register(Tool(
    name="optimize_bot",
    description="Analyze the bot AND apply config changes to make it more profitable. Jarvis uses his knowledge of the bot to decide what to change, then changes it. Use for 'optimize my bot', 'make the bot better', 'improve the strategy', 'tune the bot'.",
    parameters={"type": "object", "properties": {}},
    handler=optimize_bot,
))

registry.register(Tool(
    name="adjust_bot_config",
    description="Read or manually change specific bot config parameters. Use for 'show bot config', 'change min edge to 6%', 'set max bet to $1'. Pass changes as JSON or key=value pairs.",
    parameters={
        "type": "object",
        "properties": {
            "changes": {
                "type": "string",
                "description": "Config changes as JSON or key=value pairs (e.g. 'min_edge=0.06, max_bet_dollars=1.00'). Empty to show current config.",
            },
        },
    },
    handler=adjust_bot_config,
))

registry.register(Tool(
    name="start_kalshi_monitor",
    description="Start autonomous bot monitoring and optimization. Jarvis analyzes and tunes the bot every 2 hours. Use for 'watch my bets', 'optimize while I'm away', 'keep improving the bot'.",
    parameters={"type": "object", "properties": {}},
    handler=start_kalshi_monitor,
))

registry.register(Tool(
    name="stop_kalshi_monitor",
    description="Stop autonomous bot monitoring. Use for 'stop watching', 'stop optimizing'.",
    parameters={"type": "object", "properties": {}},
    handler=stop_kalshi_monitor,
))

registry.register(Tool(
    name="get_latest_report",
    description="Get Jarvis's most recent bot analysis or optimization report. Use for 'what did you find?', 'any updates?', 'show me the report'.",
    parameters={"type": "object", "properties": {}},
    handler=get_latest_report,
))
