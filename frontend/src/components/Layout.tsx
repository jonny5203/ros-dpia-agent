import { NavLink, Outlet, useRouteLoaderData, Navigate } from "react-router";

import type { CurrentUser } from "@/api/auth";

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/projects/hso/documents", label: "Upload" },
  { to: "/projects/hso/analysis", label: "Analysis" },
  { to: "/projects/hso/ros", label: "ROS" },
  { to: "/projects/hso/export", label: "Export" },
];

export function Layout() {
  const { user } = useRouteLoaderData("root") as { user: CurrentUser | null };

  // Loader is the primary guard; this covers the null-without-401 edge so we
  // never render protected content without a verified identity.
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b">
        <nav className="mx-auto flex max-w-6xl items-center gap-6 p-4">
          <span className="text-sm font-semibold">DPIA &amp; ROS Copilot</span>
          <div className="flex flex-1 gap-4">
            {NAV.map((item) => (
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
