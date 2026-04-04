"""Daily Digest Email - runs at 8am, sends weather + Kalshi + bot status to Gmail."""

import os
import smtplib
import datetime
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent / ".env"), override=True)

import httpx

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
KALSHI_BOT_URL = os.getenv("KALSHI_BOT_URL", "https://web-production-c8a5b.up.railway.app")
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Akron, Ohio")


def get_weather():
    try:
        city = DEFAULT_CITY.split(",")[0].strip()
        geo = httpx.get("https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1}, timeout=10).json()
        loc = geo["results"][0]
        w = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "current": "temperature_2m,weathercode,windspeed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit", "windspeed_unit": "mph", "forecast_days": 1,
        }, timeout=10).json()
        cur = w.get("current", {})
        daily = w.get("daily", {})
        temp = cur.get("temperature_2m", "?")
        hi = daily.get("temperature_2m_max", ["?"])[0]
        lo = daily.get("temperature_2m_min", ["?"])[0]
        rain = daily.get("precipitation_probability_max", [0])[0]
        return f"Currently {temp}F. Today: High {hi}F, Low {lo}F, {rain}% chance of rain."
    except Exception as e:
        return f"Weather unavailable: {e}"


def get_portfolio():
    try:
        data = httpx.get(f"{KALSHI_BOT_URL}/api/portfolio", timeout=10).json()
        balance = data.get("balance", 0)
        pv = data.get("portfolio_value", 0)
        pnl = data.get("unrealised_pnl", 0)
        positions = data.get("position_count", 0)
        return f"Balance: ${balance:.2f} | Portfolio: ${pv:.2f} | P&L: ${pnl:+.2f} | {positions} positions"
    except Exception:
        return "Portfolio unavailable"


def get_bot_status():
    try:
        data = httpx.get(f"{KALSHI_BOT_URL}/api/bot/status", timeout=10).json()
        running = "ACTIVE" if data.get("running") else "STOPPED"
        scans = data.get("scan_count", 0)
        trades = data.get("trades_today", 0)
        losses = data.get("consecutive_losses", 0)
        warnings = data.get("active_warnings", [])
        status = f"Bot: {running} | {scans} scans | {trades} trades today | {losses} consecutive losses"
        if warnings:
            status += f"\nWarnings: {', '.join(str(w) for w in warnings)}"
        return status
    except Exception:
        return "Bot status unavailable"


TEAM_CODES = {
    "NYY": "Yankees", "NYM": "Mets", "BOS": "Red Sox", "LAD": "Dodgers",
    "LAA": "Angels", "SF": "Giants", "CHC": "Cubs", "CHW": "White Sox",
    "HOU": "Astros", "ATL": "Braves", "PHI": "Phillies", "SD": "Padres",
    "SEA": "Mariners", "MIN": "Twins", "CLE": "Guardians", "DET": "Tigers",
    "TB": "Rays", "TOR": "Blue Jays", "BAL": "Orioles", "KC": "Royals",
    "TEX": "Rangers", "ARI": "Diamondbacks", "MIL": "Brewers", "CIN": "Reds",
    "PIT": "Pirates", "STL": "Cardinals", "MIA": "Marlins", "WAS": "Nationals",
    "LAL": "Lakers", "GSW": "Warriors", "BKN": "Nets", "MEM": "Grizzlies",
    "DAL": "Mavericks", "DEN": "Nuggets", "PHX": "Suns", "MIL": "Bucks",
    "NYR": "Rangers", "ATH": "Athletics", "COL": "Rockies", "OAK": "Athletics",
}


def ticker_to_name(ticker):
    """Convert ugly ticker to readable name."""
    if "FED" in ticker:
        return "Fed Rate Decision"
    if "MLB" in ticker or "GAME" in ticker:
        # Find team codes
        teams = []
        for code, name in TEAM_CODES.items():
            if code in ticker:
                teams.append(name)
        if teams:
            return " vs ".join(teams[:2]) + " (MLB)"
    if "NBA" in ticker:
        teams = [TEAM_CODES.get(c, c) for c in TEAM_CODES if c in ticker]
        if teams:
            return " vs ".join(teams[:2]) + " (NBA)"
    if "BTC" in ticker or "CRYPTO" in ticker:
        return "Bitcoin Price"
    if "GOLD" in ticker:
        return "Gold Price"
    # Fallback — use the label from the API
    return ticker[:25]


def get_positions():
    try:
        data = httpx.get(f"{KALSHI_BOT_URL}/api/portfolio", timeout=10).json()
        positions = data.get("positions", [])
        if not positions:
            return "No open positions."
        lines = []
        for p in positions:
            label = p.get("label", "")
            ticker = p.get("ticker", "?")
            name = label if label else ticker_to_name(ticker)
            side = p.get("side", "?").upper()
            upnl = p.get("upnl", 0)
            bid = p.get("bid", 0)
            ask = p.get("ask", 0)
            mid = (bid + ask) / 2
            warning = ""
            if side == "NO" and mid > 80:
                warning = " [RISKY]"
            if upnl >= 0:
                lines.append(f"  +${upnl:.2f} | {name} ({side}){warning}")
            else:
                lines.append(f"  -${abs(upnl):.2f} | {name} ({side}){warning}")
        return "\n".join(lines)
    except Exception:
        return "Positions unavailable"


NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kalshi-trader-alerts")


def send_digest():
    now = datetime.datetime.now()
    day = now.strftime("%A, %B %d")

    weather = get_weather()
    portfolio = get_portfolio()
    bot = get_bot_status()
    positions = get_positions()

    body = f"""WEATHER: {weather}

PORTFOLIO: {portfolio}

POSITIONS:
{positions}

BOT: {bot}"""

    title = f"JARVIS Daily Digest - {day}"

    # Send via ntfy.sh (same app as Kalshi bot alerts)
    try:
        resp = httpx.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            content=body.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "default",
                "Tags": "robot,chart_with_upwards_trend",
            },
            timeout=10,
        )
        print(f"[{now.strftime('%I:%M %p')}] Daily digest sent via ntfy ({resp.status_code})")
    except Exception as e:
        print(f"ntfy failed: {e}")

    # Also send email as backup
    try:
        if GMAIL_ADDRESS and GMAIL_APP_PASSWORD:
            msg = MIMEText(f"JARVIS DAILY DIGEST - {day}\n{'='*40}\n\n{body}\n\n- JARVIS")
            msg["Subject"] = title
            msg["From"] = GMAIL_ADDRESS
            msg["To"] = GMAIL_ADDRESS
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
            print(f"  Email backup also sent to {GMAIL_ADDRESS}")
    except Exception:
        pass


if __name__ == "__main__":
    send_digest()
