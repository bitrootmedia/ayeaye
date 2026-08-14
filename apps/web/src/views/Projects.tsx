import { ArchiveIcon, FolderIcon, LockIcon, PlusIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import { api } from "@/api";
import type { Shell } from "@/App";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useToastManager } from "@/components/ui/toast";
import { LEVEL_LABEL, personName, type Project, type ProjectGroup } from "@/lib/types";

const UNGROUPED = "__none__";

/**
 * Everything you can see in this organisation.
 *
 * "Everything you can see" is doing real work: a project is private to its
 * owner until it's shared, so this list is genuinely different for every
 * person. The empty state says so, because an empty screen in a busy
 * organisation otherwise reads as the product being broken.
 */
export default function Projects() {
  const { orgId } = useParams<{ orgId: string }>();
  const { organisations } = useOutletContext<Shell>();
  const toast = useToastManager();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [groups, setGroups] = useState<ProjectGroup[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!orgId) return;
    const [ps, gs] = await Promise.all([
      api<Project[]>(`/organisations/${orgId}/projects?include_archived=${showArchived}`),
      api<ProjectGroup[]>(`/organisations/${orgId}/project-groups`),
    ]);
    setProjects(ps);
    setGroups(gs);
  }, [orgId, showArchived]);

  useEffect(() => {
    void load().catch(() => setProjects([]));
  }, [load]);

  if (!org) return null;

  // Grouped for display only. The API already decided what's visible; this is
  // presentation, not a second pass at access.
  const byGroup = new Map<string, Project[]>();
  for (const p of projects ?? []) {
    const key = p.project_group_id ?? UNGROUPED;
    byGroup.set(key, [...(byGroup.get(key) ?? []), p]);
  }
  const sections = [
    ...groups
      .filter((g) => byGroup.has(g.id))
      .map((g) => ({ id: g.id, name: g.name, projects: byGroup.get(g.id)! })),
    ...(byGroup.has(UNGROUPED)
      ? [{ id: UNGROUPED, name: groups.length ? "Ungrouped" : "", projects: byGroup.get(UNGROUPED)! }]
      : []),
  ];

  return (
    <>
      <PageHeader
        crumbs={[{ label: org.name, to: `/orgs/${org.id}` }, { label: "Projects" }]}
        title="Projects"
        description="What you own, and what people have shared with you."
        actions={
          <>
            <Button variant="ghost" onClick={() => setShowArchived((v) => !v)}>
              <ArchiveIcon />
              {showArchived ? "Hide archived" : "Show archived"}
            </Button>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon />
              New project
            </Button>
          </>
        }
      />

      {projects === null ? (
        <div className="flex flex-1 items-center justify-center py-12">
          <Spinner />
        </div>
      ) : projects.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <LockIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing here yet</EmptyTitle>
            <EmptyDescription>
              Projects are private to whoever creates them, so this list only shows what you own
              or what someone has shared with you. There may be others you can&rsquo;t see.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon />
              New project
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        sections.map((section) => (
          <section key={section.id} className="space-y-3">
            {section.name && (
              <h2 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <FolderIcon className="size-4" />
                {section.name}
              </h2>
            )}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {section.projects.map((project) => (
                <Link
                  key={project.id}
                  to={`/orgs/${org.id}/projects/${project.id}`}
                  className="group flex flex-col gap-3 rounded-xl border bg-card p-4 transition-colors hover:bg-accent/50"
                >
                  <div className="min-w-0">
                    <div className="flex items-start gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium">{project.name}</span>
                      {project.archived && (
                        <Badge variant="outline" className="shrink-0 text-muted-foreground">
                          Archived
                        </Badge>
                      )}
                    </div>
                    {project.description && (
                      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                        {project.description}
                      </p>
                    )}
                  </div>
                  <div className="mt-auto flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span className="truncate">{personName(project.owner)}</span>
                    <Badge variant="outline" className="shrink-0">
                      {LEVEL_LABEL[project.access]}
                    </Badge>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        ))
      )}

      <NewProjectDialog
        open={creating}
        onOpenChange={setCreating}
        orgId={org.id}
        groups={groups}
        onCreated={async () => {
          await load();
          toast.add({
            title: "Project created",
            description: "Only you can see it — share it from its Access panel.",
          });
        }}
      />
    </>
  );
}

function NewProjectDialog({
  open,
  onOpenChange,
  orgId,
  groups,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  groups: ProjectGroup[];
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [groupId, setGroupId] = useState<string>(UNGROUPED);
  const [busy, setBusy] = useState(false);

  const items = [
    { value: UNGROUPED, label: "No group" },
    ...groups.map((g) => ({ value: g.id, label: g.name })),
  ];

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await api(`/organisations/${orgId}/projects`, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          project_group_id: groupId === UNGROUPED ? null : groupId,
        }),
      });
      setName("");
      setDescription("");
      setGroupId(UNGROUPED);
      onOpenChange(false);
      await onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            You&rsquo;ll own it, and to begin with nobody else can see it — not even the rest of
            the organisation. Share it once it exists.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="project-name">Name</Label>
            <Input
              id="project-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-description">Description</Label>
            <Textarea
              id="project-description"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {groups.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="project-group">Group</Label>
              <Select
                items={items}
                value={groupId}
                onValueChange={(v) => setGroupId(String(v))}
              >
                <SelectTrigger id="project-group">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {items.map((i) => (
                      <SelectItem key={i.value} value={i.value}>
                        {i.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {/* Worth saying, because "folder" implies "shared folder". */}
              <p className="text-xs text-muted-foreground">
                Groups are labels for tidiness. Filing a project in one grants nobody access to
                it.
              </p>
            </div>
          )}
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || !name.trim()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
