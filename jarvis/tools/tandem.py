"""Tandem tool — let Jarvis send + check Tandems on Joe's behalf.

Tandem (https://tandem.cc) is the human+Claude communication fabric Joe
and his dad Brian build. Each user has a handle (joe@tandem.cc,
brian@tandem.cc, leslie@tandem.cc, ...). Threads are first-class.

This tool gives Jarvis two operations:
  - send_tandem(to_handle, body)         — fire a Tandem
  - check_tandem_inbox(limit=5)          — list recent threads

Auth: bearer token in TANDEM_BEARER_TOKEN env var, bound to Joe's
handle (joe@tandem.cc). Mint via Tandem's admin panel; revoke without
breaking other Joe-bound tokens (each token has a unique name).

Attribution: Tandems sent via Jarvis stamp drafted_by="human" because
this surface doesn't carry the Tandem project's working context (the
shared CLAUDE.md, prior threads, memory files). Per Brian's
m_… 2026-04-25 rule (drafted-by-claude-requires-context): only
surfaces with project context should claim drafted_by="claude". Joe
is the drafter from Jarvis's POV — Jarvis just transcribes voice.

Wire format: POST https://tandem-cc.up.railway.app/v1/messages with
Authorization: Bearer <token>. The same envelope shape Tandem's CLI
sends. No magic.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone

import httpx

from jarvis.tools.base import Tool, registry


# ─── Config ───
# All overridable via env so Jarvis works against staging or a
# self-hosted Tandem if Joe ever runs one.
TANDEM_API_BASE = os.getenv(
    "TANDEM_API_BASE", "https://tandem-cc.up.railway.app"
).rstrip("/")
TANDEM_BEARER_TOKEN = os.getenv("TANDEM_BEARER_TOKEN", "")
TANDEM_HANDLE = os.getenv("TANDEM_HANDLE", "joe@tandem.cc")
TANDEM_SIGNED_BY = os.getenv("TANDEM_SIGNED_BY", "joe")
# Network timeout in seconds. Tandem's a fast HTTP API on Railway,
# but voice tools should fail fast — Joe doesn't want to wait on
# a hung request mid-conversation.
_HTTP_TIMEOUT = 10.0


# ─── Helpers ───


# Voice-friendly nickname → handle map. When Joe says "Tandem dad" we
# don't want Jarvis trying to look up dad@tandem.cc (which doesn't
# exist). This is the small list of relationship aliases for Joe's
# inner circle. Add more as the user base grows.
#
# Lowercased keys, lowercased handles. Match happens after
# .strip().lower(), so capitalization in the voice transcript doesn't
# matter.
_NICKNAMES = {
    # Family — Brian (brian@tandem.cc)
    "dad":     "brian@tandem.cc",
    "father":  "brian@tandem.cc",
    "papa":    "brian@tandem.cc",
    "pops":    "brian@tandem.cc",
    "old man": "brian@tandem.cc",
    # Add more as the Tandem userbase grows. Format:
    #     "<spoken-form>": "<canonical-handle>",
    # e.g. "mom": "alice@tandem.cc",
    #      "boss": "jeff@tandem.cc",
}


def _resolve_handle(name_or_handle: str) -> str:
    """Accept any of:
      - 'brian@tandem.cc'      → returned as-is
      - 'brian' / 'Brian'      → 'brian@tandem.cc'
      - 'dad' / 'pops' / etc.  → looked up in _NICKNAMES → 'brian@tandem.cc'

    Voice users say first names and relationship nicknames; we
    normalize everything to a canonical handle here so the rest of
    the tool only deals with one shape.
    """
    s = (name_or_handle or "").strip().lower()
    if not s:
        return ""
    if "@" in s:
        return s
    # Relationship nicknames (dad, papa, mom, etc.) take precedence
    # over the bare-name → handle@tandem.cc fallback so "dad" doesn't
    # get turned into the non-existent dad@tandem.cc.
    if s in _NICKNAMES:
        return _NICKNAMES[s]
    # Bare first names — assume @tandem.cc.
    return f"{s}@tandem.cc"


def _new_id(prefix: str) -> str:
    """Mint a Tandem-style ID: m_<8-hex>, t_<8-hex>."""
    return f"{prefix}_{secrets.token_hex(4)}"


def _post(path: str, json_body: dict) -> tuple[int, dict | str]:
    """POST to Tandem with bearer auth. Returns (status_code, body).
    Body is parsed JSON when possible, raw text otherwise."""
    url = f"{TANDEM_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {TANDEM_BEARER_TOKEN}",
        "Content-Type":  "application/json",
    }
    try:
        resp = httpx.post(url, headers=headers, json=json_body,
                          timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        return 0, f"network: {type(e).__name__}: {e}"
    try:
        return resp.status_code, resp.json()
    except json.JSONDecodeError:
        return resp.status_code, resp.text


def _get(path: str, params: dict | None = None) -> tuple[int, dict | str]:
    """GET from Tandem with bearer auth. Same return shape as _post."""
    url = f"{TANDEM_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {TANDEM_BEARER_TOKEN}",
    }
    try:
        resp = httpx.get(url, headers=headers, params=params or {},
                         timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        return 0, f"network: {type(e).__name__}: {e}"
    try:
        return resp.status_code, resp.json()
    except json.JSONDecodeError:
        return resp.status_code, resp.text


def _short_name(handle: str) -> str:
    """Local-part of a handle, for voice readback. brian@tandem.cc → brian."""
    return (handle or "").split("@", 1)[0]


# ─── send_tandem ───


def send_tandem(to: str = "", body: str = "", in_reply_to: str = "",
                drafted_by: str = "human", **kwargs) -> str:
    """Send a Tandem to a recipient handle. Voice-friendly handler.

    Args:
        to:          Handle or first name (e.g. 'brian', 'leslie',
                     'dad').
        body:        Message body (what to say).
        in_reply_to: Optional message_id ('m_xxx') to reply into. When
                     provided, the message lands in the existing thread
                     instead of starting a new one. Voice users rarely
                     supply this — usually omitted.
        drafted_by:  Attribution for who composed the body. Two valid
                     values from Jarvis:
                       - "human"  (default) — Joe dictated verbatim;
                                  Jarvis transcribed.
                       - "jarvis" — Jarvis composed the body using its
                                  Claude brain (no Tandem project
                                  context, so NOT "claude" per Brian's
                                  m_da8ec512 rule).
                     The Jarvis brain should pass "jarvis" only after
                     reading the composed draft back and getting
                     explicit "send" / "yes" / "do it" approval from
                     the user. Per the human-signs-the-wire principle:
                     never auto-send a composed draft.

    Returns a single sentence for Jarvis to speak.
    """
    if not TANDEM_BEARER_TOKEN:
        return ("I haven't been issued a Tandem bearer token, sir. "
                "Set TANDEM_BEARER_TOKEN in the environment.")
    to_handle = _resolve_handle(to)
    if not to_handle:
        return "I need a recipient handle, sir — say a name."
    if not (body or "").strip():
        return "I need something to say, sir."

    # Normalize drafted_by: only "human" or "jarvis" allowed from this
    # surface. Default to "human" if the brain passes anything else
    # (including "claude" — that attribution is reserved for Tandem-
    # project-aware Claude sessions per the workflow conventions).
    db = (drafted_by or "human").strip().lower()
    if db not in ("human", "jarvis"):
        db = "human"

    envelope = {
        "message_id":  _new_id("m"),
        "thread_id":   _new_id("t"),
        "from_handle": TANDEM_HANDLE,
        "to_handles":  [to_handle],
        "signed_by":   TANDEM_SIGNED_BY,
        "drafted_by":  db,
        "body_text":   body.strip(),
        "sent_at":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "transport":   "tandem_api",
    }
    # If replying, server-side resolver looks up the thread from
    # in_reply_to. We omit thread_id in that case so the server picks
    # the correct one.
    if in_reply_to.strip():
        envelope["in_reply_to"] = in_reply_to.strip()
        envelope.pop("thread_id", None)

    code, body_resp = _post("/v1/messages", envelope)
    if code == 201 and isinstance(body_resp, dict) and body_resp.get("ok"):
        return f"Tandem sent to {_short_name(to_handle).title()}, sir."
    if code == 401:
        return "My Tandem token was rejected, sir — likely revoked."
    if code == 403:
        return "Tandem refused the send — handle scope mismatch."
    return (f"Tandem send failed, sir — HTTP {code}. "
            f"Response: {str(body_resp)[:140]}")


# ─── check_tandem_inbox ───


def check_tandem_inbox(limit: int = 5, **kwargs) -> str:
    """List the most recent Tandem threads for the bound handle.

    Voice-friendly: returns a short summary like
    'Three new Tandems, sir. Most recent from Brian about the install path.'

    Args:
        limit: How many threads to consider (default 5, max 20).
    """
    if not TANDEM_BEARER_TOKEN:
        return ("I haven't been issued a Tandem bearer token, sir. "
                "Set TANDEM_BEARER_TOKEN in the environment.")

    cap = max(1, min(int(limit or 5), 20))
    code, data = _get("/v1/messages", params={"for": TANDEM_HANDLE,
                                              "limit": cap * 8})
    if code != 200 or not isinstance(data, dict):
        return (f"Couldn't reach the Tandem inbox, sir — HTTP {code}. "
                f"{str(data)[:120]}")

    msgs = data.get("messages") or []
    if not msgs:
        return "Nothing new in your Tandem inbox, sir."

    # Roll up by thread_id, keep the latest from each.
    by_thread: dict[str, dict] = {}
    for m in msgs:
        tid = m.get("thread_id")
        if not tid:
            continue
        prev = by_thread.get(tid)
        if (not prev or
                (m.get("sent_at") or "") > (prev.get("sent_at") or "")):
            by_thread[tid] = m

    threads = sorted(by_thread.values(),
                     key=lambda m: m.get("sent_at") or "",
                     reverse=True)[:cap]

    # Filter to threads whose latest message is from someone OTHER than Joe
    # — those are the genuinely "new" ones Jarvis should mention. Threads
    # where Joe sent the most recent message are caught up.
    inbound = [t for t in threads
               if (t.get("from_handle") or "") != TANDEM_HANDLE]
    if not inbound:
        return "Nothing new in your Tandem inbox, sir — you're caught up."

    n = len(inbound)
    latest = inbound[0]
    sender = _short_name(latest.get("from_handle", "")).title() or "someone"
    snippet = (latest.get("body_text") or "").strip()
    # First non-empty line, trim to ~50 chars for voice readability.
    first_line = ""
    for line in snippet.splitlines():
        line = line.strip()
        if line:
            first_line = line[:50]
            break

    if n == 1:
        return f"One new Tandem, sir — from {sender}: \"{first_line}\""
    word = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}.get(n, str(n))
    return (f"{word} new Tandems, sir. Most recent from {sender}: "
            f"\"{first_line}\"")


# ─── Register ───

registry.register(Tool(
    name="send_tandem",
    description=(
        "Send a Tandem message to a recipient. Two flows:\n\n"

        "DICTATION (default): The user says the exact words. "
        "Examples: 'Tandem Dad on my way', 'tell Brian I'll be late', "
        "'send Leslie that the meeting moved to 3pm'. Pass body "
        "verbatim; pass drafted_by='human'.\n\n"

        "COMPOSITION (when the user asks Jarvis to draft / write / "
        "compose): The user wants Jarvis to write the message. "
        "Examples: 'Jarvis, draft a Tandem to Dad about the install "
        "path', 'write Brian a Tandem explaining the bug we just "
        "fixed', 'compose a thank-you to Leslie'. In this case:\n"
        "  1. COMPOSE the body yourself (Jarvis brain) — keep it "
        "short and natural, sound like Joe wrote it.\n"
        "  2. READ THE DRAFT BACK to the user before calling "
        "send_tandem. Say something like: 'Drafting: \"<body>\". "
        "Send it, sir?'\n"
        "  3. WAIT for explicit approval ('send', 'yes', 'do it', "
        "'fire it'). If the user wants changes ('make it shorter', "
        "'add X'), revise and read back again.\n"
        "  4. ONLY THEN call send_tandem with drafted_by='jarvis'.\n\n"

        "NEVER auto-send a composed draft. The 'human signs the "
        "wire' rule is the core trust contract of Tandem and has no "
        "exceptions, including for short or seemingly-trivial "
        "messages. Voice approval IS the human signature.\n\n"

        "The message is signed by Joe (the bound handle) and lands "
        "in Brian's / Leslie's / etc. inbox immediately on send."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to":   {"type": "string",
                     "description": (
                         "Recipient. Accepts: relationship nickname "
                         "('dad', 'pops', 'father' = Brian); first name "
                         "('brian', 'leslie'); or full handle "
                         "('brian@tandem.cc'). The nickname → handle "
                         "mapping lives in jarvis/tools/tandem.py "
                         "(_NICKNAMES). Pass exactly what the user "
                         "said — the resolver normalizes."
                     )},
            "body": {"type": "string",
                     "description": (
                         "The Tandem body. For dictation: pass "
                         "verbatim what the user said. For "
                         "composition: pass what Jarvis composed AFTER "
                         "the user approved it."
                     )},
            "drafted_by": {
                "type": "string",
                "enum": ["human", "jarvis"],
                "description": (
                     "Attribution. 'human' (default) = Joe dictated "
                     "verbatim. 'jarvis' = Jarvis composed and the "
                     "user approved by voice. NEVER pass 'claude' — "
                     "that's reserved for Tandem-project-aware Claude "
                     "sessions (Brian's m_da8ec512 rule)."
                ),
            },
            "in_reply_to": {"type": "string",
                            "description": "Optional message_id (m_xxx) "
                                           "to reply into. Usually omit "
                                           "for new messages."},
        },
        "required": ["to", "body"],
    },
    handler=send_tandem,
))

registry.register(Tool(
    name="check_tandem_inbox",
    description=(
        "Check Joe's Tandem inbox for new messages from Brian, Leslie, or "
        "any other handle. Use for 'any new Tandems?', 'do I have a "
        "Tandem from my dad?', 'what's in my Tandem inbox?'. Returns a "
        "short voice-friendly summary — count + latest sender + snippet. "
        "Filters out threads where Joe sent the latest message (those "
        "are caught up)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer",
                      "description": "Max recent threads to consider "
                                     "(default 5, max 20)."},
        },
    },
    handler=check_tandem_inbox,
))
