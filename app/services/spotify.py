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


async def get_spotify_track(track_id):
    """Get track info from Spotify track ID"""
    if not sp:
        return None
    try:
        track = sp.track(track_id)
        search_query = f"{track['artists'][0]['name']} - {track['name']}"
        return {
            'title': f"{track['artists'][0]['name']} - {track['name']}",
            'search_query': search_query
        }
    except Exception as e:
        print(f"Error fetching Spotify track: {e}")
        return None


async def get_spotify_playlist(playlist_id):
    """Get tracks from Spotify playlist ID"""
    if not sp:
        return []
    try:
        results = sp.playlist_items(playlist_id)
        tracks = []

        for item in results['items']:
            if 'track' in item and item['track']:
                track = item['track']
                artist = track['artists'][0]['name'] if track['artists'] else 'Unknown'
                name = track['name'] if 'name' in track else 'Unknown'
                tracks.append({
                    'title': f"{artist} - {name}",
                    'search_query': f"{artist} - {name}"
                })

        while results['next'] and len(tracks) < 100:
            results = sp.next(results)
            for item in results['items']:
                if 'track' in item and item['track']:
                    track = item['track']
                    artist = track['artists'][0]['name'] if track['artists'] else 'Unknown'
                    name = track['name'] if 'name' in track else 'Unknown'
                    tracks.append({
                        'title': f"{artist} - {name}",
                        'search_query': f"{artist} - {name}"
                    })

        return tracks
    except Exception as e:
        print(f"Error fetching Spotify playlist: {e}")
        return []


async def get_spotify_album(album_id):
    """Get tracks from Spotify album ID"""
    if not sp:
        return []
    try:
        results = sp.album_tracks(album_id)
        tracks = []

        for track in results['items']:
            artist = track['artists'][0]['name'] if track['artists'] else 'Unknown'
            name = track['name'] if 'name' in track else 'Unknown'
            tracks.append({
                'title': f"{artist} - {name}",
                'search_query': f"{artist} - {name}"
            })

        while results['next']:
            results = sp.next(results)
            for track in results['items']:
                artist = track['artists'][0]['name'] if track['artists'] else 'Unknown'
                name = track['name'] if 'name' in track else 'Unknown'
                tracks.append({
                    'title': f"{artist} - {name}",
                    'search_query': f"{artist} - {name}"
                })

        return tracks
    except Exception as e:
        print(f"Error fetching Spotify album: {e}")
        return []


async def process_spotify_tracks(tracks, guild_id, channel):
    """Process and queue multiple Spotify tracks"""
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
