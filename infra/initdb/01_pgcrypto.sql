-- Applied once on first Postgres init (docker-entrypoint-initdb.d).
-- pgcrypto gives us gen_random_uuid() for UUID primary keys (see §6.1).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
