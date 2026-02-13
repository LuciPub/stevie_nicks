import asyncio
import yt_dlp as youtube_dl
from utils.config import YDL_OPTS


def _extract_info(yt_query):
    with youtube_dl.YoutubeDL(YDL_OPTS) as ydl:
        return ydl.extract_info(yt_query, download=False)


async def _extract_with_timeout(yt_query, timeout=30):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_extract_info, yt_query),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        raise Exception(f"Extraction timed out after {timeout}s")


def _get_best_audio_url(info):
    """Extract best audio URL from yt-dlp info, preferring direct URLs over HLS"""
    if 'formats' in info:
        direct_formats = []
        hls_formats = []

        for fmt in info['formats']:
            if fmt.get('acodec') == 'none':
                continue

            url = fmt.get('url', '')
            if not url:
                continue

            if '.m3u8' in url or 'hls' in fmt.get('protocol', ''):
                hls_formats.append(fmt)
            else:
                direct_formats.append(fmt)

        if direct_formats:
            direct_formats.sort(key=lambda f: f.get('abr', 0) or f.get('tbr', 0), reverse=True)
            best_url = direct_formats[0]['url']
            print(f"Selected direct format: {direct_formats[0].get('format_id')} ({direct_formats[0].get('abr', 0)}kbps)")
            return best_url

        if hls_formats:
            hls_formats.sort(key=lambda f: f.get('abr', 0) or f.get('tbr', 0), reverse=True)
            best_url = hls_formats[0]['url']
            print(f"⚠️ Using HLS format: {hls_formats[0].get('format_id')} ({hls_formats[0].get('abr', 0)}kbps)")
            return best_url

    fallback = info.get('url')
    if fallback:
        print(f"⚠️ Using fallback URL from info['url']")
    return fallback


async def refresh_url(webpage_url):
    """Re-extract URL from webpage_url (for expired streams)"""
    try:
        info = await _extract_with_timeout(webpage_url)
        url = _get_best_audio_url(info)
        if url:
            return url
    except Exception as e:
        print(f"Error refreshing URL: {e}")
    return None


async def search_youtube(query, max_results=5):
    try:
        info = await _extract_with_timeout(f'ytsearch{max_results}:{query}')
        if 'entries' not in info:
            return []
        results = []
        for entry in info['entries']:
            if not entry:
                continue
            results.append({
                'title': entry.get('title', 'Unknown'),
                'webpage_url': entry.get('webpage_url', ''),
                'duration': entry.get('duration'),
                'thumbnail': entry.get('thumbnail'),
                'channel': entry.get('channel', ''),
            })
        return results
    except Exception as e:
        print(f"Error searching YouTube: {e}")
        return []


async def resolve_youtube_entry(webpage_url):
    try:
        info = await _extract_with_timeout(webpage_url)
        url = _get_best_audio_url(info)
        if not url:
            return None
        return {
            'url': url,
            'title': info['title'],
            'webpage_url': info.get('webpage_url', webpage_url),
            'duration': info.get('duration'),
            'thumbnail': info.get('thumbnail'),
        }
    except Exception as e:
        print(f"Error resolving YouTube entry: {e}")
        return None


async def get_youtube_url(search_query):
    yt_query = (
        f'ytsearch:{search_query}'
        if not search_query.startswith(('http://', 'https://'))
        else search_query
    )

    try:
        info = await _extract_with_timeout(yt_query)

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

        url = _get_best_audio_url(info)

        if not url:
            raise ValueError("No valid stream URL found")

        return {
            'url': url,
            'title': info['title'],
            'webpage_url': info.get('webpage_url', yt_query),
            'duration': info.get('duration'),
            'thumbnail': info.get('thumbnail'),
        }

    except Exception as e:
        print(f"Error searching YouTube: {e}")
        return None
