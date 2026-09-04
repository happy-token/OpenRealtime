---
status: accepted
---

# ByteWebSearch: a real vendor conformer for the WebSearch Protocol

ADR-0014 shipped `WebSearch` with `DeterministicWebSearch` as its only
conformer and explicitly deferred a real vendor "until credentials and a
vendor choice are actually available." That choice has now been made:
ByteDance's own search API ("byte"), the same one the research reference
project ("voiceloop", `brain/byte_search.py`) already speaks. This ADR
closes that deferral.

`ByteWebSearch` (`web_search/byte_web_search.py`) POSTs JSON to
`https://open.feedcoopapi.com/search_api/web_search` (overridable via
`BYTE_WEB_SEARCH_BASE_URL`) with a bearer token read from
`BYTE_WEB_SEARCH_API_KEY`, and adapts the response's `Result.WebResults`
array directly into the Protocol's flat `list[str]` — one
`"{title}\n{summary}\n{url}"` passage per result, truncated to `top_k`.
Voiceloop's own conformer talks to the identical endpoint with an
`aiohttp`-based client and a much richer `LookupEvidence` dataclass;
neither was ported as-is, for two reasons:

- OpenRealtime already has an established, dependency-free pattern for a
  real HTTP-calling conformer — `OpenAiCompatibleLlmClient`
  (`brain/llm_clients.py`): stdlib `urllib.request.Request`/`urlopen`
  wrapped in `asyncio.to_thread`. `ByteWebSearch` reuses that exact shape
  rather than adding `aiohttp` as a new dependency, keeping with this
  project's "framework, not application" minimalism — one HTTP client
  pattern for the whole codebase, not one per vendor.
- `WebSearch.search()`'s contract is `list[str]`, not a rich evidence
  object. Voiceloop's `normalize_result_url` exists to guard against
  SSRF/private-IP results before they're rendered as clickable links or
  fetched further downstream. OpenRealtime never does either — a
  `WebSearch` result is inert text handed straight to an LLM as a tool
  result — so there is no consumer-side risk on OpenRealtime's end for that
  filtering to protect against, and it was left out rather than carried
  over speculatively.

Failures raise a dedicated `ByteWebSearchError` rather than returning
`[]`. This distinction matters because `WebSearchToolSource._search`
already treats an empty list as "No results found." and forwards that to
the LLM as an ordinary, non-error answer — appropriate for the Protocol's
own "well-formed response, zero matches" case, but wrong for a genuine
network or vendor-shape failure, which would otherwise be silently
reported to the LLM as "nothing found" instead of "the search backend is
unavailable." `[]` stays reserved strictly for the former.

Only `BYTE_WEB_SEARCH_API_KEY` (required) and `BYTE_WEB_SEARCH_BASE_URL`
(optional override) are supported. Voiceloop's `.env.example` also carries
a deprecated `WEB_SEARCH_API_KEY` alias, but that alias exists solely for
voiceloop's own migration history — OpenRealtime has no prior env var to
migrate from, so no alias was added (YAGNI).
