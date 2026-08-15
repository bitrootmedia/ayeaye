import { RotateCcwIcon, TriangleAlertIcon } from "lucide-react";
import React from "react";

import { Button } from "@/components/ui/button";

/**
 * Catches a render error and shows something instead of nothing.
 *
 * **React unmounts the entire tree when a render throws.** Not the component,
 * not the screen — everything, leaving a white page with no rail, no message
 * and nothing to click. That is exactly how a small mistake reads to the
 * person using it: "the site went blank". It happened here for real, from a
 * menu label placed outside its group.
 *
 * So this wraps the shell rather than each screen: the failure it exists for
 * is the one nobody predicted, and predicting *where* is the same problem as
 * predicting *whether*.
 *
 * Deliberately not a toast. A toast implies the app is still usable, and
 * after a render error it isn't — the tree is gone. This says so, and gives
 * the two ways out that actually work.
 */
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // The console is the only log this product has on the client, and the
    // stack is what makes a bug report actionable.
    console.error("render failed:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
        <TriangleAlertIcon className="size-8 text-status-blocker" />
        <div className="space-y-1">
          <h1 className="text-lg font-semibold">This screen stopped working</h1>
          <p className="max-w-md text-sm text-muted-foreground">
            Nothing was lost — the error is in what you were looking at, not in your data.
            Reloading almost always fixes it.
          </p>
        </div>
        {/* The message itself, in the mono voice, because "it broke" without
            the reason is a bug report nobody can act on. */}
        <code className="max-w-lg truncate rounded-md bg-muted px-2 py-1 font-mono text-xs">
          {this.state.error.message}
        </code>
        <div className="flex gap-2">
          <Button onClick={() => window.location.reload()}>
            <RotateCcwIcon />
            Reload
          </Button>
          <Button variant="outline" onClick={() => (window.location.href = "/")}>
            Start again
          </Button>
        </div>
      </div>
    );
  }
}
