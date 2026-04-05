"""Auto-DJ — learns music taste over time and auto-queues songs Deagz will like."""

import json
import datetime
import threading
from pathlib import Path

from jarvis.tools.base import Tool, registry

MUSIC_LOG = Path(__file__).parent.parent.parent / "data" / "memory" / "music_taste.json"

_dj_running = False
_dj_thread = None


def _load_taste() -> dict:
    if MUSIC_LOG.exists():
        return json.loads(MUSIC_LOG.read_text(encoding="utf-8"))
    return {"artists": {}, "genres": {}, "recent_tracks": [], "liked": [], "disliked": []}


def _save_taste(data: dict):
    MUSIC_LOG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _track_listen(artist: str, track: str, genre: str = ""):
    """Record what the user listened to."""
    taste = _load_taste()

    # Count artist plays
    taste["artists"][artist] = taste["artists"].get(artist, 0) + 1

    # Count genre plays
    if genre:
        taste["genres"][genre] = taste["genres"].get(genre, 0) + 1

    # Recent tracks (last 100)
    taste["recent_tracks"].append({
        "artist": artist, "track": track, "genre": genre,
        "ts": datetime.datetime.now().isoformat()
    })
    if len(taste["recent_tracks"]) > 100:
        taste["recent_tracks"] = taste["recent_tracks"][-100:]

    _save_taste(taste)


def auto_dj(mood: str = "", duration: int = 30, **kwargs) -> str:
    """Start Auto-DJ mode — queues songs based on learned taste + optional mood."""
    try:
        from jarvis.tools.spotify import _get_spotify
        sp = _get_spotify()
        if not sp:
            return "Spotify not configured."

        # Pull YOUR actual tracks from Spotify history
        tracks = []
        seen = set()

        # Top tracks across all time ranges
        for time_range in ["short_term", "medium_term", "long_term"]:
            try:
                top = sp.current_user_top_tracks(limit=20, time_range=time_range)
                for t in top.get("items", []):
                    if t["id"] not in seen:
                        seen.add(t["id"])
                        tracks.append(t)
            except Exception:
                pass

        # Recently played
        try:
            recent = sp.current_user_recently_played(limit=50)
            for r in recent.get("items", []):
                t = r["track"]
                if t["id"] not in seen:
                    seen.add(t["id"])
                    tracks.append(t)
        except Exception:
            pass

        if not tracks:
            return "No listening history found. Play some music first."

        # Get active device
        devices = sp.devices()
        active = None
        for d in devices.get("devices", []):
            if d.get("is_active"):
                active = d["id"]
                break
        if not active and devices.get("devices"):
            active = devices["devices"][0]["id"]

        if not active:
            return "No Spotify device found. Open Spotify first."

        # Queue all your tracks, shuffled
        uris = [t["uri"] for t in tracks]
        sp.start_playback(device_id=active, uris=uris)
        sp.shuffle(True, device_id=active)

        # Log taste
        for t in tracks[:20]:
            artist = t.get("artists", [{}])[0].get("name", "")
            if artist:
                _track_listen(artist, t.get("name", ""), "")

        return f"DJ mode started — {len(tracks)} of your tracks, shuffled."

    except Exception as e:
        return f"Auto-DJ failed: {e}"


def rate_song(rating: str = "like", **kwargs) -> str:
    """Rate the current song as liked or disliked to improve recommendations."""
    try:
        from jarvis.tools.spotify import _get_spotify
        sp = _get_spotify()
        if not sp:
            return "Spotify not configured."

        current = sp.current_playback()
        if not current or not current.get("item"):
            return "Nothing is playing."

        track = current["item"]
        name = track.get("name", "Unknown")
        artist = track.get("artists", [{}])[0].get("name", "Unknown")

        taste = _load_taste()
        entry = {"track": name, "artist": artist, "ts": datetime.datetime.now().isoformat()}

        if rating.lower() in ("like", "love", "yes", "good", "fire"):
            taste.setdefault("liked", []).append(entry)
            # Boost artist weight
            taste["artists"][artist] = taste["artists"].get(artist, 0) + 3
            _save_taste(taste)

            # Also save to Spotify liked songs
            try:
                sp.current_user_saved_tracks_add([track["id"]])
            except Exception:
                pass

            return f"Noted — you like '{name}' by {artist}. I'll queue more like this."
        else:
            taste.setdefault("disliked", []).append(entry)
            # Reduce artist weight
            taste["artists"][artist] = max(0, taste["artists"].get(artist, 0) - 2)
            _save_taste(taste)

            # Skip the song
            try:
                sp.next_track()
            except Exception:
                pass

            return f"Skipping '{name}' — I'll avoid similar tracks."

    except Exception as e:
        return f"Rating failed: {e}"


def get_music_taste(**kwargs) -> str:
    """Show what Jarvis has learned about the user's music taste."""
    taste = _load_taste()
    if not taste.get("artists"):
        return "Haven't learned your taste yet. Play some music and I'll start tracking."

    top = sorted(taste["artists"].items(), key=lambda x: x[1], reverse=True)[:10]
    lines = ["Your top artists (by play count):"]
    for artist, count in top:
        lines.append(f"  {artist}: {count} plays")

    liked = taste.get("liked", [])
    if liked:
        lines.append(f"\nLiked songs: {len(liked)}")
        for s in liked[-5:]:
            lines.append(f"  ♥ {s['track']} — {s['artist']}")

    return "\n".join(lines)


# ─── Register ───

registry.register(Tool(
    name="auto_dj",
    description="Start Auto-DJ mode — plays music based on learned taste and optional mood. Use for 'be my DJ', 'play something I'd like', 'DJ mode', 'play music based on my taste'. Mood examples: 'chill', 'hype', 'sad', 'study', 'workout'.",
    parameters={
        "type": "object",
        "properties": {
            "mood": {"type": "string", "description": "Optional mood/vibe (chill, hype, study, workout, sad, late night)"},
            "duration": {"type": "integer", "description": "Number of songs to queue (default 30)"},
        },
    },
    handler=auto_dj,
))

registry.register(Tool(
    name="rate_song",
    description="Rate the current song to improve Auto-DJ. Use for 'I like this song', 'skip this is bad', 'this is fire', 'not feeling this one'.",
    parameters={
        "type": "object",
        "properties": {
            "rating": {"type": "string", "description": "'like' or 'dislike'"},
        },
        "required": ["rating"],
    },
    handler=rate_song,
))

registry.register(Tool(
    name="get_music_taste",
    description="Show what Jarvis has learned about the user's music taste. Use for 'what music do I like', 'what's my taste', 'show my top artists'.",
    parameters={"type": "object", "properties": {}},
    handler=get_music_taste,
))
