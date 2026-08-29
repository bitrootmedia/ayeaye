import { Grid3x3Icon, PlusIcon, RotateCcwIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useToastManager } from "@/components/ui/toast";
import { personName, type Sheet } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Every sheet on a task — a grid checklist, more than one allowed.
 *
 * The same reason multiple checklists are allowed: "Weekly maintenance" and
 * "Security audit" are two different grids, not two sections of one. Rows
 * and columns are freeform labels — servers down one side, repeatable
 * checks across the top — and a cell is a checkbox at their intersection.
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
}: {
  orgId: string;
  taskId: string;
  canEdit: boolean;
  refreshKey?: number;
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

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const addSheet = async () => {
    if (!newTitle.trim() || addingSheet) return;
    setAddingSheet(true);
    try {
      await api(base, { method: "POST", body: JSON.stringify({ title: newTitle.trim() }) });
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

  if (sheets !== null && sheets.length === 0 && !canEdit) return null;

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
  const [busy, setBusy] = useState(false);

  const base = `/organisations/${orgId}/tasks/${taskId}/sheets/${sheet.id}`;
  const checkedByCell = new Map(sheet.cells.map((c) => [`${c.row_id}:${c.column_id}`, c]));

  const fail = (err: unknown, title: string) => {
    const detail = err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
    toast.add({ title, description: detail });
  };

  const toggle = async (rowId: string, columnId: string, checked: boolean) => {
    try {
      await api(`${base}/cells/${rowId}/${columnId}`, { method: checked ? "PUT" : "DELETE" });
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't update that cell");
    }
  };

  const addRow = async () => {
    if (!newRow.trim() || busy) return;
    setBusy(true);
    try {
      await api(`${base}/rows`, { method: "POST", body: JSON.stringify({ label: newRow.trim() }) });
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
        body: JSON.stringify({ label: newColumn.trim() }),
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
        {canEdit && sheet.cells.length > 0 && (
          <Button size="sm" variant="ghost" aria-label={`Reset ${sheet.title}`} onClick={reset}>
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
                  <th key={column.id} className="border-b border-l p-2 text-center font-medium">
                    <div className="flex items-center justify-center gap-1">
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
        <div className="flex flex-wrap gap-2 pt-1">
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
          <Input
            aria-label={`Add a column to ${sheet.title}`}
            placeholder="Add a column…"
            className="max-w-48"
            value={newColumn}
            onChange={(e) => setNewColumn(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addColumn()}
          />
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
      )}
    </div>
  );
}
