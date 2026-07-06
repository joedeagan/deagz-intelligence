"""One-time Spotify account linking for Jarvis.

Run on the machine that hosts the brain (from the repo root, where .env
lives). Opens a browser for the Spotify consent screen, catches the
redirect locally, and saves the token cache the spotify tools use.

    python spotify_link.py
"""

from spotipy.oauth2 import SpotifyOAuth

from jarvis.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
from jarvis.tools.spotify import SCOPES

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise SystemExit("Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in .env — add them first.")

auth = SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri=SPOTIFY_REDIRECT_URI,
    scope=SCOPES,
    cache_path=".spotify_cache",  # same path the tools read, relative to the brain dir
    open_browser=True,
)

print("A browser window will open — log into Spotify and click Agree…")
token = auth.get_access_token(as_dict=False)
print("Linked!" if token else "Something went wrong — no token saved.")
print("Jarvis can now command Spotify. You may close this window.")
