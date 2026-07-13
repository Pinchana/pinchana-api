import { readFile } from "node:fs/promises";
import { sign } from "node:crypto";

const [privateKeyPath, rawOrigin, turnstileSiteKey, validityDays = "90"] = process.argv.slice(2);
if (!privateKeyPath || !rawOrigin || !turnstileSiteKey) {
  console.error("Usage: node scripts/sign-instance-certificate.mjs <private-key.pem> <https-origin> <turnstile-site-key> [validity-days]");
  process.exit(1);
}

const originUrl = new URL(rawOrigin);
if (originUrl.protocol !== "https:" || originUrl.pathname !== "/" || originUrl.search || originUrl.hash || originUrl.username || originUrl.password) {
  throw new Error("The instance must be an HTTPS origin without a path, query, credentials, or fragment.");
}
const days = Number(validityDays);
if (!Number.isFinite(days) || days <= 0 || days > 366) throw new Error("Validity must be between 1 and 366 days.");

const issuedAt = Math.floor(Date.now() / 1000);
const claims = {
  issuer: "pinchana-project",
  protocol: 1,
  origin: originUrl.origin,
  turnstile_site_key: turnstileSiteKey,
  issued_at: issuedAt,
  expires_at: issuedAt + Math.floor(days * 86400),
};
const payloadBytes = Buffer.from(JSON.stringify(claims));
const privateKey = await readFile(privateKeyPath, "utf8");
const signature = sign(null, payloadBytes, privateKey);
process.stdout.write(`${JSON.stringify({ payload: payloadBytes.toString("base64url"), signature: signature.toString("base64url") })}\n`);
