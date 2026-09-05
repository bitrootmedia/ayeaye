import { useState } from "react";
import EmailVerification from "supertokens-auth-react/recipe/emailverification";
import Session from "supertokens-auth-react/recipe/session";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToastManager } from "@/components/ui/toast";

/**
 * Rendered by App.tsx in place of the whole shell when `GET /me` comes back
 * refused because the session's email isn't verified — the same shape
 * `MfaGate` beside it uses, and for the same reason: the server decides, the
 * UI reacts to what it says.
 *
 * Not SuperTokens' own prebuilt "verify your email" screen. That one lives
 * at `/auth/verify-email` and is where the *link in the email* lands, which
 * this deliberately leaves alone. This is the other half — what you see when
 * you are already signed in and haven't clicked it yet — and building it as
 * a plain screen means it matches the rest of the product and needs none of
 * the shadow-DOM restyling `lib/auth-theme.ts` exists for.
 *
 * **Sign out is offered as prominently as resending.** The most likely reason
 * somebody is stuck here is a typo in the address, and the only way out of
 * that is a different account — a screen whose sole action is "we sent it
 * again, honest" is a trap.
 */
export function VerifyEmailGate({
  email,
  onVerified,
  onSignOut,
}: {
  email: string | null;
  onVerified: () => void;
  onSignOut: () => void;
}) {
  const toast = useToastManager();
  const [sending, setSending] = useState(false);
  const [checking, setChecking] = useState(false);

  const resend = async () => {
    setSending(true);
    try {
      const response = await EmailVerification.sendVerificationEmail();
      toast.add(
        response.status === "EMAIL_ALREADY_VERIFIED_ERROR"
          ? { title: "Already confirmed", description: "Try continuing again." }
          : { title: "Sent", description: "Check your inbox for the link." },
      );
    } catch {
      // With no SMTP configured the server logs the link rather than sending
      // it, and still answers OK — so a failure here is a real transport
      // problem, not the ordinary self-hosted case.
      toast.add({ title: "Couldn't send that", description: "Try again in a moment." });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Confirm your email</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            We sent a link to {email ? <span className="font-medium">{email}</span> : "your address"}
            . Open it to finish setting up your account.
          </p>
          <div className="flex flex-wrap gap-2">
            {/* Re-checks with the server rather than trusting the browser:
                the link is usually opened in another tab, or on a phone, and
                nothing tells this one about it. */}
            <Button
              disabled={checking}
              onClick={() => {
                void (async () => {
                  setChecking(true);
                  // **The refresh is the load-bearing part.** Verification
                  // is recorded against the account, but this browser's
                  // access token still carries the claim's old value — and
                  // SuperTokens' fetch interceptor refreshes on a 401, not
                  // on a 403 that says a claim failed. Without this, the
                  // button re-checks, gets the same stale answer, and puts
                  // you back on this screen forever.
                  //
                  // Doubly so because the link is usually opened somewhere
                  // else entirely: another tab, or a phone. Nothing tells
                  // this session about it.
                  try {
                    await Session.attemptRefreshingSession();
                  } catch {
                    // Falls through to the re-check, which will land back
                    // here if it really isn't verified yet.
                  }
                  onVerified();
                })();
              }}
            >
              I&rsquo;ve confirmed it
            </Button>
            <Button variant="outline" disabled={sending} onClick={() => void resend()}>
              Send it again
            </Button>
            <Button variant="ghost" onClick={onSignOut}>
              Sign out
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Wrong address? Sign out and make an account with the right one.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
