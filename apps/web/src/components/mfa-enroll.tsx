import { useEffect, useState } from "react";

import { ApiError, api } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { useToastManager } from "@/components/ui/toast";

/**
 * The TOTP enrollment flow: generate a secret, confirm it against a real
 * code, show backup codes once. Shared between the Account screen's
 * TwoFactorCard (turning 2FA on voluntarily) and MfaGate (an organisation
 * forcing it and this account not enrolled yet) — the flow is identical
 * either way, only what happens on completion differs.
 *
 * Nothing is persisted until `verify_totp` confirms the secret against a
 * real code, so there's no "abandoned pending device" to clean up if
 * someone never finishes.
 */
export function TotpEnroll({ onDone }: { onDone: () => void }) {
  const toast = useToastManager();
  const [step, setStep] = useState<"loading" | "scan" | "codes">("loading");
  const [secret, setSecret] = useState("");
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [codes, setCodes] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void api<{ secret: string; qr_data_uri: string }>("/me/mfa/totp", { method: "POST" }).then(
      (d) => {
        setSecret(d.secret);
        setQr(d.qr_data_uri);
        setStep("scan");
      },
    );
  }, []);

  const verify = async () => {
    if (!code.trim() || busy) return;
    setBusy(true);
    try {
      await api("/me/mfa/totp/verify", {
        method: "POST",
        body: JSON.stringify({ secret, code: code.trim() }),
      });
      const { codes: fresh } = await api<{ codes: string[] }>("/me/mfa/backup-codes", {
        method: "POST",
      });
      setCodes(fresh);
      setStep("codes");
    } catch (err) {
      const detail = err instanceof ApiError ? "That code is wrong." : "Try again.";
      toast.add({ title: "Couldn't confirm that", description: detail });
    } finally {
      setBusy(false);
    }
  };

  if (step === "loading") {
    return (
      <div className="flex items-center justify-center py-6">
        <Spinner />
      </div>
    );
  }

  if (step === "codes") {
    return (
      <div className="space-y-3">
        <p className="text-sm font-medium">
          Save these somewhere safe — they won&rsquo;t be shown again.
        </p>
        <p className="text-xs text-muted-foreground">
          Each one signs you in once, if you lose access to your authenticator app.
        </p>
        <ul className="grid grid-cols-2 gap-1.5 rounded-lg border bg-muted/30 p-3 font-mono text-sm">
          {codes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void navigator.clipboard.writeText(codes.join("\n"));
              toast.add({ title: "Copied" });
            }}
          >
            Copy all
          </Button>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={saved}
              onChange={(e) => setSaved(e.target.checked)}
            />
            I&rsquo;ve saved these
          </label>
        </div>
        <Button disabled={!saved} onClick={onDone}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
        {qr && (
          <img src={qr} alt="QR code for your authenticator app" className="size-40 shrink-0" />
        )}
        <div className="space-y-2 text-sm">
          <p className="text-muted-foreground">
            Scan this with an authenticator app (Google Authenticator, 1Password, Authy…), or
            enter the code by hand:
          </p>
          <code className="block w-fit rounded bg-muted px-2 py-1 font-mono text-xs break-all">
            {secret}
          </code>
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="totp-code">Code from the app</Label>
        <Input
          id="totp-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          className="w-32 font-mono"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && verify()}
        />
      </div>
      <Button disabled={!code.trim() || busy} onClick={verify}>
        Confirm
      </Button>
    </div>
  );
}
