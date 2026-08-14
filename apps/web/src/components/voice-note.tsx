import { MicIcon, PauseIcon, PlayIcon, SendIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { VoiceRecorder, clock, decodePeaks } from "@/lib/audio";
import { getFromStorage } from "@/lib/storage";
import { cn } from "@/lib/utils";

/**
 * Recording a voice note.
 *
 * **Tap to start, tap to send.** Not hold-to-record: holding is hostile on a
 * trackpad and to anyone who can't sustain a press, and it makes a two-minute
 * note impossible. Cancel is its own button rather than "let go and hope".
 *
 * **The send button IS the send.** A voice note uploads and posts in one
 * action rather than being parked in the composer for a second confirmation —
 * you have already decided by the time you stop talking. Any typed draft is
 * deliberately left alone: that's a separate message the person hasn't
 * finished, so it isn't swept along with the audio.
 */
export function VoiceNoteRecorder({
  onRecorded,
  disabled,
}: {
  onRecorded: (blob: Blob, contentType: string, seconds: number) => Promise<void>;
  disabled?: boolean;
}) {
  const recorder = useRef<VoiceRecorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!recording) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 200);
    return () => clearInterval(id);
  }, [recording]);

  // Letting go of the microphone matters: a page that navigates away
  // mid-recording would otherwise leave the browser's recording indicator on.
  useEffect(() => () => recorder.current?.cancel(), []);

  const start = async () => {
    const instance = new VoiceRecorder();
    try {
      await instance.start();
    } catch {
      // Permission refused, or no microphone. Nothing to say that the
      // browser's own prompt hasn't already said.
      return;
    }
    recorder.current = instance;
    setElapsed(0);
    setRecording(true);
  };

  const send = async () => {
    const instance = recorder.current;
    if (!instance) return;
    setBusy(true);
    try {
      const { blob, contentType, seconds } = await instance.stop();
      setRecording(false);
      await onRecorded(blob, contentType, seconds);
    } finally {
      recorder.current = null;
      setBusy(false);
    }
  };

  const cancel = () => {
    recorder.current?.cancel();
    recorder.current = null;
    setRecording(false);
  };

  if (!recording) {
    return (
      <Button
        size="sm"
        variant="ghost"
        aria-label="Record a voice note"
        disabled={disabled}
        onClick={start}
      >
        <MicIcon />
      </Button>
    );
  }

  return (
    <span className="flex items-center gap-1 rounded-md border border-primary/30 bg-primary/5 py-0.5 pr-0.5 pl-2">
      <span className="relative flex size-2 shrink-0">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-primary" />
      </span>
      <span aria-label="Recording time" className="font-mono text-xs tabular-nums">
        {clock(elapsed)}
      </span>
      <Button size="sm" variant="ghost" aria-label="Discard recording" onClick={cancel}>
        <XIcon />
      </Button>
      <Button size="sm" aria-label="Send voice note" disabled={busy} onClick={send}>
        <SendIcon />
      </Button>
    </span>
  );
}

/**
 * Playing one back, with a waveform decoded from the real audio.
 *
 * The shape shows where the speech actually is. When the browser can't decode
 * the container — Safari can't always read webm Opus — it falls back to a
 * plain progress bar rather than drawing an invented shape, because a waveform
 * that doesn't match the audio is worse than no waveform.
 */
export function VoiceNotePlayer({ url, filename }: { url: string; filename: string }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Decoded on every load. Fine for a handful of short notes; storing peaks
    // alongside the row is the upgrade if threads ever get long.
    getFromStorage(url)
      .then(decodePeaks)
      .then((result) => {
        if (!cancelled) setPeaks(result);
      })
      .catch(() => {
        // Fall back to the progress bar. A voice note you can play but not
        // visualise is still a voice note.
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  const progress = duration ? position / duration : 0;

  return (
    <div className="flex w-64 items-center gap-2 rounded-lg border px-2 py-1.5">
      <audio
        ref={audio}
        src={url}
        preload="metadata"
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
        onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
        onEnded={() => {
          setPlaying(false);
          setPosition(0);
        }}
      />
      <Button
        size="sm"
        variant="ghost"
        aria-label={playing ? `Pause ${filename}` : `Play ${filename}`}
        onClick={() => {
          const element = audio.current;
          if (!element) return;
          if (playing) {
            element.pause();
            setPlaying(false);
          } else {
            void element.play();
            setPlaying(true);
          }
        }}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </Button>

      {peaks ? (
        <span
          aria-label="Waveform"
          className="flex h-6 flex-1 items-center gap-px"
        >
          {peaks.map((peak, i) => (
            <span
              key={i}
              className={cn(
                "flex-1 rounded-full",
                i / peaks.length <= progress ? "bg-primary" : "bg-border",
              )}
              // A floor, so silence is still a visible tick rather than a gap
              // in the middle of the bar.
              style={{ height: `${Math.max(12, peak * 100)}%` }}
            />
          ))}
        </span>
      ) : (
        <span className="h-1 flex-1 overflow-hidden rounded-full bg-border">
          <span
            className="block h-full rounded-full bg-primary"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </span>
      )}

      <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
        {clock(duration ? duration - position : 0)}
      </span>
    </div>
  );
}
