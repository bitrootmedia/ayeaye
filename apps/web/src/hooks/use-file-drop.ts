import { useCallback, useRef, useState } from "react";

/**
 * Drag a file onto a panel to upload it.
 *
 * Two things make this less trivial than it looks, and both are the reason
 * this is a hook rather than four inline handlers copied twice:
 *
 * **1. `dragleave` fires when you cross a child element.** Move the pointer
 * from the card onto the button inside it and the browser reports leaving,
 * even though you are still over the drop zone. Tracking a *depth counter* —
 * enter increments, leave decrements, zero means genuinely out — is what stops
 * the highlight strobing as you move across a panel.
 *
 * **2. `dragover` must call `preventDefault()` on every single event**, not
 * just the first. Without it the browser refuses the drop and the drag ends
 * with the cursor showing "no entry" for no visible reason.
 *
 * It also only reacts to actual files: dragging selected text across the page
 * shouldn't light up an upload target.
 */
export function useFileDrop(onFiles: (files: File[]) => void, disabled = false) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);

  const reset = useCallback(() => {
    depth.current = 0;
    setDragging(false);
  }, []);

  const carriesFiles = (event: React.DragEvent) =>
    Array.from(event.dataTransfer?.types ?? []).includes("Files");

  const onDragEnter = useCallback(
    (event: React.DragEvent) => {
      if (disabled || !carriesFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    [disabled],
  );

  const onDragOver = useCallback(
    (event: React.DragEvent) => {
      if (disabled || !carriesFiles(event)) return;
      // Every event, or the drop is rejected.
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [disabled],
  );

  const onDragLeave = useCallback(
    (event: React.DragEvent) => {
      if (disabled) return;
      event.preventDefault();
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    [disabled],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      if (disabled) return;
      event.preventDefault();
      reset();
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length) onFiles(files);
    },
    [disabled, onFiles, reset],
  );

  return {
    /** True while a file is over the zone — for the highlight. */
    dragging,
    /** Spread onto the element that should accept the drop. */
    dropProps: { onDragEnter, onDragOver, onDragLeave, onDrop },
  };
}
