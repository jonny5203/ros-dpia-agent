import { createBrowserRouter } from "react-router";

import { Layout } from "@/components/Layout";
import { getCurrentUser } from "@/api/auth";
import Analysis from "@/routes/Analysis";
import Callback from "@/routes/Callback";
import Dashboard from "@/routes/Dashboard";
import ExportPage from "@/routes/Export";
import Login from "@/routes/Login";
import Ros from "@/routes/Ros";
import Upload from "@/routes/Upload";

async function rootLoader() {
  // /auth/me → 200 { user } or 401 (apiFetch already redirected to /login on 401).
  // Returning null lets Layout render nothing while that navigation is in flight.
  try {
    return { user: await getCurrentUser() };
  } catch {
    return { user: null };
  }
}

export const router = createBrowserRouter([
  {
    id: "root",
    path: "/",
    element: <Layout />,
    loader: rootLoader,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "projects/:id/documents", element: <Upload /> },
      { path: "projects/:id/analysis", element: <Analysis /> },
      { path: "projects/:id/ros", element: <Ros /> },
      { path: "projects/:id/export", element: <ExportPage /> },
    ],
  },
  { path: "/login", element: <Login /> },
  { path: "/callback", element: <Callback /> },
]);
