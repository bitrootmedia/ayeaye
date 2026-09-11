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
  BookmarkIcon,
  LayoutDashboardIcon,
  BuildingIcon,
  CalendarDaysIcon,
  CalendarIcon,
  CircleDotIcon,
  CircleHelpIcon,
  ClockIcon,
  BookOpenIcon,
  FolderKanbanIcon,
  InboxIcon,
  LogOutIcon,
  MailIcon,
  MoonIcon,
  NetworkIcon,
  NotebookIcon,
  ScrollTextIcon,
  ServerCogIcon,
  SettingsIcon,
  SparklesIcon,
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
                    to: `/orgs/${currentOrg.id}/triage`,
                    label: "Triage",
                    icon: InboxIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/planner`,
                    label: "Planner",
                    icon: CalendarDaysIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/calendar`,
                    label: "Calendar",
                    icon: CalendarIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/notes`,
                    label: "Notes",
                    icon: NotebookIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/projects`,
                    label: "Projects",
                    icon: FolderKanbanIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/kb`,
                    label: "Knowledge base",
                    icon: BookOpenIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/bookmarks`,
                    label: "Bookmarks",
                    icon: BookmarkIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/changelog`,
                    label: "Changelog",
                    icon: ScrollTextIcon,
                  },
                  { to: `/orgs/${currentOrg.id}/time`, label: "Time", icon: ClockIcon },
                  { to: `/orgs/${currentOrg.id}/people`, label: "People", icon: UsersIcon },
                  {
                    to: `/orgs/${currentOrg.id}/structure`,
                    label: "Teams and groups",
                    icon: NetworkIcon,
                  },
                  {
                    to: `/orgs/${currentOrg.id}/settings`,
                    label: "Settings",
                    icon: SettingsIcon,
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
                  isActive={isActive("/sparks")}
                  tooltip="Sparks"
                  render={<Link to="/sparks" />}
                >
                  <SparklesIcon />
                  <span>Sparks</span>
                </SidebarMenuButton>
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
              {/* The installation's operator panel, for whoever holds an
                  `instance_admins` row — granted from the shell alone, never
                  from the panel itself. Hidden rather than disabled for
                  everybody else, the same "don't show a control that refuses"
                  rule as a task's Close button; the server answers 404 rather
                  than 403 regardless, so the surface isn't discoverable by
                  guessing the URL either. Last in the group because it is the
                  rarest item in the product by a distance. */}
              {me?.is_instance_admin && (
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={isActive("/instance")}
                    tooltip="Instance"
                    render={<Link to="/instance" />}
                  >
                    <ServerCogIcon />
                    <span>Instance</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}
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
              isActive={isActive("/help")}
              tooltip="Help"
              render={<Link to="/help" />}
            >
              <CircleHelpIcon />
              <span>Help</span>
            </SidebarMenuButton>
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
