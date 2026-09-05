import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api";
import { Header, Footer } from "@/views/Landing";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

/**
 * Where the "confirm this address" link lands.
 *
 * Outside the shell and outside `SessionAuth`, exactly like `AcceptInvite`
 * beside it — and for a sharper reason. The link is sent *to the address
 * being confirmed*, so it is very often opened in a different browser from
 * the one that asked for it, by someone who may not be signed in there at
 * all. A page that demanded a session would work least often precisely where
 * it is most likely to be opened.
 *
 * The token is the authority; the server decides. This page's whole job is
 * to POST it once and say what happened in words.
 */
export default function ConfirmNotificationEmail() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [detail, setDetail] = useState<{ organisation_name: string; email: string } | null>(null);

  useEffect(() => {
    if (!token) return setState("failed");
    // Once, on mount. Deliberately not a button somebody has to press: they
    // already pressed one, in their mail client.
    api<{ organisation_name: string; email: string }>(
      `/notification-emails/confirm/${token}`,
      { method: "POST" },
    )
      .then((d) => {
        setDetail(d);
        setState("done");
      })
      .catch(() => setState("failed"));
  }, [token]);

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <Header />
      <main className="flex flex-1 items-center justify-center p-6">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>
              {state === "working" && "Confirming…"}
              {state === "done" && "Address confirmed"}
              {state === "failed" && "That link didn't work"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {state === "working" && (
              <div className="flex justify-center py-4">
                <Spinner />
              </div>
            )}
            {state === "done" && detail && (
              <p className="text-sm text-muted-foreground">
                {detail.organisation_name} notifications will go to{" "}
                <span className="font-medium">{detail.email}</span> from now on. You can change
                that any time on your account.
              </p>
            )}
            {state === "failed" && (
              // One message for expired, already-used and never-existed,
              // because the server deliberately doesn't distinguish them —
              // saying which would tell a stranger that a token once
              // existed.
              <p className="text-sm text-muted-foreground">
                It may have expired, or already been used. Ask for a new one from your account
                and nothing will have changed in the meantime — notifications keep going to the
                address on your account until one is confirmed.
              </p>
            )}
            <Button render={<Link to="/account" />} nativeButton={false}>
              Go to your account
            </Button>
          </CardContent>
        </Card>
      </main>
      <Footer />
    </div>
  );
}
