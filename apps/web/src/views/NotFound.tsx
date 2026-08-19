import { CompassIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";

/**
 * The catch-all for a URL that matches nothing.
 *
 * Sits as the wildcard child of `Root` in main.tsx, so it renders inside the
 * shell for anyone signed in (rail and header intact, only the content area
 * is "not found") and behind `SessionAuth` for anyone who isn't — a bad link
 * while signed out asks for a sign-in first, exactly like any other deep
 * link, and lands here afterwards. Without a route matching `*` at all,
 * nothing in the tree matches an unknown path and the page renders blank —
 * no rail, no message, nothing to click.
 */
export default function NotFound() {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <CompassIcon />
        </EmptyMedia>
        <EmptyTitle>Nothing here</EmptyTitle>
        <EmptyDescription>
          This page doesn&rsquo;t exist — it may have moved, or the link was wrong.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button render={<Link to="/" />} nativeButton={false}>
          Take me home
        </Button>
      </EmptyContent>
    </Empty>
  );
}
