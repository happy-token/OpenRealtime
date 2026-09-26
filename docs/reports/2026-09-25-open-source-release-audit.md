# Open-source release audit — 2026-09-25

## Inspected surface

- The tracked repository contains Next.js pages and API routes, a Python WebSocket voice runtime, PostgreSQL migrations, an optional local avatar renderer, and optional GPU inference services. A static-only Cloudflare deployment would omit required behavior.
- `.env` and `.env.local` are ignored; `.env.example` is tracked with placeholders. The tracked tree and all 124 local Git revisions were searched for common private-key, AWS access-key, and long `sk-` token signatures; no matching files were found. This pattern scan does not replace provider-side key rotation or an external secret scanner.
- The tracked media inventory has eight PNG/JPEG design screenshots, no tracked video, audio, model weights, or credential files. Copyright and portrait rights for screenshots still require owner confirmation before a public release.

## Public exposure gates

| Area | Current control | Release check |
| --- | --- | --- |
| Platform voice | Server admission, 180-second default, independent ASR and TTS concurrency defaults of one | Verify public-ticket proxy, provider hard spending limits, rejection and release under concurrent traffic |
| Paid image/video creation | HappyImage requires administrator access and same-origin mutation; Vidu and LTX also restrict production submission | Verify anonymous and ordinary-user requests cannot spend platform credentials |
| Personal service | Account-owned encrypted token; exact operator-approved HTTPS origin; redirects disabled | Apply migration 0022, set stable encryption key and approved origins, verify service ownership and provider logs |
| Stored assets | Several runtime paths use local `.openrealtime` and `public/digital-human` files | Mount durable private storage; avoid multi-instance Web replicas until shared storage and job coordination are implemented |
| User identity | Casdoor user session is separate from administrator access | Configure production callback, secure cookies, PostgreSQL, and proxy origin before enabling sign-in |

## Deployment decision

Use Cloudflare for DNS/TLS/caching and run Web, Python, and PostgreSQL on conventional hosts. Cache static assets only. Keep WebSocket, authentication, user media, and all `/api` routes uncached. Follow [the deployment guide](../deployment/public-trial.md) for the explicit release checks.
