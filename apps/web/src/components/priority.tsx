import {
  ArrowUpIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  ChevronsDownIcon,
  ChevronsUpIcon,
  MinusIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { PRIORITY_LABEL, PRIORITY_TONE, type TaskPriority } from "@/lib/types";

/**
 * Priority, as a direction rather than another coloured badge.
 *
 * Status already owns the only red (blocked) and the only amber (in review).
 * A second dot badge per card would mean six more hues competing with it, and
 * red would stop meaning "this needs you". So **shape carries the level** —
 * chevrons up for above normal, down for below — and colour appears on
 * Critical and Urgent alone.
 */
const GLYPH = {
  critical: ChevronsUpIcon,
  urgent: ArrowUpIcon,
  high: ChevronUpIcon,
  normal: MinusIcon,
  low: ChevronDownIcon,
  very_low: ChevronsDownIcon,
} as const;

export function PriorityGlyph({
  priority,
  className,
  withLabel,
}: {
  priority: TaskPriority;
  className?: string;
  withLabel?: boolean;
}) {
  const Icon = GLYPH[priority];
  return (
    <span
      // Always named, never colour-only: the difference between Urgent and
      // High is a hue, and roughly one man in twelve can't rely on that.
      title={PRIORITY_LABEL[priority]}
      aria-label={`Priority: ${PRIORITY_LABEL[priority]}`}
      className={cn("inline-flex shrink-0 items-center gap-1", PRIORITY_TONE[priority], className)}
    >
      <Icon className="size-4" />
      {withLabel && <span className="text-sm">{PRIORITY_LABEL[priority]}</span>}
    </span>
  );
}
