import {
  Grid3x3Icon,
  PlusIcon,
  RotateCcwIcon,
  SquareCheckIcon,
  Trash2Icon,
  TypeIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useToastManager } from "@/components/ui/toast";
import { personName, type Sheet, type SheetCell, type SheetColumnKind } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Every sheet on a task — a grid checklist, more than one allowed.
 *
 * The same reason multiple checklists are allowed: "Weekly maintenance" and
 * "Security audit" are two different grids, not two sections of one. Rows
 * and columns are freeform labels — servers down one side, repeatable
 * checks across the top — and each column holds checkboxes or text, so the
 * same grid can carry "Version: 1.4.2" beside "Patched: ✓".
 *
 * A cell's presence in `sheet.cells` IS the check (see models/sheet.py), so
 * a newly added row or column starts unchecked against everything already
 * there for free — nothing here has to backfill it.
 */
export function SheetsPanel({
  orgId,
  taskId,
  canEdit,
  refreshKey,
  open = true,
  onLoaded,
}: {
  orgId: string;
  taskId: string;
  canEdit: boolean;
  refreshKey?: number;
  /** Render the card even with nothing in it — see `ChecklistsPanel`'s own
   *  `open`, which this mirrors exactly. */
  open?: boolean;
  /** Whether there is anything to show, reported after each load. */
  onLoaded?: (hasContent: boolean) => void;
}) {
  const toast = useToastManager();
  const [sheets, setSheets] = useState<Sheet[] | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [addingSheet, setAddingSheet] = useState(false);

  const base = `/organisations/${orgId}/tasks/${taskId}/sheets`;

  const load = useCallback(async () => {
    setSheets(await api<Sheet[]>(base).catch(() => []));
  }, [base]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // A ref, reported from its own effect — see `ChecklistsPanel` for why a
  // callback in `load`'s dependency list would refetch forever.
  const report = useRef(onLoaded);
  report.current = onLoaded;
  useEffect(() => {
    if (sheets === null) return;
    report.current?.(sheets.length > 0);
  }, [sheets]);

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const addSheet = async () => {
    if (!newTitle.trim() || addingSheet) return;
    setAddingSheet(true);
    try {
      await api(base, {
        method: "POST",
        body: JSON.stringify({ title: newTitle.trim() }),
      });
      setNewTitle("");
      await load();
    } catch (err) {
      fail(err, "Couldn't add that sheet");
    } finally {
      setAddingSheet(false);
    }
  };

  const removeSheet = async (sheetId: string) => {
    try {
      await api(`${base}/${sheetId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      fail(err, "Couldn't remove that sheet");
    }
  };

  // Nothing in it and nobody asked for it: nothing at all, not even the
  // heading — see `open`, and `ChecklistsPanel`'s own longer note.
  if (!open && !(sheets !== null && sheets.length > 0)) return null;

  return (
    <Card role="region" aria-label="Sheets">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Grid3x3Icon className="size-4" />
          Sheets
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {sheets?.map((sheet) => (
          <SheetGrid
            key={sheet.id}
            orgId={orgId}
            taskId={taskId}
            sheet={sheet}
            canEdit={canEdit}
            onChanged={load}
            onRemove={() => removeSheet(sheet.id)}
          />
        ))}

        {canEdit && (
          <div className="flex gap-2">
            <Input
              aria-label="New sheet name"
              placeholder="Add sheet…"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addSheet()}
            />
            <Button
              aria-label="Add sheet"
              disabled={!newTitle.trim() || addingSheet}
              onClick={addSheet}
            >
              <PlusIcon />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SheetGrid({
  orgId,
  taskId,
  sheet,
  canEdit,
  onChanged,
  onRemove,
}: {
  orgId: string;
  taskId: string;
  sheet: Sheet;
  canEdit: boolean;
  onChanged: () => Promise<void>;
  onRemove: () => void;
}) {
  const toast = useToastManager();
  const [newRow, setNewRow] = useState("");
  const [newColumn, setNewColumn] = useState("");
  const [newColumnKind, setNewColumnKind] = useState<SheetColumnKind>("check");
  const [busy, setBusy] = useState(false);

  const base = `/organisations/${orgId}/tasks/${taskId}/sheets/${sheet.id}`;
  const checkedByCell = new Map(sheet.cells.map((c) => [`${c.row_id}:${c.column_id}`, c]));
  const checkColumns = new Set(sheet.columns.filter((c) => c.kind === "check").map((c) => c.id));
  // Reset only unticks — text survives it — so it's offered only when
  // there is a tick to undo.
  const anyTicked = sheet.cells.some((c) => checkColumns.has(c.column_id));

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const toggle = async (rowId: string, columnId: string, checked: boolean) => {
    try {
      await api(`${base}/cells/${rowId}/${columnId}`, {
        method: checked ? "PUT" : "DELETE",
      });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't update that cell");
    }
  };

  const setValue = async (rowId: string, columnId: string, value: string) => {
    try {
      await api(`${base}/values/${rowId}/${columnId}`, {
        method: "PUT",
        body: JSON.stringify({ value }),
      });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't save that cell");
    }
  };

  const addRow = async () => {
    if (!newRow.trim() || busy) return;
    setBusy(true);
    try {
      await api(`${base}/rows`, {
        method: "POST",
        body: JSON.stringify({ label: newRow.trim() }),
      });
      setNewRow("");
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't add that row");
    } finally {
      setBusy(false);
    }
  };

  const addColumn = async () => {
    if (!newColumn.trim() || busy) return;
    setBusy(true);
    try {
      await api(`${base}/columns`, {
        method: "POST",
        body: JSON.stringify({ label: newColumn.trim(), kind: newColumnKind }),
      });
      setNewColumn("");
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't add that column");
    } finally {
      setBusy(false);
    }
  };

  const removeRow = async (rowId: string) => {
    try {
      await api(`${base}/rows/${rowId}`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't remove that row");
    }
  };

  const removeColumn = async (columnId: string) => {
    try {
      await api(`${base}/columns/${columnId}`, { method: "DELETE" });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't remove that column");
    }
  };

  const reset = async () => {
    try {
      await api(`${base}/reset`, { method: "POST" });
      await onChanged();
      toast.add({ title: `"${sheet.title}" reset` });
    } catch (err) {
      fail(err, "Couldn't reset that sheet");
    }
  };

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{sheet.title}</span>
        {canEdit && anyTicked && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Reset ${sheet.title}`}
            title="Untick every checkbox — text stays"
            onClick={reset}
          >
            <RotateCcwIcon />
          </Button>
        )}
        {canEdit && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Delete sheet ${sheet.title}`}
            onClick={onRemove}
          >
            <Trash2Icon />
          </Button>
        )}
      </div>

      {(sheet.rows.length > 0 || sheet.columns.length > 0) && (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-muted/40">
                <th className="border-b p-2 text-left font-medium" />
                {sheet.columns.map((column) => (
                  <th
                    key={column.id}
                    className={cn(
                      "border-b border-l p-2 font-medium",
                      column.kind === "text" ? "min-w-32 text-left" : "text-center",
                    )}
                  >
                    <div
                      className={cn(
                        "flex items-center gap-1",
                        column.kind === "check" && "justify-center",
                      )}
                    >
                      <span className="truncate">{column.label}</span>
                      {canEdit && (
                        <button
                          type="button"
                          aria-label={`Remove column ${column.label}`}
                          className="text-muted-foreground hover:text-foreground"
                          onClick={() => removeColumn(column.id)}
                        >
                          <Trash2Icon className="size-3" />
                        </button>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheet.rows.map((row) => (
                <tr key={row.id}>
                  <th className="border-b p-2 text-left font-medium">
                    <div className="flex items-center gap-1">
                      <span className="truncate">{row.label}</span>
                      {canEdit && (
                        <button
                          type="button"
                          aria-label={`Remove row ${row.label}`}
                          className="text-muted-foreground hover:text-foreground"
                          onClick={() => removeRow(row.id)}
                        >
                          <Trash2Icon className="size-3" />
                        </button>
                      )}
                    </div>
                  </th>
                  {sheet.columns.map((column) => {
                    const cell = checkedByCell.get(`${row.id}:${column.id}`);
                    if (column.kind === "text") {
                      return (
                        <td key={column.id} className="max-w-64 border-b border-l p-1">
                          <SheetTextCell
                            label={`${row.label}, ${column.label}`}
                            cell={cell}
                            canEdit={canEdit}
                            onSave={(value) => setValue(row.id, column.id, value)}
                          />
                        </td>
                      );
                    }
                    return (
                      <td
                        key={column.id}
                        className={cn("border-b border-l p-2 text-center", cell && "bg-primary/5")}
                      >
                        {/* A plain <td> isn't a flex container, and Base
                            UI's Checkbox root is an inline <span> — its
                            explicit width/height are ignored outside one,
                            collapsing the box to a hairline. This div is
                            what makes the checkbox a proper square here. */}
                        <div className="flex justify-center">
                          <Checkbox
                            aria-label={`${row.label}, ${column.label}`}
                            checked={cell !== undefined}
                            disabled={!canEdit}
                            title={
                              cell
                                ? `${personName(cell.checked_by)} — ${new Date(cell.checked_at).toLocaleString()}`
                                : undefined
                            }
                            onCheckedChange={(checked) => toggle(row.id, column.id, checked)}
                          />
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canEdit && (
        // Two groups that wrap as wholes, so the Checkbox/Text choice never
        // lands on a line away from the column it's about.
        <div className="flex flex-wrap gap-2 pt-1">
          <div className="flex gap-2">
            <Input
              aria-label={`Add a row to ${sheet.title}`}
              placeholder="Add a row…"
              className="max-w-48"
              value={newRow}
              onChange={(e) => setNewRow(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRow()}
            />
            <Button
              size="sm"
              variant="outline"
              aria-label={`Add row to ${sheet.title}`}
              disabled={!newRow.trim() || busy}
              onClick={addRow}
            >
              <PlusIcon />
              Row
            </Button>
          </div>
          <div className="flex gap-2">
            <Input
              aria-label={`Add a column to ${sheet.title}`}
              placeholder="Add a column…"
              className="max-w-48"
              value={newColumn}
              onChange={(e) => setNewColumn(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addColumn()}
            />
            <div
              role="group"
              aria-label="New column holds"
              className="flex items-center rounded-lg border p-0.5"
            >
              <Button
                size="xs"
                variant={newColumnKind === "check" ? "secondary" : "ghost"}
                aria-pressed={newColumnKind === "check"}
                onClick={() => setNewColumnKind("check")}
              >
                <SquareCheckIcon />
                Checkbox
              </Button>
              <Button
                size="xs"
                variant={newColumnKind === "text" ? "secondary" : "ghost"}
                aria-pressed={newColumnKind === "text"}
                onClick={() => setNewColumnKind("text")}
              >
                <TypeIcon />
                Text
              </Button>
            </div>
            <Button
              size="sm"
              variant="outline"
              aria-label={`Add column to ${sheet.title}`}
              disabled={!newColumn.trim() || busy}
              onClick={addColumn}
            >
              <PlusIcon />
              Column
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * One cell of a text column: the value in mono, since a version or a host
 * is data, and a click to edit it in place. Enter or leaving the cell saves,
 * Escape puts it back, and an empty value clears the cell. Tab saves and
 * moves on to the next cell, which is just the browser's own focus order.
 */
function SheetTextCell({
  label,
  cell,
  canEdit,
  onSave,
}: {
  label: string;
  cell: SheetCell | undefined;
  canEdit: boolean;
  onSave: (value: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  // What was just typed, shown until the refetch brings it back — without
  // it the old value flashes up between the save and the reload.
  const [pending, setPending] = useState<string | null>(null);
  // Escape unmounts the input, and a blur on the way out must not save.
  const cancelled = useRef(false);

  const saved = cell?.value ?? "";
  const shown = pending ?? saved;
  const who = cell
    ? `${personName(cell.checked_by)} — ${new Date(cell.checked_at).toLocaleString()}`
    : undefined;

  const start = () => {
    cancelled.current = false;
    setDraft(saved);
    setEditing(true);
  };

  const commit = async () => {
    setEditing(false);
    if (cancelled.current) return;
    const value = draft.trim();
    if (value === saved) return;
    setPending(value);
    try {
      await onSave(value);
    } finally {
      setPending(null);
    }
  };

  if (editing) {
    return (
      <Input
        autoFocus
        aria-label={label}
        className="h-7 font-mono"
        maxLength={500}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            cancelled.current = true;
            setEditing(false);
          }
        }}
      />
    );
  }

  const text = shown ? (
    <span className="font-mono tabular-nums break-words whitespace-pre-wrap">{shown}</span>
  ) : (
    <span className="text-muted-foreground">—</span>
  );

  if (!canEdit) {
    return (
      <div title={who} className="px-1.5 py-1">
        {text}
      </div>
    );
  }
  return (
    <button
      type="button"
      aria-label={`${label}: ${shown || "empty"}`}
      title={who}
      className="block min-h-7 w-full rounded-md px-1.5 py-1 text-left hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
      onClick={start}
    >
      {text}
    </button>
  );
}
