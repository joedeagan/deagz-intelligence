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

# ─── Complete bot knowledge + trading strategy intelligence for Jarvis ───
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
6. **correlated_arb** — finds pricing inconsistencies between related markets

### SIGNAL SCORING (EV Score)
- Base EV = edge * payout_ratio
- Sweet spot bonus: +30% for 25-60% win probability
- Liquidity multiplier: 0.8-1.3x based on volume
- Spread penalty: 1% per cent of bid/ask spread
- Time multiplier: +50% for <4h to close, -60% for 30+ days out
- Multi-source bonus: +25% when 2+ strategies agree
- Source reliability weights: sports_odds=1.4x, fred=1.3x, weather=1.2x, polymarket=1.0x, news=0.9x

### POSITION SIZING (Kelly Criterion)
- Dynamic fraction = 0.15 * (edge/0.08)^mult * source_mult * time_mult * drawdown_mult
- Drawdown protection: scales down 15% per consecutive loss (min 0.25x)
- Hard cap: min(kelly * balance, max_bet_pct * balance, max_bet_dollars)

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
- min_edge (default 6%, range 1-20%) — minimum edge to trigger a bet
- max_edge (default 15%, range 5-30%) — reject signals above this as model error
- min_bet_cents (default 5) — minimum bet size
- max_bet_dollars (default $1.50, range $0.05-$5.00) — max per trade
- max_bet_pct (default 8%) — max bet as % of balance
- max_positions (default 12, range 1-30) — max open positions
- daily_loss_limit_cents (default 200 = $2) — pause trading if exceeded
- interval_seconds (default 300, range 60-3600) — scan frequency
- min_volume_24h (default 200) — skip thin markets
- max_spread_cents (default 15) — skip wide spreads
- min_win_prob / max_win_prob (default 40-75%) — probability bounds
- multi_source_boost (default 0.25) — EV bonus for multi-source agreement
- max_series_positions / max_region_positions (default 2 each) — correlation limits
- min_poly_return (default 3%) — minimum Polymarket ROI

## JARVIS TRADING STRATEGY INTELLIGENCE

You are not just reading data — you are an AI trading strategist. Use these principles to evaluate
every position, signal, and config decision:

### CORE PRINCIPLE: EXPECTED VALUE (EV)
A bet is only worth making if: (probability_of_winning * profit) - (probability_of_losing * loss) > 0
- A 60% chance to win $0.40 vs 40% chance to lose $0.60: EV = 0.60*0.40 - 0.40*0.60 = $0.00 (break even)
- You need POSITIVE EV. If the market prices something at 60% and you think it's 70%, that's a +EV bet.
- The EDGE is: your_estimated_probability - market_implied_probability
- Only bet when edge > costs (spread + fees). Kalshi fee is 0.7% per contract.

### WHEN TO BET YES vs NO
- Bet YES when you think the event is MORE likely than the market price implies
- Bet NO when you think the event is LESS likely than the market price implies
- CRITICAL: For NO bets, check the NO price, not the YES price. If YES is 99 cents, NO is 1 cent.
  Buying 100 NO contracts at 1 cent costs $1 and pays $100 only if event DOESN'T happen (1% chance = terrible bet)
- NEVER buy NO contracts when YES price is above 90 cents unless you have very strong evidence the market is wrong
- NEVER buy YES contracts when YES price is above 85 cents — the upside is tiny relative to the risk

### POSITION MANAGEMENT RULES
1. CUT LOSERS FAST — if a position drops 30%+ and the reason you entered no longer holds, exit
2. LET WINNERS RUN — don't exit a winning position just because it's up. Exit when the edge disappears
3. NEVER AVERAGE DOWN — adding to a losing position is how you blow up
4. DIVERSIFY — max 2-3 bets on the same event type. Don't put 5 bets on MLB games on the same day
5. SIZE BY CONVICTION — high confidence = bigger bet (within limits), low confidence = minimum bet or skip

### MARKET CATEGORIES — WHAT ACTUALLY WORKS
- **Sports (MLB/NBA/NHL/NFL):** Most liquid, fastest resolution. Best for the bot because:
  - Games resolve within hours, not days/weeks
  - Odds are well-established from Vegas/sportsbooks — can cross-reference
  - High volume means tight spreads
  - WARNING: The bot's sports_odds strategy uses historical stats, but injuries/rest/weather matter more for single games

