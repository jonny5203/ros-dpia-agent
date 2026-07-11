# dpia-ros-frontend

React 19 + TypeScript SPA (Vite 6, Tailwind + shadcn/ui, React Router 7,
TanStack Query). Served by the compose `web` service (nginx) in production; in
dev the Vite server proxies `/api` to `http://localhost:8000`.

## Dev

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api -> :8000)
npm run typecheck  # tsc --noEmit
npm run lint       # eslint src
npm run build      # vite build -> dist/
```

## Adding shadcn components

`components.json` is already configured (Tailwind + CSS variables, neutral base,
`@/` alias). Add components on demand:

```bash
npx shadcn@latest add button card dialog table
```

## Layout

```
src/
  main.tsx          # React 19 root + RouterProvider + QueryClientProvider
  App.tsx           # router shell + nav layout
  api/client.ts     # credentialed fetch (BFF cookie) + problem+json error parsing
  routes/           # Dashboard (live /api/health), Upload, Analysis, Ros, Export, Login, Callback
  components/ui/    # shadcn primitives land here
  lib/utils.ts      # cn() helper
```

Auth (BFF/Keycloak) is wired in Phase 1; until then the SPA is reachable but
unauthenticated.
