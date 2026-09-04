---
status: accepted
---

# Device Fleet: standardized Seam contract, no bundled implementation

Multi-device-ecosystem support (the PRD's 小智 reference) bundles four concerns that don't belong in one place. The wire protocol (MQTT+UDP/WebSocket framing, capability negotiation, Opus audio) is a Transport Adapter, consistent with the existing Transport Adapter Seam. Device-side MCP/tool announcement is just another dynamic source feeding the existing Tool Normalization layer (ADR-0001) — no new Seam needed. Device activation, OTA firmware distribution, and device-fleet inventory get their own new Seam, **Device Fleet**, but the framework ships only the standardized contract (`activate`/`checkFirmware`/`listDevices`) plus a minimal in-memory default (single-process, no persistence, no real OTA delivery) — never a production-grade implementation.

We considered two alternatives: excluding device-fleet concerns from the framework entirely (leaving deployers to bolt on their own solution with no shared contract), and having the framework ship a fully working fleet-management implementation (activation server, OTA delivery, device inventory — closer to 小智's own manager backend). We rejected full exclusion because the user specifically wants deployers to get a professional, standardized integration point, not silence. We rejected a bundled real implementation because owning IoT fleet operations (persistence, OTA delivery infrastructure, credential issuance) is a different product than "voice interface + dialogue state management" and would make the core framework responsible for a subsystem it has no comparative advantage in. The standardized-contract-only middle path is not the obvious choice a reader would guess — it's neither "in" nor "out" — so it's recorded here.
