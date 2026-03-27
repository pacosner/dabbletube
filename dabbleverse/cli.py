from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from urllib.parse import urlparse
from typing import Any

from yt_dlp import YoutubeDL

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
DEFAULT_CHANNELS_FILE = Path("channels.txt")


@dataclass(slots=True)
class VideoRecord:
    channel_input: str
    channel_title: str
    title: str
    video_id: str
    webpage_url: str
    upload_date: str | None
    published_at: str | None
    local_path: str | None
    extractor: str | None


@dataclass(slots=True)
class AddedVideoRecord:
    added_at: str
    playlist_id: str
    playlist_url: str
    title: str
    video_id: str
    webpage_url: str
    channel_title: str
    channel_input: str
    upload_date: str | None


def log(message: str) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{timestamp}] {message}", flush=True)


class YtDlpLogger:
    def debug(self, message: str) -> None:
        normalized = (message or "").strip()
        if not normalized:
            return
        if normalized.startswith("[youtube]") or normalized.startswith("[download]") or normalized.startswith("[info]"):
            log(f"yt-dlp: {normalized}")

    def warning(self, message: str) -> None:
        normalized = (message or "").strip()
        if normalized:
            log(f"yt-dlp warning: {normalized}")

    def error(self, message: str) -> None:
        normalized = (message or "").strip()
        if normalized:
            log(f"yt-dlp error: {normalized}")


def start_progress_watch(label: str, interval_seconds: float = 15.0) -> tuple[Event, Thread]:
    stop_event = Event()

    def watch() -> None:
        started_at = perf_counter()
        while not stop_event.wait(interval_seconds):
            log(f"Still working on {label}... {perf_counter() - started_at:.1f}s elapsed")

    thread = Thread(target=watch, daemon=True)
    thread.start()
    return stop_event, thread


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect videos from multiple YouTube channels and build a local or YouTube playlist."
    )
    parser.add_argument(
        "--channel",
        action="append",
        default=[],
        help="YouTube channel URL, @handle, or channel ID. May be used multiple times.",
    )
    parser.add_argument(
        "--channels-file",
        type=Path,
        help="Path to a text file containing one channel input per line. Defaults to ./channels.txt when present.",
    )
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=Path("library"),
        help="Directory for downloaded media.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for generated playlist and manifest.",
    )
    parser.add_argument(
        "--playlist-name",
        default="combined",
        help="Base name for generated local output files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of videos to process per channel. Defaults to all available videos.",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        help="Optional random seed to enable reproducible playlist shuffling.",
    )
    parser.add_argument(
        "--request-sleep",
        type=float,
        default=1.5,
        help="Seconds to sleep between YouTube requests to reduce rate limiting. Defaults to 1.5.",
    )
    parser.add_argument(
        "--socket-timeout",
        type=float,
        default=30.0,
        help="Network socket timeout in seconds for yt-dlp requests. Defaults to 30.",
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        help="Path to a Netscape-format cookies file to pass through to yt-dlp.",
    )
    parser.add_argument(
        "--cookies-from-browser",
        help="Browser name to import cookies from for yt-dlp, for example chrome, firefox, safari, or edge.",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio only instead of the best video+audio format.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect metadata and create output files without downloading media or changing YouTube.",
    )
    parser.add_argument(
        "--archive-file",
        type=Path,
        help="yt-dlp download archive file to avoid repeat downloads across runs.",
    )
    parser.add_argument(
        "--download-media",
        action="store_true",
        help="Download local media files. By default, YouTube playlist mode only collects metadata.",
    )
    parser.add_argument(
        "--youtube-create-playlist",
        action="store_true",
        help="Create a real YouTube playlist from the collected video IDs.",
    )
    parser.add_argument(
        "--youtube-playlist-id",
        help="Existing YouTube playlist ID to update instead of creating a new playlist.",
    )
    parser.add_argument(
        "--youtube-replace-existing",
        action="store_true",
        help="When used with --youtube-playlist-id, remove current playlist items before adding new ones.",
    )
    parser.add_argument(
        "--youtube-prune-older-than-days",
        type=float,
        help="When used with --youtube-playlist-id, remove playlist items added more than N days ago before syncing.",
    )
    parser.add_argument(
        "--youtube-client-secrets",
        type=Path,
        help="Path to the Google OAuth client secrets JSON for a desktop app.",
    )
    parser.add_argument(
        "--youtube-token-file",
        type=Path,
        default=Path(".secrets/youtube-token.json"),
        help="Path where the OAuth access/refresh token should be cached.",
    )
    parser.add_argument(
        "--youtube-playlist-title",
        help="Title for the YouTube playlist. Defaults to --playlist-name.",
    )
    parser.add_argument(
        "--youtube-playlist-description",
        default="Created with dabbleverse.",
        help="Description for the YouTube playlist.",
    )
    parser.add_argument(
        "--youtube-privacy-status",
        choices=["private", "unlisted", "public"],
        default="private",
        help="Privacy setting for the created YouTube playlist.",
    )
    return parser.parse_args()


