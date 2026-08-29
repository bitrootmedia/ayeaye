import { CheckSquareIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useToastManager } from "@/components/ui/toast";
import type { Checklist } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Every checklist on a task — more than one allowed.
 *
 * Shared task content, not a personal record: `canEdit` (the caller's own
 * `write` access, resolved server-side like every other edit control on this
 * screen) gates adding, checking off and removing here, the same bar tagging
 * and attaching a file already clear. A read-only viewer sees the lists but
 * gets no controls to change them, the same pattern `TaskFilesPanel` uses.
 */
export function ChecklistsPanel({
  orgId,
  taskId,
  canEdit,
  refreshKey,
}: {
  orgId: string;
  taskId: string;
  canEdit: boolean;
  refreshKey?: number;
}) {
  const toast = useToastManager();
  const [checklists, setChecklists] = useState<Checklist[] | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [addingList, setAddingList] = useState(false);

  const base = `/organisations/${orgId}/tasks/${taskId}/checklists`;

  const load = useCallback(async () => {
    setChecklists(await api<Checklist[]>(base).catch(() => []));
  }, [base]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const addChecklist = async () => {
    if (!newTitle.trim() || addingList) return;
    setAddingList(true);
    try {
      await api(base, { method: "POST", body: JSON.stringify({ title: newTitle.trim() }) });
      setNewTitle("");
      await load();
    } catch (err) {
      fail(err, "Couldn't add that list");
    } finally {
      setAddingList(false);
    }
  };

  const removeChecklist = async (checklistId: string) => {
    try {
      await api(`${base}/${checklistId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      fail(err, "Couldn't remove that list");
    }
  };

  // Checklists themselves are few (a handful per task at most); nothing here
  // needs the pagination or per-column bounding a task list or board does.
  if (checklists !== null && checklists.length === 0 && !canEdit) return null;

  return (
    <Card role="region" aria-label="Checklists">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CheckSquareIcon className="size-4" />
          Checklists
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {checklists?.map((checklist) => (
          <ChecklistCard
            key={checklist.id}
            orgId={orgId}
            taskId={taskId}
            checklist={checklist}
            canEdit={canEdit}
            onChanged={load}
            onRemove={() => removeChecklist(checklist.id)}
          />
        ))}

        {canEdit && (
          <div className="flex gap-2">
            <Input
              aria-label="New checklist name"
              placeholder="Add todo list…"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addChecklist()}
            />
            <Button
              aria-label="Add checklist"
              disabled={!newTitle.trim() || addingList}
              onClick={addChecklist}
            >
              <PlusIcon />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ChecklistCard({
  orgId,
  taskId,
  checklist,
  canEdit,
  onChanged,
  onRemove,
}: {
  orgId: string;
  taskId: string;
  checklist: Checklist;
  canEdit: boolean;
  onChanged: () => Promise<void>;
  onRemove: () => void;
}) {
  const toast = useToastManager();
  const [newItem, setNewItem] = useState("");
  const [addingItem, setAddingItem] = useState(false);

  const base = `/organisations/${orgId}/tasks/${taskId}/checklists/${checklist.id}`;
  const done = checklist.items.filter((i) => i.done).length;

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const toggle = async (itemId: string, next: boolean) => {
    try {
      await api(`${base}/items/${itemId}`, {
        method: "PATCH",
        body: JSON.stringify({ done: next }),
      });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't update that item");
    }
  };

  const removeItem = async (itemId: string) => {
    try {
      await api(`${base}/items/${itemId}`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't remove that item");
    }
  };

  const addItem = async () => {
    if (!newItem.trim() || addingItem) return;
    setAddingItem(true);
    try {
      await api(`${base}/items`, {
        method: "POST",
        body: JSON.stringify({ text: newItem.trim() }),
      });
      setNewItem("");
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't add that item");
    } finally {
      setAddingItem(false);
    }
  };

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{checklist.title}</span>
        {checklist.items.length > 0 && (
          <span className="font-mono text-xs text-muted-foreground">
            {done}/{checklist.items.length}
          </span>
        )}
        {canEdit && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Delete checklist ${checklist.title}`}
            onClick={onRemove}
          >
            <Trash2Icon />
          </Button>
        )}
      </div>

      {checklist.items.length > 0 && (
        <ul className="space-y-1">
          {checklist.items.map((item) => (
            <li key={item.id} className="flex items-center gap-2">
              <Checkbox
                aria-label={item.text}
                checked={item.done}
                disabled={!canEdit}
                onCheckedChange={(checked) => toggle(item.id, checked)}
              />
              <span
                className={cn(
                  "min-w-0 flex-1 truncate text-sm",
                  item.done && "text-muted-foreground line-through",
                )}
              >
                {item.text}
              </span>
              {canEdit && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Remove ${item.text}`}
                  onClick={() => removeItem(item.id)}
                >
                  <Trash2Icon />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <div className="flex gap-2 pt-1">
          <Input
            aria-label={`Add an item to ${checklist.title}`}
            placeholder="Add an item…"
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addItem()}
          />
          <Button
            size="sm"
            aria-label={`Add item to ${checklist.title}`}
            disabled={!newItem.trim() || addingItem}
            onClick={addItem}
          >
            <PlusIcon />
          </Button>
        </div>
      )}
    </div>
  );
}
