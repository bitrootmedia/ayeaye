import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import * as reactRouterDom from "react-router-dom";
import SuperTokens, { SuperTokensWrapper } from "supertokens-auth-react";
import EmailPassword from "supertokens-auth-react/recipe/emailpassword";
import { EmailPasswordPreBuiltUI } from "supertokens-auth-react/recipe/emailpassword/prebuiltui";
import Session, { SessionAuth } from "supertokens-auth-react/recipe/session";
import { getSuperTokensRoutesForReactRouterDom } from "supertokens-auth-react/ui";

import App from "@/App";
import { ErrorBoundary } from "@/components/error-boundary";
import { API_DOMAIN, AUTH_BASE_PATH, WEBSITE_DOMAIN } from "@/config";
import { AUTH_STYLE } from "@/lib/auth-theme";
import { BRAND } from "@/lib/brand";
import { applyStoredTheme } from "@/lib/theme";
import { lastOrg } from "@/lib/current-org";
import AcceptInvite from "@/views/AcceptInvite";
import OAuthAuthorize from "@/views/OAuthAuthorize";
import Account from "@/views/Account";
import CalendarView from "@/views/Calendar";
import Dashboard from "@/views/Dashboard";
import Help from "@/views/Help";
import Landing, { Footer, Header } from "@/views/Landing";
import ArticleDetail from "@/views/ArticleDetail";
import BookDetail from "@/views/BookDetail";
import KnowledgeBase from "@/views/KnowledgeBase";
import OrganisationDetail from "@/views/OrganisationDetail";
import OrganisationSettings from "@/views/OrganisationSettings";
import Organisations from "@/views/Organisations";
import Notifications from "@/views/Notifications";
import NotFound from "@/views/NotFound";
import Notepad from "@/views/Notepad";
import Planner from "@/views/Planner";
import Reminders from "@/views/Reminders";
import ProjectDetail from "@/views/ProjectDetail";
import Projects from "@/views/Projects";
import Sparks from "@/views/Sparks";
import TaskDetail from "@/views/TaskDetail";
import Tasks from "@/views/Tasks";
import Teams from "@/views/Teams";
import Time from "@/views/Time";

// Design tokens. Imported here, once, for the whole app.
import "@/index.css";

// Before React mounts: the auth screens live outside the shell, where
// `useTheme` never runs.
applyStoredTheme();

// **A file dropped anywhere else must not navigate away.** The browser's
// default for a dropped file is to open it, which throws away a half-written
// comment and everything else on the page — and missing a drop target by
// twenty pixels is the normal case, not an edge one. Nothing else needs to
// happen here; the drop zones themselves stop propagation by handling it.
for (const type of ["dragover", "drop"] as const) {
  window.addEventListener(type, (event) => event.preventDefault());
}

SuperTokens.init({
  appInfo: {
    appName: BRAND.name,
    // Same origin for both — see config.ts. Because they match, the session
    // cookie is first-party and none of the cross-site cookie rules apply.
    apiDomain: API_DOMAIN,
    websiteDomain: WEBSITE_DOMAIN,
    apiBasePath: "/api/auth",
    websiteBasePath: AUTH_BASE_PATH,
  },
  getRedirectionURL: async (context) => {
    if (context.action === "SUCCESS") {
      // Honour ?redirectToPath first — it's what carries someone back to the
      // invitation link they were following when we asked them to sign in.
      if (context.redirectToPath) return context.redirectToPath;
      // Otherwise drop back into the organisation you were last in, rather
      // than onto a chooser you have to click through every session. If it's
      // gone or you've been removed, that screen says so and links back.
      const last = lastOrg();
      return last ? `/orgs/${last}` : "/";
    }
    return undefined;
  },
  // The pre-built auth screens, restyled with the product's own tokens rather
  // than a second palette — see lib/auth-theme.ts.
  style: AUTH_STYLE,
  recipeList: [
    EmailPassword.init({
      signInAndUpFeature: {
        signUpForm: {
          formFields: [
            // A courtesy pre-check echoing `security/authn.py`'s own
            // `strong_password_validator` — the server is what actually
            // decides (and the reset-password screen has no equivalent
            // client-side hook, so it always round-trips), but matching the
            // rule here means sign-up doesn't wait on a request for the
            // common case. The sign-in form is untouched: an account made
            // before this policy tightened must still be able to log in.
            {
              id: "password",
              label: "Password",
              validate: async (value: string) => {
                if (typeof value !== "string" || value.length < 10) {
                  return "Use at least 10 characters.";
                }
                if (!/[a-z]/.test(value)) return "Include at least one lowercase letter.";
                if (!/[A-Z]/.test(value)) return "Include at least one uppercase letter.";
                if (!/[0-9]/.test(value)) return "Include at least one number.";
                return undefined;
              },
            },
          ],
        },
      },
    }),
    Session.init(),
  ],
});

