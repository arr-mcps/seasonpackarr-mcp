# AGENTS.md - seasonpackarr-mcp

MCP server exposing SeasonPackArr's REST API as 3 resource-scoped portmanteau
tools (6 operations). Uses FastMCP, `uv` for deps. Tested against SeasonPackArr
v1.0.0 (the version running in CT 111 on the new box).

## Tool design

Exactly 3 tools are registered, one per entry in `_GROUPS` in
`seasonpackarr_mcp.py`: `seasonpackarr_health`, `seasonpackarr_pack`,
`seasonpackarr_search`. Each tool takes an `operation` (a `Literal` of its
functions' names) plus an `arguments` dict and dispatches to a plain async
endpoint function. Do not register individual endpoint functions as tools. See
the arr-mcps masterlist `AGENTS.md` for the rationale.

Only 3 groups exist because the upstream API has only 6 endpoints
(`docs/API.md` plus `internal/http/server.go` in nuxencs/seasonpackarr v1.0.0:
healthz liveness/readiness, candidate/match/import webhooks, search).
Splitting further would mean one tool per endpoint, which the portmanteau
standard forbids; the ceiling is on group count, not a floor.

`_register_group` marks a group `readOnlyHint=True` only when every operation
in it is a GET. Only `seasonpackarr_health` is read-only; `seasonpackarr_pack`
imports packs into the torrent client and `seasonpackarr_search` imports packs
unless `dry_run` is set.

`dispatch` returns `ReturnVal = JSONObj | list[Any] | str | int | float | bool | None`
because successful responses are bare text (`OK` from health, `successful
match` with HTTP 250 from match/import), rejections are JSON
(`{"statusCode": ..., "error": ...}` with codes 200-230), and the search
report is a JSON object. FastMCP validates the declared return type, so do
not narrow it.

Auth is the `X-API-Token` header (the `apikey` query parameter also works
upstream, but the header has priority there and stays out of access logs).
`X-API-Token` is only sent when `SEASONPACKARR_API_KEY` is set, matching an
instance with an empty `apiToken`.

Request bodies stay plain JSON dictionaries matching upstream's documented
shape (`name`/`torrent`/`clientname` for webhooks, `clientname`/`dryRun`/
`verify` for search); `torrent` accepts the base64 string or the byte list
that autobrr writes for `{{ .TorrentDataRawBytes | js }}`. Optional fields
are omitted when unset, so `clientname` falls back to upstream's `default`
client. Do not place real API keys, passwords, or tokens in tool descriptions
or commit messages.

## Testing

- Offline suite: `make test` (or `uv run pytest`)
- Live integration (needs `SEASONPACKARR_URL`): `make test-integration`.
  Only the unauthenticated health endpoints are exercised live - webhooks and
  search read client state and can import packs, so they are never called
  against the live service.
- `tests/test_tools.py` has exact request-shape assertions for every
  operation, a generic smoke test that executes every endpoint function
  through its group with type-appropriate dummy arguments, and
  `test_all_seasonpackarr_grouped`, which asserts every endpoint function
  appears in exactly one `_GROUPS` entry.

## Release workflow

Use `make bump-*` (`uv version --bump patch|minor|major`), which updates
`pyproject.toml` and `uv.lock` together. Never hand-edit the version. Commit
message is just the version, tag `v<version>`, then push main and the tag.
This repo has no remote yet; add `https://github.com/arr-mcps/seasonpackarr-mcp.git`
when publishing.
