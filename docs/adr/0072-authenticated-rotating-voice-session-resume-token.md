---
status: accepted
---

# Authenticate data-plane identity and rotate Voice Session Resume Tokens

The v2 WebSocket data plane authenticates the endpoint before processing SessionHello. Tenant, user, and device identity come from a trusted login session or bearer credential; self-reported Hello fields are untrusted metadata and never authorize a Session, Thread, Tool, or resume operation. Production profiles reject missing identity. An explicitly named localhost development profile may use a fixed unsafe identity only with prominent startup diagnostics.

Starting a Voice Session issues a cryptographically random 256-bit Resume Token. The owner-process Registry stores only its cryptographic hash and binds it to authenticated identity, `voice_session_id`, selected protocol version, and lifecycle/grace state. Resume requires both Session ID and token over the authenticated channel, and all bindings must match. The token is accepted only while the Session is detached within grace, rotates atomically after a successful attach, and is invalidated on closure, continuation, expiry, or identity change.

One Voice Session has at most one attached Endpoint. A second attach while active is rejected rather than silently taking over or creating split media ownership. Invalid ID, bad/old token, identity mismatch, active attachment, expired grace, and unknown Session produce non-enumerating `resume_rejected` or `continuation_required` outcomes and never disclose whether the named Session exists.

The browser stores the Resume Token only in tab-scoped memory or `sessionStorage`, never in URL, logs, IndexedDB, LocalStorage, analytics, or ordinary crash reports. The token is proof of permission to attempt same-session resume, not a user login, Thread ownership grant, API key, or permission to bypass Recovery/Admission barriers.

Starting a session accepts at most an optional `requested_thread_id`. If absent, the server creates a Thread owned by the authenticated tenant/user. If present, the server verifies current ownership/access before reading or binding it; concurrent tabs sharing a Thread are each authorized independently. A Continuation derives `thread_id` from the authoritative previous-Session/Journal relationship and rejects a conflicting client value. Thread authorization failures use the same non-enumerating error discipline, and a valid Resume Token alone never grants Thread access.

Contract and security tests cover guessed Session IDs, wrong tenant/user/device, missing authentication, token hash storage, old-token replay after rotation, concurrent attach, grace expiry, closure, protocol mismatch, generic error behavior, browser storage/log redaction, and explicit localhost-only unsafe mode.
