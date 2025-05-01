import asyncio
import tempfile
import subprocess
import shutil
import os
from utils.config import FFMPEG_PATH, MAX_FILE_SIZE


async def create_clip(url, start_sec, end_sec, format="mp3"):
    """Create audio clip from URL with start and end time"""
    temp_dir = tempfile.mkdtemp()
    output_path = os.path.join(temp_dir, f"clip.{format}")

    try:
        cmd = [
            FFMPEG_PATH,
            '-ss', str(start_sec),
            '-t', str(end_sec - start_sec),
            '-i', url,
            '-c:a', 'libmp3lame',
            '-q:a', '4',
            output_path
        ]

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(cmd, check=True, stderr=subprocess.PIPE))

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            if os.path.getsize(output_path) > MAX_FILE_SIZE:
                return None, "File too large"
            return output_path, temp_dir
        return None, "Failed to create file"
    except Exception as e:
        return None, str(e)


async def download_audio(url, title, format="mp3"):
    """Download audio from URL and convert to specified format"""
    temp_dir = tempfile.mkdtemp()
    output_path = os.path.join(temp_dir, f"download.{format}")

    try:
        cmd = [
            FFMPEG_PATH,
            '-i', url,
            '-c:a', 'libmp3lame',
            '-q:a', '4',
            output_path
        ]

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(cmd, check=True, stderr=subprocess.PIPE))

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            if os.path.getsize(output_path) > MAX_FILE_SIZE:
                return None, "File too large"
            return output_path, temp_dir
        return None, "Failed to create file"
    except Exception as e:
        return None, str(e)


def cleanup_temp_dir(temp_dir):
    """Clean up temporary directory"""
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except:
        pass
