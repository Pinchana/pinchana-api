# Mobile installation authentication

Pinchana Mobile does not contain a machine API key. Authentication is optional
for mobile scrape, cached media, and capability requests. When a bearer token
is supplied, the gateway validates it and its route scope. Private DLP jobs
always require a session because the signed installation ID isolates each
client's jobs.

The gateway can grant sessions to an installation after a single-use challenge.
Platform attestation is optional and is not required for the current
distribution model. Set `MOBILE_AUTH_REQUIRED=true` only when every public
mobile request must carry a valid installation session.

## Runtime modes

- `disabled`: do not issue installation sessions. Public mobile routes remain
  anonymous unless `MOBILE_AUTH_REQUIRED=true`, in which case they fail closed.
- `guest`: issue scoped, non-attested installation grants. This is the current
  production Compose default for sideloaded builds.
- `attested`: require Apple App Attest or Google Play Integrity.
- `hybrid`: prefer platform attestation but allow a lower-trust guest grant on
  unsupported devices.

Attested providers are not advertised unless both `MOBILE_ATTESTATION_URL` and
`MOBILE_ATTESTATION_TOKEN` are configured. This prevents a client from
generating a platform attestation that the gateway cannot validate.

## Production deployment

When installation grants are enabled, generate a random value for the mobile
session signer:

```sh
openssl rand -base64 48
```

Set these values in the production `.env`:

```dotenv
MOBILE_AUTH_MODE=guest
MOBILE_AUTH_REQUIRED=false
MOBILE_SESSION_SECRET=<generated value>
MOBILE_ATTESTATION_URL=
MOBILE_ATTESTATION_TOKEN=
MOBILE_ACCESS_TOKEN_MAX_AGE=900
MOBILE_REFRESH_TOKEN_MAX_AGE=2592000
MOBILE_CHALLENGE_TTL=120
MOBILE_CHALLENGE_RATE_WINDOW=600
MOBILE_CHALLENGE_RATE_LIMIT=10
MOBILE_TRUST_PROXY_HEADERS=false
MOBILE_GUEST_SCOPES=mobile:scrape,mobile:media,mobile:capabilities
```

Do not reuse `TURNSTILE_SESSION_SECRET`, a DLP secret, or a value from
`PINCHANA_API_KEYS`. The mobile app must never contain the session secret.

For an existing Compose deployment, pull and recreate only the gateway:

```sh
docker compose pull server
docker compose up -d --no-deps --force-recreate server
docker compose logs --tail=100 server
```

This mode proves control of an issued installation session, not that the app
came from an official store. Anonymous clients receive only the fixed scrape,
media, and capability permissions; `MOBILE_GUEST_SCOPES` applies to issued guest
tokens and does not make DLP anonymous. Keep token scopes narrow, retain the
challenge rate limit, and revoke abusive installations through the admin
endpoint. Optional store attestation can be enabled later without changing the
session contract.

When `MOBILE_AUTH_REQUIRED=false`, a missing or placeholder
`MOBILE_SESSION_SECRET` disables the installation grant endpoints without
preventing the gateway from starting; anonymous mobile routes remain available.
Strict mode keeps the startup check fail-closed.

## Grant lifecycle

1. `POST /v1/mobile/challenges` with the installation ID, platform, and native
   application ID.
2. When an attested provider is enabled, the client creates evidence over the
   canonical client data:

   ```text
   {challenge}.{app_id}.{installation_id}
   ```

3. `POST /v1/mobile/grants` consumes the challenge and returns:
   - a short-lived, scoped mobile access token;
   - an opaque rotating refresh token.
4. `POST /v1/mobile/session/refresh` rotates the refresh token. Reuse of any
   consumed token revokes its complete refresh family.
5. `DELETE /v1/mobile/session` revokes the refresh family on sign-out/reset.

Operators can revoke an installation and all of its refresh families with
`DELETE /admin/mobile/installations/{installation_id}` using an authorized
machine API key. Already-issued access tokens expire within the configured
short access-token lifetime.

Access tokens use `aud=pinchana-mobile`, `typ=mobile_access`, a stable
installation `sub`, and route-specific scopes. Web sessions and mobile sessions
are not interchangeable. `/v1/mobile/attest` remains a deprecated alias for
older clients.

## Optional attestation verifier contract

For attested providers, the gateway sends the complete mobile grant request to
`MOBILE_ATTESTATION_URL` with:

```http
Authorization: Bearer <MOBILE_ATTESTATION_TOKEN>
Content-Type: application/json
```

The verifier returns HTTP 200 with:

```json
{
  "valid": true,
  "platform": "ios",
  "app_id": "cc.pinchana.mobile"
}
```

For App Attest, `evidence` is a JSON string containing `keyId`,
`attestationObject`, and `clientDataHash`. The verifier must independently
recompute the client-data hash, validate the Apple certificate chain and nonce,
match the key ID and RP ID, validate the AAGUID/environment, and require an
initial counter of zero. It must not trust the client-provided hash.

For Play Integrity, `evidence` is the encrypted standard-integrity token. Decode
it through Google's server API, require package `cc.pinchana.mobile`, compare
the request hash to the base64url SHA-256 digest of the canonical client data,
and enforce the configured app-recognition, licensing, and device-integrity
verdicts.

The verifier token is an internal service credential and must never be placed in
the mobile app or an `EXPO_PUBLIC_` variable.

## Storage and operations

`MOBILE_SESSION_DB_PATH` defaults to
`$CACHE_PATH/mobile-sessions.sqlite3`. SQLite transactions make challenge
consumption and refresh rotation atomic. The file must live on the gateway's
persistent volume and must not be shared by multiple gateway containers over a
network filesystem. A multi-replica deployment should replace this store with a
transactional shared database before scaling the gateway horizontally.

Challenge requests are rate-limited by a keyed hash of the remote address.
Proxy forwarding headers are ignored unless `MOBILE_TRUST_PROXY_HEADERS=true`;
enable that only behind a proxy that overwrites client-supplied forwarding
headers.

Never log access tokens, refresh tokens, attestation evidence, cookies, or
authorization headers.
