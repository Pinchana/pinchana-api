# YouTube groups

The gateway bundles this module for group delivery through
`POST /v1/bot/ytgroups`, which requires a configured Telegram client API key.
It accepts regular YouTube video links. Anonymous metadata must identify a
public or unlisted, completed full-format video before the download can use the
same operator cookie file as Shorts. The module uses its own transient media
scope for each upload.

The downloader chooses compact H.264/AAC streams up to 1080p and 30 fps.
1080p is selected when its estimated size meets the 15 MB/minute target.
Otherwise it starts at 720p and lowers resolution as needed. It remuxes the
selected streams to a streamable MP4 and enforces a 2,000,000,000-byte limit.
