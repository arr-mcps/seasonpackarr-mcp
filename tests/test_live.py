"""Opt-in smoke tests for a live SeasonPackArr instance.

Only the unauthenticated health endpoints are exercised - the webhook and
search endpoints read client state and can import packs, so they are never
called against the live service.
"""

import os

import pytest
from fastmcp import Client

import seasonpackarr_mcp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SEASONPACKARR_URL"),
        reason="requires SEASONPACKARR_URL (and optionally SEASONPACKARR_API_KEY)",
    ),
]


@pytest.fixture(autouse=True)
def configure_client():
    seasonpackarr_mcp._client = seasonpackarr_mcp.build_client(
        os.environ["SEASONPACKARR_URL"], os.environ.get("SEASONPACKARR_API_KEY")
    )
    yield


async def call(group, operation, **arguments):
    async with Client(seasonpackarr_mcp.mcp) as client:
        return await client.call_tool(
            group, {"operation": operation, "arguments": arguments}
        )


async def test_liveness():
    result = await call("seasonpackarr_health", "seasonpackarr_health_get_liveness")
    assert result.data is not None


async def test_readiness():
    result = await call("seasonpackarr_health", "seasonpackarr_health_get_readiness")
    assert result.data is not None
