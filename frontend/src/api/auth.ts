import { apiFetch } from "@/api/client";

export type AppRole =
  | "admin"
  | "privacy-officer"
  | "it-security"
  | "project-manager"
  | "viewer";

export interface CurrentUser {
  sub: string;
  email: string;
  name: string;
  role: AppRole;
  is_admin: boolean;
}

export const getCurrentUser = () => apiFetch<CurrentUser>("/auth/me");

export const getLoginUrl = () => "/auth/login";
