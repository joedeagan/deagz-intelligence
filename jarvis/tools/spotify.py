"""Spotify integration — direct playback control via Spotify API."""

import webbrowser
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from jarvis.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
from jarvis.tools.base import Tool, registry

# Spotify scopes needed for playback control
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-modify-private playlist-modify-public user-read-recently-played user-top-read user-library-read"

_sp = None


def _get_spotify():
    """Get authenticated Spotify client. Auto-refreshes expired tokens."""
    global _sp
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None

    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPES,
        cache_path=".spotify_cache",
        open_browser=False,  # Don't open browser on server
    )

    # Force token refresh if expired
    token_info = auth_manager.get_cached_token()
    if token_info and auth_manager.is_token_expired(token_info):
        try:
            token_info = auth_manager.refresh_access_token(token_info["refresh_token"])
        except Exception:
            pass

    if not token_info:
        return None

    _sp = spotipy.Spotify(auth_manager=auth_manager)
    return _sp


def spotify_play(query: str, play_type: str = "track") -> str:
    """Search and play a song, album, artist, or playlist on Spotify."""
    sp = _get_spotify()
    if not sp:
        return "Spotify not configured. Need client ID and secret."

    try:
        # Get active device
        devices = sp.devices()
        active_device = None
        for d in devices.get("devices", []):
            if d.get("is_active"):
                active_device = d["id"]
                break

        if not active_device:
            # Use first available device
            device_list = devices.get("devices", [])
            if device_list:
                active_device = device_list[0]["id"]
            else:
                # Try opening Spotify first
                import subprocess
                subprocess.Popen("start spotify", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                import time
                time.sleep(3)
                devices = sp.devices()
                device_list = devices.get("devices", [])
                if device_list:
                    active_device = device_list[0]["id"]
                else:
                    return "No Spotify devices found. Open Spotify first."

        # Search based on type
        search_type = play_type.lower()
        if search_type not in ("track", "album", "artist", "playlist"):
            search_type = "track"

        results = sp.search(q=query, type=search_type, limit=1)
        items_key = f"{search_type}s"
        items = results.get(items_key, {}).get("items", [])

        if not items:
            return f"Couldn't find '{query}' on Spotify."

        item = items[0]
        name = item.get("name", query)
        uri = item.get("uri", "")

        if search_type == "track":
            artist = item.get("artists", [{}])[0].get("name", "")
            sp.start_playback(device_id=active_device, uris=[uri])
            return f"Now playing '{name}' by {artist}."

        elif search_type == "album":
            artist = item.get("artists", [{}])[0].get("name", "")
            sp.start_playback(device_id=active_device, context_uri=uri)
            return f"Now playing album '{name}' by {artist}."

        elif search_type == "artist":
            sp.start_playback(device_id=active_device, context_uri=uri)
            return f"Now playing {name}."

        elif search_type == "playlist":
            sp.start_playback(device_id=active_device, context_uri=uri)
            return f"Now playing playlist '{name}'."

    except spotipy.exceptions.SpotifyException as e:
        if "PREMIUM_REQUIRED" in str(e):
            return "Spotify Premium is required for playback control."
        return f"Spotify error: {e}"
    except Exception as e:
        return f"Failed to play: {e}"


def spotify_control(action: str) -> str:
    """Control Spotify playback — pause, resume, skip, previous, shuffle, repeat."""
    sp = _get_spotify()
    if not sp:
        return "Spotify not configured."

    try:
        action = action.lower().strip()

        if action in ("pause", "stop"):
            sp.pause_playback()
            return "Paused."

        elif action in ("play", "resume"):
            sp.start_playback()
            return "Resumed."

        elif action in ("next", "skip"):
            sp.next_track()
            return "Skipped to next track."

        elif action in ("previous", "back", "prev"):
            sp.previous_track()
            return "Playing previous track."

        elif action == "shuffle on":
            sp.shuffle(True)
            return "Shuffle enabled."

        elif action == "shuffle off":
            sp.shuffle(False)
            return "Shuffle disabled."

        elif action.startswith("volume"):
            # Extract number
            import re
            nums = re.findall(r'\d+', action)
            if nums:
                vol = min(100, max(0, int(nums[0])))
                sp.volume(vol)
                return f"Volume set to {vol}%."
            return "Specify a volume level, e.g. 'volume 50'."

        else:
            return f"Unknown action '{action}'. Try: pause, play, next, previous, shuffle on/off, volume [0-100]."

    except Exception as e:
        return f"Spotify control error: {e}"


def spotify_now_playing() -> str:
    """Get what's currently playing on Spotify."""
    sp = _get_spotify()
    if not sp:
        return "Spotify not configured."

    try:
        current = sp.current_playback()
        if not current or not current.get("item"):
            return "Nothing is playing on Spotify right now."

        item = current["item"]
        name = item.get("name", "Unknown")
        artist = item.get("artists", [{}])[0].get("name", "Unknown")
        album = item.get("album", {}).get("name", "")
        is_playing = current.get("is_playing", False)
        progress = current.get("progress_ms", 0) // 1000
        duration = item.get("duration_ms", 0) // 1000

        status = "Playing" if is_playing else "Paused"
        mins_p, secs_p = divmod(progress, 60)
        mins_d, secs_d = divmod(duration, 60)

        result = f"{status}: '{name}' by {artist}"
        if album:
            result += f" from '{album}'"
        result += f" — {mins_p}:{secs_p:02d}/{mins_d}:{secs_d:02d}"
        return result

    except Exception as e:
        return f"Could not get playback info: {e}"


# Register tools
registry.register(Tool(
    name="spotify_play",
    description="Search and play a song, album, artist, or playlist directly on Spotify. Use for 'play Rodeo', 'put on Drake', 'play my Liked Songs'.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for — song name, artist, album, or playlist"},
            "play_type": {"type": "string", "description": "'track' (default), 'album', 'artist', or 'playlist'"},
        },
        "required": ["query"],
    },
    handler=spotify_play,
))

