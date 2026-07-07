"""Gameday - live game mode for the wall.

While a Cleveland team is playing, a watcher polls ESPN every ~60s:
  - the wall shows a live score line under the clock (GET /api/gameday)
  - Jarvis SPEAKS the moments that matter: our runs/baskets (rate-limited),
    lead changes (always), and the final (always)

Quiet hours: spoken calls stop at 10pm (the wall sleeps) but the score line
keeps updating silently - night games don't wake the room.
"""

import datetime
import threading
import time

import httpx

TRACKED = (  # (sport, league, ESPN abbreviation, spoken name)
    ("baseball", "mlb", "CLE", "Guardians"),
    ("basketball", "nba", "CLE", "Cavaliers"),
    ("football", "nfl", "CLE", "Browns"),
)
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
POLL_SECONDS = 60
SCORE_ANNOUNCE_GAP = 180  # our scores: at most one call every 3 minutes

_running = False
_state: dict = {}   # per-game memory: last scores, lead sign, final-announced
_live: dict = {}    # the wall's snapshot: {} when no live game


def snapshot() -> dict:
    return dict(_live)


def _quiet() -> bool:
    h = datetime.datetime.now().hour
    return h >= 22 or h < 8


def _check_league(sport, league, abbr, spoken, announce):
    r = httpx.get(f"{ESPN}/{sport}/{league}/scoreboard", timeout=10)
    for event in r.json().get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        status = comp.get("status", {}).get("type", {})
        competitors = comp.get("competitors", [])
        us = next((c for c in competitors
                   if (c.get("team") or {}).get("abbreviation") == abbr), None)
        if not us:
            continue
        them = next((c for c in competitors if c is not us), {})
        state = status.get("state", "")
        if state not in ("in", "post"):
            continue

        gid = event.get("id", "")
        mem = _state.setdefault(gid, {"us": -1, "them": -1, "lead": 0,
                                      "final": False, "last_call": 0})
        s_us = int(us.get("score") or 0)
        s_them = int(them.get("score") or 0)
        them_name = ((them.get("team") or {}).get("shortDisplayName")
                     or (them.get("team") or {}).get("displayName", "the opponent"))
        detail = status.get("shortDetail", "")

        if state == "in":
            _live.clear()
            _live.update({"team": spoken, "opp": them_name, "us": s_us,
                          "them": s_them, "detail": detail, "sport": sport})

        # spoken moments (skipped in quiet hours; the score line still updates)
        now = time.time()
        lead = (s_us > s_them) - (s_us < s_them)
        if mem["us"] >= 0 and not _quiet():
            if state == "in" and lead != mem["lead"] and lead == 1:
                announce(f"Sir — the {spoken} just took the lead, {s_us} to {s_them}.")
                mem["last_call"] = now
            elif state == "in" and lead != mem["lead"] and lead == -1:
                announce(f"The {spoken} have fallen behind, sir — {s_them} to {s_us}.")
                mem["last_call"] = now
            elif state == "in" and s_us > mem["us"] and now - mem["last_call"] > SCORE_ANNOUNCE_GAP:
                announce(f"{spoken} score, sir — it's {s_us} to {s_them}.")
                mem["last_call"] = now
        if state == "post" and not mem["final"]:
            mem["final"] = True
            if _live.get("team") == spoken:
                _live.clear()  # game over — drop the score line
            verdict = "win" if s_us > s_them else "fall to the" if s_us < s_them else "tie with the"
            if s_us > s_them:
                announce(f"Final, sir: the {spoken} win it, {s_us} to {s_them}.")
            else:
                announce(f"Final, sir: the {spoken} {verdict} {them_name}, {s_them} to {s_us}.")

        mem["us"], mem["them"], mem["lead"] = s_us, s_them, lead


def _loop(announce):
    time.sleep(90)  # let the house boot
    while True:
        for sport, league, abbr, spoken in TRACKED:
            try:
                _check_league(sport, league, abbr, spoken, announce)
            except Exception as e:
                print(f"[gameday] {league} check failed: {str(e)[:120]}")
        any_live = bool(_live)
        print(f"[gameday] sweep done — live: {_live if any_live else 'none'}")
        # no game: sweep every 90s (games go live BETWEEN lazy sweeps and the
        # wall looked broken for 5 minutes); live game: every minute
        time.sleep(POLL_SECONDS if any_live else 90)


def start_gameday(announce_fn):
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, args=(announce_fn,), daemon=True,
                     name="jarvis-gameday").start()
