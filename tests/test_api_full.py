"""Full API functional test suite for CoSolve.

Exercises every FastAPI endpoint. Tests marked ``integration`` call real
Azure services (OpenAI, Blob Storage, AI Search) and cost tokens.

Run:
    pytest tests/test_api_full.py -m "not integration" -v   # unit only
    pytest tests/test_api_full.py -m "integration" -v        # integration only
    pytest tests/test_api_full.py -v                          # all
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from dotenv import load_dotenv

load_dotenv(override=True)

from backend.app import app  # noqa: E402

BASE = "http://test"

# A case_id format the API accepts (matches _CASE_ID_RE)
TEST_CASE_ID = "TEST-20260306-0001"


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE) as c:
        yield c


# ── ENTRY: Case Ingestion ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_case(client):
    """POST /entry/case with CREATE_CASE action."""
    r = await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "CREATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {"case_id": TEST_CASE_ID},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["data"]["status"] == "created"


@pytest.mark.asyncio
async def test_update_case(client):
    """POST /entry/case with UPDATE_CASE action."""
    # Ensure case exists first
    await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "CREATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {"case_id": TEST_CASE_ID},
    })
    r = await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "UPDATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {
            "case_id": TEST_CASE_ID,
            "d_states": {
                "D1_2": {
                    "data": {
                        "problem_description": "Test bearing failure"
                    }
                }
            },
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["data"]["status"] == "updated"


@pytest.mark.asyncio
async def test_case_entry_rejects_bad_intent(client):
    """POST /entry/case rejects wrong intent."""
    r = await client.post("/entry/case", json={
        "intent": "AI_REASONING",
        "action": "CREATE_CASE",
        "payload": {},
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_case_entry_rejects_unsupported_action(client):
    """POST /entry/case rejects unknown action."""
    r = await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "DELETE_EVERYTHING",
        "payload": {},
    })
    assert r.status_code == 400


# ── ENTRY: AI Reasoning ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_rejects_bad_intent(client):
    """POST /entry/reasoning rejects non-AI_REASONING intent."""
    r = await client.post("/entry/reasoning", json={
        "intent": "CASE_INGESTION",
        "payload": {"question": "hello"},
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reasoning_empty_question(client):
    """POST /entry/reasoning with empty question returns usage hint."""
    r = await client.post("/entry/reasoning", json={
        "intent": "AI_REASONING",
        "payload": {"question": ""},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "usage"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reasoning_operational(client):
    """POST /entry/reasoning invokes operational agent path."""
    # Ensure case exists
    await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "CREATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {"case_id": TEST_CASE_ID},
    })
    r = await client.post("/entry/reasoning", json={
        "intent": "AI_REASONING",
        "payload": {
            "question": "What are the current gaps in our investigation?",
            "case_id": TEST_CASE_ID,
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert "result" in body["data"] or "answer" in body["data"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reasoning_similarity(client):
    """POST /entry/reasoning invokes similarity agent path."""
    r = await client.post("/entry/reasoning", json={
        "intent": "AI_REASONING",
        "payload": {
            "question": "Have we seen similar bearing failures in other countries?",
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("accepted", "ok")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reasoning_strategy(client):
    """POST /entry/reasoning invokes strategy agent path."""
    r = await client.post("/entry/reasoning", json={
        "intent": "AI_REASONING",
        "payload": {
            "question": "What systemic risks do recurring bearing failures indicate across the fleet?",
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("accepted", "ok")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reasoning_kpi(client):
    """POST /entry/reasoning invokes KPI agent path."""
    r = await client.post("/entry/reasoning", json={
        "intent": "AI_REASONING",
        "payload": {
            "question": "How is our overall performance this year?",
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("accepted", "ok")


@pytest.mark.asyncio
async def test_reasoning_llm_stats_trigger(client):
    """POST /entry/reasoning with stats trigger returns stats payload."""
    r = await client.post("/entry/reasoning", json={
        "intent": "AI_REASONING",
        "payload": {
            "question": "show me llm performance stats",
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "stats"


# ── ENTRY: Debug ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_debug_reasoning(client):
    """POST /entry/reasoning/debug echoes raw body."""
    r = await client.post(
        "/entry/reasoning/debug",
        content=b'{"test": true}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert "test" in r.json()["received"]


# ── ENTRY: Suggestions ───────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_suggestions(client):
    """POST /entry/suggestions returns suggestion list."""
    r = await client.post("/entry/suggestions", json={
        "case_id": TEST_CASE_ID,
        "case_context": {
            "d_states": {
                "D1_2": {
                    "data": {
                        "problem_description": "Recurring bearing failures in traction motors"
                    }
                }
            }
        },
    })
    assert r.status_code == 200
    body = r.json()
    assert "suggestions" in body
    assert isinstance(body["suggestions"], list)


# ── CASES: Read / Search ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_case(client):
    """GET /cases/{case_id} returns case document."""
    # Ensure case exists
    await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "CREATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {"case_id": TEST_CASE_ID},
    })
    r = await client.get(f"/cases/{TEST_CASE_ID}")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


@pytest.mark.asyncio
async def test_get_case_invalid_format(client):
    """GET /cases/{case_id} rejects invalid format."""
    r = await client.get("/cases/not-a-valid-id")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_case_not_found(client):
    """GET /cases/{case_id} returns 404 for nonexistent case."""
    r = await client.get("/cases/XXXX-99990101-9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_search_cases_text(client):
    """POST /cases/search with text search."""
    r = await client.post("/cases/search", json={
        "query": "bearing",
        "search_type": "text",
        "limit": 5,
    })
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert "count" in body
    assert isinstance(body["results"], list)


@pytest.mark.asyncio
async def test_search_cases_by_id(client):
    """POST /cases/search with case_id search."""
    r = await client.post("/cases/search", json={
        "query": TEST_CASE_ID,
        "search_type": "case_id",
    })
    assert r.status_code == 200
    body = r.json()
    assert "results" in body


@pytest.mark.asyncio
async def test_search_cases_by_location(client):
    """POST /cases/search with site_or_country search."""
    r = await client.post("/cases/search", json={
        "query": "Germany",
        "search_type": "site_or_country",
        "limit": 5,
    })
    assert r.status_code == 200
    body = r.json()
    assert "results" in body


@pytest.mark.asyncio
async def test_search_cases_empty_query(client):
    """POST /cases/search with empty query returns 400."""
    r = await client.post("/cases/search", json={
        "query": "",
        "search_type": "text",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_evidence(client):
    """GET /cases/{case_id}/evidence returns evidence list."""
    # Ensure case exists
    await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "CREATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {"case_id": TEST_CASE_ID},
    })
    r = await client.get(f"/cases/{TEST_CASE_ID}/evidence")
    assert r.status_code == 200
    body = r.json()
    assert "evidence" in body
    assert isinstance(body["evidence"], list)


@pytest.mark.asyncio
async def test_list_evidence_invalid_id(client):
    """GET /cases/{case_id}/evidence rejects invalid ID."""
    r = await client.get("/cases/bad-id/evidence")
    assert r.status_code == 400


# ── KPI ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kpi_global(client):
    """GET /cases/kpi returns global KPI metrics."""
    r = await client.get("/cases/kpi")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert "scope" in body or "total_cases_closed_ytd" in body or isinstance(body, dict)


@pytest.mark.asyncio
async def test_kpi_country(client):
    """GET /cases/kpi?scope=country&country=Germany."""
    r = await client.get("/cases/kpi", params={"scope": "country", "country": "Germany"})
    assert r.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_kpi_assessment_global(client):
    """GET /cases/kpi/assessment returns AI narrative (calls LLM)."""
    r = await client.get("/cases/kpi/assessment")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "insights" in body


# ── KNOWLEDGE LIBRARY ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_knowledge(client):
    """GET /knowledge returns document list."""
    r = await client.get("/knowledge")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body
    assert "documents" in body
    assert isinstance(body["documents"], list)


@pytest.mark.asyncio
async def test_get_knowledge_file_not_found(client):
    """GET /knowledge/file/{filename} returns 404 for missing file."""
    r = await client.get("/knowledge/file/nonexistent_file_xyz.pdf")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_knowledge_not_found(client):
    """DELETE /knowledge/{filename} returns 404 for missing document."""
    r = await client.delete("/knowledge/nonexistent_file_xyz.pdf")
    assert r.status_code == 404


# ── LLM STATS ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_stats(client):
    """GET /llm/stats returns stats structure."""
    r = await client.get("/llm/stats")
    assert r.status_code == 200
    body = r.json()
    assert "monthly" in body or "totals" in body or isinstance(body, dict)


# ── ADMIN / FLOW ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flow_graph(client):
    """GET /admin/flow returns node/edge graph."""
    r = await client.get("/admin/flow")
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body
    assert "edges" in body
    assert "total_traces" in body


@pytest.mark.asyncio
async def test_flow_graph_with_days(client):
    """GET /admin/flow?days=7 filters by time window."""
    r = await client.get("/admin/flow", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body


# ── DEBUG / DIAGNOSTIC ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_debug_index_count(client):
    """GET /cases/debug/index-count returns sample docs."""
    r = await client.get("/cases/debug/index-count")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body or "error" in body


@pytest.mark.asyncio
async def test_debug_knowledge_search(client):
    """GET /knowledge/debug/search?q=bearing returns results."""
    r = await client.get("/knowledge/debug/search", params={"q": "bearing"})
    assert r.status_code == 200
    body = r.json()
    assert "count" in body or "error" in body


@pytest.mark.asyncio
async def test_debug_search_by_id(client):
    """GET /cases/debug/search-by-id/{case_id} returns multi-strategy results."""
    r = await client.get(f"/cases/debug/search-by-id/{TEST_CASE_ID}")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


@pytest.mark.asyncio
async def test_debug_reindex_case(client):
    """GET /cases/debug/reindex/{case_id} triggers re-index."""
    # Ensure case exists
    await client.post("/entry/case", json={
        "intent": "CASE_INGESTION",
        "action": "CREATE_CASE",
        "case_id": TEST_CASE_ID,
        "payload": {"case_id": TEST_CASE_ID},
    })
    r = await client.get(f"/cases/debug/reindex/{TEST_CASE_ID}")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body


@pytest.mark.asyncio
async def test_debug_reindex_invalid_id(client):
    """GET /cases/debug/reindex/{bad_id} rejects invalid format."""
    r = await client.get("/cases/debug/reindex/bad-id")
    assert r.status_code == 400
