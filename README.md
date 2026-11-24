# seasonpackarr-mcp

Part of the [arr-mcps](https://github.com/arr-mcps/arr-mcps) collection.
An MCP server exposing [SeasonPackArr](https://github.com/nuxencs/seasonpackarr)'s
REST API as tools for checking, matching, and importing TV season packs, plus
on-demand Prowlarr searches.

## Requirements

- SeasonPackArr with its REST API reachable (tested against v1.0.0)
- Python 3.11+ and `uv` for source development

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `SEASONPACKARR_URL` | Yes | SeasonPackArr base URL, for example `http://10.10.10.15:42069`. The server appends `/api`. |
| `SEASONPACKARR_API_KEY` | No | Token sent as `X-API-Token`. Leave unset when SeasonPackArr's `apiToken` is empty. |

Install a built wheel and register it with Claude Code:

```bash
uv tool install seasonpackarr_mcp-*.whl
claude mcp add seasonpackarr \
  --env SEASONPACKARR_URL=http://10.10.10.15:42069 \
  --env SEASONPACKARR_API_KEY=<token> \
  -- seasonpackarr-mcp
```

For a source checkout:

```bash
uv sync
claude mcp add seasonpackarr \
  --env SEASONPACKARR_URL=http://10.10.10.15:42069 \
  --env SEASONPACKARR_API_KEY=<token> \
  -- uv run --directory /path/to/seasonpackarr-mcp seasonpackarr-mcp
```

## Tools

**3 resource-scoped tools** cover all 6 SeasonPackArr REST operations via an
`operation` parameter. Call a tool with `operation` set to one of its listed
operations and an `arguments` dict matching that operation's parameters. Each
tool's own description (visible to your MCP client) lists every operation, its
signature, and a one-line doc, so no discovery round-trip is needed.

| Tool | Operations | Covers |
| --- | --- | --- |
| `seasonpackarr_health` | 2 | Liveness/readiness probes (no auth needed) |
| `seasonpackarr_pack` | 3 | Candidate check, match, and import webhooks |
| `seasonpackarr_search` | 1 | Targeted Prowlarr search with dry-run/verify modes |

The `health` group is marked `readOnlyHint=True`; the other two groups
contain write operations and carry no hint.

Example:

```text
seasonpackarr_health(operation="seasonpackarr_health_get_readiness", arguments={})
seasonpackarr_pack(operation="seasonpackarr_pack_check_candidate", arguments={"name": "Show.S01.1080p.WEB-DL-GRP"})
seasonpackarr_search(operation="seasonpackarr_search_run_search", arguments={"dry_run": true})
```

Notes on special operations:

- Successful match/import responses are bare text (`successful match`) with
  HTTP status 250; rejections and failures return JSON
  (`{"statusCode": ..., "error": ...}`) with the status code from SeasonPackArr's
  table (see upstream `docs/API.md`). A `200` search report still needs its
  `failures` checked - a 200 status alone does not prove all work succeeded.
- `torrent` accepts the `.torrent` bytes as a base64 string or as the byte
  list that autobrr writes for `{{ .TorrentDataRawBytes | js }}`.
- Omitting `clientname` uses the client named `default`.
- `seasonpackarr_pack_import_pack` hardlinks episodes and adds the pack to the
  torrent client; `seasonpackarr_search_run_search` without `dry_run` does the
  same for every pack it accepts. Do not call either casually.
- Do not put real API keys, passwords, or tokens in prompts.

## Development

```bash
make sync
make test
make test-integration   # requires SEASONPACKARR_URL and optionally SEASONPACKARR_API_KEY
make build
```

The offline tests use `httpx.MockTransport`; integration tests are skipped by
default and only hit the unauthenticated health endpoints.
