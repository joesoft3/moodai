"""v1.9.4 — 🧠 pgvector brain + 🖼 durable generated images.

- pgvector facade: backend chooser, filter translation, SQL shape, row mapping
- Gemini embeddings: batch dims pinned, batch→single fallback, provider order
- QUOTA_ECONOMY switch re-pauses memory side-calls
- /chat/image archive: R2/local/hotlink/data-URL paths
"""

import asyncio
import base64

import httpx
import pytest
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue, PointIdsList, PointStruct

from app.config import settings
from app.services import memory, vectorstore
from app.services.vectorstore import PgVectorStore, _filter_sql, pgvector_active, vector_literal


def run(coro):
    return asyncio.run(coro)


# ---------------------------- backend chooser ----------------------------

def test_auto_prefers_pgvector_when_qdrant_is_localhost(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "auto")
    monkeypatch.setattr(settings, "QDRANT_URL", "http://localhost:6333")
    assert pgvector_active() is True


def test_auto_prefers_real_qdrant_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "auto")
    monkeypatch.setattr(settings, "QDRANT_URL", "https://qdrant.example.internal:6333")
    assert pgvector_active() is False
    monkeypatch.setattr(settings, "QDRANT_URL", "")
    assert pgvector_active() is True


def test_forced_modes(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "pgvector")
    assert pgvector_active() is True
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "qdrant")
    assert pgvector_active() is False


def test_factory_returns_facade_on_defaults(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "auto")
    monkeypatch.setattr(settings, "QDRANT_URL", "http://localhost:6333")
    monkeypatch.setattr(memory, "_qdrant", None)
    assert isinstance(memory.qdrant(), PgVectorStore)
    monkeypatch.setattr(memory, "_qdrant", None)


# ---------------------------- SQL translation ----------------------------

def test_filter_sql_must_and_must_not():
    params: dict = {}
    sql = _filter_sql(
        Filter(
            must=[FieldCondition(key="user_id", match=MatchValue(value="u1"))],
            must_not=[FieldCondition(key="kind", match=MatchValue(value="chat"))],
        ),
        params,
    )
    assert "payload->>'user_id' = :f0" in sql
    assert "payload->>'kind' IS DISTINCT FROM :f1" in sql
    assert sorted(params.values()) == ["chat", "u1"]


def test_filter_sql_rejects_unsafe_keys():
    with pytest.raises(ValueError):
        _filter_sql(Filter(must=[FieldCondition(key="x'); DROP TABLE", match=MatchValue(value="1"))]), {})


def test_vector_literal_roundtrip_shape():
    lit = vector_literal([0.1, -0.25, 1.0])
    assert lit.startswith("[") and lit.endswith("]") and len(lit.split(",")) == 3


# ---------------------------- facade over a fake session ----------------------------

class _FakeResult:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalars(self):
        return self


class FakeDB:
    """Records every execute(); returns queued canned results."""

    def __init__(self, results=()):
        self.results = list(results)
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self.calls.append((str(sql), params or {}))
        return self.results.pop(0) if self.results else _FakeResult()

    async def commit(self):
        pass


def _patch_db(monkeypatch, db):
    monkeypatch.setattr(vectorstore, "SessionLocal", lambda: db)


def test_query_points_maps_rows_and_sql(monkeypatch):
    db = FakeDB([_FakeResult(rows=[{"id": "p1", "payload": {"fact": "likes kenkey", "user_id": "u1"}, "score": 0.91}])])
    _patch_db(monkeypatch, db)
    vs = PgVectorStore()
    vs._ensured = True
    res = run(
        vs.query_points(
            "user_memories",
            [0.1, 0.2] * 192,
            limit=5,
            query_filter=Filter(must=[FieldCondition(key="user_id", match=MatchValue(value="u1"))]),
        )
    )
    assert res.points[0].payload["fact"] == "likes kenkey"
    assert res.points[0].score == 0.91
    sql = db.calls[-1][0]
    assert "embedding <=>" in sql and "ORDER BY embedding" in sql and "payload->>'user_id'" in sql
    assert db.calls[-1][1]["col"] == "user_memories" and db.calls[-1][1]["lim"] == 5


