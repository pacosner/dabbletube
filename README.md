# Dabbleverse

`dabbleverse` collects videos from multiple YouTube channels and, by default, creates a shuffled playlist from metadata without downloading media files.

## What it does

- accepts one or more YouTube channel URLs, `@handle` values, or channel IDs
- collects all available videos by default unless you set `--limit`
- prefers newest uploads first when deciding which videos to include
- creates a YouTube playlist from the collected video IDs
- shuffles the final playlist order before writing it
- optionally downloads channel videos with `yt-dlp` when you pass `--download-media`
- stores a JSON manifest with metadata about downloaded files
- creates a merged playlist sorted by upload date

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip3 install -e .
dabbleverse \
  --channel https://www.youtube.com/@OpenAI \
  --dry-run
```

This writes output to:

- `output/combined.m3u` for the merged playlist
- `output/combined.manifest.json` for metadata about downloaded videos

By default, no videos are downloaded. If you want local downloads too, add `--download-media`.

## Create a real YouTube playlist

1. In Google Cloud, create a project and enable the YouTube Data API v3.
2. Create an OAuth client ID for a Desktop app.
3. Download the client secrets JSON file.
4. Run:

```bash
dabbleverse \
  --channel https://www.youtube.com/@OpenAI \
  --channel https://www.youtube.com/@veritasium \
  --youtube-create-playlist \
  --youtube-client-secrets client_secret.json \
  --youtube-playlist-title "My Combined Feed" \
  --youtube-privacy-status private
```

The first run opens a browser for Google sign-in and stores the token in `.secrets/youtube-token.json`.

Output files:

- `output/combined.m3u` contains YouTube watch URLs by default
- `output/combined.manifest.json` includes the created YouTube playlist ID and URL

Channel inputs are normalized to the channel `videos` tab when possible so the tool prefers normal uploads over channel landing-page or live placeholders.

## Download local media too

```bash
dabbleverse \
  --channel https://www.youtube.com/@OpenAI \
  --channel https://www.youtube.com/@veritasium \
  --youtube-create-playlist \
  --youtube-client-secrets client_secret.json \
  --download-media
```

## Channel inputs

Each `--channel` value can be one of:

- a full YouTube channel URL
- a YouTube `@handle`
- a YouTube channel ID like `UCxxxxxxxxxxxxxxxxxxxxxx`

You can also load channels from a text file:

```bash
dabbleverse --channels-file channels.txt
```

If `channels.txt` exists in the project root and you do not pass any `--channel` values, it will be picked up automatically.

Example `channels.txt`:

```text
https://www.youtube.com/@OpenAI
@veritasium
UCsooa4yRKGN_zEE8iknghZA
```

Then you can run:

```bash
dabbleverse \
  --youtube-create-playlist \
  --youtube-client-secrets secret.json \
  --youtube-playlist-title "Combined Feed"
```

## Replace an existing YouTube playlist

Use the playlist ID from a URL like `https://www.youtube.com/playlist?list=PL...`.

```bash
dabbleverse \
  --youtube-playlist-id PLXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX \
  --youtube-replace-existing \
  --youtube-client-secrets secret.json
```

That clears the playlist first, then adds the newly collected videos.

## Sync new videos into an existing playlist

If you pass `--youtube-playlist-id` without `--youtube-replace-existing`, the playlist is treated like a continuously updated feed.

```bash
dabbleverse \
  --youtube-playlist-id PLXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX \
  --youtube-client-secrets secret.json
```

That mode:

- loads the videos already in the playlist
- collects videos from `channels.txt`
- only adds videos that are not already present
- leaves the existing playlist items in place
- appends each newly added video to `output/combined.sync-log.jsonl`

## Useful options

```bash
dabbleverse --help
```

- `--limit 25` keeps the latest 25 collected videos before shuffling
- `--shuffle-seed 42` makes the shuffled order reproducible
- `--request-sleep 2` waits between YouTube requests to reduce rate limiting
- `--youtube-create-playlist` creates a real playlist on your YouTube account
- `--youtube-playlist-id PL...` targets an existing playlist instead of creating a new one
- `--youtube-replace-existing` clears an existing playlist before repopulating it
- `--youtube-client-secrets client_secret.json` points to your Google OAuth desktop client file
- `--youtube-playlist-title "My Combined Feed"` sets the playlist title on YouTube
- `--youtube-privacy-status private|unlisted|public` controls visibility
- `--download-media` downloads local files instead of metadata-only collection
- `--audio-only` downloads audio formats instead of full video
- `--dry-run` fetches metadata and writes the manifest without downloading media
- `--archive-file .cache/archive.txt` prevents re-downloading items across runs

## Notes

- This project relies on `yt-dlp`, which handles channel extraction and media downloads.
- YouTube playlist publishing uses OAuth and the YouTube Data API v3.
- Some extracted entries, especially live placeholders or unavailable videos, may be skipped if YouTube rejects them during playlist insertion.
- If YouTube rate-limits the current session, wait for the cooldown window and rerun with a higher `--request-sleep` value.
- Some YouTube channels or videos may be unavailable because of region, age, or login restrictions.
