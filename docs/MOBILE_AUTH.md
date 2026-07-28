# Mobile installation authentication

Pinchana Mobile does not contain a machine API key. The gateway grants sessions
to an installation after a single-use challenge and, when required, platform
attestation.

## Runtime modes

- `disabled`: fail closed. This is the production Compose default.
- `guest`: issue explicitly lower-trust grants. Use only for development or a
  self-hosted instance that accepts anonymous clients.
- `attested`: require Apple App Attest or Google Play Integrity.
- `hybrid`: prefer platform attestation but allow a lower-trust guest grant on
  unsupported devices.

Attested providers are not advertised unless both `MOBILE_ATTESTATION_URL` and
`MOBILE_ATTESTATION_TOKEN` are configured. This prevents a client from
generating a platform attestation that the gateway cannot validate.

## Grant lifecycle

1. `POST /v1/mobile/challenges` with the installation ID, platform, and native
   application ID.
2. The client creates evidence over the canonical client data:

   ```text
   {challenge}.{app_id}.{installation_id}
   ```

3. `POST /v1/mobile/attest` consumes the challenge and returns:
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
are not interchangeable.

## Attestation verifier contract

The gateway sends the complete `/v1/mobile/attest` request to
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
