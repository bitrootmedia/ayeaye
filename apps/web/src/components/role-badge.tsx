import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ROLE_LABEL, type MemberStatus, type Role } from "@/lib/types";

/**
 * Colour lives in a dot, not a pill.
 *
 * A roster of saturated badges is confetti and the label loses contrast
 * against its own background. An outline badge with a coloured dot keeps the
 * text at full contrast and leaves saturated colour meaning something.
 */
const ROLE_DOT: Record<Role, string> = {
  owner: "bg-primary",
  admin: "bg-chart-3",
  member: "bg-muted-foreground/50",
};

export function RoleBadge({ role, className }: { role: Role; className?: string }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5", className)}>
      <span className={cn("size-1.5 shrink-0 rounded-full", ROLE_DOT[role])} />
      {ROLE_LABEL[role]}
    </Badge>
  );
}

/** Only rendered for `invited` or `disabled`. An active member's status is
 *  the absence of this badge — a row saying "Active" on every line is noise. */
export function PendingBadge({ status }: { status: MemberStatus }) {
  if (status === "invited") {
    return (
      <Badge variant="outline" className="gap-1.5 text-muted-foreground">
        <span className="size-1.5 shrink-0 rounded-full bg-status-review" />
        Invited
      </Badge>
    );
  }
  if (status === "disabled") {
    // Muted, not red — this isn't a task status and doesn't compete with the
    // product's one red (blocker) for what "needs you" means.
    return (
      <Badge variant="outline" className="gap-1.5 text-muted-foreground">
        <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
        Disabled
      </Badge>
    );
  }
  return null;
}