def test_upsert_conflict_and_delete_paths(monkeypatch):
    db = FakeDB()
    _patch_db(monkeypatch, db)
    vs = PgVectorStore()
    vs._ensured = True
    run(vs.upsert("user_memories", [PointStruct(id="abc", vector=[0.0] * 384, payload={"user_id": "u1"})]))
    up_sql, up_params = db.calls[-1]
    assert "ON CONFLICT (collection, id)" in up_sql
    assert up_params["pid"] == "abc" and up_params["col"] == "user_memories"

    run(vs.delete("user_memories", points_selector=PointIdsList(points=["abc"])))
    assert "jsonb_array_elements_text" in db.calls[-1][0]

    run(
        vs.delete(
            "doc_chunks",
            points_selector=FilterSelector(filter=Filter(must=[FieldCondition(key="file_id", match=MatchValue(value="f9"))])),
        )
    )
    del_sql, del_params = db.calls[-1]
    assert "DELETE FROM vector_points" in del_sql and "payload->>'file_id'" in del_sql
    assert "f9" in del_params.values()


def test_lazy_ensure_creates_extension_and_table(monkeypatch):
    db = FakeDB()
    _patch_db(monkeypatch, db)
    vs = PgVectorStore()
    run(vs.create_collection("user_memories"))
    ddl = "\n".join(c[0] for c in db.calls)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in ddl
    assert "CREATE TABLE IF NOT EXISTS vector_points" in ddl
    assert "vector(384)" in ddl
    assert vs._ensured is True


def test_ensure_self_heals_after_a_transient_failure(monkeypatch):
    """Live bug: cold-boot DDL raced requests → breaker opened → memory-blind minutes.
    A failed attempt must NOT mark the store ensured; the next call retries cleanly."""

    class FlakyDB(FakeDB):
        def __init__(self, results=()):
            super().__init__(results)
            self.boomed = 0

        async def execute(self, sql, params=None):
            if not self.boomed:
                self.boomed += 1
                raise RuntimeError("duplicate key: concurrent CREATE EXTENSION")
            return await super().execute(sql, params)

    db = FlakyDB()
    _patch_db(monkeypatch, db)
    vs = PgVectorStore()
    run(vs.create_collection("user_memories"))  # first execute fails, retry succeeds
    assert vs._ensured is True
    assert any("CREATE EXTENSION" in c[0] for c in db.calls)


def test_ensure_not_marked_after_hard_failure(monkeypatch):
    class DeadDB(FakeDB):
        async def execute(self, sql, params=None):
            raise RuntimeError("db unreachable")

    _patch_db(monkeypatch, DeadDB())
    vs = PgVectorStore()
    with pytest.raises(RuntimeError):
        run(vs.create_collection("user_memories"))
    assert vs._ensured is False  # next request gets a fresh chance


# ---------------------------- same-fate budget floor ----------------------------

def test_ctx_budget_floor_for_pgvector(monkeypatch):
    """Live lesson: the 4s external-Qdrant budget false-trips on Neon wake-from-idle
    (~4-8s first query); pgvector shares fate with the main DB, so floor = 8s."""
    from app.api.routes import chat as chat_route

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "auto")
    monkeypatch.setattr(settings, "QDRANT_URL", "http://localhost:6333")
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_S", 4.0)
    assert chat_route._ctx_budget() == 8.0
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "qdrant")
    assert chat_route._ctx_budget() == 4.0


# ---------------------------- Gemini embeddings ----------------------------

class _Resp:
    def __init__(self, code, payload=None, content=b"", headers=None):
        self.status_code = code
        self._p = payload or {}
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "https://generativelanguage.googleapis.com/x")
            raise httpx.HTTPStatusError("bad", request=req, response=httpx.Response(self.status_code, request=req))


class _FakeHTTP:
    def __init__(self, script):
        self.script = list(script)
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, params=None, json=None):
        self.posts.append(url)
        return self.script.pop(0)

    async def get(self, url):
        self.posts.append(url)
        return self.script.pop(0)


def _emb(n=384, v=0.01):
    return {"values": [v] * n}


def test_gemini_batch_pins_dims(monkeypatch):
    http = _FakeHTTP([_Resp(200, {"embeddings": [_emb(), _emb(384, 0.02)]})])
    monkeypatch.setattr(memory.httpx, "AsyncClient", lambda **kw: http)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")
    out = run(memory._embed_via_gemini(["a", "b"]))
    assert len(out) == 2 and len(out[0]) == 384
    assert "batchEmbedContents" in http.posts[0] and "gemini-embedding-001" in http.posts[0]


def test_gemini_batch_falls_back_to_singles(monkeypatch):
    http = _FakeHTTP([_Resp(400, {"error": "no batch"}), _Resp(200, {"embedding": _emb()}), _Resp(200, {"embedding": _emb()})])
    monkeypatch.setattr(memory.httpx, "AsyncClient", lambda **kw: http)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")
    out = run(memory._embed_via_gemini(["a", "b"]))
    assert len(out) == 2 and all(len(v) == 384 for v in out)
    assert any("embedContent" in u and "batch" not in u for u in http.posts)


