import { DownloadIcon, XIcon } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * An image, full size, over the page.
 *
 * A thumbnail answers "is this the right file"; the full image answers "what
 * does it say". Opening the original in a new tab loses the task — you come
 * back to a browser tab, not to where you were — so it opens here instead and
 * Escape puts you straight back.
 *
 * Not built on the Dialog primitive: this needs an edge-to-edge black surface
 * with no padding, header or card chrome, and reaching that through Dialog is
 * more overrides than markup. It keeps Dialog's obligations though — Escape
 * closes, the backdrop closes, and the panel is labelled.
 */
export function Lightbox({
  src,
  alt,
  downloadUrl,
  onClose,
}: {
  src: string;
  alt: string;
  /** The original, when `src` is a thumbnail. */
  downloadUrl?: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    // The page behind mustn't scroll while this is up — a wheel over the
    // backdrop scrolling the task away is disorientating.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      className="fixed inset-0 z-[100] flex flex-col bg-black/85 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="flex items-center justify-between gap-3 p-3">
        <span className="min-w-0 truncate text-sm text-white/80">{alt}</span>
        <span className="flex shrink-0 items-center gap-1">
          {/* A real anchor, not a Button rendering one: Base UI's Button puts
              `role="button"` on whatever it renders, and this needs to behave
              like a link — middle-click, "save link as", the lot. */}
          <a
            href={downloadUrl ?? src}
            target="_blank"
            rel="noreferrer"
            download
            aria-label="Download the original"
            className="inline-flex size-8 items-center justify-center rounded-lg text-white transition-colors hover:bg-white/15"
            onClick={(event) => event.stopPropagation()}
          >
            <DownloadIcon className="size-4" />
          </a>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Close the image"
            className="text-white hover:bg-white/15 hover:text-white"
            onClick={onClose}
          >
            <XIcon />
          </Button>
        </span>
      </div>
      {/* Click-to-close is the backdrop's job, so the image itself swallows
          the click — otherwise zooming in on a detail dismisses the thing you
          were looking at. */}
      <div className="flex min-h-0 flex-1 items-center justify-center p-4 pt-0">
        <img
          src={downloadUrl ?? src}
          alt={alt}
          className="max-h-full max-w-full object-contain"
          onClick={(event) => event.stopPropagation()}
        />
      </div>
    </div>
  );
}