registry.register(Tool(
    name="spotify_control",
    description="Control Spotify playback — pause, play/resume, next/skip, previous/back, shuffle on/off, volume [0-100].",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "Action: pause, play, next, skip, previous, back, shuffle on, shuffle off, volume 50"},
        },
        "required": ["action"],
    },
    handler=spotify_control,
))

def spotify_queue(**kwargs) -> str:
    """Show what's coming up next in the Spotify queue."""
    sp = _get_spotify()
    if not sp:
        return "Spotify not configured."
    try:
        queue = sp.queue()
        current = queue.get("currently_playing")
        upcoming = queue.get("queue", [])[:8]

        lines = []
        if current:
            lines.append(f"Now: {current['name']} - {current['artists'][0]['name']}")
        if upcoming:
            lines.append("Up next:")
            for i, t in enumerate(upcoming, 1):
                lines.append(f"  {i}. {t['name']} - {t['artists'][0]['name']}")
        else:
            lines.append("Queue is empty.")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not get queue: {e}"

registry.register(Tool(
    name="spotify_queue",
    description="Show what's coming up next in the Spotify queue. Use for 'what's next', 'show queue', 'what's playing next'.",
    parameters={"type": "object", "properties": {}},
    handler=spotify_queue,
))

registry.register(Tool(
    name="spotify_now_playing",
    description="Check what's currently playing on Spotify with artist, album, and progress.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=spotify_now_playing,
))


def spotify_create_playlist(name: str = "", description: str = "", tracks: str = "", mood: str = "", **kwargs) -> str:
    """Queue tracks on Spotify from specific songs or a mood search."""
    sp = _get_spotify()
    if not sp:
        return "Spotify not configured."

    try:
        track_list = []

        if tracks:
            # User gave specific track names
            for track_name in tracks.split(","):
                track_name = track_name.strip()
                if not track_name:
                    continue
                results = sp.search(q=track_name, type="track", limit=1)
                items = results.get("tracks", {}).get("items", [])
                if items:
                    track_list.append(items[0])

        elif mood:
            # Search for tracks matching the mood
            results = sp.search(q=mood, type="track", limit=20)
            track_list = results.get("tracks", {}).get("items", [])

        if not track_list:
            return f"Couldn't find tracks for '{mood or tracks}'."

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

        # Queue and play
        uris = [t["uri"] for t in track_list]
        sp.start_playback(device_id=active, uris=uris)
        sp.shuffle(True, device_id=active)

        return f"Playing {len(track_list)} tracks — {mood or 'custom mix'}."

    except Exception as e:
        return f"Failed: {e}"


registry.register(Tool(
    name="spotify_create_playlist",
    description="Create a Spotify playlist from a mood, vibe, or specific tracks. Use for 'make me a chill playlist', 'create a workout mix', 'build a playlist with these songs'. Automatically starts playing it.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Playlist name (optional — auto-generated if empty)"},
            "mood": {"type": "string", "description": "Mood/vibe for auto-generating tracks (e.g. 'chill study', 'workout hype', 'late night drive', 'sad vibes')"},
            "tracks": {"type": "string", "description": "Comma-separated list of specific songs to add (e.g. 'Rodeo by Travis Scott, Sicko Mode, HUMBLE')"},
            "description": {"type": "string", "description": "Optional playlist description"},
        },
    },
    handler=spotify_create_playlist,
))
