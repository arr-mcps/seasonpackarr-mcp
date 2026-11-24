"""MCP tools for the SeasonPackArr REST API.

Full API coverage, exposed as 3 resource-scoped *portmanteau* tools instead
of one tool per endpoint. Each tool takes an `operation` enum plus an
`arguments` dict; see AGENTS.md for the rationale. `_GROUPS` near the bottom
buckets every endpoint function by resource and `_register_group` wraps each
bucket in one dispatching MCP tool; the functions themselves are not tools.

SeasonPackArr authenticates with a token sent as the `X-API-Token` request
header (the `apikey` query parameter also works upstream, but the header has
priority there and keeps the token out of access logs, so this server always
uses the header). When no token is configured the server sends no auth header,
matching an SeasonPackArr instance with an empty `apiToken`.
"""

import inspect
import os
import sys
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations

JSONObj = dict[str, Any]
JSONVal = JSONObj | list[Any]
ReturnVal = JSONVal | str | int | float | bool | None
READONLY = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP("seasonpackarr-mcp")
_client: httpx.AsyncClient | None = None


def build_client(
    base_url: str,
    api_key: str | None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.AsyncClient:
    headers = {"X-API-Token": api_key} if api_key else {}
    return httpx.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/api", headers=headers, transport=transport
    )


def _path(value: Any) -> str:
    return quote(str(value), safe="")


def _params(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


async def _req(
    method: str,
    path: str,
    json: Any = None,
    params: dict[str, Any] | None = None,
) -> ReturnVal:
    assert _client is not None, "client not configured"
    response = await _client.request(method, path, json=json, params=params)
    if response.status_code >= 400:
        try:
            body = response.json()
            message = body.get("error", body) if isinstance(body, dict) else body
        except ValueError:
            message = response.text
        raise ToolError(f"SeasonPackArr API {response.status_code}: {message}")
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return response.json()
    text = response.text
    if text.startswith("{") or text.startswith("["):
        try:
            return response.json()
        except ValueError:
            pass
    try:
        return int(text)
    except ValueError:
        return text


# health ---------------------------------------------------------------------

async def seasonpackarr_health_get_liveness() -> ReturnVal:
    """Liveness (GET /api/healthz/liveness). Returns text OK. No auth needed."""
    return await _req("GET", "/healthz/liveness")


async def seasonpackarr_health_get_readiness() -> ReturnVal:
    """Readiness (GET /api/healthz/readiness). Returns text OK. No auth needed."""
    return await _req("GET", "/healthz/readiness")


# pack -----------------------------------------------------------------------

async def seasonpackarr_pack_check_candidate(
    name: str,
    clientname: str | None = None,
    torrent: str | list | None = None,
) -> ReturnVal:
    """Candidate check (POST /api/candidate). Compares the release name with the episode torrents in the client. Downloads no torrent and changes nothing; `torrent` is accepted but ignored."""
    return await _req(
        "POST", "/candidate", json=_params(name=name, torrent=torrent, clientname=clientname)
    )


async def seasonpackarr_pack_match_pack(
    name: str,
    torrent: str | list,
    clientname: str | None = None,
) -> ReturnVal:
    """Match (POST /api/match). Reads the torrent file list, accepts or rejects the season pack, and keeps an accepted import plan in memory. Changes no files and touches no client. `torrent` is the .torrent bytes as a base64 string or byte list."""
    return await _req(
        "POST", "/match", json=_params(name=name, torrent=torrent, clientname=clientname)
    )


async def seasonpackarr_pack_import_pack(
    name: str,
    torrent: str | list,
    clientname: str | None = None,
) -> ReturnVal:
    """Import (POST /api/import). Creates hardlinks and adds the season pack to the client. Uses the stored import plan from the match when still in memory. This writes files and modifies the client."""
    return await _req(
        "POST", "/import", json=_params(name=name, torrent=torrent, clientname=clientname)
    )


# search ---------------------------------------------------------------------

async def seasonpackarr_search_run_search(
    clientname: str | None = None,
    dry_run: bool | None = None,
    verify: bool | None = None,
) -> ReturnVal:
    """Run a targeted Prowlarr search (POST /api/search). Omit `clientname` to scan all configured clients. `dry_run` reports outcomes without importing; `verify` (requires `dry_run`) also downloads torrents to check exact reuse. A non-dry run imports packs into the client."""
    return await _req(
        "POST",
        "/search",
        json=_params(clientname=clientname, dryRun=dry_run, verify=verify),
    )


# Resource groups for portmanteau registration. Every tool function name
# must appear in exactly one group - see test_all_seasonpackarr_grouped.
_GROUPS: dict[str, tuple[str, ...]] = {
    "seasonpackarr_health": (
        "seasonpackarr_health_get_liveness",
        "seasonpackarr_health_get_readiness",
    ),
    "seasonpackarr_pack": (
        "seasonpackarr_pack_check_candidate",
        "seasonpackarr_pack_import_pack",
        "seasonpackarr_pack_match_pack",
    ),
    "seasonpackarr_search": (
        "seasonpackarr_search_run_search",
    ),
}


def _op_line(name: str, fn: Any) -> str:
    """One line of a group tool's description: signature + one-line doc."""
    sig = ", ".join(
        p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}"
        for p in inspect.signature(fn).parameters.values()
    )
    return f"- {name}({sig}) - {' '.join((fn.__doc__ or '').split())}"


def _register_group(
    group: str, names: tuple[str, ...], ns: dict[str, Any], readonly_names: set[str]
) -> None:
    """Register one dispatching tool that fans out to every function named
    in `names`. The functions themselves are untouched - they're just
    looked up by name instead of each becoming its own tool."""
    fns = {n: ns[n] for n in names}

    async def dispatch(
        operation: str, arguments: JSONObj | None = None
    ) -> ReturnVal:
        fn = fns.get(operation)
        if fn is None:
            raise ToolError(
                f"Unknown operation {operation!r} for {group}. Valid: {', '.join(fns)}"
            )
        return await fn(**(arguments or {}))

    dispatch.__annotations__["operation"] = Literal[names]
    ann = READONLY if set(names) <= readonly_names else None
    mcp.add_tool(
        Tool.from_function(
            dispatch,
            name=group,
            description=(
                f"{group.replace('_', ' ')} operations on SeasonPackArr. Pass `operation` and an "
                f"`arguments` dict matching that operation's parameters.\n\n"
                + "\n".join(_op_line(n, f) for n, f in fns.items())
            ),
            annotations=ann,
        )
    )


def _register_tools() -> None:
    ns = globals()
    readonly_names: set[str] = {
        "seasonpackarr_health_get_liveness",
        "seasonpackarr_health_get_readiness",
    }
    for group, names in _GROUPS.items():
        _register_group(group, names, ns, readonly_names)


_register_tools()


def main() -> None:
    global _client
    url = os.environ.get("SEASONPACKARR_URL")
    if not url:
        print(
            "SEASONPACKARR_URL environment variable is required (e.g. http://10.10.10.15:42069)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    _client = build_client(url, os.environ.get("SEASONPACKARR_API_KEY"))
    mcp.run()


if __name__ == "__main__":
    main()
