import { useEffect, useState } from "react";

import { ApiError, api } from "@/api";
import { TotpEnroll } from "@/components/mfa-enroll";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";

/**
 * Rendered by App.tsx in place of the whole shell whenever a session's own
 * `st-mfa-ok` claim isn't satisfied — see `security/authn.py`. Not a
 * SuperTokens prebuilt screen: there's nothing to restyle here because there
 * is no shadow DOM to restyle, this is a plain screen built with the same
 * components as everywhere else.
 *
 * Two states, decided by `GET /me/mfa/status`:
 *
 * - **Not enrolled** — an organisation forced this, and the account never
 *   turned 2FA on personally. Reuses the identical enrollment flow the
 *   Account screen offers voluntarily; there's no second implementation of
 *   "scan a QR, confirm a code."
 * - **Already enrolled** — enter the current code, or fall back to a backup
 *   code. Either path calls the server, which marks the session's claim
 *   satisfied and lets `onSatisfied` re-check `/me`.
 */
export function MfaGate({ onSatisfied }: { onSatisfied: () => void }) {
  const [status, setStatus] = useState<"loading" | "enroll" | "challenge">("loading");

  useEffect(() => {
    void api<{ enrolled: boolean }>("/me/mfa/status").then((d) =>
      setStatus(d.enrolled ? "challenge" : "enroll"),
    );
  }, []);

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Two-factor authentication</CardTitle>
        </CardHeader>
        <CardContent>
          {status === "loading" && (
            <div className="flex items-center justify-center py-6">
              <Spinner />
            </div>
          )}
          {status === "enroll" && (
            <>
              <p className="mb-4 text-sm text-muted-foreground">
                One of your organisations requires two-factor authentication. Set it up to
                continue.
              </p>
              <TotpEnroll onDone={onSatisfied} />
            </>
          )}
          {status === "challenge" && <Challenge onSatisfied={onSatisfied} />}
        </CardContent>
      </Card>
    </div>
  );
}

function Challenge({ onSatisfied }: { onSatisfied: () => void }) {
  const [useBackup, setUseBackup] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!code.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(useBackup ? "/me/mfa/backup-codes/redeem" : "/me/mfa/totp/challenge", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      onSatisfied();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? useBackup
            ? "That code is wrong or already used."
            : "That code is wrong."
          : "Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="mfa-code">{useBackup ? "Backup code" : "Code from your app"}</Label>
        <Input
          id="mfa-code"
          autoFocus
          inputMode={useBackup ? "text" : "numeric"}
          autoComplete="one-time-code"
          className="font-mono"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
      <Button disabled={!code.trim() || busy} onClick={submit} className="w-full">
        Continue
      </Button>
      <button
        type="button"
        className="text-sm text-muted-foreground underline underline-offset-2"
        onClick={() => {
          setUseBackup((v) => !v);
          setCode("");
          setError("");
        }}
      >
        {useBackup ? "Use your authenticator app instead" : "Lost your device? Use a backup code"}
      </button>
    </div>
  );
}
