import { AnchorIcon, ShieldAlertIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Session from "supertokens-auth-react/recipe/session";

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
import { AUTH_BASE_PATH } from "@/config";
import { ROLE_LABEL, type Organisation, type Role } from "@/lib/types";

type Preview = {
  organisation_name: string;
  invited_email: string | null;
  role: Role;
  invited_by: string | null;
};

/**
 * The invitation link.
 *
 * Deliberately **outside** the signed-in shell. Most people opening one of
 * these have no account yet, and putting it behind a session gate would mean
 * signing up for something you haven't been allowed to look at. The preview is
 * unauthenticated and shows only the organisation's name — enough to decide,
 * nothing about its contents.
 */
export default function AcceptInvite() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();

  const [preview, setPreview] = useState<Preview | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);

  useEffect(() => {
    Session.doesSessionExist().then(setSignedIn);
    api<Preview>(`/invites/${token}`)
      .then(setPreview)
      .catch(() => setError("That invitation link is no longer valid."));
  }, [token]);

  const join = async () => {
    setJoining(true);
    try {
      const org = await api<Organisation>(`/invites/${token}/accept`, { method: "POST" });
      navigate(`/orgs/${org.id}`);
    } catch {
      setError("That invitation link is no longer valid.");
      setJoining(false);
    }
  };

  // Come back here after signing in or registering, so the link survives the
  // detour rather than dropping people on an empty home screen.
  const authHref = `${AUTH_BASE_PATH}?redirectToPath=${encodeURIComponent(`/invites/${token}`)}`;

  if (error) {
    return (
      <Screen>
        <Empty className="max-w-md">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ShieldAlertIcon />
            </EmptyMedia>
            <EmptyTitle>This link doesn&rsquo;t work any more</EmptyTitle>
            <EmptyDescription>
              Invitation links are single-use and can be revoked. Ask whoever invited you to
              send a fresh one.
            </EmptyDescription>
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
            <AnchorIcon />
          </EmptyMedia>
          <EmptyTitle>Join {preview.organisation_name}</EmptyTitle>
          <EmptyDescription>
            {preview.invited_by ? `${preview.invited_by} invited` : "You've been invited"}{" "}
            {preview.invited_email ? (
              <span className="font-mono text-xs">{preview.invited_email}</span>
            ) : (
              "you"
            )}{" "}
            to join as {ROLE_LABEL[preview.role].toLowerCase()}.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {signedIn ? (
            <Button onClick={join} disabled={joining}>
              {joining ? "Joining…" : `Join ${preview.organisation_name}`}
            </Button>
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
