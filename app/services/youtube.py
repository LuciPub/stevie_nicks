import yt_dlp as youtube_dl
from utils.config import YDL_OPTS


async def get_youtube_url(search_query):
    """Convert a search query to a YouTube URL and title"""
    yt_query = f'ytsearch:{search_query}' if not search_query.startswith(
        ('http://', 'https://')) else search_query

    try:
        with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(yt_query, download=False)

            if 'entries' in info:
                info = info['entries'][0]

            return {
                'url': info['url'],
                'title': info['title']
            }
    except Exception as e:
        print(f"Error searching YouTube: {e}")
        return None
