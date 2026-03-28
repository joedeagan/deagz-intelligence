"""Kalshi trading bot integration — talks to the Flask API."""

import httpx
import re

from jarvis.config import KALSHI_BOT_URL
from jarvis.tools.base import Tool, registry


# Maps Kalshi ticker codes to readable info
TEAM_CODES = {
    "NYY": "New York Yankees", "NYM": "New York Mets", "BOS": "Boston Red Sox",
    "LAD": "Los Angeles Dodgers", "LAA": "Los Angeles Angels", "SF": "San Francisco Giants",
    "CHC": "Chicago Cubs", "CHW": "Chicago White Sox", "HOU": "Houston Astros",
    "ATL": "Atlanta Braves", "PHI": "Philadelphia Phillies", "SD": "San Diego Padres",
    "SEA": "Seattle Mariners", "MIN": "Minnesota Twins", "CLE": "Cleveland Guardians",
    "DET": "Detroit Tigers", "TB": "Tampa Bay Rays", "TOR": "Toronto Blue Jays",
    "BAL": "Baltimore Orioles", "KC": "Kansas City Royals", "TEX": "Texas Rangers",
    "ARI": "Arizona Diamondbacks", "COL": "Colorado Rockies", "MIL": "Milwaukee Brewers",
    "CIN": "Cincinnati Reds", "PIT": "Pittsburgh Pirates", "STL": "St. Louis Cardinals",
    "MIA": "Miami Marlins", "OAK": "Oakland Athletics", "WAS": "Washington Nationals",
    # NBA
    "LAL": "Los Angeles Lakers", "GSW": "Golden State Warriors", "BKN": "Brooklyn Nets",
    "MEM": "Memphis Grizzlies", "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "BOS": "Boston Celtics", "MIL": "Milwaukee Bucks", "PHX": "Phoenix Suns",
    # NHL
    "NYR": "New York Rangers",
    # Soccer / UCL
    "RMA": "Real Madrid", "BMU": "Borussia Munich", "PSG": "Paris Saint-Germain",
    "LFC": "Liverpool", "ARS": "Arsenal", "BAR": "Barcelona", "MCI": "Man City",
    "JUV": "Juventus", "INT": "Inter Milan", "ACM": "AC Milan", "BVB": "Dortmund",
    "ATM": "Atletico Madrid", "CHE": "Chelsea",
}


def parse_ticker(ticker: str) -> dict:
    """Parse a Kalshi ticker to extract event info."""
    info = {"ticker": ticker, "sport": "unknown", "event": ticker}

    if "MLB" in ticker:
        info["sport"] = "MLB Baseball"
    elif "NBA" in ticker:
        info["sport"] = "NBA Basketball"
    elif "NHL" in ticker:
        info["sport"] = "NHL Hockey"
    elif "NFL" in ticker:
        info["sport"] = "NFL Football"
    elif "UCL" in ticker:
        info["sport"] = "UEFA Champions League"
    elif "SOCCER" in ticker or "MLS" in ticker:
        info["sport"] = "Soccer"
    elif "FED" in ticker:
        info["sport"] = "Federal Reserve"
        info["event"] = "Fed Interest Rate Decision"

    # Extract team codes from ticker
    teams_found = []
    for code, name in TEAM_CODES.items():
        if code in ticker:
            teams_found.append(name)
    if teams_found:
        info["teams"] = teams_found
        info["event"] = " vs ".join(teams_found[:2]) if len(teams_found) >= 2 else teams_found[0]

    # Extract date from ticker (e.g., 26MAR...)
    # Note: ticker format is like 26MAR291920 where 26MAR is the date,
    # the rest is game time — year is NOT in the ticker, use current year
    import datetime as _dt
    date_match = re.search(r'(\d{2})([A-Z]{3})', ticker)
    if date_match:
        day = date_match.group(1)
        month = date_match.group(2)
        year = _dt.datetime.now().year
        info["date"] = f"{day} {month} {year}"

    return info


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
        ticker = pos.get("ticker", "")
        side = pos.get("side", "?").upper()
        contracts = pos.get("contracts", 0)
        avg_price = pos.get("avg_price", 0)
        bid = pos.get("bid", 0)
        ask = pos.get("ask", 0)
        upnl = pos.get("upnl", pos.get("unrealised_pnl_cents", 0))
        if isinstance(upnl, (int, float)) and abs(upnl) > 10:
            upnl = upnl / 100  # cents to dollars

        # Parse ticker for readable info
        info = parse_ticker(ticker)
        event_desc = info.get("event", label)
        sport = info.get("sport", "")
        date = info.get("date", "")

        # Current mid price
        mid = (bid + ask) / 2 if bid and ask else 0

        lines.append(f"  [{sport}] {event_desc}")
        lines.append(f"    Bet: {label} ({side} x{contracts})")
        lines.append(f"    Entry: {avg_price:.0f} cents | Now: {mid:.0f} cents | P&L: ${upnl:+.2f}")
        if date:
            lines.append(f"    Game date: {date}")
        lines.append("")

    lines.append(f"Total unrealized P&L: ${total_pnl:+.2f}")
    return "\n".join(lines)


def get_live_scores(sport: str = "mlb") -> str:
    """Get live scores from ESPN API."""
    sport_map = {
        "mlb": "baseball/mlb",
        "nba": "basketball/nba",
        "nhl": "hockey/nhl",
        "nfl": "football/nfl",
    }
    sport_path = sport_map.get(sport.lower(), "baseball/mlb")

    try:
        resp = httpx.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard",
            timeout=10,
        )
        data = resp.json()
        events = data.get("events", [])

        if not events:
            return f"No {sport.upper()} games right now."

        lines = [f"Live {sport.upper()} Scores:"]
        for event in events[:8]:
            name = event.get("shortName", "?")
            status = event.get("status", {}).get("type", {}).get("shortDetail", "")
            competitors = event.get("competitions", [{}])[0].get("competitors", [])

            scores = []
            for team in competitors:
                team_name = team.get("team", {}).get("abbreviation", "?")
                score = team.get("score", "0")
                scores.append(f"{team_name} {score}")

            score_str = " - ".join(scores) if scores else "TBD"
            lines.append(f"  {score_str} ({status})")

        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch live scores: {e}"


