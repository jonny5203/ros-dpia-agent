# syntax=docker/dockerfile:1
# Multi-stage: build the SPA with Node, serve it with nginx.

# ── build ───────────────────────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install --no-audit --no-fund
COPY . .
RUN npm run build

# ── serve ───────────────────────────────────────────────────────────────
FROM nginx:alpine
# curl is required for the container healthcheck.
RUN apk add --no-cache curl
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
