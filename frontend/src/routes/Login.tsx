import { useEffect } from "react";
import { useSearchParams } from "react-router";

import { getLoginUrl } from "@/api/auth";

export default function Login() {
  const [params] = useSearchParams();
  const hasError = params.has("error");

  useEffect(() => {
    // No error → kick off the OIDC flow immediately (seamless 401 → Keycloak).
    // An error param means Keycloak reported a failure on a previous attempt;
    // render the retry UI below instead of looping back into the flow.
    if (!hasError) window.location.assign(getLoginUrl());
  }, [hasError]);

  if (hasError) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="space-y-4 text-center">
          <h1 className="text-2xl font-semibold">Login failed</h1>
          <p className="text-muted-foreground">
            The sign-in was cancelled or rejected by the identity provider.
          </p>
          <button
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            onClick={() => window.location.assign(getLoginUrl())}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">Redirecting to login…</p>
    </div>
  );
}
