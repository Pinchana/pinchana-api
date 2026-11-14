"""Encrypt optional operator-supplied cookies for one allocated worker."""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAX_COOKIE_BYTES = 256 * 1024


def configured_path() -> Path | None:
    value = os.getenv("DLP_HOST_COOKIES_FILE", "").strip()
    return Path(value) if value else None


def host_cookies_available() -> bool:
    path = configured_path()
    return path is not None and path.is_file()


def host_cookie_envelope(job_id: str, record: dict) -> dict | None:
    path = configured_path()
    if path is None or not path.is_file():
        return None
    with path.open("rb") as handle:
        data = bytearray(handle.read(MAX_COOKIE_BYTES + 1))
    try:
        if not data or len(data) > MAX_COOKIE_BYTES:
            raise ValueError("invalid host cookies")
        text = data.decode("utf-8")
        rows = [line for line in text.splitlines()
                if line.strip() and (not line.startswith("#") or line.startswith("#HttpOnly_"))]
        if not rows or "\0" in text:
            raise ValueError("invalid host cookies")
        for line in rows:
            fields = line.split("\t")
            if len(fields) != 7 or fields[1] not in {"TRUE", "FALSE"} or fields[3] not in {"TRUE", "FALSE"}:
                raise ValueError("invalid host cookies")
            int(fields[4])
        private = x25519.X25519PrivateKey.generate()
        public = x25519.X25519PublicKey.from_public_bytes(base64.b64decode(record["workerPubKey"], validate=True))
        key_id = record["keyId"]
        salt, iv = os.urandom(32), os.urandom(12)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                   info=f"pinchana-dlp/cookies/v2/{job_id}/{key_id}".encode()).derive(private.exchange(public))
        encode = lambda value: base64.b64encode(value).decode("ascii")
        return {"version": 2, "keyId": key_id,
                "clientPubKey": encode(private.public_key().public_bytes_raw()),
                "salt": encode(salt), "iv": encode(iv),
                "ciphertext": encode(AESGCM(key).encrypt(iv, bytes(data), f"pinchana-dlp:v2:{job_id}:{key_id}".encode()))}
    finally:
        data[:] = b"\0" * len(data)
