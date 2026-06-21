"""FastMCP server: MCP tools + REST custom routes + startup entry."""
from pathlib import Path
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from fastmcp import FastMCP
from . import db as db_mod, store, search, config, queue, transcript, ui

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
        text = body.get("transcript", "")
        tp = body.get("transcript_path")
        if tp:
            text = transcript.parse_transcript(tp)
        conn = db_mod.connect(db_path)
        try:
            qid = queue.enqueue(conn, {
                "transcript": text,
                "project": body.get("project"),
                "agent": body.get("agent"),
                "session_id": body.get("session_id"),
            })
        except Exception as e:
            return JSONResponse({"queued": None, "error": str(e)}, status_code=200)
        finally:
            conn.close()
        return JSONResponse({"queued": qid})

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

    @mcp.custom_route("/inject", methods=["POST"])
    async def inject(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"context": ""}, status_code=200)
        conn = db_mod.connect(db_path)
        try:
            results = search.search(conn, query="", project=body.get("project"),
                                    scope="current,global", limit=6)
        except Exception:
            return JSONResponse({"context": ""}, status_code=200)
        finally:
            conn.close()
        if not results:
            return JSONResponse({"context": ""})
        lines = [f"## 相关记忆 (memhub · {len(results)} 条)"]
        for r in results:
            snippet = r["content"].replace("\n", " ")[:160]
            lines.append(f"- [{r['kind']}] {snippet}")
        return JSONResponse({"context": "\n".join(lines)})

    @mcp.custom_route("/memories", methods=["GET"])
    async def list_memories_route(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            limit = int(q.get("limit", 50)); offset = int(q.get("offset", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "limit/offset must be integers"}, status_code=400)
        conn = db_mod.connect(db_path)
        try:
            items = store.list_memories(conn, project=q.get("project"),
                                        kind=q.get("kind"), limit=limit, offset=offset)
        finally:
            conn.close()
        return JSONResponse({"memories": items})

    @mcp.custom_route("/memories/{mid:int}", methods=["DELETE"])
    async def delete_memory_route(request: Request) -> JSONResponse:
        mid = request.path_params["mid"]
        conn = db_mod.connect(db_path)
        try:
            ok = store.delete_memory(conn, mid)
        finally:
            conn.close()
        return JSONResponse({"deleted": ok}, status_code=200 if ok else 404)

    @mcp.custom_route("/ui", methods=["GET"])
    async def ui_route(request: Request) -> HTMLResponse:
        return HTMLResponse(ui.PAGE)

    return mcp

def build_app(db_path: str | Path = config.DB_PATH):
    return build_server(db_path).http_app()

def main() -> None:
    import threading
    from .capture import LLMCapturer, RawCapturer
    from . import worker
    c = db_mod.connect(config.DB_PATH)
    db_mod.init_schema(c)
    c.close()
    t = threading.Thread(
        target=worker.run_loop,
        args=(config.DB_PATH, LLMCapturer(), RawCapturer()),
        daemon=True,
    )
    t.start()
    build_server(config.DB_PATH).run(transport="http", host=config.HOST, port=config.PORT)

if __name__ == "__main__":
    main()
