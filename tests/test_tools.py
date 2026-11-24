"""Offline contract tests for the SeasonPackArr MCP tools."""

import inspect
import json

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

import seasonpackarr_mcp


class Recorder:
    def __init__(self):
        self.method = None
        self.url = None
        self.headers = None
        self.json = None
        self.raw = None
        self.response = httpx.Response(200, json={"ok": True})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.method = request.method
        self.url = request.url
        self.headers = request.headers
        self.raw = request.content
        try:
            self.json = json.loads(request.content) if request.content else None
        except ValueError:
            self.json = None
        return self.response


@pytest.fixture
def recorder():
    return Recorder()


@pytest_asyncio.fixture
async def server(recorder, monkeypatch):
    client = seasonpackarr_mcp.build_client(
        "http://10.10.10.15:42069",
        "test-key",
        transport=httpx.MockTransport(recorder.handler),
    )
    monkeypatch.setattr(seasonpackarr_mcp, "_client", client)
    yield seasonpackarr_mcp.mcp
    await client.aclose()


_OP_GROUP = {
    op: group for group, ops in seasonpackarr_mcp._GROUPS.items() for op in ops
}


async def call(server, op_name, **kwargs):
    """Call `op_name` (an operation name) through its portmanteau tool."""
    async with Client(server) as client:
        return await client.call_tool(
            _OP_GROUP[op_name], {"operation": op_name, "arguments": kwargs}
        )


@pytest.mark.parametrize(
    ("name", "kwargs", "method", "path"),
    [
        ("seasonpackarr_health_get_liveness", {}, "GET", "/api/healthz/liveness"),
        ("seasonpackarr_health_get_readiness", {}, "GET", "/api/healthz/readiness"),
        ("seasonpackarr_pack_check_candidate", {"name": "Show.S01.1080p-GRP"}, "POST", "/api/candidate"),
        (
            "seasonpackarr_pack_match_pack",
            {"name": "Show.S01.1080p-GRP", "torrent": "dGVzdA=="},
            "POST",
            "/api/match",
        ),
        (
            "seasonpackarr_pack_import_pack",
            {"name": "Show.S01.1080p-GRP", "torrent": "dGVzdA=="},
            "POST",
            "/api/import",
        ),
        ("seasonpackarr_search_run_search", {}, "POST", "/api/search"),
    ],
)
async def test_endpoint_routes(server, recorder, name, kwargs, method, path):
    await call(server, name, **kwargs)
    assert recorder.method == method
    assert recorder.url.raw_path.split(b"?")[0].decode() == path


@pytest.mark.parametrize(
    ("name", "kwargs", "method", "path", "body"),
    [
        (
            "seasonpackarr_pack_check_candidate",
            {"name": "Show.S01.1080p-GRP", "clientname": "default"},
            "POST",
            "/api/candidate",
            {"name": "Show.S01.1080p-GRP", "clientname": "default"},
        ),
        (
            "seasonpackarr_pack_match_pack",
            {"name": "Show.S01.1080p-GRP", "torrent": "dGVzdA==", "clientname": "qb"},
            "POST",
            "/api/match",
            {"name": "Show.S01.1080p-GRP", "torrent": "dGVzdA==", "clientname": "qb"},
        ),
        (
            "seasonpackarr_search_run_search",
            {"dry_run": True, "verify": True},
            "POST",
            "/api/search",
            {"dryRun": True, "verify": True},
        ),
        (
            "seasonpackarr_search_run_search",
            {"clientname": "default"},
            "POST",
            "/api/search",
            {"clientname": "default"},
        ),
    ],
)
async def test_request_bodies(server, recorder, name, kwargs, method, path, body):
    await call(server, name, **kwargs)
    assert recorder.method == method
    assert recorder.url.path == path
    assert recorder.json == body


async def test_optional_fields_omitted_when_unset(server, recorder):
    await call(server, "seasonpackarr_pack_check_candidate", name="Show.S01.1080p-GRP")
    assert recorder.json == {"name": "Show.S01.1080p-GRP"}


async def test_api_key_header(server, recorder):
    await call(server, "seasonpackarr_health_get_readiness")
    assert recorder.headers["x-api-token"] == "test-key"