def load_channels(args: argparse.Namespace) -> list[str]:
    channels = list(args.channel)
    channels_file = args.channels_file
    if not channels and channels_file is None and DEFAULT_CHANNELS_FILE.exists():
        channels_file = DEFAULT_CHANNELS_FILE
        print(f"Using channels from {channels_file}...", flush=True)

    if channels_file:
        file_lines = channels_file.read_text(encoding="utf-8").splitlines()
        channels.extend(line.strip() for line in file_lines if line.strip() and not line.strip().startswith("#"))

    normalized = [normalize_channel_input(value) for value in channels]
    deduped: list[str] = []
    seen = set()
    for value in normalized:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    if not deduped:
        raise SystemExit("No channels provided. Use --channel, --channels-file, or create ./channels.txt.")
    return deduped


def normalize_channel_input(value: str) -> str:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return normalize_channel_url(value)
    if value.startswith("@"):
        return f"https://www.youtube.com/{value}/videos"
    if value.startswith("UC") and len(value) >= 20:
        return f"https://www.youtube.com/channel/{value}/videos"
    return value


def normalize_channel_url(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if not host.endswith("youtube.com"):
        return value

    path = parsed.path.rstrip("/")
    if not path:
        return value

    channel_roots = ("/channel/", "/c/", "/user/", "/@")
    terminal_tabs = ("/videos", "/streams", "/shorts", "/featured", "/playlists", "/live")

    if path.endswith(terminal_tabs):
        return value
    if path.startswith(channel_roots):
        return f"{value.rstrip('/')}/videos"
    return value


def should_download_media(args: argparse.Namespace) -> bool:
    if args.dry_run:
        return False
    return args.download_media


def make_ydl_opts(args: argparse.Namespace, library_dir: Path, download_media: bool) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extract_flat": False,
        "outtmpl": str(library_dir / "%(uploader)s" / "%(upload_date>%Y-%m-%d)s - %(title)s [%(id)s].%(ext)s"),
        "restrictfilenames": False,
        "windowsfilenames": False,
        "sleep_interval_requests": args.request_sleep,
        "socket_timeout": args.socket_timeout,
        "logger": YtDlpLogger(),
    }
    if args.limit and args.limit > 0:
        opts["playlistend"] = args.limit
    if args.cookies:
        opts["cookiefile"] = str(args.cookies)
    if args.cookies_from_browser:
        opts["cookiesfrombrowser"] = (args.cookies_from_browser,)
    if download_media:
        opts["format"] = "bestaudio/best" if args.audio_only else "bv*+ba/b"
    if args.audio_only and download_media:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    if args.archive_file:
        opts["download_archive"] = str(args.archive_file)
    if not download_media:
        opts["skip_download"] = True
        opts["simulate"] = True
        opts["ignore_no_formats_error"] = True
    return opts


