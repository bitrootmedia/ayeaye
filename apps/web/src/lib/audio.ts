/**
 * Recording a voice note, and turning one into a waveform.
 *
 * ## The content-type trap
 *
 * `MediaRecorder` reports `audio/webm;codecs=opus`. A presigned URL's
 * signature covers Content-Type **byte for byte**, so uploading with the
 * codec parameter against a signature for `audio/webm` fails with
 * `SignatureDoesNotMatch` — an error that mentions nothing about codecs and
 * costs an afternoon.
 *
 * `bareType()` is the whole fix, and the server normalises the same way and
 * hands back what it actually signed. Chrome and Firefox produce webm (Opus);
 * Safari produces mp4 (AAC). Both are in the allowed list.
 */

export type Recording = { blob: Blob; contentType: string; seconds: number };

/** Strip codec parameters: `audio/webm;codecs=opus` → `audio/webm`. */
export function bareType(mimeType: string): string {
  return (mimeType || "").split(";")[0].trim().toLowerCase();
}

/**
 * The best container this browser will actually produce.
 *
 * Asked rather than assumed: Safari has no webm encoder, and
 * `new MediaRecorder(stream, {mimeType: "audio/webm"})` simply throws there.
 */
export function preferredMimeType(): string | null {
  if (typeof MediaRecorder === "undefined") return null;
  for (const candidate of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return null;
}

export const canRecord = () =>
  typeof navigator !== "undefined" &&
  !!navigator.mediaDevices?.getUserMedia &&
  preferredMimeType() !== null;

/**
 * A recorder you start and stop.
 *
 * **Tap to start, tap to send — not hold-to-record.** Holding is hostile on a
 * trackpad and to anyone who can't sustain a press, and it makes a two-minute
 * note impossible. Cancel is its own button rather than "release and pray".
 */
export class VoiceRecorder {
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stream: MediaStream | null = null;
  private startedAt = 0;

  async start(): Promise<void> {
    const mimeType = preferredMimeType();
    if (!mimeType) throw new Error("this browser can't record audio");

    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream, { mimeType });
    this.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    // A timeslice, so a long note still produces data if something goes wrong
    // before stop() — without it a crash loses the entire recording.
    this.recorder.start(1000);
    this.startedAt = Date.now();
  }

  /** Stop and hand back the audio. */
  stop(): Promise<Recording> {
    return new Promise((resolve, reject) => {
      const recorder = this.recorder;
      if (!recorder) {
        reject(new Error("not recording"));
        return;
      }
      recorder.onstop = () => {
        const contentType = bareType(recorder.mimeType || "audio/webm");
        const blob = new Blob(this.chunks, { type: contentType });
        this.release();
        resolve({ blob, contentType, seconds: (Date.now() - this.startedAt) / 1000 });
      };
      recorder.stop();
    });
  }

  /** Throw the recording away and let go of the microphone. */
  cancel(): void {
    try {
      this.recorder?.stop();
    } catch {
      // Already stopped. Releasing the tracks is the part that matters.
    }
    this.chunks = [];
    this.release();
  }

  private release() {
    // Without this the browser's recording indicator stays on, which is both
    // alarming and a real privacy problem.
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.recorder = null;
  }
}

/**
 * Peaks for drawing a waveform, decoded from the **real audio**.
 *
 * So the shape shows where the speech actually is, rather than an invented
 * decoration. Returns `null` when the browser can't decode the container —
 * Safari can't always read a webm Opus file — and the caller falls back to a
 * plain progress bar rather than drawing something untrue.
 */
export async function decodePeaks(bytes: ArrayBuffer, buckets = 48): Promise<number[] | null> {
  const Ctx = window.AudioContext ?? (window as never as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  if (!Ctx) return null;
  const context = new Ctx();
  try {
    const audio = await context.decodeAudioData(bytes.slice(0));
    const data = audio.getChannelData(0);
    const per = Math.max(1, Math.floor(data.length / buckets));
    const peaks: number[] = [];
    for (let i = 0; i < buckets; i++) {
      let peak = 0;
      for (let j = 0; j < per; j++) {
        const sample = Math.abs(data[i * per + j] ?? 0);
        if (sample > peak) peak = sample;
      }
      peaks.push(peak);
    }
    // Normalised, so a quietly-recorded note still fills the bar rather than
    // rendering as a flat line.
    const loudest = Math.max(...peaks, 0.01);
    return peaks.map((p) => p / loudest);
  } catch {
    return null;
  } finally {
    void context.close();
  }
}

/** `0:07`. Voice notes are short; minutes and seconds is enough.
 *
 *  Guards against `Infinity`/`NaN`, not just negative input: Chromium
 *  reports `Infinity` for a `MediaRecorder`-produced webm's `duration`
 *  until a seek forces it to work out the real value (its container never
 *  carries one in the header), and `Infinity - anything` is still
 *  `Infinity` — without this guard that rendered as the literal string
 *  "Infinity:NaN" rather than "0:00". */
export function clock(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
