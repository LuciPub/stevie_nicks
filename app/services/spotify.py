import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from services.youtube import get_youtube_url
from services.music import add_to_queue
from utils.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, MAX_PLAYLIST_TRACKS


sp = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    ))


def _format_track(track):
    artist = track.get('artists', [{}])[0].get('name', 'Unknown')
    name = track.get('name', 'Unknown')
    title = f"{artist} - {name}"
    return {'title': title, 'search_query': title}


async def get_spotify_track(track_id):
    if not sp:
        return None
    try:
        track = sp.track(track_id)
        return _format_track(track)
    except Exception as e:
        print(f"Error fetching Spotify track: {e}")
        return None


def _extract_tracks(items):
    tracks = []
    for item in items:
        track = item.get('track') if 'track' in item else item
        if track:
            tracks.append(_format_track(track))
    return tracks


async def get_spotify_playlist(playlist_id):
    if not sp:
        return []
    try:
        results = sp.playlist_items(playlist_id)
        tracks = _extract_tracks(results['items'])

        while results['next'] and len(tracks) < 100:
            results = sp.next(results)
            tracks.extend(_extract_tracks(results['items']))

        return tracks
    except Exception as e:
        print(f"Error fetching Spotify playlist: {e}")
        return []


async def get_spotify_album(album_id):
    if not sp:
        return []
    try:
        results = sp.album_tracks(album_id)
        tracks = _extract_tracks(results['items'])

        while results['next']:
            results = sp.next(results)
            tracks.extend(_extract_tracks(results['items']))

        return tracks
    except Exception as e:
        print(f"Error fetching Spotify album: {e}")
        return []


async def process_spotify_tracks(tracks, guild_id, channel):
    max_tracks = min(MAX_PLAYLIST_TRACKS, len(tracks))

    for track in tracks[:max_tracks]:
        try:
            youtube_info = await get_youtube_url(track['search_query'])
            if youtube_info:
                add_to_queue(guild_id, {
                    'url': youtube_info['url'],
                    'title': track['title']
                })
        except Exception as e:
            print(f"Error processing track {track['title']}: {e}")
