# backend/app/ingest_closed_case_v1.py

import json
from datetime import datetime, timezone
from pathlib import Path
import time

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.core.exceptions import ResourceNotFoundError
from openai import AzureOpenAI

from app.infrastructure.search.case_index import (
    build_doc_id,
    validate_doc_id,
    CASE_INDEX_NAME,
)
from app.config import settings


def to_datetime_offset(value: str | None) -> str | None:
    """
    Convert ISO-like datetime strings to RFC3339 DateTimeOffset (UTC).
    """
    if not value:
        return None

    dt = datetime.fromisoformat(value.replace("Z", ""))
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


# -------------------------
# 1. Load case JSON (local for Sprint 3)
# -------------------------

CASE_JSON_PATH = (
    Path(__file__).resolve().parent.parent / "INC-20260122-0001.json"
)  # located at backend/INC-20260122-0001.json

with open(CASE_JSON_PATH, "r", encoding="utf-8") as f:
    case_data = json.load(f)


# -------------------------
# 2. Extract core metadata
# -------------------------

case_id = case_data["case"]["case_number"]


status = case_data["case"]["status"]

if status != "closed":
    raise ValueError(
        f"Only closed cases can be ingested. Case {case_id} status={status}."
    )

opening_date = to_datetime_offset(case_data["case"]["opening_date"])
closure_date = to_datetime_offset(case_data["case"]["closure_date"])

meta = case_data["meta"]
version = meta["version"]
created_at = to_datetime_offset(meta["created_at"])
updated_at = to_datetime_offset(meta["updated_at"])


# -------------------------
# 3. Extract D1–D3 (problem context)
# -------------------------

d1 = case_data["phases"]["D1_D2"]["data"]
d3 = case_data["phases"]["D3"]["data"]

problem_description = d1["problem_description"]

organization = d1["organization"]
organization_country = organization["country"]
organization_site = organization["site"]
organization_department = organization["department"]

team_members = d1.get("team_members", [])

what_happened = d3["what_happened"]
why_problem = d3["why_problem"]
when = d3["when"]
where = d3["where"]
who = d3["who"]
how_identified = d3["how_identified"]
impact = d3["impact"]


# -------------------------
# 4. Extract D4–D6 (actions & investigation)
# -------------------------


def join_actions(actions, key):
    return "\n".join(
        f"- {a[key]} (Responsible: {a['responsible']}, Due: {a['due_date']}, Actual: {a['actual_date']})"
        for a in actions
    )


immediate_actions_text = join_actions(
    case_data["phases"]["D4"]["data"]["actions"], "action"
)

permanent_actions_text = join_actions(
    case_data["phases"]["D6"]["data"]["actions"], "action"
)

investigation_tasks_text = join_actions(
    case_data["phases"]["D5"]["data"]["investigation_tasks"], "task"
)


# -------------------------
# 5. Extract D5 analysis (fishbone, factors, 5-whys)
# -------------------------

d5 = case_data["phases"]["D5"]["data"]

fishbone_text = "\n".join(
    f"{k.upper()}: {', '.join(v)}" for k, v in d5["fishbone"].items()
)

factors_text = "\n".join(
    f"- {f['factor']} (Owner: {f['owner']}, Status: {f['status']})"
    for f in d5["factors"]
)

five_whys_text = "\n".join(f"{k}: {' → '.join(v)}" for k, v in d5["five_whys"].items())


# -------------------------
# 6. Build embedding text (THIS is what the model sees)
# -------------------------

embedding_text = f"""
CASE {case_id}

Problem:
{problem_description}

What happened:
{what_happened}

Why:
{why_problem}

Impact:
{impact}

When:
{when}

Where:
{where}

Who:
{who}

How identified:
{how_identified}

Immediate actions:
{immediate_actions_text}

Permanent actions:
{permanent_actions_text}

Investigation tasks:
{investigation_tasks_text}

Fishbone analysis:
{fishbone_text}

Key factors:
{factors_text}

Five whys:
{five_whys_text}
""".strip()


def preflight() -> None:
    # Verify required settings exist
    required = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_ADMIN_KEY",
    ]
    missing = [name for name in required if not getattr(settings, name, None)]
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")

    # Verify index exists
    index_client = SearchIndexClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
    )
    try:
        index_client.get_index(CASE_INDEX_NAME)
    except ResourceNotFoundError as exc:
        raise ValueError(f"Index {CASE_INDEX_NAME} not found.") from exc

    # Verify embedding deployment is reachable
    test_client = AzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )
    test_embedding = (
        test_client.embeddings.create(
            model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input="ping",
        )
        .data[0]
        .embedding
    )
    if len(test_embedding) != settings.AZURE_SEARCH_VECTOR_DIMENSIONS:
        raise ValueError(
            "Embedding dimension mismatch: "
            f"expected {settings.AZURE_SEARCH_VECTOR_DIMENSIONS}, "
            f"got {len(test_embedding)}."
        )


# -------------------------
# 7. Create embedding
# -------------------------


def _mask_secret(value: str | None) -> str:
    if not value:
        return "MISSING"
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


print(
    "Azure OpenAI config loaded:",
    f"endpoint={'SET' if settings.AZURE_OPENAI_ENDPOINT else 'MISSING'}",
    f"api_key={_mask_secret(settings.AZURE_OPENAI_API_KEY)}",
    f"api_version={'SET' if settings.AZURE_OPENAI_API_VERSION else 'MISSING'}",
    f"deployment={settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT or 'MISSING'}",
)

