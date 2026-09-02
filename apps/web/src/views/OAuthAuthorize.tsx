import { ShieldAlertIcon, SparklesIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Session from "supertokens-auth-react/recipe/session";

import { ApiError, api } from "@/api";
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
import { AUTH_BASE_PATH } from "@/config";

type Preview = {
  client_name: string;
  scope: "read" | "write";
};

/**
 * The OAuth consent screen — what Claude.ai's and ChatGPT's own "connect an
 * MCP server" flows land on after Dynamic Client Registration.
 *
 * Deliberately **outside** the signed-in shell, the identical shape
 * `AcceptInvite.tsx` already uses: the preview is unauthenticated (a
 * client's name and scope ceiling are public metadata, safe to show before
 * signing in), and someone arriving with no session yet is sent to sign in
 * with `redirectToPath` carrying every original query param, so the whole
 * request survives the detour.
 *
 * The actual code-minting call (`POST /api/oauth/authorize/decision`)
 * re-validates everything server-side — see `services/oauth.py::decide` —
 * so nothing read from `window.location.search` here is trusted by the
 * server merely for having been echoed back.
 */
export default function OAuthAuthorize() {
  const [params] = useSearchParams();
  const clientId = params.get("client_id") ?? "";
  const redirectUri = params.get("redirect_uri") ?? "";
  const responseType = params.get("response_type") ?? "code";
  const codeChallenge = params.get("code_challenge") ?? "";
  const codeChallengeMethod = params.get("code_challenge_method") ?? "S256";
  const state = params.get("state");
  const resource = params.get("resource");

  const [preview, setPreview] = useState<Preview | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [scope, setScope] = useState<"read" | "write">("read");

  useEffect(() => {
    Session.doesSessionExist().then(setSignedIn);
    const query = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: responseType,
      code_challenge: codeChallenge,
      code_challenge_method: codeChallengeMethod,
    });
    api<Preview>(`/oauth/authorize/preview?${query}`)
      .then(setPreview)
      .catch((err) => {
        const detail =
          err instanceof ApiError
            ? (JSON.parse(err.body)?.detail?.error_description as string | undefined)
            : undefined;
        setError(detail ?? "This connection request isn't valid, or has expired.");
      });
    // Re-run only if the request itself changes — not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, redirectUri, responseType, codeChallenge, codeChallengeMethod]);

  const decide = async (allow: boolean) => {
    setDeciding(true);
    try {
      const { redirect_to } = await api<{ redirect_to: string }>("/oauth/authorize/decision", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          redirect_uri: redirectUri,
          response_type: responseType,
          code_challenge: codeChallenge,
          code_challenge_method: codeChallengeMethod,
          state,
          resource,
          allow,
          scope,
        }),
      });
      window.location.href = redirect_to;
    } catch {
      setError("Something went wrong finishing that. Try again from the app you were connecting.");
      setDeciding(false);
    }
  };

  const authHref = `${AUTH_BASE_PATH}?redirectToPath=${encodeURIComponent(
    `/oauth/authorize?${params.toString()}`,
  )}`;

  if (error) {
    return (
      <Screen>
        <Empty className="max-w-md">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ShieldAlertIcon />
            </EmptyMedia>
            <EmptyTitle>Can&rsquo;t connect that</EmptyTitle>
            <EmptyDescription>{error}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      </Screen>
    );
  }

  if (!preview || signedIn === null) {
    return (
      <Screen>
        <Spinner />
        <span className="sr-only">Loading</span>
      </Screen>
    );
  }

  return (
    <Screen>
      <Empty className="max-w-md">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <SparklesIcon />
          </EmptyMedia>
          <EmptyTitle>Connect {preview.client_name}</EmptyTitle>
          <EmptyDescription>
            {preview.client_name} wants to access your account. It&rsquo;ll be able to reach
            exactly what you can reach, and nothing more.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {signedIn ? (
            <div className="flex flex-col items-center gap-3">
              {preview.scope === "write" && (
                <div className="flex items-center gap-2 text-sm">
                  <label htmlFor="oauth-scope" className="text-muted-foreground">
                    Access
                  </label>
                  <select
                    id="oauth-scope"
                    className="h-8 rounded-lg border bg-background px-2 text-sm"
                    value={scope}
                    onChange={(e) => setScope(e.target.value as "read" | "write")}
                  >
                    <option value="read">Read only</option>
                    <option value="write">Can change things</option>
                  </select>
                </div>
              )}
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => decide(false)} disabled={deciding}>
                  Deny
                </Button>
                <Button onClick={() => decide(true)} disabled={deciding}>
                  {deciding ? "Connecting…" : `Allow ${preview.client_name}`}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Manage this later from Account → Connected apps.
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Button render={<a href={authHref} />} nativeButton={false}>
                Sign in or create an account
              </Button>
              <p className="text-xs text-muted-foreground">
                We&rsquo;ll bring you straight back here.
              </p>
            </div>
          )}
        </EmptyContent>
      </Empty>
    </Screen>
  );
}

function Screen({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">{children}</div>
  );
}