/** See the `__crash` route. */
function Crash(): React.ReactNode {
  throw new Error("deliberate crash, for testing the error boundary");
}

/**
 * The landing page's header and footer, around the sign-in/sign-up/reset
 * screens and nowhere else.
 *
 * Those screens are SuperTokens' own routes — `getSuperTokensRoutesForReactRouterDom`
 * hands back a flat list of `<Route>`s with their own absolute paths, so they
 * can't be nested under a layout route the way `orgs/:orgId/*` is under
 * `Root`. Wrapping the whole `<Routes>` tree in a pathname check instead
 * sidesteps that: everywhere else this is a no-op passthrough, since the app
 * shell (`App.tsx`) already supplies its own chrome.
 *
 * Without this, `/auth` was a dead end — no way back to `/` except the
 * browser's own Back button, which doesn't exist if it's the tab's first page.
 */
function AuthChrome({ children }: { children: React.ReactNode }): React.ReactNode {
  const onAuthPages = useLocation().pathname.startsWith(AUTH_BASE_PATH);
  if (!onAuthPages) return children;
  return (
    <div className="flex min-h-dvh flex-col">
      <Header />
      <div className="flex-1">{children}</div>
      <Footer />
    </div>
  );
}

/**
 * What `/` is depends on whether you're anybody yet.
 *
 * Signed in it is the shell, exactly as before. Signed out it is the landing
 * page — the one public screen in the product.
 *
 * This is the layout route's element, so it stands in front of every child
 * route too, which is the reason for the pathname test: a stranger following
 * a deep link to `/orgs/…` must still hit `SessionAuth` and be sent to sign in
 * with `redirectToPath` set, so they land where they were going. Only the bare
 * root is public. Getting that backwards would replace every "please sign in"
 * with a marketing page and quietly lose the link they arrived on.
 *
 * `Landing` renders no `<Outlet>`, so no child route can render underneath it.
 */

/**
 * A detail screen, keyed to the thing it is showing.
 *
 * **Going from one task straight to another — from ⌘K, say — matches the
 * same route, so React Router keeps the same component instance.** Every
 * piece of local state seeded from the old one then survives the
 * navigation: `Details` on the task screen holds its title in
 * `useState(task.title)`, which only ever runs on mount, so the input went
 * on showing the *previous* task's title while everything fed straight
 * from props around it updated. That was the reported bug, and it is a
 * whole class rather than one field — the same `useState(project.name)`
 * shape is in `ProjectDetail` and `BookDetail`, and the task screen also
 * carried its collapsed-panel state, a half-typed delete confirmation and
 * a half-written comment across.
 *
 * Keying on the id says the true thing — a different task is a different
 * screen — and fixes the class rather than each field, which is the only
 * version that stays fixed as fields are added. The cost is a remount, and
 * a remount is what a fresh page load already does: everything here
 * refetches on the id anyway, and `use-realtime`'s 250ms linger exists
 * precisely so subscription churn like this drops nothing.
 */
function Keyed({ param, element }: { param: string; element: React.ReactElement }) {
  const params = reactRouterDom.useParams();
  return <React.Fragment key={params[param]}>{element}</React.Fragment>;
}

