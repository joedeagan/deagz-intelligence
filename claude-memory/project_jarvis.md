---
name: Deagz Intelligence — Jarvis Project Status
description: Current state of the Jarvis assistant project, features, and architecture
type: project
---

## Architecture
- Python FastAPI server on port 3002
- Frontend: single-page HTML + Canvas 2D orb + Web Speech API
- Claude Sonnet 4 as the brain
- 45 tools registered across 7 modules
- Launched via `start_jarvis_web.bat`
- GitHub repo: https://github.com/joedeagan/deagz-intelligence

## Completed Features
- Voice control (click orb or spacebar, Web Speech API)
- ElevenLabs Daniel TTS ($5/mo, 30k chars, ~240 responses/month)
- 2D HUD orb with concentric rings, tick marks, segmented rings
- Dashboard: live time, weather, Kalshi portfolio, bot status (refreshes every 30s)
- Kalshi integration: portfolio, picks, bot status, trades, P&L, live scores, bet research
- Spotify: direct playback, skip, pause, now playing (authenticated as joedeagan)
- YouTube: voice-controlled search/open
- Weather: current + tomorrow + weekly forecast (Akron default)
- Study mode: AI-generated flashcards, voice quiz (can help with Algebra 1)
- Song ID: Shazam-like audio recognition
- Web search (DuckDuckGo)
- News headlines (by topic or general)
- Article summarizer
- Document creation (Word .docx or .txt, saved to Desktop, auto-opens)
- Email drafting (opens mailto: in default client)
- Screenshot analysis (captures screen, analyzes with Claude vision)
- Computer control: files, processes, screenshots, shell commands
- Reminders
- Conversation memory system (saves chats, preferences, facts to JSON)
- Speech correction for "Kalshi" (Chrome misheard as "call she")

## API Keys In Use
- Anthropic (Claude Sonnet 4) — user's own key
- ElevenLabs — $5/month starter plan, 30k chars/month, Daniel voice (ID: onwK4e9ZLuTAKqWW03F9)
- Spotify — OAuth via spotipy, cached at .spotify_cache
- Fish Audio — has key, not primary TTS
- Kalshi bot — Railway hosted Flask API

## Known Issues
- Server must be manually restarted to pick up code changes (close terminal + rerun bat)
- Chrome autoplay policy requires first click to unlock audio
- Port conflicts when old server isn't fully killed
- ElevenLabs TTS adds ~2s latency per response
- Claude Haiku model was deprecated, switched to Sonnet 4

## Planned Features (User Wants These)
- Host online for phone access
- Push notifications for Kalshi bets ("Your bet just hit, Deagz")
- Alexa/Google Home integration
- Smart home control (lights, thermostat)
- JARVIS movie startup sound
- "Good morning Deagz" daily briefing
- Conversation history scrollback in the UI
