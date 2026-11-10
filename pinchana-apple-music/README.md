# Apple Music tracks

`POST /scrape` accepts an individual `https://music.apple.com/.../song/.../ID`
link or an album link with exactly one numeric `?i=TRACK_ID` selection.
Albums, playlists and artist pages are unsupported and rejected before lookup.

Set `SOCIALCRAWL_API_KEY` in the API deployment environment. The key is sent
only in the `x-api-key` header. Socialcrawl's `apple_music/track` endpoint
provides title and artist metadata; its preview audio is never downloaded.
The service searches YouTube Music for `artist title official audio`, using
the same song search and shared yt-dlp/MP3 pipeline as Spotify. Matches can
differ from the original Apple Music recording. Audio download does not require Spotify credentials. Artwork uses Socialcrawl
`content.thumbnail_url` when available; otherwise optional `SPOTIFY_CLIENT_ID`
and `SPOTIFY_CLIENT_SECRET` enable a Spotify search matching title, artist and
duration. Spotify outages or missing artwork never block the audio download.
Covers are embedded in the MP3 and served as the audio thumbnail.

Socialcrawl costs 1 credit per uncached successful lookup. Contract and pricing
were verified using the free utility guide and `dry_run=1`; production does
one metadata lookup per uncached track. Each lookup has a UUID idempotency key,
preserved across up to three retries and a 60-second timeout per attempt.
Only explicitly retryable API errors and timeouts are retried. Withdrawn
endpoints (`SERVICE_UNAVAILABLE` without `Retry-After`) are not retried.
Missing/empty tracks return 404. Download retries do not repeat paid lookups.
Completed MP3s use the shared cache (`am-TRACK_ID`) with concurrent requests
deduplicated. Cache invalidation works through the gateway's cache admin API.

Run `uv run uvicorn pinchana_apple_music.main:app --port 8091` inside this directory,
or use the `apple_music` service in either Compose file.

Run the isolated tests with `uv run python -m unittest discover -s tests -v`.