def test_embed_auto_prefers_gemini(monkeypatch):
    http = _FakeHTTP([_Resp(200, {"embeddings": [_emb()]})])
    monkeypatch.setattr(memory.httpx, "AsyncClient", lambda **kw: http)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")
    monkeypatch.setattr(settings, "EMBED_PROVIDER", "auto")
    monkeypatch.setattr(memory, "TextEmbedding", None)
    out = run(memory.embed(["hello"]))
    assert len(out) == 1 and http.posts  # gemini served it


def test_embed_raises_when_no_backend(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "EMBED_PROVIDER", "auto")
    monkeypatch.setattr(memory, "TextEmbedding", None)
    with pytest.raises(memory.EmbeddingUnavailable):
        run(memory.embed(["hello"]))


# ---------------------------- quota economy switch ----------------------------

def test_quota_economy_pauses_extraction(monkeypatch):
    monkeypatch.setattr(settings, "QUOTA_ECONOMY", True)
    calls = {"n": 0}

    async def _count(*a, **k):
        calls["n"] += 1

    monkeypatch.setattr(memory.llm, "complete", _count)
    run(memory.extract_and_store("u1", "hi", "yo"))
    assert calls["n"] == 0


def test_quota_economy_default_is_full_memory(monkeypatch):
    assert settings.QUOTA_ECONOMY is False  # default keeps extraction + titles live


# ---------------------------- image persistence ----------------------------

class _DB:
    def __init__(self):
        self.rows = []
        self.committed = 0

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        self.committed += 1


class _User:
    id = "u1"


def _patch_storage(monkeypatch, remote=True):
    from app.services import storage

    async def _put(user_id, filename, data):
        return f"r2:gallery/{filename}" if remote else f"/tmp/{filename}"

    async def _presign(marker, seconds=None):
        assert seconds == settings.IMAGE_PERSIST_TTL_S
        return "https://signed.example/img.jpg" if remote else None

    monkeypatch.setattr(storage, "put_upload", _put)
    monkeypatch.setattr(storage, "presigned_url", _presign)


def test_persist_archives_to_r2_and_files_it(monkeypatch):
    from app.api.routes import chat as chatmod

    monkeypatch.setattr(settings, "IMAGE_PERSIST", True)
    http = _FakeHTTP([_Resp(200, content=b"\xff\xd8fakejpeg", headers={"content-type": "image/jpeg"})])
    monkeypatch.setattr(chatmod.httpx, "AsyncClient", lambda **kw: http)
    _patch_storage(monkeypatch, remote=True)
    db = _DB()
    url, stored = run(chatmod._persist_generated_image(db, _User(), "https://image.pollinations.ai/prompt/x"))
    assert stored == "r2"
    assert url == "https://signed.example/img.jpg"
    row = db.rows[0]
    assert row.mime == "image/jpeg" and row.path == f"r2:gallery/{row.filename}" and row.size_bytes == len(b"\xff\xd8fakejpeg")
    assert db.committed == 1


def test_persist_falls_back_to_hotlink_on_fetch_failure(monkeypatch):
    from app.api.routes import chat as chatmod

    monkeypatch.setattr(settings, "IMAGE_PERSIST", True)
    http = _FakeHTTP([_Resp(500)])
    monkeypatch.setattr(chatmod.httpx, "AsyncClient", lambda **kw: http)
    db = _DB()
    url, stored = run(chatmod._persist_generated_image(db, _User(), "https://provider.example/img.png"))
    assert (url, stored) == ("https://provider.example/img.png", "hotlink")
    assert db.rows == []


def test_persist_handles_data_url(monkeypatch):
    from app.api.routes import chat as chatmod

    monkeypatch.setattr(settings, "IMAGE_PERSIST", True)
    payload = base64.b64encode(b"\x89PNGfake").decode()
    http = _FakeHTTP([])  # must never be hit for data URLs
    monkeypatch.setattr(chatmod.httpx, "AsyncClient", lambda **kw: http)
    _patch_storage(monkeypatch, remote=True)
    db = _DB()
    url, stored = run(chatmod._persist_generated_image(db, _User(), f"data:image/png;base64,{payload}"))
    assert stored == "r2" and url == "https://signed.example/img.jpg"
    assert db.rows[0].mime == "image/png" and db.rows[0].filename.endswith(".png")
    assert http.posts == []


def test_persist_disabled_returns_hotlink(monkeypatch):
    from app.api.routes import chat as chatmod

    monkeypatch.setattr(settings, "IMAGE_PERSIST", False)
    db = _DB()
    url, stored = run(chatmod._persist_generated_image(db, _User(), "https://provider.example/img.png"))
    assert (url, stored) == ("https://provider.example/img.png", "hotlink")
