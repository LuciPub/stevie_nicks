from os import getenv
import re

FFMPEG_PATH = '/usr/bin/ffmpeg'
CMD_PREFIX = '!!'

SPOTIFY_CLIENT_ID = getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = getenv("SPOTIFY_CLIENT_SECRET")

SPOTIFY_PATTERNS = {
    'track': re.compile(r'https://open\.spotify\.com/track/([a-zA-Z0-9]+)'),
    'playlist': re.compile(r'https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)'),
    'album': re.compile(r'https://open\.spotify\.com/album/([a-zA-Z0-9]+)')
}

YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio[protocol^=http]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,
    'default_search': 'ytsearch',
    'socket_timeout': 15,
    'retries': 3,
    'extract_flat': False,
    'nocheckcertificate': False,
    'http_chunk_size': 10485760,
    'prefer_free_formats': False,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

MAX_QUEUE_DISPLAY = 10
MAX_PLAYLIST_TRACKS = 25
MAX_CLIP_LENGTH = 60
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB
