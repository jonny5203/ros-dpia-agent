import { Navigate, NavLink, Outlet, matchPath, useLocation, useRouteLoaderData } from "react-router";

import type { CurrentUser } from "@/api/auth";

export function Layout() {
  const { user } = useRouteLoaderData("root") as { user: CurrentUser | null };
  const location = useLocation();
  const activeProjectId =
    matchPath("/projects/:id/*", location.pathname)?.params.id ??
    import.meta.env.VITE_DEMO_PROJECT_ID;
  const projectPath = activeProjectId
    ? `/projects/${encodeURIComponent(activeProjectId)}`
    : null;
  const nav: { to: string; label: string; end?: boolean }[] = [
    { to: "/", label: "Dashboard", end: true },
    ...(projectPath
      ? [
          { to: `${projectPath}/documents`, label: "Upload" },
          { to: `${projectPath}/analysis`, label: "Analysis" },
          { to: `${projectPath}/ros`, label: "ROS" },
          { to: `${projectPath}/export`, label: "Export" },
        ]
      : []),
  ];

  // Loader is the primary guard; this covers the null-without-401 edge so we
  // never render protected content without a verified identity.
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b">
        <nav className="mx-auto flex max-w-6xl items-center gap-6 p-4">
          <span className="text-sm font-semibold">DPIA &amp; ROS Copilot</span>
          <div className="flex flex-1 gap-4">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  "text-sm " +
                  (isActive ? "font-medium text-foreground" : "text-muted-foreground")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
          <span className="text-sm text-muted-foreground">
            {user.name} · {user.role}
          </span>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl p-6">
        <Outlet />
      </main>
    </div>
  );
}
