// Bundle integrity: every member is fetched, length- and SHA-256-checked
// against the reference in the JSON that names it, and resolved relative to
// that JSON's own URL.  This detects a corrupted or mixed bundle; it is not
// an authenticity claim about who produced it.

export class BundleError extends Error {
  constructor(message, detail) { super(message); this.name = "BundleError"; this.detail = detail; }
}

export function resolveMember(ref, definingUrl) {
  if (!ref || typeof ref.href !== "string") throw new BundleError("a member reference has no href");
  if (/^[a-z][a-z0-9+.-]*:/i.test(ref.href) || ref.href.startsWith("/") || ref.href.startsWith("//")) {
    throw new BundleError(`member ${ref.href} is not a relative path`);
  }
  const url = new URL(ref.href, definingUrl);
  const base = new URL(".", definingUrl);
  if (url.origin !== base.origin) throw new BundleError(`member ${ref.href} leaves the bundle origin`);
  return url;
}

export async function sha256Hex(buffer) {
  if (!globalThis.crypto || !crypto.subtle) throw new BundleError("this browser context has no Web Crypto digest (serve over http://localhost or https)");
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function fetchVerified(ref, definingUrl, { signal, expectType } = {}) {
  const url = resolveMember(ref, definingUrl);
  if (expectType && ref.media_type !== expectType) throw new BundleError(`member ${ref.href} has media type ${ref.media_type}, expected ${expectType}`);
  let response;
  try {
    response = await fetch(url, { signal, cache: "no-cache" });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new BundleError(`could not fetch ${ref.href}: ${error.message}`);
  }
  if (!response.ok) throw new BundleError(`could not fetch ${ref.href}: HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength !== ref.bytes) throw new BundleError(`${ref.href} has ${buffer.byteLength} bytes; the manifest records ${ref.bytes}`);
  const digest = await sha256Hex(buffer);
  if (digest !== ref.sha256) throw new BundleError(`${ref.href} does not match its recorded SHA-256`);
  return { url, buffer };
}

export async function fetchVerifiedJson(ref, definingUrl, options = {}) {
  const { url, buffer } = await fetchVerified(ref, definingUrl, { ...options, expectType: "application/json" });
  let value;
  try { value = JSON.parse(new TextDecoder("utf-8").decode(buffer)); } catch (error) { throw new BundleError(`${ref.href} is not valid JSON`); }
  // The verified bytes travel with the parsed value, so a download is the
  // exact file that was checked.
  return { url, value, buffer };
}

export async function fetchVerifiedImage(ref, definingUrl, options = {}) {
  const type = options.expectType || "image/png";
  require(["image/png", "image/webp"].includes(type), "Unsupported verified image type");
  const { url, buffer } = await fetchVerified(ref, definingUrl, { ...options, expectType: type });
  try {
    const bitmap = await createImageBitmap(new Blob([buffer], { type }));
    return { url, bitmap, buffer };
  } catch (error) {
    throw new BundleError(`${ref.href} could not be decoded as an image`);
  }
}

export function require(condition, message) {
  if (!condition) throw new BundleError(message);
}

export function isFiniteOrNull(value) { return value === null || (typeof value === "number" && Number.isFinite(value)); }
