"""YouTube Data API v3 - Resumable video upload."""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "28",  # Science & Technology
    privacy_status: str = "private",
    thumbnail_path: str | None = None,
) -> str:
    """Upload a video to YouTube and return the video ID.

    Uses OAuth2 with a refresh token for authentication.
    Performs a resumable upload via the YouTube Data API v3.
    """
    if not all([settings.youtube_client_id, settings.youtube_client_secret, settings.youtube_refresh_token]):
        raise RuntimeError("YouTube API credentials not fully configured")

    import asyncio

    # YouTube API client is synchronous, run in executor
    video_id = await asyncio.get_event_loop().run_in_executor(
        None, _upload_sync, video_path, title, description, tags or [], category_id, privacy_status,
        thumbnail_path,
    )
    return video_id


def _upload_sync(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str,
    privacy_status: str,
    thumbnail_path: str | None = None,
) -> str:
    """Synchronous YouTube upload using google-api-python-client."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = Credentials(
        token=None,
        refresh_token=settings.youtube_refresh_token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )

    youtube = build("youtube", "v3", credentials=credentials)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    logger.info("Uploaded to YouTube: https://youtu.be/%s", video_id)

    # Upload thumbnail if provided
    if thumbnail_path:
        try:
            import os
            if os.path.exists(thumbnail_path):
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=thumb_media,
                ).execute()
                logger.info("Thumbnail uploaded for video %s", video_id)
        except Exception as e:
            logger.warning("Thumbnail upload failed: %s", e)

    return video_id