async def test_no_api_key_header(recorder, monkeypatch):
    client = seasonpackarr_mcp.build_client(
        "http://10.10.10.15:42069",
        None,
        transport=httpx.MockTransport(recorder.handler),
    )
    monkeypatch.setattr(seasonpackarr_mcp, "_client", client)
    await call(seasonpackarr_mcp.mcp, "seasonpackarr_health_get_readiness")
    assert "x-api-token" not in recorder.headers
    await client.aclose()


async def test_text_scalar_response(server, recorder):
    recorder.response = httpx.Response(
        250, text="successful match", headers={"content-type": "text/plain"}
    )
    result = await call(
        server,
        "seasonpackarr_pack_match_pack",
        name="Show.S01.1080p-GRP",
        torrent="dGVzdA==",
    )
    assert result.data == "successful match"


async def test_health_text_response(server, recorder):
    recorder.response = httpx.Response(
        200, text="OK", headers={"content-type": "text/plain"}
    )
    result = await call(server, "seasonpackarr_health_get_readiness")
    assert result.data == "OK"


async def test_rejection_json_passes_through(server, recorder):
    recorder.response = httpx.Response(
        203, json={"statusCode": 203, "error": "release group did not match"}
    )
    result = await call(
        server, "seasonpackarr_pack_check_candidate", name="Show.S01.1080p-GRP"
    )
    assert result.data == {"statusCode": 203, "error": "release group did not match"}


async def test_error_message(server, recorder):
    recorder.response = httpx.Response(401, json={"error": "unauthorized"})
    with pytest.raises(ToolError, match="401.*unauthorized"):
        await call(server, "seasonpackarr_health_get_readiness")


async def test_non_json_error(server, recorder):
    recorder.response = httpx.Response(502, text="<html>Bad Gateway</html>")
    with pytest.raises(ToolError, match="502"):
        await call(server, "seasonpackarr_health_get_readiness")


def test_main_requires_url(monkeypatch):
    monkeypatch.delenv("SEASONPACKARR_URL", raising=False)
    with pytest.raises(SystemExit):
        seasonpackarr_mcp.main()


# --- full-surface smoke coverage ---------------------------------------------
# Every operation has exact request-shape assertions above, but this exercises
# each endpoint function's URL-templating/body-marshaling path with
# type-appropriate dummy arguments as a backstop.

ALL_ENDPOINT_NAMES = sorted(
    name
    for name in dir(seasonpackarr_mcp)
    if name.startswith("seasonpackarr_")
    and inspect.iscoroutinefunction(getattr(seasonpackarr_mcp, name))
)


def _sample_value(param: inspect.Parameter):
    ann = str(param.annotation)
    if "dict" in ann:
        return {}
    if "list" in ann:
        return []
    if "bool" in ann:
        return True
    if "int" in ann:
        return 1
    if "float" in ann:
        return 1
    return "x"


@pytest.mark.parametrize("name", ALL_ENDPOINT_NAMES)
async def test_every_endpoint_is_callable(server, recorder, name):
    fn = getattr(seasonpackarr_mcp, name)
    kwargs = {
        p.name: _sample_value(p)
        for p in inspect.signature(fn).parameters.values()
        if p.default is inspect.Parameter.empty
    }
    await call(server, name, **kwargs)
    assert recorder.method in ("GET", "POST", "PUT", "DELETE", "PATCH")
    assert recorder.url.path.startswith("/")


# --- portmanteau grouping safety net ------------------------------------------

def test_all_seasonpackarr_grouped():
    """Every endpoint function must land in exactly one portmanteau group."""
    grouped_names = [n for names in seasonpackarr_mcp._GROUPS.values() for n in names]
    assert sorted(grouped_names) == sorted(ALL_ENDPOINT_NAMES)
    assert len(grouped_names) == len(set(grouped_names))


async def test_group_tools_are_the_only_registered_tools(server):
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == set(seasonpackarr_mcp._GROUPS)


async def test_unknown_operation_rejected_by_schema(server):
    # The Literal[...] enum on `operation` means an invalid value never reaches
    # _register_group's dispatch body - pydantic rejects it first.
    with pytest.raises(ToolError, match="validation error"):
        async with Client(server) as client:
            await client.call_tool("seasonpackarr_pack", {"operation": "not_real"})
