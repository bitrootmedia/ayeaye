import { CheckIcon, CopyIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * A read-only value with a copy button.
 *
 * This is the component that makes SMTP optional (PLAN.md §2.4). An invitation
 * whose only delivery is email is an invitation that a self-hoster without a
 * mail provider cannot send at all — so the link is always on screen, whether
 * or not the email went, and pasting it into chat is a first-class path rather
 * than a workaround.
 */
export function CopyLink({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Non-secure origin, or permission refused. The input is selectable, so
      // there is still a way through — don't leave a dead button either way.
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="flex gap-2">
      <Input
        readOnly
        value={value}
        aria-label={label ?? "Link"}
        className="font-mono text-xs"
        onFocus={(e) => e.currentTarget.select()}
      />
      <Button variant="outline" onClick={copy} aria-label="Copy link">
        {copied ? <CheckIcon /> : <CopyIcon />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}
