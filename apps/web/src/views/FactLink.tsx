import { LockIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { api } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import type { Fact } from "@/lib/types";

/**
 * `/orgs/:orgId/kb/facts/:factId` — a fact's permalink.
 *
 * A fact has no screen of its own; it is a row in its book. But a link to
 * one has to be stable on its own — ⌘K hands back a fact's id, and so does
 * the `recall` MCP tool, which an assistant quotes back to a person — and
 * the id alone doesn't say which book. So this resolves the fact and
 * replaces itself with the book, the fact picked out (`?fact=`). The same
 * 404-is-no-access screen the book shows, because a fact in a book you
 * can't see doesn't exist as far as you're concerned.
 */
export default function FactLink() {
  const { orgId, factId } = useParams<{ orgId: string; factId: string }>();
  const [fact, setFact] = useState<Fact | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    void api<Fact>(`/organisations/${orgId}/kb/facts/${factId}`)
      .then(setFact)
      .catch(() => setGone(true));
  }, [orgId, factId]);

  if (fact) {
    return <Navigate replace to={`/orgs/${orgId}/kb/books/${fact.book_id}?fact=${fact.id}`} />;
  }
  if (!gone) {
    return (
      <div className="flex flex-1 items-center justify-center py-12">
        <Spinner />
        <span className="sr-only">Loading</span>
      </div>
    );
  }
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <LockIcon />
        </EmptyMedia>
        <EmptyTitle>You don&rsquo;t have access to this fact</EmptyTitle>
        <EmptyDescription>
          It may have been deleted, or it&rsquo;s in a book that was never shared with you.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button render={<Link to={`/orgs/${orgId}/kb`} />} nativeButton={false}>
          Back to the knowledge base
        </Button>
      </EmptyContent>
    </Empty>
  );
}
