import { ArrowRightIcon, BuildingIcon, PlusIcon } from "lucide-react";
import { Link, useOutletContext } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { RoleBadge } from "@/components/role-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { useToastManager } from "@/components/ui/toast";
import { ROLE_LABEL } from "@/lib/types";

/**
 * The front door: what you're in, and what you've been asked to join.
 *
 * Invitations sit above the list on purpose. They're the only thing here that
 * expects an answer, and an invitation you don't notice is one you never
 * accept — which reads to the person who sent it as the product losing it.
 */
export default function Organisations() {
  const { organisations, invites, reload, openCreateOrg } = useOutletContext<Shell>();
  const toast = useToastManager();

  const respond = async (id: string, name: string, accept: boolean) => {
    try {
      await api(`/me/invites/${id}${accept ? "/accept" : ""}`, {
        method: accept ? "POST" : "DELETE",
      });
      await reload();
      toast.add({
        title: accept ? `You've joined ${name}` : "Invitation declined",
        description: accept ? undefined : "They can invite you again if it was a mistake.",
      });
    } catch {
      toast.add({ title: "That didn't work", description: "Try again in a moment." });
    }
  };

  return (
    <>
      <PageHeader
        title="Your organisations"
        description="Everything — teams, projects and tasks — lives inside one of these."
        actions={
          <Button onClick={openCreateOrg}>
            <PlusIcon />
            New organisation
          </Button>
        }
      />

      {invites.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              {invites.length === 1 ? "You've been invited" : `${invites.length} invitations`}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {invites.map((invite) => (
              <div
                key={invite.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">{invite.organisation_name}</div>
                  <div className="text-sm text-muted-foreground">
                    {invite.invited_by ? `${invite.invited_by} invited you` : "You were invited"}{" "}
                    as {ROLE_LABEL[invite.role].toLowerCase()}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    onClick={() => respond(invite.id, invite.organisation_name, false)}
                  >
                    Decline
                  </Button>
                  <Button onClick={() => respond(invite.id, invite.organisation_name, true)}>
                    Join
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {organisations.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BuildingIcon />
            </EmptyMedia>
            <EmptyTitle>No organisations yet</EmptyTitle>
            <EmptyDescription>
              Create one to get started, or wait for someone to invite you to theirs.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={openCreateOrg}>
              <PlusIcon />
              New organisation
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {organisations.map((org) => (
            <Link
              key={org.id}
              to={`/orgs/${org.id}`}
              className="group rounded-xl border bg-card p-4 transition-colors hover:bg-accent/50"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">{org.name}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground">
                    {org.slug}
                  </div>
                </div>
                <ArrowRightIcon className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <div className="mt-3">
                <RoleBadge role={org.role} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
