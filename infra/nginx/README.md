# infra/nginx

The **runtime** nginx config used by the `web` service lives at
`frontend/nginx.conf`, because the `web` image is built from the `frontend/`
Docker build context and a Dockerfile can only `COPY` files inside its context.

This directory is reserved for a future **production/edge** nginx config (TLS
termination, larger `client_max_body_size` for uploads, SSE buffering tweaks,
etc.) used when `web` is deployed outside the single-origin dev compose stack.