function Root(): React.ReactNode {
  const session = Session.useSessionContext();
  const atRoot = useLocation().pathname === "/";

  // Briefly, on a cold load, before the session context resolves. Rendering
  // the landing page here instead would flash it at everybody who is already
  // signed in, on every refresh.
  if (session.loading) return null;

  if (atRoot && !session.doesSessionExist) return <Landing />;

  return (
    <SessionAuth>
      <App />
    </SessionAuth>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SuperTokensWrapper>
      {/* Outermost: a render error anywhere unmounts the whole tree, so the
          only place that can still show something is above all of it. */}
      <ErrorBoundary>
        <BrowserRouter>
          <AuthChrome>
            <Routes>
              {/* Sign in, sign up, forgot password and reset password. */}
              {getSuperTokensRoutesForReactRouterDom(reactRouterDom, [
                EmailPasswordPreBuiltUI,
              ])}

              {/* Outside the shell and outside SessionAuth on purpose: whoever
                follows an invitation usually has no account yet. */}
              <Route path="/invites/:token" element={<AcceptInvite />} />

              {/* The OAuth consent screen — same reasoning as the invite
                link above it: it does its own signed-in check and its own
                "sign in, then come straight back" redirect rather than
                relying on SessionAuth, since the query string it needs to
                preserve wouldn't survive that gate's own redirect. */}
              <Route path="/oauth/authorize" element={<OAuthAuthorize />} />

              {/* Signed in, this is the shell (rail, header, the /me gate) and
                screens render into its <Outlet>; signed out, `/` alone is the
                landing page. Real routes rather than local-state nav, so every
                screen is bookmarkable and Back works. */}
              <Route path="/" element={<Root />}>
                <Route index element={<Organisations />} />
                {/* The org's home is the dashboard. The people roster moved to
                  /people — it's a reference screen you visit on purpose, and it
                  was only the landing page by accident of being built first. */}
                <Route path="orgs/:orgId" element={<Dashboard />} />
                <Route
                  path="orgs/:orgId/people"
                  element={<OrganisationDetail />}
                />
                <Route
                  path="orgs/:orgId/settings"
                  element={<OrganisationSettings />}
                />
                <Route path="orgs/:orgId/structure" element={<Teams />} />
                <Route path="orgs/:orgId/projects" element={<Projects />} />
                <Route
                  path="orgs/:orgId/projects/:projectId"
                  element={<Keyed param="projectId" element={<ProjectDetail />} />}
                />
                <Route path="orgs/:orgId/tasks" element={<Tasks />} />
                <Route
                  path="orgs/:orgId/tasks/:taskId"
                  element={<Keyed param="taskId" element={<TaskDetail />} />}
                />
                <Route path="orgs/:orgId/kb" element={<KnowledgeBase />} />
                <Route
                  path="orgs/:orgId/kb/books/:bookId"
                  element={<Keyed param="bookId" element={<BookDetail />} />}
                />
                <Route
                  path="orgs/:orgId/kb/articles/:articleId"
                  element={<Keyed param="articleId" element={<ArticleDetail />} />}
                />
                <Route path="orgs/:orgId/planner" element={<Planner />} />
                <Route path="orgs/:orgId/calendar" element={<CalendarView />} />
                <Route path="orgs/:orgId/notes" element={<Notepad />} />
                <Route path="orgs/:orgId/time" element={<Time />} />
                <Route path="notifications" element={<Notifications />} />
                {/* Personal and cross-organisation, like the inbox above it. */}
                <Route path="reminders" element={<Reminders />} />
                <Route path="sparks" element={<Sparks />} />
                <Route path="account" element={<Account />} />
                <Route path="help" element={<Help />} />
                {/* A route that throws, so the error boundary can be tested
                    rather than assumed. **Dev only** — `import.meta.env.DEV` is
                    a compile-time constant, so this and the component below are
                    removed from a production build entirely.
                    A boundary nobody exercises is a boundary that has quietly
                    stopped working, and it only gets discovered on the day it
                    was needed. */}
                {import.meta.env.DEV && <Route path="__crash" element={<Crash />} />}
                {/* Catches everything else. Without a wildcard here, a URL
                    matching no route above matches nothing in the tree at
                    all — not even Root — and renders a blank page: no rail,
                    no message, nothing to click. */}
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </AuthChrome>
        </BrowserRouter>
      </ErrorBoundary>
    </SuperTokensWrapper>
  </React.StrictMode>,
);
