/**
 * Which organisation you're in, at the top of the rail.
 *
 * Everything in this product is scoped to one organisation, so this can't be
 * buried in a settings page — the answer to "which one am I looking at" has to
 * be on screen on every screen. It doubles as the switcher and as the way in
 * to creating another.
 */

import { AnchorIcon, CheckIcon, ChevronsUpDownIcon, PlusIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";
import { BRAND } from "@/lib/brand";
import type { Organisation } from "@/lib/types";
import { ROLE_LABEL } from "@/lib/types";

export function OrgSwitcher({
  organisations,
  current,
  onCreate,
}: {
  organisations: Organisation[];
  current: Organisation | null;
  onCreate: () => void;
}) {
  const navigate = useNavigate();

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                size="lg"
                tooltip={current?.name ?? BRAND.name}
                className="data-[state=open]:bg-sidebar-accent"
              />
            }
          >
            <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <AnchorIcon className="size-4" />
            </div>
            <div className="grid flex-1 text-left leading-tight">
              <span className="truncate text-sm font-semibold">
                {current?.name ?? BRAND.name}
              </span>
              {/* Three states, not two. "No organisation yet" is only true
                  when there genuinely aren't any — on the organisations list
                  there's simply none *selected*, and saying otherwise tells
                  someone who just created one that it didn't work. */}
              <span className="truncate text-xs text-muted-foreground">
                {current
                  ? ROLE_LABEL[current.role]
                  : organisations.length === 0
                    ? "No organisation yet"
                    : organisations.length === 1
                      ? organisations[0].name
                      : `${organisations.length} organisations`}
              </span>
            </div>
            <ChevronsUpDownIcon className="ml-auto size-4 opacity-60" />
          </DropdownMenuTrigger>

          <DropdownMenuContent align="start" className="w-64">
            {/* **The label lives inside the group.** Base UI's `GroupLabel`
                reads a context that only `Menu.Group` provides, and outside
                one it throws on open — which, with no error boundary, used to
                blank the whole app the first time anybody clicked here. */}
            <DropdownMenuGroup>
              <DropdownMenuLabel>Organisations</DropdownMenuLabel>
              {organisations.length === 0 && (
                <DropdownMenuItem disabled>None yet</DropdownMenuItem>
              )}
              {organisations.map((org) => (
                <DropdownMenuItem key={org.id} onClick={() => navigate(`/orgs/${org.id}`)}>
                  <span className="truncate">{org.name}</span>
                  <span className="ml-auto flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {ROLE_LABEL[org.role]}
                    </span>
                    {org.id === current?.id && <CheckIcon className="size-4" />}
                  </span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onCreate}>
              <PlusIcon />
              New organisation
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
