/**
 * The navigation rail.
 *
 * The organisation switcher sits at the top rather than in a settings page:
 * everything in this product is scoped to one organisation, so which one
 * you're in has to be answerable from every screen.
 */

import {
  BellIcon,
  BellRingIcon,
  LayoutDashboardIcon,
  BuildingIcon,
  CircleDotIcon,
  ClockIcon,
  FolderKanbanIcon,
  LogOutIcon,
  MailIcon,
  MoonIcon,
  NetworkIcon,
  SunIcon,
  UserIcon,
  UsersIcon,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import type { Me } from "@/App";
import { OrgSwitcher } from "@/components/org-switcher";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import type { Organisation } from "@/lib/types";
import { useTheme } from "@/lib/theme";

export function AppSidebar({
  me,
  organisations,
  currentOrg,
  inviteCount,
  unread,
  remindersDue,
  onCreateOrg,
  onSignOut,
}: {
  me: Me | null;
  organisations: Organisation[];
  currentOrg: Organisation | null;
  inviteCount: number;
  /** Polled in the shell, so the count is right on every screen. */
  unread: number;
  remindersDue: number;
  onCreateOrg: () => void;
  onSignOut: () => void;
}) {
  const { theme, toggle } = useTheme();
  const { pathname } = useLocation();

  // Highlight the section, not the exact URL — a member's detail page is still
  // "People" as far as the rail is concerned.
  const isActive = (to: string, exact?: boolean) =>
    exact ? pathname === to || pathname === `${to}/` : pathname.startsWith(to);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <OrgSwitcher
          organisations={organisations}
          current={currentOrg}
          onCreate={onCreateOrg}
        />
      </SidebarHeader>

      <SidebarContent>
        {currentOrg && (
          <SidebarGroup>
            <SidebarGroupLabel>{currentOrg.name}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {[
                  {
                    to: `/orgs/${currentOrg.id}`,
                    label: "Dashboard",
                    icon: LayoutDashboardIcon,
                    exact: true,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/tasks`,
                    label: "Tasks",
                    icon: CircleDotIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/projects`,
                    label: "Projects",
                    icon: FolderKanbanIcon,
                  },
                  { to: `/orgs/${currentOrg.id}/time`, label: "Time", icon: ClockIcon },
                  { to: `/orgs/${currentOrg.id}/people`, label: "People", icon: UsersIcon },
                  {
                    to: `/orgs/${currentOrg.id}/structure`,
                    label: "Teams and groups",
                    icon: NetworkIcon,
                  },
                ].map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      isActive={isActive(item.to, item.exact)}
                      tooltip={item.label}
                      render={<Link to={item.to} />}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}

        <SidebarGroup>
          <SidebarGroupLabel>You</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isActive("/", true)}
                  tooltip="Organisations"
                  render={<Link to="/" />}
                >
                  <BuildingIcon />
                  <span>Organisations</span>
                </SidebarMenuButton>
                {/* An invitation nobody sees is an invitation nobody accepts,
                    and it can arrive while you're on any screen. */}
                {inviteCount > 0 && (
                  <SidebarMenuBadge className="font-mono text-primary">
                    <MailIcon className="mr-1 size-3" />
                    {inviteCount}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isActive("/notifications")}
                  tooltip="Notifications"
                  render={<Link to="/notifications" />}
                >
                  <BellIcon />
                  <span>Notifications</span>
                </SidebarMenuButton>
                {unread > 0 && (
                  <SidebarMenuBadge className="font-mono text-primary">{unread}</SidebarMenuBadge>
                )}
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isActive("/reminders")}
                  tooltip="Reminders"
                  render={<Link to="/reminders" />}
                >
                  <BellRingIcon />
                  <span>Reminders</span>
                </SidebarMenuButton>
                {/* Red, and the ONLY red outside the status scale — a reminder
                    that has come due is the definition of "this needs you",
                    which is exactly what that colour means here. */}
                {remindersDue > 0 && (
                  <SidebarMenuBadge className="font-mono text-status-blocker">
                    {remindersDue}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={isActive("/account")}
                  tooltip="Account"
                  render={<Link to="/account" />}
                >
                  <UserIcon />
                  <span>Account</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <div className="truncate px-2 py-1 font-mono text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
              {me?.display_name || me?.email || "signed in"}
            </div>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={toggle}
              tooltip={theme === "dark" ? "Switch to light" : "Switch to dark"}
            >
              {theme === "dark" ? <SunIcon /> : <MoonIcon />}
              <span>{theme === "dark" ? "Light" : "Dark"}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="Log out" onClick={onSignOut}>
              <LogOutIcon />
              <span>Log out</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
