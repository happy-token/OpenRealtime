---
status: accepted
---

# Independently deploy the frontend and session management service

The backend consists of the session management service and voice interaction
service. Both are backend services; the root UI is the frontend.

The user requires frontend/backend separation while retaining existing functions,
with local verification before deploying the backend to an application server and the frontend to Cloudflare.

The root Next.js application owns presentation, navigation, browser audio and
documentation. OpenNext runs it on Cloudflare. It does not authenticate users,
resolve provider secrets, access PostgreSQL, or read mutable product catalogs.
Presentation initialization crosses `/api/frontend/context` and
`/api/frontend/conversation`; identity, administrator grants, continuation
ownership, role selection and capabilities are decided by the session management service.
Responses are private and uncached. Frontend rendering forwards browser cookies
only to a configured backend origin, never following its redirects.

Existing route handlers move to `apps/backend/src/app/api`. Their TypeScript
implementations remain reusable under the shared source tree; this first phase
separates execution and build targets without a business-logic rewrite. The
backend has its own Next.js configuration, build and retention initialization.
It ships with full runtime dependencies and catalogs, not a standalone file-trace
bundle: tracing dynamic catalog roots is disabled in its build adapter.

The same public origin keeps `/api/*` and `/voice` compatibility. Cloudflare
forwards API requests without caching and preserves redirects, cookies, streams
and WebSocket upgrades. UI routes run in the frontend Worker. Existing public
Avatar media stays at the origin, retaining byte-range behavior. A local frontend
transport adapter proxies business requests for independent development/testing;
it does not implement business policy. Public documentation is materialized from
the explicit document catalog during the build.

Frontend builds use an isolated source projection and minimal environment. No
backend dotenv files, credentials or writable data volume enter the Worker.
`check-frontend-boundary.mjs` rejects runtime database, credential and filesystem
dependencies reachable from UI routes. OpenNext issue 1380 requires a bounded
build compatibility patch that inlines the actual middleware manifest, preserving
its content and failing if the loader shape changes.

ADR0028's React/Next navigation remains. ADR0049's Application Control Plane and
Realtime Session Plane semantics and ADR0050/0055's state authorities remain.
This phase does not expose ADR0027's loopback-only control plane or relocate
Voice Session Runtime. The session management service and voice runtime still share a
loopback control path and mutable data directories. Their network and storage
separation must precede migrating the voice runtime to another server; that is
subsequent work and is not claimed complete here.

Acceptance covers two local processes, real catalog/memory mutations and source
checks, history recovery/deletion, administrator login navigation, Workers runtime
rendering, independent builds, and a staged release with old Web/Worker rollback.
