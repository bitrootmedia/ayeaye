import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { STATUS_DOT, STATUS_LABEL, type TaskStatus } from "@/lib/types";

/**
 * Status as an outline badge with a coloured dot.
 *
 * A board of saturated pills is confetti and the label loses contrast against
 * its own background. The dot carries the colour; the text stays readable.
 */
export function StatusBadge({
  status,
  className,
}: {
  status: TaskStatus;
  className?: string;
}) {
  return (
    <Badge variant="outline" className={cn("gap-1.5", className)}>
      <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_DOT[status])} />
      {STATUS_LABEL[status]}
    </Badge>
  );
}

/**
 * Only shown when a task is closed.
 *
 * Open is the normal state, and a badge on every open row is noise. This is
 * also the visual reminder that closed is *not* a status — a closed task keeps
 * whatever status it had.
 */
export function ClosedBadge({ isOpen }: { isOpen: boolean }) {
  if (isOpen) return null;
  return (
    <Badge variant="outline" className="gap-1.5 text-muted-foreground">
      <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
      Closed
    </Badge>
  );
}
