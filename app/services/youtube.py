import asyncio
import yt_dlp as youtube_dl
from utils.config import YDL_OPTS


def _extract_info(yt_query):
    with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
        return ydl.extract_info(yt_query, download=False)


async def get_youtube_url(search_query):
    """Convert a search query to a YouTube URL and title"""

    yt_query = (
        f'ytsearch:{search_query}'
        if not search_query.startswith(('http://', 'https://'))
        else search_query
    )

    try:
        # 🔥 roda em thread separada
        info = await asyncio.to_thread(_extract_info, yt_query)

        if 'entries' in info:
            entries = info['entries']

            for entry in entries[:5]:
                if entry:
                    title_lower = entry.get('title', '').lower()
                    channel_lower = entry.get('channel', '').lower()

                    if (
                        any(k in title_lower for k in [
                            'official audio', 'audio', 'lyric'])
                        or 'topic' in channel_lower
                        or 'vevo' in channel_lower
                    ):
                        info = entry
                        break
            else:
                info = entries[0]

        return {
            'url': info['url'],
            'title': info['title']
        }

    except Exception as e:
        print(f"Error searching YouTube: {e}")
        return None
