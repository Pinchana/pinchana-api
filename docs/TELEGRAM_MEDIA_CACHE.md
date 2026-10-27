# Telegram media caching

The `pinchana-bot` can archive successfully delivered media in a private
Telegram channel and reuse their `file_id` values. Bot API clients requesting
`POST /v1/scrape` with `X-Pinchana-Delivery: telegram` receive a disposable
scraper namespace instead of reading from or writing to the persistent cache.

Only machine client names listed by `PINCHANA_TELEGRAM_CLIENTS` (default:
`bot`) may use this mode. The API generates the namespace itself. Other API
clients and web/mobile endpoints retain their previous persistent caching.

The scraper services write temporary files below
`CACHE_PATH/.transient/<scope>/`. The gateway returns URLs pointing into that
namespace and provides its identifier in the `X-Pinchana-Cache-Scope` response
header. The bot uses the normal authenticated media endpoints to upload to
Telegram, copies the sent message(s) into its private archive channel, stores
the file IDs and post metadata in SQLite, then calls:

```
DELETE /v1/bot/cache/<scope>
X-API-Key: <bot-machine-key>
```

The endpoint only deletes the matching temporary namespace. Missing scopes
also succeed (idempotent). Orphaned namespaces after crashes are automatically
removed after six hours by the API's background cleanup task.

The files may briefly exist on disk while the first Telegram upload is in
progress. This is a transient processing workspace, not a persistent media
cache; ordinary API clients remain unaffected.

Deploy `pinchana-core` and `pinchana-server` together with their new submodule
pins before enabling the bot's `TELEGRAM_CACHE_CHAT_ID`.
