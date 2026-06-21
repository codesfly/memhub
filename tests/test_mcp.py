"""MCP tool roundtrip: store_note then search_memories via in-memory client."""
import asyncio
from fastmcp.client import Client
from memhub import server, db as db_mod


def test_mcp_store_then_search_roundtrip(tmp_path):
    db_path = tmp_path / "mcp.db"
    c = db_mod.connect(db_path)
    db_mod.init_schema(c)
    c.close()

    mcp = server.build_server(db_path)

    async def run():
        async with Client(mcp) as client:
            store_res = await client.call_tool(
                "store_note",
                {"content": "use JWT for authentication", "project": "p1"},
            )
            stored = store_res.data
            assert stored.get("id"), f"store_note returned no id: {stored}"

            search_res = await client.call_tool(
                "search_memories",
                {"query": "auth login", "project": "p1", "scope": "all"},
            )
            results = search_res.data
            assert any("JWT" in m["content"] for m in results), \
                f"stored note not found in search results: {results}"

    asyncio.run(run())
