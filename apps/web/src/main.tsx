import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import * as reactRouterDom from "react-router-dom";
import SuperTokens, { SuperTokensWrapper } from "supertokens-auth-react";
import EmailPassword from "supertokens-auth-react/recipe/emailpassword";
import { EmailPasswordPreBuiltUI } from "supertokens-auth-react/recipe/emailpassword/prebuiltui";
import Session, { SessionAuth } from "supertokens-auth-react/recipe/session";
import { getSuperTokensRoutesForReactRouterDom } from "supertokens-auth-react/ui";

import App from "@/App";
import { API_DOMAIN, AUTH_BASE_PATH, WEBSITE_DOMAIN } from "@/config";
import { AUTH_STYLE } from "@/lib/auth-theme";
import { BRAND } from "@/lib/brand";
import { applyStoredTheme } from "@/lib/theme";
import { lastOrg } from "@/lib/current-org";
import AcceptInvite from "@/views/AcceptInvite";
import Account from "@/views/Account";
import Dashboard from "@/views/Dashboard";
import OrganisationDetail from "@/views/OrganisationDetail";
import Organisations from "@/views/Organisations";
import Notifications from "@/views/Notifications";
import Reminders from "@/views/Reminders";
import ProjectDetail from "@/views/ProjectDetail";
import Projects from "@/views/Projects";
import TaskDetail from "@/views/TaskDetail";
import Tasks from "@/views/Tasks";
import Teams from "@/views/Teams";
import Time from "@/views/Time";

// Design tokens. Imported here, once, for the whole app.
import "@/index.css";

// Before React mounts: the auth screens live outside the shell, where
// `useTheme` never runs.
applyStoredTheme();

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
  recipeList: [EmailPassword.init(), Session.init()],
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SuperTokensWrapper>
      <BrowserRouter>
        <Routes>
          {/* Sign in, sign up, forgot password and reset password. */}
          {getSuperTokensRoutesForReactRouterDom(reactRouterDom, [EmailPasswordPreBuiltUI])}

          {/* Outside the shell and outside SessionAuth on purpose: whoever
              follows an invitation usually has no account yet. */}
          <Route path="/invites/:token" element={<AcceptInvite />} />

          {/* App is the shell (rail, header, the /me gate); screens render
              into its <Outlet>. Real routes rather than local-state nav, so
              every screen is bookmarkable and Back works. */}
          <Route
            path="/"
            element={
              <SessionAuth>
                <App />
              </SessionAuth>
            }
          >
            <Route index element={<Organisations />} />
            {/* The org's home is the dashboard. The people roster moved to
                /people — it's a reference screen you visit on purpose, and it
                was only the landing page by accident of being built first. */}
            <Route path="orgs/:orgId" element={<Dashboard />} />
            <Route path="orgs/:orgId/people" element={<OrganisationDetail />} />
            <Route path="orgs/:orgId/structure" element={<Teams />} />
            <Route path="orgs/:orgId/projects" element={<Projects />} />
            <Route path="orgs/:orgId/projects/:projectId" element={<ProjectDetail />} />
            <Route path="orgs/:orgId/tasks" element={<Tasks />} />
            <Route path="orgs/:orgId/tasks/:taskId" element={<TaskDetail />} />
            <Route path="orgs/:orgId/time" element={<Time />} />
            <Route path="notifications" element={<Notifications />} />
            {/* Personal and cross-organisation, like the inbox above it. */}
            <Route path="reminders" element={<Reminders />} />
            <Route path="account" element={<Account />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SuperTokensWrapper>
  </React.StrictMode>,
);
