"""Strategy backtester — simulate config changes against historical signals."""

import json
import datetime

import anthropic
import httpx

from jarvis.config import ANTHROPIC_API_KEY, KALSHI_BOT_URL
from jarvis.tools.base import Tool, registry


def _bot_get(endpoint: str):
    try:
        return httpx.get(f"{KALSHI_BOT_URL}{endpoint}", timeout=15).json()
    except Exception as e:
        return {"error": str(e)}


def backtest_config(changes: str = "", **kwargs) -> str:
    """Simulate how different config settings would have performed against recent signals."""
    signals = _bot_get("/api/bot/signals?limit=50")
    analytics = _bot_get("/api/bot/analytics")
    config = _bot_get("/api/bot/config")
    current_config = config.get("config", {})

    signal_list = signals.get("signals", [])
    if not signal_list:
        return "No signal history to backtest against."

    # Parse proposed changes
    proposed = dict(current_config)
    if changes:
        try:
            mods = json.loads(changes)
            proposed.update(mods)
        except json.JSONDecodeError:
            for part in changes.split(","):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    try:
                        proposed[k.strip()] = float(v.strip()) if "." in v else int(v.strip())
                    except ValueError:
                        pass

    # Simulate: how many signals would have been acted on with each config
    current_acted = 0
    proposed_acted = 0
    current_skipped_reasons = {}
    proposed_skipped_reasons = {}

    for sig in signal_list:
        edge = sig.get("edge", 0)
        spread = sig.get("spread_cents", 0)
        volume = sig.get("volume_24h", 0)
        skip_reason = sig.get("skip_reason", "")

        # Current config simulation
        if not skip_reason or skip_reason == "acted":
            current_acted += 1
        else:
            current_skipped_reasons[skip_reason] = current_skipped_reasons.get(skip_reason, 0) + 1

        # Proposed config simulation
        would_skip = False
        reason = ""
        if edge < proposed.get("min_edge", 0.06):
            would_skip = True
            reason = "edge_too_low"
        elif edge > proposed.get("max_edge", 0.15):
            would_skip = True
            reason = "edge_too_high"
        elif spread > proposed.get("max_spread_cents", 15):
            would_skip = True
            reason = "spread_too_wide"
        elif volume < proposed.get("min_volume_24h", 200):
            would_skip = True
            reason = "low_volume"

        if would_skip:
            proposed_skipped_reasons[reason] = proposed_skipped_reasons.get(reason, 0) + 1
        else:
            proposed_acted += 1

    # Use Claude to analyze the comparison
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""Compare these two Kalshi bot configs based on signal simulation:

CURRENT CONFIG: acted on {current_acted}/{len(signal_list)} signals
  Skip reasons: {json.dumps(current_skipped_reasons)}
  Key settings: min_edge={current_config.get('min_edge')}, max_edge={current_config.get('max_edge')}, min_volume={current_config.get('min_volume_24h')}

PROPOSED CONFIG: would act on {proposed_acted}/{len(signal_list)} signals
  Skip reasons: {json.dumps(proposed_skipped_reasons)}
  Key changes: {changes or 'none specified'}

In 2-3 sentences, explain which config is better and why. Use US dollars. Be direct."""
            }],
        )
        analysis = resp.content[0].text
    except Exception:
        analysis = ""

    result = f"Backtest results ({len(signal_list)} signals):\n"
    result += f"  Current config: {current_acted} acted, {len(signal_list) - current_acted} skipped\n"
    result += f"  Proposed config: {proposed_acted} acted, {len(signal_list) - proposed_acted} skipped\n"
    result += f"  Difference: {'+'if proposed_acted > current_acted else ''}{proposed_acted - current_acted} signals\n"
    if analysis:
        result += f"\n{analysis}"

    return result


def get_equity_history(**kwargs) -> str:
    """Get the equity curve data for charting."""
    equity = _bot_get("/api/bot/equity?days=30")
    points = equity.get("equity", [])

    if not points:
        return "No equity data available yet."

    lines = [f"Equity curve ({len(points)} data points):"]

    # Summarize — show daily snapshots
    seen_dates = {}
    for p in points:
        ts = p.get("ts", "")
        date = ts[:10] if ts else "?"
        if date not in seen_dates:
            seen_dates[date] = p

    for date, p in list(seen_dates.items())[-7:]:
        equity_cents = p.get("equity_cents", 0)
        pnl = p.get("daily_pnl_cents", 0)
        positions = p.get("open_positions", 0)
        lines.append(f"  {date}: ${equity_cents/100:.2f} equity, {positions} positions, P&L ${pnl/100:+.2f}")

    # Current
    if points:
        latest = points[-1]
        lines.append(f"\nCurrent: ${latest.get('equity_cents', 0)/100:.2f} equity")

    return "\n".join(lines)


def get_strategy_performance(**kwargs) -> str:
    """Get performance breakdown by strategy."""
    perf = _bot_get("/api/bot/performance")
    analytics = _bot_get("/api/bot/analytics")

    lines = ["Bot Performance Summary:"]
    lines.append(f"  Total signals evaluated: {analytics.get('total_signals', 0)}")
    lines.append(f"  Total trades: {analytics.get('total_trades', 0)}")
    lines.append(f"  Win rate: {analytics.get('win_rate', 0):.0%}")
    lines.append(f"  Average edge: {analytics.get('avg_edge', 0):.1f}%")
    lines.append(f"  Total P&L: ${analytics.get('total_pnl_cents', 0)/100:.2f}")

    by_strat = perf.get("by_strategy", {})
    if by_strat:
        lines.append("\nBy Strategy:")
        for strat, data in by_strat.items():
            lines.append(f"  {strat}: {json.dumps(data)}")

    by_series = perf.get("by_series", {})
    if by_series:
        lines.append("\nBy Market Series:")
        for series, data in list(by_series.items())[:10]:
            lines.append(f"  {series}: {json.dumps(data)}")

    return "\n".join(lines)


# ─── Register ───

registry.register(Tool(
    name="backtest_config",
    description="Simulate how different bot config settings would perform against recent signal history. Use for 'what if I changed min edge to 8%', 'backtest this config', 'would these settings be better'. Pass changes as JSON or key=value.",
    parameters={
        "type": "object",
        "properties": {
            "changes": {"type": "string", "description": "Config changes to test (e.g. 'min_edge=0.08, max_positions=10' or JSON)"},
        },
    },
    handler=backtest_config,
))

registry.register(Tool(
    name="get_equity_history",
    description="Get the bot's equity curve over the last 30 days. Use for 'show equity curve', 'how has the bot performed over time', 'chart my bot'.",
    parameters={"type": "object", "properties": {}},
    handler=get_equity_history,
))

registry.register(Tool(
    name="get_strategy_performance",
    description="Get performance breakdown by strategy and market series. Use for 'which strategy is best', 'performance by strategy', 'bot stats'.",
    parameters={"type": "object", "properties": {}},
    handler=get_strategy_performance,
))
