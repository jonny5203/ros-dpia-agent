import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { getCurrentUser } from "@/api/auth";

export default function Callback() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  useEffect(() => {
    // Verify the session cookie the backend just set actually authenticates us.
    // On 401, apiFetch redirects to /login — no explicit error branch needed.
    getCurrentUser()
      .then(() => navigate(params.get("ret") ?? "/", { replace: true }))
      .catch(() => {
        /* redirectToLogin already fired inside apiFetch */
      });
  }, [navigate, params]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-muted-foreground">Completing sign-in…</p>
    </div>
  );
}