def collect_channel_records(channel_input: str, ydl: YoutubeDL, download_media: bool) -> list[VideoRecord]:
    started_at = perf_counter()
    stop_event, watch_thread = start_progress_watch(f"channel extraction for {channel_input}")
    try:
        info = ydl.extract_info(channel_input, download=download_media)
    finally:
        stop_event.set()
        watch_thread.join(timeout=0.1)
    if not info:
        log(f"Finished {channel_input}: no videos returned in {perf_counter() - started_at:.1f}s")
        return []

    entries = info.get("entries") or [info]
    records: list[VideoRecord] = []
    for entry in entries:
        if not entry:
            continue

        requested_downloads = entry.get("requested_downloads") or []
        local_path = None
        if requested_downloads:
            local_path = requested_downloads[0].get("filepath")
        elif entry.get("_filename"):
            local_path = entry["_filename"]

        video_id = entry.get("id") or ""
        webpage_url = entry.get("webpage_url") or entry.get("original_url") or ""
        if not webpage_url and video_id:
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"

        records.append(
            VideoRecord(
                channel_input=channel_input,
                channel_title=entry.get("channel") or entry.get("uploader") or info.get("title") or channel_input,
                title=entry.get("title") or video_id or "Untitled",
                video_id=video_id,
                webpage_url=webpage_url,
                upload_date=entry.get("upload_date"),
                published_at=coerce_iso_datetime(entry),
                local_path=local_path,
                extractor=entry.get("extractor_key") or entry.get("extractor"),
            )
        )
    channel_title = info.get("title") or channel_input
    log(
        f"Finished {channel_title}: collected {len(records)} records in {perf_counter() - started_at:.1f}s"
    )
    return records


def coerce_iso_datetime(entry: dict[str, Any]) -> str | None:
    timestamp = entry.get("timestamp")
    if timestamp:
        return datetime.fromtimestamp(timestamp).isoformat()
    upload_date = entry.get("upload_date")
    if upload_date and len(upload_date) == 8:
        return datetime.strptime(upload_date, "%Y%m%d").isoformat()
    return None


def sort_records(records: list[VideoRecord]) -> list[VideoRecord]:
    def sort_key(record: VideoRecord) -> tuple[int, str, str, str]:
        if record.published_at:
            return (0, record.published_at, record.channel_title.lower(), record.title.lower())
        if record.upload_date and record.upload_date.isdigit():
            return (1, record.upload_date, record.channel_title.lower(), record.title.lower())
        return (2, "", record.channel_title.lower(), record.title.lower())

    return sorted(records, key=sort_key, reverse=True)


def sort_records_by_upload_date(records: list[VideoRecord]) -> list[VideoRecord]:
    def sort_key(record: VideoRecord) -> tuple[int, int, str]:
        primary = int(record.upload_date) if record.upload_date and record.upload_date.isdigit() else 0
        missing = 1 if primary == 0 else 0
        return (missing, -primary, record.title.lower())

    return sorted(records, key=sort_key)


def dedupe_records(records: list[VideoRecord]) -> list[VideoRecord]:
    deduped: list[VideoRecord] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for record in records:
        marker = record.video_id or record.webpage_url
        if not marker:
            continue
        if record.video_id and record.video_id in seen_ids:
            continue
        if not record.video_id and record.webpage_url in seen_urls:
            continue
        if record.video_id:
            seen_ids.add(record.video_id)
        if record.webpage_url:
            seen_urls.add(record.webpage_url)
        deduped.append(record)
    return deduped


def shuffle_records(records: list[VideoRecord], seed: int | None) -> list[VideoRecord]:
    if seed is None:
        return list(records)
    shuffled = list(records)
    rng = random.Random(seed)
    rng.shuffle(shuffled)
    return shuffled


def limit_records(records: list[VideoRecord], limit: int | None) -> list[VideoRecord]:
    if not limit or limit <= 0:
        return records
    return records[:limit]


def is_valid_video_id(video_id: str) -> bool:
    return bool(VIDEO_ID_PATTERN.fullmatch(video_id))


def write_manifest(manifest_path: Path, records: list[VideoRecord], extras: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "video_count": len(records),
        "videos": [asdict(record) for record in records],
    }
    if extras:
        payload.update(extras)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_playlist(playlist_path: Path, records: list[VideoRecord], use_web_urls: bool) -> None:
    lines = ["#EXTM3U"]
    for record in records:
        target = record.webpage_url if use_web_urls else (record.local_path or record.webpage_url)
        if not target:
            continue
        lines.append(f"#EXTINF:-1,{record.channel_title} - {record.title}")
        lines.append(target)
    playlist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_sync_log(log_path: Path, entries: list[AddedVideoRecord]) -> None:
    if not entries:
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(asdict(entry)) + "\n")


