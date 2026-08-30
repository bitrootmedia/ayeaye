import { BuildingIcon, SettingsIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { ExportCard } from "@/components/export-card";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToastManager } from "@/components/ui/toast";
import { forgetOrg } from "@/lib/current-org";
import { canDeleteOrg, canRename, canRequireMfa, type Role } from "@/lib/types";

/**
 * The organisation's own settings, and its data export — a screen of its
 * own, moved off `/people` where it used to be a second, unrelated card
 * beneath the roster. `ExportCard` is visible to every member (a data
 * export is scoped to the requester's own visibility, not an admin
 * privilege — see `services/exports.py`); rename, the two-factor
 * requirement and deletion stay conditionally rendered on the caller's
 * role, exactly as they were on the People page.
 */
export default function OrganisationSettings() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations, reload } = useOutletContext<Shell>();
  const org = organisations.find((o) => o.id === orgId) ?? null;

  if (!org) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BuildingIcon />
          </EmptyMedia>
          <EmptyTitle>You don&rsquo;t have access to this organisation</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or you may have been removed from it.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Settings" }]}
        title="Settings"
        description="Your data, and — for admins — the organisation itself."
      />

      <div className="grid max-w-2xl gap-4">
        <ExportCard orgId={org.id} projectId={null} />

        {(canRename(org.role) || canRequireMfa(org.role) || canDeleteOrg(org.role)) && (
          <OrgSettingsCard org={org} onDone={reload} />
        )}
      </div>
    </>
  );
}

function OrgSettingsCard({
  org,
  onDone,
}: {
  org: { id: string; name: string; role: Role; require_mfa: boolean };
  onDone: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const toast = useToastManager();
  const [name, setName] = useState(org.name);
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [mfaBusy, setMfaBusy] = useState(false);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SettingsIcon className="size-4" />
          Organisation
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {canRename(org.role) && (
          <div className="space-y-2">
            <Label htmlFor="org-rename">Name</Label>
            <div className="flex gap-2">
              <Input
                id="org-rename"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="max-w-sm"
              />
              <Button
                variant="outline"
                disabled={!name.trim() || name.trim() === org.name}
                onClick={async () => {
                  await api(`/organisations/${org.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ name: name.trim() }),
                  });
                  await onDone();
                  toast.add({ title: "Renamed" });
                }}
              >
                Rename
              </Button>
            </div>
            {/* Worth saying out loud: people bookmark and share these. */}
            <p className="text-xs text-muted-foreground">
              The URL stays the same — renaming changes the label, not the address.
            </p>
          </div>
        )}

        {canRequireMfa(org.role) && (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={org.require_mfa}
                disabled={mfaBusy}
                onChange={async (e) => {
                  setMfaBusy(true);
                  try {
                    await api(`/organisations/${org.id}/require-mfa`, {
                      method: "POST",
                      body: JSON.stringify({ enabled: e.target.checked }),
                    });
                    await onDone();
                    toast.add({
                      title: e.target.checked
                        ? "Two-factor authentication required"
                        : "Two-factor authentication no longer required",
                    });
                  } finally {
                    setMfaBusy(false);
                  }
                }}
              />
              Require two-factor authentication for all members
            </label>
            <p className="text-xs text-muted-foreground">
              Anyone who hasn&rsquo;t already turned it on for themselves is asked to set it up
              at their next sign-in. Turning this off never removes a member&rsquo;s own
              enrollment.
            </p>
          </div>
        )}

        {canDeleteOrg(org.role) && (
          <div className="space-y-2 rounded-lg border border-destructive/30 p-3">
            <div className="font-medium">Delete this organisation</div>
            <p className="text-sm text-muted-foreground">
              Everything in it goes with it, for everyone. This cannot be undone.
            </p>
            <Button variant="destructive" onClick={() => setConfirming(true)}>
              <Trash2Icon />
              Delete
            </Button>
          </div>
        )}
      </CardContent>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {org.name}?</DialogTitle>
            <DialogDescription>
              This removes it for every member, along with everything inside it. Type the name
              to confirm.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={confirmText}
            placeholder={org.name}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
            <Button
              variant="destructive"
              disabled={confirmText !== org.name}
              onClick={async () => {
                await api(`/organisations/${org.id}`, { method: "DELETE" });
                forgetOrg(org.id);
                setConfirming(false);
                await onDone();
                navigate("/");
                toast.add({ title: `${org.name} deleted` });
              }}
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
