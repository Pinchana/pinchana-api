# Pinchana instance certificates

The official Pinchana web client accepts a custom API origin only when that exact
origin has a valid, unexpired Ed25519 certificate issued by the Pinchana project.
Instance operators receive the certificate envelope, never the private signing
key. The web deployment pins only the public key.

The certificate binds these claims:

- issuer and protocol version;
- the exact HTTPS API origin;
- that origin's Cloudflare Turnstile site key;
- issue and expiry timestamps.

## Issuing a certificate

Keep the Ed25519 private key offline and outside this repository. A maintainer can
generate a key pair with OpenSSL:

```sh
openssl genpkey -algorithm Ed25519 -out pinchana-instance-private.pem
openssl pkey -in pinchana-instance-private.pem -pubout -out pinchana-instance-public.pem
```

Set the public PEM as `PINCHANA_INSTANCE_PUBLIC_KEY` on the official web client.
After reviewing an instance origin, issue a short-lived certificate:

```sh
node scripts/sign-instance-certificate.mjs \
  /secure/pinchana-instance-private.pem \
  https://api.example.com \
  0x4AAAAAAA-example-site-key \
  90
```

Give the resulting one-line JSON to the instance operator. They configure it as
`PINCHANA_INSTANCE_CERTIFICATE` or mount it and set
`PINCHANA_INSTANCE_CERTIFICATE_FILE`. The API exposes the public envelope at
`GET /web/identity`.

The Turnstile argument is the public **site key** for the Web hostname that will
use this API. It is not the private Siteverify secret. The API origin must match
the final public HTTPS origin exactly and must not include a trailing path.

## Installing with Docker Compose

The private signing key never belongs on the API host. Copy only the one-line
JSON envelope into the API repository's `.env`, quoting the whole value so the
Compose dotenv parser preserves it:

```ini
PINCHANA_INSTANCE_CERTIFICATE='{"payload":"BASE64URL_CLAIMS","signature":"BASE64URL_SIGNATURE"}'
PINCHANA_INSTANCE_CERTIFICATE_FILE=
```

The same API deployment must have the matching Turnstile server settings. The
site key is embedded in the certificate; the secret stays only in the API:

```ini
TURNSTILE_SECRET_KEY=REPLACE_WITH_PRIVATE_TURNSTILE_SECRET
TURNSTILE_EXPECTED_HOSTNAME=pinchana.example.com
TURNSTILE_EXPECTED_ACTION=turnstile-spin-v1
TURNSTILE_SESSION_SECRET=REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS
```

Recreate the server so it receives the changed environment, then check the
public identity endpoint through the final HTTPS origin:

```sh
docker compose up -d --force-recreate server
curl --fail --silent https://api.example.com/web/identity
```

The response must be the same `payload` and `signature` envelope. A `503`
response means neither certificate source reached the server container. Use
`docker compose exec server printenv PINCHANA_INSTANCE_CERTIFICATE` only during
private troubleshooting because it prints the certificate value.

For file-based configuration, mount the certificate read-only and use its
container path, not its host path:

```yaml
services:
  server:
    volumes:
      - ./secrets/instance-certificate.json:/run/secrets/pinchana-instance-certificate.json:ro
    environment:
      PINCHANA_INSTANCE_CERTIFICATE_FILE: /run/secrets/pinchana-instance-certificate.json
```

Leave `PINCHANA_INSTANCE_CERTIFICATE` empty when using the file. The inline
value takes precedence if both are configured.

## Renewal

Issue a new envelope before `expires_at`, replace the inline value or mounted
file, and recreate `server`. The signing tool accepts a validity of 1 through
366 days. Existing Web cookies cannot outlive the certificate; users must select
the instance again after an expired certificate is replaced.

## Security boundary

This proves that the Pinchana project authorized a specific origin and Turnstile
configuration. It blocks arbitrary endpoints and copied certificates used on a
different origin. It does **not** prove that a third-party host continues to run
an unmodified binary after issuance. That stronger guarantee requires measured
boot and hardware-backed remote attestation. Keep certificates short-lived and
revoke trust by refusing renewal if an operator becomes untrusted.