def build_youtube_client(client_secrets_path: Path, token_path: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Missing Google API dependencies. Reinstall with `pip install -e .` to add YouTube support."
        ) from exc

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing cached YouTube OAuth token...", flush=True)
        creds.refresh(Request())

    if not creds or not creds.valid:
        print("Starting Google sign-in flow in your browser...", flush=True)
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), YOUTUBE_SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        print(f"Saved YouTube OAuth token to {token_path}", flush=True)

    return build("youtube", "v3", credentials=creds)


def require_youtube_args(args: argparse.Namespace) -> None:
    youtube_write_requested = args.youtube_create_playlist or args.youtube_playlist_id
    if youtube_write_requested and not args.youtube_client_secrets:
        raise SystemExit("--youtube-client-secrets is required for YouTube playlist updates.")
    if args.youtube_replace_existing and not args.youtube_playlist_id:
        raise SystemExit("--youtube-replace-existing requires --youtube-playlist-id.")
    if args.youtube_prune_older_than_days and not args.youtube_playlist_id:
        raise SystemExit("--youtube-prune-older-than-days requires --youtube-playlist-id.")


def clear_existing_playlist(youtube: Any, playlist_id: str) -> int:
    removed = 0
    next_page_token: str | None = None
    page = 0

    while True:
        page += 1
        log(f"Loading playlist page {page} to clear existing items...")
        response = (
            youtube.playlistItems()
            .list(
                part="id",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token,
            )
            .execute()
        )

        items = response.get("items", [])
        log(f"Clearing {len(items)} items from playlist page {page}...")
        for item in items:
            playlist_item_id = item.get("id")
            if not playlist_item_id:
                continue
            youtube.playlistItems().delete(id=playlist_item_id).execute()
            removed += 1
            if removed % 25 == 0:
                log(f"Removed {removed} existing playlist items so far...")

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return removed


def parse_api_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_existing_playlist_video_ids(youtube: Any, playlist_id: str) -> set[str]:
    existing_video_ids: set[str] = set()
    next_page_token: str | None = None
    page = 0

    while True:
        page += 1
        log(f"Loading existing playlist items page {page}...")
        response = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token,
            )
            .execute()
        )

        items = response.get("items", [])
        for item in items:
            resource_id = item.get("snippet", {}).get("resourceId", {})
            video_id = resource_id.get("videoId")
            if video_id:
                existing_video_ids.add(video_id)
        log(f"Loaded {len(existing_video_ids)} existing playlist videos so far...")

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return existing_video_ids


def prune_existing_playlist_items(youtube: Any, playlist_id: str, prune_older_than_days: float) -> tuple[int, set[str]]:
    cutoff = datetime.now().astimezone().timestamp() - (prune_older_than_days * 86400)
    remaining_video_ids: set[str] = set()
    removed = 0
    next_page_token: str | None = None
    page = 0

    while True:
        page += 1
        log(f"Loading existing playlist items page {page} for prune check...")
        response = (
            youtube.playlistItems()
            .list(
                part="id,snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token,
            )
            .execute()
        )

        items = response.get("items", [])
        for item in items:
            snippet = item.get("snippet", {})
            playlist_item_id = item.get("id")
            video_id = snippet.get("resourceId", {}).get("videoId")
            added_at = parse_api_datetime(snippet.get("publishedAt"))
            should_prune = bool(playlist_item_id and added_at and added_at.timestamp() < cutoff)
            if should_prune:
                youtube.playlistItems().delete(id=playlist_item_id).execute()
                removed += 1
                continue
            if video_id:
                remaining_video_ids.add(video_id)

        if removed and (removed % 25 == 0):
            log(f"Pruned {removed} existing playlist items so far...")

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return removed, remaining_video_ids