- **Weather:** Good edge source because:
  - Weather forecasts (Open-Meteo, NWS) are highly accurate 24-48h out
  - Kalshi weather markets are often stale (not updated as fast as forecasts)
  - WARNING: Edge disappears >48h out. Only bet weather markets resolving within 2 days

- **Fed/Economics:** Dangerous because:
  - These markets are heavily traded by institutional money — hard to beat
  - Long time to resolution = capital tied up for weeks/months
  - WARNING: The Fed bet disaster (111 NO contracts at 1 cent on 99% YES market) shows the bot doesn't properly evaluate these
  - RECOMMENDATION: Reduce exposure to Fed/economic markets or require much higher edge (15%+)

- **Polymarket Cross-Reference:** Good for arbitrage but:
  - Price differences are often due to liquidity, not mispricing
  - WARNING: If Kalshi and Polymarket disagree by >10%, check WHY before betting. Markets disagree for a reason.

### KNOWN BOT BUGS / WEAKNESSES TO WATCH FOR
1. **NO-side price check bug:** The bot bought 111 NO contracts at 2 cents on a 99% YES market. The circuit breaker checks YES price (99 cents, passes) instead of NO price (1 cent, should fail). Flag any NO position where the implied YES probability is >85%.
2. **News sentiment overreaction:** The news strategy shifts fair value by up to 10% based on headlines. Headlines are noisy — 3 bullish headlines don't mean a team will win. Recommend reducing news weight or requiring 5+ headlines.
3. **Loss streak behavior:** After 5 consecutive losses, the bot reduces bet sizes. This is correct BUT it doesn't re-evaluate whether the losing strategy should be disabled entirely. If news_sentiment has lost 5 in a row, DISABLE IT, don't just reduce sizing.
4. **No exit on stale positions:** The bot holds positions that haven't moved in days. If a position is +/-0% after 48 hours, the capital is better deployed elsewhere.

### WHAT TO LOOK FOR IN SIGNALS
When evaluating signals, rank them by:
1. **Edge after costs** (edge - spread/2 - 0.7% fee). If this is <3%, skip.
2. **Volume** — >$500/day means the market is liquid enough to exit
3. **Time to resolution** — 2-48 hours is ideal. >7 days ties up capital
4. **Source agreement** — 2+ strategies agreeing = much higher confidence
5. **Market category** — sports > weather > economics for this bot's skill set

### HOW TO OPTIMIZE THE BOT CONFIG
When running optimize_bot, think about:
- If win rate is <50%: raise min_edge (be pickier)
- If win rate is >60% but low volume: lower min_edge (take more bets)
- If consecutive losses on one strategy: consider disabling that strategy via higher confidence thresholds
- If spreads are eating profits: lower max_spread_cents
- If capital is sitting idle: increase max_positions or lower min_volume_24h
- If taking too many correlated bets: lower max_series_positions to 1
- After a loss streak: DON'T immediately loosen filters — analyze WHY the losses happened first
- The ideal setup: 55-65% win rate, 10-20 bets per day, average profit 2-5x the average loss

## ADVANCED QUANTITATIVE TRADING INTELLIGENCE

### MARKET MICROSTRUCTURE — HOW KALSHI ACTUALLY WORKS
- Kalshi is a binary options exchange: contracts settle at $1.00 (YES) or $0.00 (NO)
- The bid-ask SPREAD is your biggest hidden cost. A 5-cent spread on a 50-cent contract = 10% round-trip cost
- NEVER market buy. Always use limit orders 1-2 cents inside the spread to get better fills
- Liquidity concentrates near market open and 1-2 hours before resolution. These are the best times to trade
- After-hours markets (overnight) have wide spreads — avoid unless the edge is massive
- Volume spikes = new information. If volume suddenly doubles, someone knows something. Don't fight the flow

### EDGE DECAY — WHY SIGNALS EXPIRE
- An edge of 8% right now might be 3% in 30 minutes as other traders discover the same mispricing
- Sports edges decay fastest — odds update within seconds of news (injuries, lineup changes)
- Weather edges are more durable — forecasts update every 6 hours, but Kalshi markets update slower
- Economic edges (Fed, CPI) barely exist — institutional traders price these within seconds of data release
- RULE: If a signal is >2 hours old and hasn't been acted on, re-evaluate before betting. The edge may be gone

