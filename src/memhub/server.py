"""FastMCP server: MCP tools + REST custom routes + startup entry."""
from pathlib import Path
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastmcp import FastMCP
from . import db as db_mod, store, search, config

def build_server(db_path: str | Path = config.DB_PATH) -> FastMCP:
    mcp = FastMCP("memhub")

    @mcp.tool
    def search_memories(query: str, scope: str = "current,global",
                        kind: str | None = None, project: str | None = None,
                        limit: int = config.DEFAULT_LIMIT) -> list[dict]:
        """Search shared memory (hybrid vector + keyword)."""
        conn = db_mod.connect(db_path)
        try:
            return search.search(conn, query, project=project, scope=scope, kind=kind, limit=limit)
        finally:
            conn.close()

    @mcp.tool
    def store_note(content: str, tags: list[str] | None = None,
                   scope: str = "current", project: str | None = None) -> dict:
        """Store a memory note explicitly."""
        conn = db_mod.connect(db_path)
        try:
            mid = store.store_memory(conn, content=content, project=project,
                                     agent="manual", kind="note", tags=tags, scope=scope)
            return {"id": mid}
        finally:
            conn.close()

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/capture", methods=["POST"])
    async def capture(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        transcript = body.get("transcript", "")
        conn = db_mod.connect(db_path)
        try:
            mid = store.store_memory(
                conn, content=transcript, project=body.get("project"),
                agent=body.get("agent"), kind="raw", scope="current",
                session_id=body.get("session_id"),
            )
        except Exception as e:
            return JSONResponse({"stored": [], "error": str(e)}, status_code=200)
        finally:
            conn.close()
        return JSONResponse({"stored": [] if mid is None else [mid]})

    @mcp.custom_route("/search", methods=["GET"])
    async def search_route(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            limit = int(q.get("limit", config.DEFAULT_LIMIT))
        except (TypeError, ValueError):
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        conn = db_mod.connect(db_path)
        try:
            results = search.search(
                conn, q.get("query", ""), project=q.get("project"),
                scope=q.get("scope", "current,global"), kind=q.get("kind"), limit=limit,
            )
        except Exception:
            return JSONResponse({"results": []}, status_code=200)
        finally:
            conn.close()
        return JSONResponse({"results": results})

    return mcp

def build_app(db_path: str | Path = config.DB_PATH):
    return build_server(db_path).http_app()

def main() -> None:
    c = db_mod.connect(config.DB_PATH)
    db_mod.init_schema(c)
    c.close()
    build_server(config.DB_PATH).run(transport="http", host=config.HOST, port=config.PORT)

if __name__ == "__main__":
    main()