def create_youtube_playlist(args: argparse.Namespace, records: list[VideoRecord]) -> dict[str, Any]:
    require_youtube_args(args)
    from googleapiclient.errors import HttpError

    print("Connecting to the YouTube Data API...", flush=True)
    youtube = build_youtube_client(args.youtube_client_secrets, args.youtube_token_file)
    title = args.youtube_playlist_title or args.playlist_name

    created_new = False
    replaced_existing = False
    removed_item_count = 0
    pruned_item_count = 0
    existing_video_ids: set[str] = set()
    if args.youtube_playlist_id:
        playlist_id = args.youtube_playlist_id
        print(f"Using existing YouTube playlist {playlist_id}", flush=True)
        if args.youtube_replace_existing:
            print(f"Clearing existing items from playlist {playlist_id}...", flush=True)
            removed_item_count = clear_existing_playlist(youtube, playlist_id)
            replaced_existing = True
            print(f"Removed {removed_item_count} existing playlist items.", flush=True)
        else:
            if args.youtube_prune_older_than_days and args.youtube_prune_older_than_days > 0:
                print(
                    f"Pruning playlist items older than {args.youtube_prune_older_than_days:g} days from {playlist_id}...",
                    flush=True,
                )
                pruned_item_count, existing_video_ids = prune_existing_playlist_items(
                    youtube, playlist_id, args.youtube_prune_older_than_days
                )
                print(
                    f"Pruned {pruned_item_count} playlist items older than "
                    f"{args.youtube_prune_older_than_days:g} days.",
                    flush=True,
                )
            else:
                print(f"Loading existing items from playlist {playlist_id}...", flush=True)
                existing_video_ids = get_existing_playlist_video_ids(youtube, playlist_id)
            print(f"Found {len(existing_video_ids)} existing videos. Only new videos will be added.", flush=True)
    else:
        print(f"Creating YouTube playlist '{title}'...", flush=True)
        playlist_response = (
            youtube.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title,
                        "description": args.youtube_playlist_description,
                    },
                    "status": {"privacyStatus": args.youtube_privacy_status},
                },
            )
            .execute()
        )
        playlist_id = playlist_response["id"]
        created_new = True
        print(f"Created playlist with ID {playlist_id}", flush=True)

    added_video_ids: list[str] = []
    added_videos_log: list[AddedVideoRecord] = []
    skipped_videos: list[dict[str, str]] = []
    already_present_video_ids: list[str] = []
    records_with_ids = [record for record in records if record.video_id]
    if args.youtube_create_playlist or args.youtube_replace_existing:
        records_to_add = list(reversed(sort_records_by_upload_date(records_with_ids)))
        log("Using upload-date order for full playlist creation/rebuild, oldest first so newest ends up first.")
    else:
        records_to_add = list(reversed(records_with_ids))
        log("Using added-order upload for incremental sync, oldest first so newest ends up first.")
    total = len(records_to_add)
    log(f"Preparing to add {total} videos with valid IDs to YouTube playlist...")
    for index, record in enumerate(records_to_add, start=1):
        if not is_valid_video_id(record.video_id):
            print(f"Skipping invalid video ID for: {record.title}", flush=True)
            skipped_videos.append(
                {"title": record.title, "video_id": record.video_id, "reason": "invalid_video_id"}
            )
            continue
        if record.video_id in existing_video_ids:
            already_present_video_ids.append(record.video_id)
            continue
        print(f"Adding video {index}/{total}: {record.title}", flush=True)
        try:
            (
                youtube.playlistItems()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "position": 0,
                            "resourceId": {"kind": "youtube#video", "videoId": record.video_id},
                        }
                    },
                )
                .execute()
            )
        except HttpError as exc:
            print(f"Skipping unaddable video {record.video_id}: {exc}", flush=True)
            skipped_videos.append(
                {"title": record.title, "video_id": record.video_id, "reason": "youtube_insert_failed"}
            )
            continue
        added_video_ids.append(record.video_id)
        added_videos_log.append(
            AddedVideoRecord(
                added_at=datetime.now().astimezone().isoformat(),
                playlist_id=playlist_id,
                playlist_url=f"https://www.youtube.com/playlist?list={playlist_id}",
                title=record.title,
                video_id=record.video_id,
                webpage_url=record.webpage_url,
                channel_title=record.channel_title,
                channel_input=record.channel_input,
                upload_date=record.upload_date,
            )
        )
        if index % 25 == 0 or index == total:
            log(f"YouTube playlist progress: processed {index}/{total}, added {len(added_video_ids)}")

    return {
        "youtube_playlist_id": playlist_id,
        "youtube_playlist_url": f"https://www.youtube.com/playlist?list={playlist_id}",
        "youtube_playlist_title": title,
        "youtube_created_new_playlist": created_new,
        "youtube_replaced_existing_playlist": replaced_existing,
        "youtube_removed_existing_item_count": removed_item_count,
        "youtube_pruned_item_count": pruned_item_count,
        "youtube_already_present_video_count": len(already_present_video_ids),
        "youtube_already_present_video_ids": already_present_video_ids,
        "youtube_video_count": len(added_video_ids),
        "youtube_video_ids": added_video_ids,
        "youtube_added_videos_log": [asdict(entry) for entry in added_videos_log],
        "youtube_skipped_videos": skipped_videos,
    }