### BAYESIAN UPDATING — HOW TO THINK ABOUT PROBABILITY
- Start with the market price as your base rate (the market is usually right)
- Only deviate when you have SPECIFIC, CONCRETE evidence the market hasn't priced in
- Example: MLB game, market says Team A has 55% chance. You see their star pitcher was scratched 10 min ago and the line hasn't moved yet. That's a real edge.
- Example of FAKE edge: "I feel like the Cavs will win tonight." That's not evidence. The market already incorporates public sentiment.
- Every piece of evidence shifts probability by a SMALL amount. One news headline ≠ 10% shift. More like 1-3%.
- Multiple independent sources agreeing = much stronger signal than one source saying something loudly

### KELLY CRITERION — ADVANCED SIZING
- Full Kelly: bet_fraction = (edge / odds). If you have 8% edge on an even-money bet, bet 8% of bankroll.
- NEVER use full Kelly — variance will destroy you. Use FRACTIONAL Kelly:
  - Conservative: 0.10x Kelly (slow growth, very safe)
  - Moderate: 0.15-0.20x Kelly (current bot setting, good for small bankrolls)
  - Aggressive: 0.25x Kelly (faster growth, higher drawdown risk)
- With a $10-15 bankroll, even 0.15x Kelly means bets of $0.05-$0.20. This is correct — small bets compound
- CRITICAL: Kelly assumes you know your true edge. If edge estimate is wrong (common), you'll overbet. Always err conservative.

### CORRELATION RISK — THE HIDDEN KILLER
- 5 MLB YES bets on the same day are NOT 5 independent bets. If it rains, ALL outdoor games might be affected.
- Fed rate + economic markets are heavily correlated. Betting on multiple Fed outcomes = concentrated risk.
- Weather markets in the same region are correlated (one storm affects all nearby cities).
- RULE: Total exposure to correlated events should be <25% of bankroll. Currently max_series_positions=2 is good.
- Think about hidden correlations: a market crash affects crypto, stocks, AND economic prediction markets simultaneously.

### MEAN REVERSION VS MOMENTUM — WHEN TO BET AGAINST THE CROWD
- Markets that moved FAST (>10% in 1 hour) often overreact. This is mean reversion opportunity.
  - Example: A team's odds drop from 55% to 40% because a backup player got injured. The market overreacted — bet YES at 40%.
- Markets that moved SLOWLY over days are usually RIGHT. Don't bet against a slow, steady trend.
  - Example: A team's odds drifted from 55% to 48% over a week. This reflects accumulating evidence. Don't fight it.
- EXCEPTION: Markets near resolution (last 1-2 hours) don't mean revert. Price = reality at that point.

### TIMING AND EXECUTION
- BEST time to enter sports bets: 30-60 minutes before game time. Lines are sharpest but late scratches create edges.
- WORST time: Immediately after a game starts. Markets are efficient and volatile — you're just gambling.
- Weather bets: Enter 12-24 hours before resolution when forecast is most accurate but market hasn't fully adjusted.
- Fed/economic: Either bet weeks early (if you have a thesis) or don't bet at all. Day-of is pure noise.
- ALWAYS check if you can exit a position profitably before entering. If the market has 0 bid, you're trapped.

### RISK MANAGEMENT — SURVIVAL FIRST
- RULE 1: Never risk more than 2% of bankroll on a single bet. With $10 bankroll = max $0.20 per bet.
- RULE 2: Daily loss limit should be 5-10% of bankroll. Stop trading after hitting it. NO EXCEPTIONS.
- RULE 3: If you lose 20% of bankroll in a week, stop for 48 hours. Re-evaluate everything.
- RULE 4: Track your actual win rate per strategy. If any strategy is below 45% over 20+ bets, disable it.
- RULE 5: The goal is CONSISTENT small profits, not occasional big wins. A bot that makes $0.50/day reliably is worth more than one that makes $5 once a week and loses $3 the other days.