def research_bet(ticker: str = "", label: str = "") -> str:
    """Research what a Kalshi bet is about — parses the ticker and gets live game info."""
    # If no ticker given, pull from current portfolio
    if not ticker and not label:
        data = _get("/api/portfolio")
        if isinstance(data, str):
            return data
        positions = data.get("positions", [])
        if not positions:
            return "No active positions to research."

        lines = ["Current bets breakdown:"]
        for pos in positions:
            t = pos.get("ticker", "")
            l = pos.get("label", "")
            info = parse_ticker(t)
            side = pos.get("side", "?").upper()
            mid = (pos.get("bid", 0) + pos.get("ask", 0)) / 2

            lines.append(f"\n  Ticker: {t}")
            lines.append(f"  Sport: {info.get('sport', 'Unknown')}")
            lines.append(f"  Event: {info.get('event', l)}")
            lines.append(f"  Your bet: {l} ({side})")
            lines.append(f"  Current price: {mid:.0f}c")
            if info.get("date"):
                lines.append(f"  Game date: {info['date']}")

        return "\n".join(lines)

    info = parse_ticker(ticker) if ticker else {"event": label}
    return f"Bet info: {info}"


def ai_research_bet(ticker: str = "", query: str = "") -> str:
    """Deep research a Kalshi bet — searches news, stats, and odds to give a confidence score."""
    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY

    # Get all positions if no specific ticker
    positions = []
    if not ticker and not query:
        data = _get("/api/portfolio")
        if isinstance(data, dict):
            positions = data.get("positions", [])
        if not positions:
            return "No active positions to research."
    elif ticker:
        positions = [{"ticker": ticker, "label": query or ticker}]
    else:
        positions = [{"ticker": "", "label": query}]

    results = []
    for pos in positions[:3]:  # Limit to 3 to save time
        t = pos.get("ticker", "")
        label = pos.get("label", "")
        info = parse_ticker(t) if t else {"event": label}
        event = info.get("event", label)
        sport = info.get("sport", "")
        date = info.get("date", "")
        side = pos.get("side", "")
        avg_price = pos.get("avg_price", 0)

        # Build search context
        search_query = f"{event} {sport} {date}".strip()
        if not search_query:
            search_query = label

        # Search for real data
        search_results = []
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                news = list(ddgs.news(search_query, max_results=3))
                for n in news:
                    search_results.append(f"- {n.get('title', '')}: {n.get('body', '')[:200]}")
        except Exception:
            pass

        # Get live scores if it's a sports bet
        live_info = ""
        if sport and sport != "unknown":
            sport_key = "mlb" if "MLB" in sport.upper() else \
                        "nba" if "NBA" in sport.upper() else \
                        "nhl" if "NHL" in sport.upper() else \
                        "nfl" if "NFL" in sport.upper() else ""
            if sport_key:
                live_info = get_live_scores(sport_key)

        # Ask Claude to analyze
        context = f"""Analyze this Kalshi bet and give a confidence assessment:

Bet: {label}
Ticker: {t}
Sport: {sport}
Event: {event}
Date: {date}
User's position: {side} at {avg_price}c

Recent news:
{chr(10).join(search_results) if search_results else 'No recent news found.'}

Live scores:
{live_info if live_info else 'No live data.'}

Give a brief analysis (3-4 sentences max):
1. What this bet is about
2. Key factors that could affect the outcome
3. Confidence score (Low/Medium/High) with brief reasoning
Keep it concise for spoken delivery."""

        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=250,
                messages=[{"role": "user", "content": context}],
            )
            analysis = resp.content[0].text
            results.append(f"[{event}]\n{analysis}")
        except Exception as e:
            results.append(f"[{event}] Could not analyze: {e}")

    return "\n\n".join(results)


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

registry.register(Tool(
    name="get_live_scores",
    description="Get live sports scores from ESPN. Supports MLB, NBA, NHL, NFL. Use this to check how games are going that relate to Kalshi bets.",
    parameters={
        "type": "object",
        "properties": {
            "sport": {"type": "string", "description": "Sport league: mlb, nba, nhl, or nfl (default: mlb)"},
        },
        "required": [],
    },
    handler=get_live_scores,
))

registry.register(Tool(
    name="research_kalshi_bet",
    description="Research and explain what Kalshi bets are about. Parses tickers to identify the sport, teams, game date, and bet type. Call with no arguments to analyze all current positions.",
    parameters={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Kalshi ticker to research (optional — omit to analyze all positions)"},
            "label": {"type": "string", "description": "Bet label to research"},
        },
        "required": [],
    },
    handler=research_bet,
))

registry.register(Tool(
    name="ai_research_bet",
    description="Deep AI research on a Kalshi bet — searches news, polls, stats, live scores and gives a confidence score (Low/Medium/High). Use when user asks 'research my bets', 'how confident are you in this bet?', 'analyze my positions', or 'should I hold this bet?'. Call with no arguments to analyze all current positions.",
    parameters={
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Specific Kalshi ticker to research (optional)"},
            "query": {"type": "string", "description": "Event or topic to research (e.g. 'Lakers vs Celtics', 'Fed rate decision')"},
        },
        "required": [],
    },
    handler=ai_research_bet,
))