openai_client = AzureOpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
)

embedding = (
    openai_client.embeddings.create(
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        input=embedding_text,
    )
    .data[0]
    .embedding
)

if len(embedding) != settings.AZURE_SEARCH_VECTOR_DIMENSIONS:
    raise ValueError(
        "Embedding dimension mismatch: "
        f"expected {settings.AZURE_SEARCH_VECTOR_DIMENSIONS}, "
        f"got {len(embedding)}."
    )


# -------------------------
# 8. Build search document
# -------------------------


def _normalize_string(value):
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(str(v) for v in value if v is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _normalize_string_list(value):
    """
    Normalize a value into a list[str] suitable for Azure AI Search Collection(String).

    - None            -> []
    - list[str]       -> list[str]
    - list[primitive] -> list[str]
    - list[dict]      -> ❌ rejected
    - single value    -> [str(value)]
    """
    if value is None:
        return []

    if isinstance(value, list):
        normalized = []
        for v in value:
            if isinstance(v, (str, int, float)):
                normalized.append(str(v))
            elif v is None:
                continue
            else:
                raise ValueError(
                    f"Invalid item in collection field: {type(v).__name__} -> {v}"
                )
        return normalized

    if isinstance(value, (str, int, float)):
        return [str(value)]

    raise ValueError(
        f"Invalid value for collection field: {type(value).__name__} -> {value}"
    )


def _normalize_vector(value):
    if not isinstance(value, list):
        raise ValueError("content_vector must be a list of floats")
    return [float(v) for v in value]


document = {
    "case_id": case_id,
    "status": status,
    "opening_date": opening_date,
    "closure_date": closure_date,
    "created_at": created_at,
    "updated_at": updated_at,
    "version": version,
    "organization_country": organization_country,
    "organization_site": organization_site,
    "organization_department": organization_department,
    "discipline_completed": ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"],
    "problem_description": problem_description,
    "team_members": team_members,
    "what_happened": what_happened,
    "why_problem": why_problem,
    "when": when,
    "where": where,
    "who": who,
    "how_identified": how_identified,
    "impact": impact,
    "immediate_actions_text": immediate_actions_text,
    "permanent_actions_text": permanent_actions_text,
    "investigation_tasks_text": investigation_tasks_text,
    "factors_text": factors_text,
    "fishbone_text": fishbone_text,
    "five_whys_text": five_whys_text,
    "evidence_descriptions": "",
    "evidence_tags": [],
    "ai_summary": "",
    "content_vector": embedding,
}

document["doc_id"] = build_doc_id(case_id)
validate_doc_id(document["doc_id"])

# Defensive normalization for Azure Search schema alignment
document.update(
    {
        "problem_description": _normalize_string(document["problem_description"]),
        "what_happened": _normalize_string(document["what_happened"]),
        "why_problem": _normalize_string(document["why_problem"]),
        "when": _normalize_string(document["when"]),
        "where": _normalize_string(document["where"]),
        "who": _normalize_string(document["who"]),
        "how_identified": _normalize_string(document["how_identified"]),
        "impact": _normalize_string(document["impact"]),
        "immediate_actions_text": _normalize_string(document["immediate_actions_text"]),
        "permanent_actions_text": _normalize_string(document["permanent_actions_text"]),
        "investigation_tasks_text": _normalize_string(
            document["investigation_tasks_text"]
        ),
        "factors_text": _normalize_string(document["factors_text"]),
        "fishbone_text": _normalize_string(document["fishbone_text"]),
        "five_whys_text": _normalize_string(document["five_whys_text"]),
        "evidence_descriptions": _normalize_string(document["evidence_descriptions"]),
        "ai_summary": _normalize_string(document["ai_summary"]),
        "team_members": _normalize_string_list(document["team_members"]),
        "discipline_completed": _normalize_string_list(
            document["discipline_completed"]
        ),
        "evidence_tags": _normalize_string_list(document["evidence_tags"]),
        "content_vector": _normalize_vector(document["content_vector"]),
    }
)

# -------------------------
# DEBUG GUARD: fail fast if arrays remain in primitive fields
# -------------------------

ALLOWED_LIST_FIELDS = {
    "team_members",
    "discipline_completed",
    "evidence_tags",
    "content_vector",
}

for key, value in document.items():
    if isinstance(value, list) and key not in ALLOWED_LIST_FIELDS:
        raise RuntimeError(
            f"❌ LIST STILL PRESENT IN PRIMITIVE FIELD: {key} -> {value}"
        )


# -------------------------
# 9. Upload to Azure AI Search
# -------------------------

search_client = SearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=CASE_INDEX_NAME,
    credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
)

preflight()
upload_results = search_client.upload_documents([document])

# 1️⃣ Check upload results FIRST
failed = [r for r in upload_results if not r.succeeded]
if failed:
    messages = "; ".join(f"{r.key}: {r.error_message}" for r in failed)
    raise ValueError(f"Azure Search upload failed: {messages}")

# 2️⃣ Strongly consistent verification (ADD THIS HERE)
try:
    search_client.get_document(document["doc_id"])
except Exception as exc:
    raise ValueError(
        f"Uploaded document not retrievable by key: {document['doc_id']}"
    ) from exc

# 3️⃣ Success output
print(f"✅ Ingested closed case {case_id} into {CASE_INDEX_NAME}")
print(f"✅ Uploaded doc_id: {document['doc_id']}")