### SHARPE RATIO — THE REAL MEASURE OF SUCCESS
- Don't just look at total profit. Look at profit RELATIVE to volatility.
- Sharpe ratio = (average daily return) / (standard deviation of daily returns)
- Sharpe > 1.0 = good. Sharpe > 2.0 = excellent. Sharpe < 0.5 = the returns aren't worth the risk.
- A bot making $0.30/day with $0.10 variance (Sharpe ~3.0) is BETTER than one making $1.00/day with $2.00 variance (Sharpe ~0.5)
- Track this. If Sharpe drops below 0.5, the bot's strategies aren't working and need overhaul.

### MARKET MAKER BEHAVIOR — READING THE ORDER BOOK
- If the bid is much thicker than the ask (lots of buy orders), the market is likely to move UP
- If the ask is thick and bid is thin, market likely moves DOWN
- A sudden widening of the spread = uncertainty. Wait for it to tighten before entering.
- If someone places a large order that moves the price, wait 2-3 minutes. Often it reverts as other participants respond.

### SPORTS-SPECIFIC INTELLIGENCE
- MLB: Starting pitcher is 60-70% of the edge. Always check if the listed starter is actually pitching.
- NBA: Back-to-back games = 3-5% win probability reduction for the traveling team. Load management announcements create edges.
- NFL: Home field = ~3% advantage. Weather (wind >15mph, rain) reduces passing game and total points.
- NHL: Goalie matchup is the single biggest factor. Backup goalies = 5-10% probability shift.
- LIVE betting: The most profitable edges appear in live sports when the score changes. A team down 10 points early is often overpriced for NO (because comeback probability is higher than people think in NBA).

### PORTFOLIO THEORY FOR PREDICTION MARKETS
- Treat your total Kalshi portfolio like an investment portfolio, not individual bets
- Ideal: 60% sports (high turnover, quick resolution), 30% weather (stable edges), 10% other
- Expected return per bet should be 3-8% after costs. Below 3% isn't worth the execution risk.
- Track hit rate by: strategy, market type, time of day, bet size. Double down on what works.
- Monthly review: calculate total invested, total returned, net profit, win rate, avg bet size, best/worst strategies
- Compound growth: $10 at 2% daily = $72 in 100 days. $10 at 5% daily = $1,315 in 100 days. Small daily edge = massive compounding.
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


def send_daily_report(**kwargs) -> str:
    """Generate and email a daily performance report."""
    import smtplib
    from email.mime.text import MIMEText
    from jarvis.config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Gmail not configured. Need GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env."

    # Generate the report
    analysis = analyze_kalshi_strategy()
    scan = scan_kalshi_markets()

    # Get portfolio summary
    portfolio = _bot_get("/api/portfolio")
    balance = portfolio.get("balance", 0) if isinstance(portfolio, dict) else 0
    pv = portfolio.get("portfolio_value", 0) if isinstance(portfolio, dict) else 0
    positions = portfolio.get("position_count", 0) if isinstance(portfolio, dict) else 0

    now = datetime.datetime.now()
    subject = f"JARVIS Daily Report — {now.strftime('%B %d, %Y')}"

    body = f"""JARVIS DAILY REPORT — {now.strftime('%A, %B %d, %Y at %I:%M %p')}
{'='*60}

PORTFOLIO SNAPSHOT
  Balance: ${balance:.2f}
  Portfolio Value: ${pv:.2f}
  Open Positions: {positions}

{'='*60}
STRATEGY ANALYSIS
{'='*60}

{analysis}

{'='*60}
MARKET OPPORTUNITIES
{'='*60}

{scan}

{'='*60}
Report generated by JARVIS — Deagz Intelligence
"""

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = GMAIL_ADDRESS

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

        # Save locally too
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        (REPORTS_DIR / f"daily_email_{timestamp}.txt").write_text(body, encoding="utf-8")

        return f"Daily report emailed to {GMAIL_ADDRESS}."
    except Exception as e:
        return f"Failed to send email: {e}"


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

registry.register(Tool(
    name="send_daily_report",
    description="Generate and email a daily Kalshi performance report with strategy analysis and market opportunities. Use for 'email me a report', 'send daily summary', 'send me an update'.",
    parameters={"type": "object", "properties": {}},
    handler=send_daily_report,
))
