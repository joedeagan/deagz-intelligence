"""Kalshi trading bot integration — talks to the Flask API."""

import httpx

from jarvis.config import KALSHI_BOT_URL
from jarvis.tools.base import Tool, registry


def _get(endpoint: str, params: dict | None = None) -> dict | list | str:
    """Make a GET request to the Kalshi bot API."""
    try:
        resp = httpx.get(
            f"{KALSHI_BOT_URL}{endpoint}",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return "Could not connect to Kalshi bot. Is it running?"
    except Exception as e:
        return f"Kalshi API error: {e}"


def get_portfolio() -> str:
    data = _get("/api/portfolio")
    if isinstance(data, str):
        return data

    # Handle both cents-based and dollar-based API responses
    balance = data.get("balance", data.get("balance_cents", 0))
    available = data.get("available", data.get("available_cents", 0))
    if balance > 1000:  # cents
        balance /= 100
        available /= 100
    portfolio_value = data.get("portfolio_value", 0)
    total_pnl = data.get("unrealised_pnl", 0)
    positions = data.get("positions", [])

    lines = [
        f"Balance: ${balance:.2f} (${available:.2f} available)",
        f"Portfolio value: ${portfolio_value:.2f}",
        f"Open positions: {len(positions)}",
        "",
    ]

    for pos in positions:
        label = pos.get("label", pos.get("ticker", "?"))
        side = pos.get("side", "?").upper()
        contracts = pos.get("contracts", 0)
        avg_price = pos.get("avg_price", 0)
        bid = pos.get("bid", 0)
        ask = pos.get("ask", 0)
        upnl = pos.get("upnl", pos.get("unrealised_pnl_cents", 0))
        if isinstance(upnl, (int, float)) and abs(upnl) > 10:
            upnl = upnl / 100  # cents to dollars

        # Current mid price
        mid = (bid + ask) / 2 if bid and ask else 0

        lines.append(
            f"  {label}: {side} x{contracts} | "
            f"Entry: {avg_price:.0f}c | Now: {mid:.0f}c | P&L: ${upnl:+.2f}"
        )

    lines.append("")
    lines.append(f"Total unrealized P&L: ${total_pnl:+.2f}")
    return "\n".join(lines)


def get_picks(force: bool = False) -> str:
    params = {"force": "1"} if force else {}
    data = _get("/api/picks", params)
    if isinstance(data, str):
        return data

    picks = data if isinstance(data, list) else data.get("picks", [])
    if not picks:
        return "No picks available right now."

    lines = [f"Top {len(picks)} picks:"]
    for i, pick in enumerate(picks[:5], 1):
        ticker = pick.get("ticker", "?")
        title = pick.get("title", ticker)
        side = pick.get("recommended_side", "?")
        score = pick.get("score", 0)
        edge = pick.get("edge", pick.get("fair_value_edge", 0))

        # Truncate title for speech
        if len(title) > 60:
            title = title[:57] + "..."

        lines.append(f"  {i}. {title} — {side} (score: {score:.0%}, edge: {edge:.0%})")

    return "\n".join(lines)


def get_bot_status() -> str:
    data = _get("/api/bot/status")
    if isinstance(data, str):
        return data

    running = "running" if data.get("running") else "stopped"
    scans = data.get("scan_count", 0)
    trades_today = data.get("trades_today", 0)
    daily_loss = data.get("daily_loss_cents", 0) / 100

    return (
        f"Bot is {running}. "
        f"Scans today: {scans}. "
        f"Trades today: {trades_today}. "
        f"Daily P&L: ${daily_loss:+.2f}."
    )


def get_recent_trades(limit: int = 5) -> str:
    data = _get("/api/bot/trades", {"limit": limit})
    if isinstance(data, str):
        return data

    trades = data if isinstance(data, list) else data.get("trades", [])
    if not trades:
        return "No recent trades."

    lines = [f"Last {len(trades)} trades:"]
    for t in trades:
        ticker = t.get("ticker", "?")
        side = t.get("side", "?")
        pnl = t.get("realized_pnl", t.get("realized_pnl_cents", 0))
        if isinstance(pnl, (int, float)) and abs(pnl) > 1:
            pnl = pnl / 100  # Convert cents to dollars
        status = t.get("status", "open")
        lines.append(f"  {ticker} {side.upper()} — {status} (P&L: ${pnl:+.2f})")

    return "\n".join(lines)


def get_daily_performance() -> str:
    data = _get("/api/bot/performance/daily")
    if isinstance(data, str):
        return data

    days = data if isinstance(data, list) else data.get("daily", [])
    if not days:
        return "No performance data available."

    # Summarize last few days
    lines = ["Daily performance:"]
    for d in days[-5:]:
        date = d.get("date", "?")
        pnl = d.get("pnl_cents", d.get("daily_pnl_cents", 0)) / 100
        lines.append(f"  {date}: ${pnl:+.2f}")

    return "\n".join(lines)


def get_warnings() -> str:
    data = _get("/api/bot/warnings")
    if isinstance(data, str):
        return data

    warnings = data if isinstance(data, list) else data.get("warnings", [])
    if not warnings:
        return "No active warnings. All clear."

    lines = [f"{len(warnings)} active warnings:"]
    for w in warnings:
        if isinstance(w, str):
            lines.append(f"  - {w}")
        else:
            lines.append(f"  - {w.get('message', str(w))}")

    return "\n".join(lines)


# Register all Kalshi tools
registry.register(Tool(
    name="get_kalshi_portfolio",
    description="Get current Kalshi trading portfolio — balance, positions, and unrealized P&L.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_portfolio,
))

registry.register(Tool(
    name="get_kalshi_picks",
    description="Get today's top Kalshi market picks and recommendations.",
    parameters={
        "type": "object",
        "properties": {
            "force": {"type": "boolean", "description": "Force refresh (bypass cache)"},
        },
        "required": [],
    },
    handler=get_picks,
))

registry.register(Tool(
    name="get_kalshi_bot_status",
    description="Check if the Kalshi trading bot is running, plus scan count and daily stats.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_bot_status,
))

registry.register(Tool(
    name="get_kalshi_trades",
    description="Get recent Kalshi bot trades with P&L.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Number of trades to return (default 5)"},
        },
        "required": [],
    },
    handler=get_recent_trades,
))

registry.register(Tool(
    name="get_kalshi_daily_performance",
    description="Get daily P&L performance for the Kalshi trading bot.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_daily_performance,
))

registry.register(Tool(
    name="get_kalshi_warnings",
    description="Check for active portfolio health warnings from the Kalshi trading bot.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_warnings,
))
