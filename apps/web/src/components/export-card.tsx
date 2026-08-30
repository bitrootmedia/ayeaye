import { DownloadIcon, PackageIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToastManager } from "@/components/ui/toast";
import { ago } from "@/lib/format";
import type { Export, ExportStatus } from "@/lib/types";

/** How often to re-check while something in the list is still building.
 *  Cleared the moment nothing is — contained to this card's own lifecycle
 *  rather than another global App.tsx poll, since nothing else on the page
 *  needs to know an export finished. */
const POLL_MS = 4_000;

const STATUS_LABEL: Record<ExportStatus, string> = {
  pending: "Preparing…",
  ready: "Ready",
  failed: "Failed",
  expired: "Expired",
};

/**
 * A "take your data" export: everything visible in this scope, one
 * directory per task. Reused unscoped (`projectId={null}`, the whole
 * organisation) and scoped to one project — the build itself always
 * reflects *your own* visibility, never anyone else's, so this card only
 * ever shows exports *you* started. See services/exports.py.
 */
export function ExportCard({ orgId, projectId }: { orgId: string; projectId: string | null }) {
  const toast = useToastManager();
  const [rows, setRows] = useState<Export[]>([]);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const all = await api<Export[]>(`/organisations/${orgId}/exports`).catch(() => []);
    setRows(all.filter((e) => e.project_id === projectId));
  }, [orgId, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something in the list is still building.
  useEffect(() => {
    const stillPending = rows.some((e) => e.status === "pending");
    if (stillPending && !pollRef.current) {
      pollRef.current = setInterval(load, POLL_MS);
    } else if (!stillPending && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [rows, load]);

  const start = async () => {
    setStarting(true);
    try {
      await api("/organisations/" + orgId + "/exports", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      });
      await load();
      toast.add({
        title: "Export started",
        description: "You'll be notified when it's ready to download.",
      });
    } finally {
      setStarting(false);
    }
  };

  const download = async (id: string) => {
    const { download_url } = await api<{ download_url: string }>(
      `/organisations/${orgId}/exports/${id}/download`,
    );
    window.location.href = download_url;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PackageIcon className="size-4" />
          Export data
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          {projectId
            ? "Everything you can see in this project — one folder per task, with its files inside."
            : "Everything you can see in this organisation — one folder per task, grouped by project, with files inside."}
        </p>
        <Button size="sm" onClick={start} disabled={starting}>
          Start export
        </Button>

        {rows.length > 0 && (
          <div className="space-y-2 border-t pt-3">
            {rows.map((row) => (
              <div key={row.id} className="flex items-center gap-3 text-sm">
                <Badge variant="outline">{STATUS_LABEL[row.status]}</Badge>
                <span className="font-mono text-xs text-muted-foreground">
                  {ago(row.created_at)}
                </span>
                <span className="flex-1" />
                {row.status === "ready" && (
                  <Button size="sm" variant="ghost" onClick={() => void download(row.id)}>
                    <DownloadIcon />
                    Download
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
