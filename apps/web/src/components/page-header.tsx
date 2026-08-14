import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

export type Crumb = { label: string; to?: string };

/**
 * Title block for a screen.
 *
 * The trail earns its place once access is per-resource: you can be looking at
 * a task in a project you were granted individually, inside an organisation
 * whose other projects you can't see at all. The breadcrumb is what tells you
 * where you actually are.
 */
export function PageHeader({
  crumbs = [],
  title,
  description,
  actions,
}: {
  crumbs?: Crumb[];
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      {crumbs.length > 0 && (
        <Breadcrumb>
          <BreadcrumbList>
            {crumbs.map((crumb, i) => (
              <BreadcrumbItem key={`${crumb.label}-${i}`}>
                {crumb.to ? (
                  <BreadcrumbLink render={<Link to={crumb.to} />}>{crumb.label}</BreadcrumbLink>
                ) : (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                )}
                {/* Separator by position, not by linkedness. Keying it off
                    `crumb.to` ran two unlinked crumbs together — a task inside
                    a project you can only see the name of rendered as
                    "Hull refit Strip the old antifoul". */}
                {i < crumbs.length - 1 && <BreadcrumbSeparator />}
              </BreadcrumbItem>
            ))}
          </BreadcrumbList>
        </Breadcrumb>
      )}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-xl font-semibold">{title}</h1>
          {description && (
            <div className="max-w-prose text-sm text-muted-foreground">{description}</div>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
