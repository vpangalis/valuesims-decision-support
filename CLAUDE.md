# CLAUDE.md — CoSolve Hard Rules for Claude Code

Read this file completely before writing any code. These rules are non-negotiable.
Violation of any rule = reject the output and start again.

---

## HARD RULES

### Nodes
- Nodes are **module-level functions**, never classes
- One node per file. File name = function name = graph node name
- Every node function signature is: `def node_name(state: IncidentGraphState) -> dict`
- Nodes return a **dict slice** — only the keys they update, nothing else
- Never return a Pydantic model from a node. Never call `.model_dump()` in a node. Never call `cast()` in a node

### State
- There is **exactly one state class**: `IncidentGraphState` in `backend/state.py`
- Never create a new TypedDict or dataclass for state
- Never create a Pydantic output model for a node — collapse it into state fields instead
- State never crosses the wire to the UI — it is internal to the graph

### LLM
- Never instantiate `AzureChatOpenAI` directly in a node
- Always use `get_llm(deployment, temperature)` from `backend/llm.py`
- Each node declares its own deployment and temperature explicitly

### Tools
- Search indexes are exposed as `@tool` decorated functions in `backend/tools.py`
- Never create a custom search client class
- Never call Azure Search SDK directly from a node — always go through a tool
- Tool docstrings are mandatory — they are what the LLM reads to decide which tool to use

### API Contract
- The only objects that cross the UI/backend wire are `CoSolveRequest` and `CoSolveResponse` in `backend/api/schemas.py`
- `routes.py` is the only place where state is converted to/from the envelope
- Never expose `IncidentGraphState` fields directly in an API response

### Files
- Do not create new files without explicit instruction
- Do not modify files outside the scope of the current task
- Do not delete tested code — mark it with `# DEPRECATED` if it needs to be removed and ask first

### Classes
- Node files contain no classes
- `tools.py` contains no classes — only `@tool` functions and retriever singletons
- The only permitted classes are: `LLMProvider` in `llm.py`, `LangfuseTracer` in `tracing.py` (if re-enabled), Pydantic models in `schemas.py`, and `IncidentGraphState` in `state.py`

### Minimum Footprint
- Make the smallest possible change that solves the problem
- Audit existing code before writing anything new
- Run 4 checks after every change:
  1. `py_compile` on every modified file
  2. No new standalone functions outside permitted locations
  3. No new classes outside permitted locations
  4. API contract unchanged unless explicitly instructed

---

## REFERENCE FILES — READ BEFORE CODING

- `ARCHITECTURE.md` — structural decisions and rationale
- `REFERENCE.py` — canonical code patterns to follow exactly
- `API_CONTRACT.md` — UI/backend envelope definition

---

## NO-GO LIST

- `cast()` anywhere
- `.model_dump()` in nodes
- `__init__` in node files
- Direct Azure Search SDK calls in nodes
- New Pydantic output models for nodes
- Passing objects through node constructors
- Module-level singletons outside `llm.py` and `tools.py`
