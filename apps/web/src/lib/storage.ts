/**
 * Uploading straight from the browser to object storage.
 *
 * ## The captured constructor, and why it's different here
 *
 * `const PristineXHR = window.XMLHttpRequest` runs at **module load**, before
 * `SuperTokens.init()` executes in `main.tsx`. ES modules evaluate imports
 * before the importing module's body, so anything reaching storage through
 * this file gets the untouched constructor.
 *
 * In the project this is descended from, that was load-bearing for a specific
 * reason: its apps were on other origins, SuperTokens' patched XHR injected
 * `st-auth-mode` into the cross-origin PUT, and the CORS preflight then failed
 * because the storage service answered `Allow-Headers: *` alongside
 * `Allow-Credentials: true` — which browsers refuse to treat as a wildcard.
 *
 * **That specific failure cannot happen here.** Caddy serves storage at
 * `/media/*` on the same origin as the app, so an upload is same-origin and
 * there is no preflight to fail. Single origin bought that.
 *
 * The capture is kept anyway, for two reasons that do still apply:
 *
 * 1. A presigned URL's signature covers the request. Letting an interceptor
 *    that knows nothing about SigV4 add headers or retry a `PUT` on a 401 is a
 *    class of bug with a very confusing error message ("SignatureDoesNotMatch"
 *    says nothing about session handling).
 * 2. XHR gives upload progress. `fetch` still can't, and a phone video with no
 *    progress bar reads as a hung app.
 *
 * **This breaks if a caller is ever behind `React.lazy`**, because then this
 * module evaluates after `init()`. Keep storage callers in the static import
 * graph.
 */

const PristineXHR = window.XMLHttpRequest;

export class UploadError extends Error {}

/**
 * PUT one blob to a presigned URL.
 *
 * `contentType` must be **exactly** what the ticket returned. SigV4 covers the
 * Content-Type byte for byte, so `audio/webm;codecs=opus` against a signature
 * for `audio/webm` fails — which is why the server hands back the normalised
 * type for the client to echo rather than trusting it to strip the parameter.
 */
export function putToStorage(
  url: string,
  body: Blob | File,
  contentType: string,
  onProgress?: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new PristineXHR();
    xhr.open("PUT", url, true);
    xhr.setRequestHeader("Content-Type", contentType);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new UploadError(`storage rejected the upload (${xhr.status})`));
    };
    xhr.onerror = () => reject(new UploadError("couldn't reach storage"));
    xhr.onabort = () => reject(new UploadError("upload cancelled"));

    xhr.send(body);
  });
}

/** Bytes, human-sized. `1.4 MB`. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export const isImage = (contentType: string) => contentType.startsWith("image/");

/**
 * GET one object as bytes, for decoding a voice note into a waveform.
 *
 * Same captured constructor as the upload: nothing should mutate a request
 * whose URL carries its own signature. `<audio src>` and `<img src>` need none
 * of this — the browser issues those itself.
 */
export function getFromStorage(url: string): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const xhr = new PristineXHR();
    xhr.open("GET", url, true);
    xhr.responseType = "arraybuffer";
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as ArrayBuffer);
      else reject(new UploadError(`storage refused the read (${xhr.status})`));
    };
    xhr.onerror = () => reject(new UploadError("couldn't reach storage"));
    xhr.send();
  });
}

export const isAudio = (contentType: string) => contentType.startsWith("audio/");