def main() -> int:
    run_started_at = perf_counter()
    args = parse_args()
    channels = load_channels(args)
    download_media = should_download_media(args)

    log(
        f"Starting dabbleverse with {len(channels)} channels, "
        f"download_media={'yes' if download_media else 'no'}, "
        f"youtube_sync={'yes' if bool(args.youtube_create_playlist or args.youtube_playlist_id) else 'no'}"
    )
    if args.limit:
        log(f"Per-channel extraction limit is set to {args.limit}.")
    if args.cookies_from_browser:
        log(f"Using browser cookies from {args.cookies_from_browser}.")
    elif args.cookies:
        log(f"Using cookies file {args.cookies}.")
    log(f"yt-dlp socket timeout is {args.socket_timeout:.1f}s.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if download_media:
        args.library_dir.mkdir(parents=True, exist_ok=True)
    if args.archive_file:
        args.archive_file.parent.mkdir(parents=True, exist_ok=True)
    if args.youtube_create_playlist or args.youtube_playlist_id:
        args.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)

    ydl_opts = make_ydl_opts(args, args.library_dir, download_media)
    all_records: list[VideoRecord] = []
    with YoutubeDL(ydl_opts) as ydl:
        for index, channel in enumerate(channels, start=1):
            log(f"Collecting channel {index}/{len(channels)}: {channel}")
            all_records.extend(collect_channel_records(channel, ydl, download_media))

    log(f"Collected {len(all_records)} raw records across all channels.")
    deduped_records = dedupe_records(all_records)
    log(f"Kept {len(deduped_records)} unique records after dedupe.")
    records = sort_records(deduped_records)
    records = shuffle_records(records, args.shuffle_seed)
    if args.shuffle_seed is not None:
        log(f"Shuffled {len(records)} records with seed {args.shuffle_seed}.")
    log(f"Collected {len(records)} final videos for output.")
    manifest_path = args.output_dir / f"{args.playlist_name}.manifest.json"
    playlist_path = args.output_dir / f"{args.playlist_name}.m3u"

    youtube_result: dict[str, Any] | None = None
    if (args.youtube_create_playlist or args.youtube_playlist_id) and not args.dry_run:
        youtube_result = create_youtube_playlist(args, records)

    write_manifest(manifest_path, records, youtube_result)
    log(f"Wrote manifest to {manifest_path}")
    write_playlist(playlist_path, records, use_web_urls=not download_media)
    log(f"Wrote playlist to {playlist_path}")
    sync_log_path = args.output_dir / f"{args.playlist_name}.sync-log.jsonl"
    if youtube_result and args.youtube_playlist_id and not args.youtube_replace_existing:
        added_entries = [AddedVideoRecord(**entry) for entry in youtube_result.get("youtube_added_videos_log", [])]
        append_sync_log(sync_log_path, added_entries)
        log(f"Appended {len(added_entries)} entries to sync log {sync_log_path}")

    print(f"Processed {len(records)} videos from {len(channels)} channels.")
    print(f"Manifest: {manifest_path}")
    print(f"Playlist: {playlist_path}")
    if youtube_result:
        print(f"YouTube playlist: {youtube_result['youtube_playlist_url']}")
        print(f"Added {youtube_result['youtube_video_count']} new videos.", flush=True)
        if args.youtube_playlist_id and not args.youtube_replace_existing:
            print(f"Sync log: {sync_log_path}", flush=True)
        if youtube_result["youtube_already_present_video_count"]:
            print(
                f"Skipped {youtube_result['youtube_already_present_video_count']} videos already in the playlist.",
                flush=True,
            )
    elif (args.youtube_create_playlist or args.youtube_playlist_id) and args.dry_run:
        print("Dry run enabled: skipped YouTube playlist creation.")
    log(f"Run completed in {perf_counter() - run_started_at:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
