import {
  ArchiveIcon,
  CircleAlertIcon,
  CircleDotIcon,
  FolderIcon,
  LayoutGridIcon,
  LockIcon,
  PlusIcon,
  SearchIcon,
  TableIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext, useParams, useSearchParams } from "react-router-dom";

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
import { lastView, rememberView } from "@/lib/view-preference";

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
  const [params, setParams] = useSearchParams();

  const org = organisations.find((o) => o.id === orgId) ?? null;
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [groups, setGroups] = useState<ProjectGroup[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);

  // Both in the URL, same reasoning as the task list: a view somebody
  // arrived at — filtered, as a table — is one they can send to a colleague.
  // Absent the param entirely, fall back to whatever you last toggled to
  // here rather than always defaulting to Cards.
  const query = params.get("q") ?? "";
  const viewParam = params.get("view");
  const view: "table" | "cards" =
    viewParam === "table" || viewParam === "cards"
      ? viewParam
      : lastView("projects") === "table"
        ? "table"
        : "cards";
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null || value === "") next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

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

  // Client-side: the visible-to-you list is never large enough to need the
  // list screen's server-side filtering, and a name filter narrowing what's
  // already on screen doesn't need a round trip.
  const q = query.trim().toLowerCase();
  const filtered = q ? (projects ?? []).filter((p) => p.name.toLowerCase().includes(q)) : projects ?? [];

  // Grouped for display only. The API already decided what's visible; this is
  // presentation, not a second pass at access.
  const byGroup = new Map<string, Project[]>();
  for (const p of filtered) {
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
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                aria-label="Filter by name"
                placeholder="Filter by name…"
                className="w-48 pl-8"
                onChange={(e) => setParam("q", e.target.value)}
              />
            </div>
            <Button
              variant="ghost"
              aria-label={view === "cards" ? "View as a table" : "View as cards"}
              onClick={() => {
                const next = view === "cards" ? "table" : "cards";
                // "cards" clears the param rather than writing it — same
                // "default stays out of the URL" convention `?view=` already
                // followed before this — but the preference still needs
                // remembering either way, or toggling back to Cards would
                // silently keep offering Table as tomorrow's default.
                setParam("view", next === "cards" ? null : next);
                rememberView("projects", next);
              }}
            >
              {view === "cards" ? <TableIcon /> : <LayoutGridIcon />}
              {view === "cards" ? "Table" : "Cards"}
            </Button>
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
      ) : filtered.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No projects match &ldquo;{query.trim()}&rdquo;.
        </p>
      ) : view === "table" ? (
        <ProjectsTable orgId={org.id} projects={filtered} />
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
                  <ProjectStats project={project} />
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

/** Open tasks, and open-and-important tasks, on this project — the caller's
 *  own visibility, same as everything else here. Muted, not coloured: this
 *  merges three priority levels into one number, and status already owns
 *  the product's only red and only amber. */
function ProjectStats({ project }: { project: Project }) {
  if (project.open_task_count === 0 && project.important_task_count === 0) return null;
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span className="flex items-center gap-1" title="Open tasks">
        <CircleDotIcon className="size-3.5" />
        {project.open_task_count} open
      </span>
      {project.important_task_count > 0 && (
        <span
          className="flex items-center gap-1"
          title="Critical, urgent or high priority"
        >
          <CircleAlertIcon className="size-3.5" />
          {project.important_task_count} important
        </span>
      )}
    </div>
  );
}

/** The same list, as rows instead of cards — better for scanning a lot of
 *  projects at once, which is exactly when the card grid stops working. */
function ProjectsTable({ orgId, projects }: { orgId: string; projects: Project[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Owner</th>
            <th className="px-3 py-2 font-medium">Access</th>
            <th className="px-3 py-2 text-right font-medium">Open</th>
            <th className="px-3 py-2 text-right font-medium">Important</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.id} className="border-b last:border-0 hover:bg-accent/50">
              <td className="px-3 py-2">
                <Link
                  to={`/orgs/${orgId}/projects/${project.id}`}
                  className="flex min-w-0 items-center gap-2 font-medium hover:underline"
                >
                  <span className="min-w-0 truncate">{project.name}</span>
                  {project.archived && (
                    <Badge variant="outline" className="shrink-0 text-muted-foreground">
                      Archived
                    </Badge>
                  )}
                </Link>
              </td>
              <td className="px-3 py-2 text-muted-foreground">{personName(project.owner)}</td>
              <td className="px-3 py-2">
                <Badge variant="outline">{LEVEL_LABEL[project.access]}</Badge>
              </td>
              <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                {project.open_task_count}
              </td>
              <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                {project.important_task_count > 0 ? project.important_task_count : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
