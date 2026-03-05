// ===== API CONFIG (single source of truth) =====
const API_BASE = "http://127.0.0.1:8010";

let caseState = {};

const PHASE_META = {
  D1_2: { name: "Problem Definition", discipline: ["D1", "D2"] },
  D3: { name: "Containment Actions", discipline: "D3" },
  D4: { name: "Root Cause Analysis", discipline: "D4" },
  D5: { name: "Permanent Corrective Actions", discipline: "D5" },
  D6: { name: "Implementation & Validation", discipline: "D6" },
  D7: { name: "Prevention", discipline: "D7" },
  D8: { name: "Closure & Learnings", discipline: "D8" }
};

const DEBOUNCE_MS = 900;
let pendingPatch = {};
let saveTimer = null;


function buildEntryEnvelope(entry_mode, case_id, payload) {
  const envelope = {
    intent: "CASE_INGESTION",
    action: entry_mode,
    payload: payload || {}
  };
  if (case_id) envelope.case_id = case_id;
  return envelope;
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("File read failed"));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Unexpected FileReader result"));
        return;
      }
      // data:<mime>;base64,<data>
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

function parseCsvLine(line) {
  const result = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === "\"") {
      if (inQuotes && line[i + 1] === "\"") {
        current += "\"";
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (char === "," && !inQuotes) {
      result.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  result.push(current.trim());
  return result;
}

function parseCsvToObjects(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (!lines.length) return [];
  const headers = parseCsvLine(lines[0]).map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const obj = {};
    headers.forEach((header, idx) => {
      if (!header) return;
      obj[header] = values[idx] ?? "";
    });
    return obj;
  });
}



document.addEventListener("DOMContentLoaded", () => {




  const caseIdInput = document.getElementById("case-id-input");
  const boardEl = document.querySelector(".board");
  const leftColumn = document.querySelector(".column[data-column='left']");
  const workspaceColumn = document.querySelector(".column[data-column='workspace']");
  const aiColumn = document.querySelector(".column[data-column='ai']");
  const createBtn = document.getElementById("create-incident-btn");
  const loadBtn = document.getElementById("load-incident-btn");

  const searchInput = document.getElementById("search_input");
  const runCaseSearchBtn = document.getElementById("run_case_search_btn");
  const caseSearchResults = document.getElementById("case_search_results");
  const docBulkImportBtn = document.getElementById("doc_bulk_import_btn");
  const docBulkImportInput = document.getElementById("doc_bulk_import_input");
  const docBulkImportList = document.getElementById("doc_bulk_import_list");

  const knowledgeUploadBtn = document.getElementById("knowledge_upload_btn");
  const knowledgeUploadInput = document.getElementById("knowledge_upload_input");
  const knowledgeUploadList = document.getElementById("knowledge_upload_list");

  const aiResponseOutput = document.getElementById("ai_response_output");
  const aiQuestionInput = document.getElementById("ai_question_input");
  const aiSendBtn = document.getElementById("ai_send_btn");
  const aiClearBtn = document.getElementById("ai_clear_btn");

  // Clear inline input error as soon as the user starts typing
  if (aiQuestionInput) {
    aiQuestionInput.addEventListener("input", () => {
      const errorEl = document.getElementById("ai_input_error");
      if (errorEl) errorEl.textContent = "";
    });
  }

  const navButtons = document.querySelectorAll(".d-state-btn");
  const phaseCards = document.querySelectorAll(".phase-card[data-phase]");

  const actionButtons = document.querySelectorAll(
    "[data-action='upload-evidence'], .add-row-btn, .confirm-phase-btn"
  );

  const editFields = Array.from(
    document.querySelectorAll("[data-json-path]")
  ).filter((el) => el.id !== "case-id-input");

  const incidentIdRegex = /^[A-Za-z]{3,4}-\d{8}-\d{4}$/i;

  const uploadBtn = document.getElementById("upload-evidence-btn");
  const fileInput = document.getElementById("evidence-file-input");
  const uploadStatus = document.getElementById("upload-status");

  let evidenceMetadata = [];

  // Knowledge docs sort state
  let kbSortMode = "name-asc"; // cycles: name-asc → name-desc → date-desc → date-asc
  let kbDocsCache = [];

  const KB_SORT_MODES = ["name-asc", "name-desc", "date-desc", "date-asc"];
  const KB_SORT_TITLES = {
    "name-asc":  "Sort: A → Z",
    "name-desc": "Sort: Z → A",
    "date-desc": "Sort: Newest first",
    "date-asc":  "Sort: Oldest first"
  };
  // SVG path inner content for each sort mode
  const KB_SORT_PATHS = {
    "name-asc":  `<path d="M1 2h7M2 4.5h5M3 7h3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>`,
    "name-desc": `<path d="M1 7h7M2 4.5h5M3 2h3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>`,
    "date-desc": `<path d="M1 2h5M1 4.5h3.5M7 1.5v6M5.5 6l1.5 1.5 1.5-1.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`,
    "date-asc":  `<path d="M1 2h5M1 4.5h3.5M7 7.5V1.5M5.5 3 7 1.5 8.5 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`,
  };

  function sortKbDocs(docs) {
    const copy = [...docs];
    switch (kbSortMode) {
      case "name-asc":  return copy.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
      case "name-desc": return copy.sort((a, b) => (b.title || "").localeCompare(a.title || ""));
      case "date-desc": return copy.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      case "date-asc":  return copy.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
    }
    return copy;
  }

  let currentFocus = "workspace";
  let currentExpanded = null; // key of the currently expanded panel, or null

  const focusMap = {
    workspace: { column: workspaceColumn, boardClass: "focus-workspace" },
    ai: { column: aiColumn, boardClass: "focus-ai" },
    documents: { column: leftColumn, boardClass: null },
    default: { column: null, boardClass: null }
  };

  function setColumnFocus(mode) {
    if (!boardEl) return;
    const target = focusMap[mode] ? mode : "default";
    if (currentFocus === target) return;
    currentFocus = target;

    boardEl.classList.remove("focus-workspace", "focus-ai");
    leftColumn?.classList.remove("is-focused");
    workspaceColumn?.classList.remove("is-focused");
    aiColumn?.classList.remove("is-focused");

    const next = focusMap[target];
    if (next?.boardClass) {
      boardEl.classList.add(next.boardClass);
    }
    if (next?.column) {
      next.column.classList.add("is-focused");
    }
  }

  // ── Click-to-expand panel behaviour ─────────────────────────────────────
  // Clicking a panel title expands that panel (4fr) and collapses others (1fr).
  // Clicking the same title again returns all panels to equal width.
  const expandMap = {
    left: { column: leftColumn, boardClass: "panel-expanded-left" },
    workspace: { column: workspaceColumn, boardClass: "panel-expanded-workspace" },
    ai: { column: aiColumn, boardClass: "panel-expanded-ai" },
  };

  function togglePanelExpand(mode) {
    if (!boardEl) return;
    const entry = expandMap[mode];
    if (!entry) return;

    // Toggle off: clicking the already-active title restores equal widths.
    if (currentExpanded === mode) {
      boardEl.classList.remove(entry.boardClass);
      entry.column?.classList.remove("panel--active");
      currentExpanded = null;
      return;
    }

    // Collapse any previously expanded panel.
    if (currentExpanded && expandMap[currentExpanded]) {
      boardEl.classList.remove(expandMap[currentExpanded].boardClass);
      expandMap[currentExpanded].column?.classList.remove("panel--active");
    }

    // Expand the clicked panel.
    currentExpanded = mode;
    boardEl.classList.add(entry.boardClass);
    entry.column?.classList.add("panel--active");
  }


  // --- Safety check
  if (!caseIdInput || !createBtn) {
    console.warn("Incident ID input or Create button not found");
    return;
  }

  // --- Initial state (page load)
  createBtn.disabled = true;
  if (loadBtn) loadBtn.disabled = true;
  actionButtons.forEach(btn => btn.disabled = true);
  editFields.forEach(el => el.disabled = true);

  setColumnFocus("workspace");

  // Load knowledge document library on page start.
  refreshKnowledgeList();

  Object.keys(PHASE_META).forEach((phase) => {
    setPhaseStatus(phase, "not_started");
  });

  setActivePhaseFromCase();

  // --- Case ID typing
  caseIdInput.addEventListener("input", () => {
    const value = caseIdInput.value.trim();
    const isValid = incidentIdRegex.test(value);

    // Enable Create Incident when ID is valid
    createBtn.disabled = !isValid;
    if (loadBtn) loadBtn.disabled = !isValid;
    updateCaseIdAttention();
  });

  caseIdInput.addEventListener("focus", () => updateCaseIdAttention());
  caseIdInput.addEventListener("blur", () => updateCaseIdAttention());
  caseIdInput.addEventListener("change", () => updateCaseIdAttention());

  updateCaseIdAttention();

  // --- Due date overdue indicator
  function checkDueDateOverdue(input) {
    if (!input.value) { input.classList.remove("date-overdue"); return; }
    const today = new Date().toISOString().split("T")[0];
    // Find actual_date in the same table row (if filled, task is done — still flag if late)
    const row = input.closest("tr");
    const actualInput = row ? row.querySelector("input[data-field='actual_date'], input[data-json-path*='actual_date']") : null;
    const isDone = actualInput && actualInput.value;
    // Flag overdue: due date is in the past (regardless of completion — shows delay)
    input.classList.toggle("date-overdue", input.value < today);
  }

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.type !== "date") return;
    const path = el.dataset.jsonPath || el.dataset.field || "";
    if (path.includes("due_date")) checkDueDateOverdue(el);
    // Also re-check due_date in same row when actual_date changes
    if (path.includes("actual_date") || el.dataset.field === "actual_date") {
      const row = el.closest("tr");
      const dueInput = row ? row.querySelector("input[data-field='due_date'], input[data-json-path*='due_date']") : null;
      if (dueInput) checkDueDateOverdue(dueInput);
    }
  });

  workspaceColumn?.addEventListener("click", () => {
    setColumnFocus("workspace");
  });

  workspaceColumn?.addEventListener("focusin", () => {
    setColumnFocus("workspace");
  });

  workspaceColumn?.querySelector(".header")?.addEventListener("click", (e) => {
    e.stopPropagation(); // prevent column body listener from also firing
    togglePanelExpand("workspace");
  });

  leftColumn?.addEventListener("click", () => {
    setColumnFocus("documents");
  });

  leftColumn?.addEventListener("focusin", () => {
    setColumnFocus("documents");
  });

  leftColumn?.querySelector(".header")?.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePanelExpand("left");
  });

  aiColumn?.addEventListener("click", () => {
    setColumnFocus("ai");
  });

  aiColumn?.addEventListener("focusin", () => {
    setColumnFocus("ai");
  });

  aiColumn?.querySelector(".header")?.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePanelExpand("ai");
  });

  async function runCaseSearch() {
    if (!searchInput || !caseSearchResults) return;
    const query = searchInput.value.trim();

    if (!query) {
      caseSearchResults.innerHTML = "<div class='muted empty-state'>Enter a search query to run case search.</div>";
      return;
    }

    // Full case ID → exact OData filter path (case_id eq '...')
    const isFullCaseId = /^[A-Za-z]{3,4}-\d{8}-\d{4}$/i.test(query);
    // Partial case ID prefix/segment → text path with wildcard (e.g. "TRM", "0002", "TRM-2025")
    const isPartialCaseId = /^[A-Za-z]{3,4}(-\d{0,8}(-\d{0,4})?)?$/i.test(query)
      || /^\d{4,8}$/.test(query);
    const isCaseId = isFullCaseId;  // exact-filter path reserved for full IDs only
    // Append wildcard for partial patterns so Azure returns prefix matches.
    // Lowercase required: standard analyser stores tokens lowercased at index time,
    // but Lucene wildcard queries bypass the analyser at query time → "TRM*" misses "trm".
    const searchQuery = (isPartialCaseId && !isFullCaseId) ? query.toLowerCase() + "*" : query;
    caseSearchResults.innerHTML = "<div class='muted empty-state'>Searching cases...</div>";

    try {
      const res = await fetch(`${API_BASE}/cases/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: searchQuery,
          search_type: isCaseId ? "case_id" : "text",
          limit: 10
        })
      });

      if (!res.ok) {
        let detail = "";
        try { const err = await res.json(); detail = err?.detail || ""; } catch (_) { }
        console.error("[Search] error", res.status, detail);
        caseSearchResults.innerHTML = `<div class='error'>Search failed (${res.status})${detail ? ": " + detail : "."}</div>`;
        return;
      }

      const data = await res.json();
      renderCaseSearchResults(data);
    } catch (err) {
      console.error("[Search] fetch error", err);
      caseSearchResults.innerHTML = "<div class='error'>Could not reach the search endpoint.</div>";
    }
  }

  runCaseSearchBtn?.addEventListener("click", runCaseSearch);

  searchInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runCaseSearch();
  });

  docBulkImportBtn?.addEventListener("click", () => {
    docBulkImportInput?.click();
  });

  docBulkImportInput?.addEventListener("change", () => {
    const files = Array.from(docBulkImportInput.files || []);
    if (!files.length || !docBulkImportList) return;

    if (docBulkImportList.querySelector(".muted")) {
      docBulkImportList.innerHTML = "";
    }

    files.forEach((file) => {
      const row = document.createElement("div");
      row.className = "doc-row";

      const nameEl = document.createElement("div");
      nameEl.textContent = file.name;

      const metaEl = document.createElement("div");
      metaEl.className = "doc-meta";
      metaEl.textContent = new Date().toLocaleString();

      const statusEl = document.createElement("div");
      statusEl.className = "status-badge status-pending";
      statusEl.textContent = "Pending";

      row.appendChild(nameEl);
      row.appendChild(metaEl);
      row.appendChild(statusEl);

      docBulkImportList.appendChild(row);
    });
  });

  knowledgeUploadBtn?.addEventListener("click", () => {
    knowledgeUploadInput?.click();
  });

  // ------------------------------------------------------------------
  // Knowledge document library
  // ------------------------------------------------------------------

  function renderKbDocs(docs) {
    const listEl = document.getElementById("knowledge_upload_list");
    if (!listEl) return;

    if (!docs.length) {
      listEl.innerHTML = `<div class="muted empty-state">No knowledge documents uploaded yet.</div>`;
      return;
    }

    listEl.innerHTML = "";
    sortKbDocs(docs).forEach((doc) => {
        const row = document.createElement("div");
        row.className = "kb-doc-row";

        // File icon + truncated name (clickable) + chunk count
        const nameEl = document.createElement("div");
        nameEl.className = "kb-doc-name";
        const rawName = doc.title || doc.doc_id || "";
        const sourceFilename = doc.source || doc.title || doc.doc_id || "";
        const displayName = rawName.length > 30 ? rawName.slice(0, 29) + "\u2026" : rawName;
        nameEl.title = rawName;
        const fileUrl = `${API_BASE}/knowledge/file/${encodeURIComponent(sourceFilename)}`;
        const chunkCount = doc.chunk_count || 1;
        const chunkLabel = `(${chunkCount} chunk${chunkCount !== 1 ? "s" : ""})`;
        nameEl.innerHTML = `<span class="kb-file-icon">📄</span><a href="${fileUrl}" target="_blank" rel="noopener noreferrer" class="kb-doc-link">${displayName}</a><span class="kb-chunk-count muted"> ${chunkLabel}</span>`;

        // Date
        const dateEl = document.createElement("div");
        dateEl.className = "kb-doc-date";
        try {
          dateEl.textContent = new Date(doc.created_at).toLocaleDateString();
        } catch { dateEl.textContent = ""; }

        // Status badge
        const badgeEl = document.createElement("span");
        badgeEl.className = doc.status === "no_text"
          ? "kb-status-badge kb-status-no-text"
          : "kb-status-badge kb-status-indexed";
        badgeEl.textContent = doc.status === "no_text" ? "No text" : "Indexed";

        // Trash button
        const trashBtn = document.createElement("button");
        trashBtn.className = "kb-trash-btn";
        trashBtn.title = "Delete document";
        trashBtn.textContent = "\uD83D\uDDD1";
        trashBtn.addEventListener("click", async () => {
          const name = doc.title || doc.doc_id;
          if (!confirm(`Delete "${name}"?`)) return;
          try {
            const delRes = await fetch(`${API_BASE}/knowledge/${encodeURIComponent(doc.source || doc.title || doc.doc_id)}`, { method: "DELETE" });
            if (!delRes.ok) throw new Error(`HTTP ${delRes.status}`);
            await new Promise(resolve => setTimeout(resolve, 1500));
            await refreshKnowledgeList();
          } catch (err) {
            alert(`Delete failed: ${err.message}`);
          }
        });

        // Right-aligned controls container
        const controlsEl = document.createElement("div");
        controlsEl.className = "kb-doc-controls";
        controlsEl.appendChild(badgeEl);
        controlsEl.appendChild(trashBtn);

        row.appendChild(nameEl);
        row.appendChild(dateEl);
        row.appendChild(controlsEl);
        listEl.appendChild(row);
      });
  }

  async function refreshKnowledgeList() {
    try {
      const res = await fetch(`${API_BASE}/knowledge`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      kbDocsCache = Array.isArray(data) ? data : (data.documents || []);
      renderKbDocs(kbDocsCache);
    } catch (err) {
      console.warn("[KNOWLEDGE] refreshKnowledgeList error", err);
    }
  }

  const docSortBtn = document.getElementById("doc-sort-btn");
  if (docSortBtn) {
    docSortBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const modes = ["name-asc", "name-desc", "date-desc", "date-asc"];
      kbSortMode = modes[(modes.indexOf(kbSortMode) + 1) % modes.length];
      const icons = {
        "name-asc":  `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M7 12h10M11 18h2"/></svg>`,
        "name-desc": `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h2M7 12h10M11 18h6"/></svg>`,
        "date-desc": `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M6 12l3 3 3-3M9 15V9"/></svg>`,
        "date-asc":  `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M6 12l3-3 3 3M9 9v6"/></svg>`,
      };
      const titles = {
        "name-asc": "Sort: A→Z", "name-desc": "Sort: Z→A",
        "date-desc": "Sort: Newest first", "date-asc": "Sort: Oldest first",
      };
      docSortBtn.innerHTML = icons[kbSortMode];
      docSortBtn.title = titles[kbSortMode];
      renderKbDocs(kbDocsCache);
    });
  }

  // Show an "Uploading..." placeholder while files are in flight.
  // The real upload is handled by uploadKnowledgeDocuments() which then
  // calls refreshKnowledgeList() when done.
  knowledgeUploadInput?.addEventListener("change", () => {
    const files = Array.from(knowledgeUploadInput.files || []);
    if (!files.length || !knowledgeUploadList) return;
    knowledgeUploadList.innerHTML = files
      .map((f) => `<div class="kb-doc-row kb-uploading">
        <div class="kb-doc-name"><span class="kb-file-icon">📄</span>${f.name}</div>
        <div class="kb-doc-date"></div>
        <div class="kb-doc-controls"><span class="kb-status-badge">Uploading…</span></div>
      </div>`)
      .join("");
  });

  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const dState = btn.dataset.dState;
      if (!dState) return;
      setActivePhase(dState);
    });
  });

  document.addEventListener("keydown", async (event) => {
    const inputEl = document.getElementById("ai_question_input");
    if (event.target !== inputEl) return;
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    await submitAiQuestion();
  });

  if (aiSendBtn) {
    aiSendBtn.addEventListener("click", submitAiQuestion);
  }

  if (aiClearBtn) {
    aiClearBtn.addEventListener("click", (e) => {
      // Stop the click from propagating to the column header (which toggles column expand)
      e.stopPropagation();
      clearAiConversation();
    });
  }

  // ── Suggestion chip click delegation ─────────────────────────────────
  if (aiResponseOutput) {
    aiResponseOutput.addEventListener("click", (e) => {
      const chip = e.target.closest(".ai-suggestion-chip");
      if (!chip) return;
      const input = document.getElementById("ai_question_input");
      if (input) {
        input.value = chip.dataset.question || chip.textContent.replace(/\s+/g, ' ').trim();
        input.focus();
        if (chip.closest(".ai-suggestions-bar")) {
          input.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
    });
  }

  const evidenceListEl = document.getElementById("evidence-list");

  window.downloadEvidence = async (caseId, filename) => {
    const safeCaseId = encodeURIComponent(caseId);
    const safeFilename = encodeURIComponent(filename);

    const url = `${API_BASE}/cases/${safeCaseId}/evidence/${safeFilename}`;
    window.open(url, "_blank");
  };

  async function loadEvidence(caseId) {
    if (!evidenceListEl) return;

    evidenceListEl.textContent = "Loading evidence...";

    try {
      const safeCaseId = encodeURIComponent(caseId);
      const res = await fetch(`${API_BASE}/cases/${safeCaseId}/evidence`);
      if (!res.ok) throw new Error("Failed to load evidence");

      const data = await res.json();
      const files = Array.isArray(data?.evidence) ? data.evidence : [];
      evidenceMetadata = files.map((file) => ({
        filename: file.file_name || file.filename || "",
        size_bytes: file.size_bytes || 0,
        content_type: file.content_type || ""
      }));

      if (!files.length) {
        evidenceListEl.innerHTML = "<div class='muted empty-state'>No evidence uploaded</div>";
        return;
      }

      evidenceListEl.innerHTML = "";
      files.forEach((f) => {
        const row = document.createElement("div");
        row.className = "evidence-row";

        const fileNameEl = document.createElement("a");
        const filename = f.file_name || f.filename || "";
        fileNameEl.textContent = filename || "(unnamed)";
        fileNameEl.href = `${API_BASE}/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(filename)}`;
        fileNameEl.target = "_blank";
        fileNameEl.rel = "noopener noreferrer";
        fileNameEl.className = "evidence-link";

        const sizeEl = document.createElement("span");
        const kb = Math.round((f.size_bytes || 0) / 1024);
        sizeEl.textContent = `${kb} KB`;

        const downloadEl = document.createElement("a");
        downloadEl.textContent = "⬇";
        downloadEl.href = fileNameEl.href;
        downloadEl.target = "_blank";
        downloadEl.title = "Open / Download evidence";
        downloadEl.className = "evidence-download";

        row.appendChild(fileNameEl);
        row.appendChild(sizeEl);
        row.appendChild(downloadEl);

        evidenceListEl.appendChild(row);
      });
    } catch (err) {
      evidenceListEl.innerHTML = "<span class='error'>Failed to load evidence</span>";
    }
  }

  // --- Create Incident = formal lock only
  createBtn.addEventListener("click", async () => {
    const incidentId = caseIdInput.value.trim();

    if (!incidentIdRegex.test(incidentId)) {
      alert("Invalid Incident ID format.");
      return;
    }

    createBtn.disabled = true;

    try {
      const response = await fetch(`${API_BASE}/entry/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          buildEntryEnvelope("CREATE_CASE", null, {
            case_id: incidentId,
            case_status: "open",
            opened_at: nowIsoDate()
          })
        )
      });

      if (!response.ok) {
        const err = await response.json();
        alert(err.detail || "Failed to create case");
        createBtn.disabled = false;
        return;
      }

      // ✅ Backend confirmed → unlock UI
      caseIdInput.disabled = true;
      editFields.forEach(el => el.disabled = false);
      actionButtons.forEach(btn => btn.disabled = false);

      const nextState = buildEmptyCaseState(incidentId);
      hydrateCase(nextState);
      updateCaseIdAttention();

      loadEvidence(incidentId);

      alert(`Incident ${incidentId} created successfully`);

    } catch (err) {
      alert("Backend not reachable");
      createBtn.disabled = false;
    }
  });

  loadBtn?.addEventListener("click", async () => {
    const incidentId = caseIdInput.value.trim();
    if (!incidentIdRegex.test(incidentId)) {
      alert("Invalid Incident ID format.");
      return;
    }

    loadBtn.disabled = true;

    try {
      await loadCaseById(incidentId);
    } finally {
      loadBtn.disabled = false;
    }
  });


  // --- Track edits + autosave
  const jsonFields = document.querySelectorAll("[data-json-path]");
  jsonFields.forEach((el) => bindJsonField(el));

  uploadBtn?.addEventListener("click", () => {
    fileInput?.click();
  });

  fileInput?.addEventListener("change", async () => {
    const files = Array.from(fileInput.files || []);
    if (!files.length) return;

    const caseId = caseIdInput.value.trim();
    if (!caseId) {
      alert("Case ID missing");
      return;
    }

    if (uploadBtn) uploadBtn.disabled = true;
    if (uploadStatus) uploadStatus.textContent = "Uploading files...";

    try {
      const xhr = new XMLHttpRequest();

      const encodedFiles = [];
      for (const f of files) {
        const data_base64 = await readFileAsBase64(f);
        encodedFiles.push({
          filename: f.name,
          content_type: f.type || "application/octet-stream",
          data_base64
        });
      }

      const body = JSON.stringify(
        buildEntryEnvelope("UPLOAD_EVIDENCE", caseId, { files: encodedFiles })
      );

      xhr.open("POST", `${API_BASE}/entry/case`);
      xhr.setRequestHeader("Content-Type", "application/json");

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && uploadStatus) {
          const percent = Math.round((e.loaded / e.total) * 100);
          uploadStatus.textContent = `Uploading… ${percent}%`;
        }
      };

      xhr.onload = async () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          if (uploadStatus) uploadStatus.textContent = "Upload completed ✅";
          fileInput.value = "";
          await loadEvidence(caseId);
        } else {
          if (uploadStatus) uploadStatus.textContent = "Upload failed ❌";
          alert("Upload failed");
        }
        if (uploadBtn) uploadBtn.disabled = false;
      };

      xhr.onerror = () => {
        if (uploadStatus) uploadStatus.textContent = "Upload error ❌";
        if (uploadBtn) uploadBtn.disabled = false;
      };

      xhr.send(body);
    } catch (err) {
      if (uploadStatus) uploadStatus.textContent = "Unexpected upload error";
      if (uploadBtn) uploadBtn.disabled = false;
    }
  });

  // --- Confirm Phase buttons
  const confirmButtons = document.querySelectorAll(".confirm-phase-btn");
  confirmButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (caseState?.case_status === "closed") return;
      const phase = btn.dataset.phase;
      if (!phase) return;
      if (phase === "D8") {
        const closureDate = caseState?.d_states?.D8?.closure_date || null;
        if (!closureDate) {
          alert("Set a closure date before confirming Closure & Learnings.");
          return;
        }
      }

      const dState = ensureDState(phase);
      dState.status = "completed";
      dState.confirmed_at = dState.confirmed_at || nowIsoDate();
      setPhaseStatus(phase, dState.status);
      updateWfDurations();

      if (phase === "D8") {
        const closureDate = caseState?.d_states?.D8?.closure_date || null;
        const statusValue = "closed";
        setByPath(caseState, "closed_at", closureDate || null);
        setByPath(caseState, "case_status", statusValue);
        updateIncidentOverviewClosure(closureDate || "");
        updateIncidentOverviewStatus(statusValue);
        applyClosedState(Boolean(statusValue === "closed"));
      }

      clearPendingSave();
      if (phase === "D8") {
        await sendCaseClosureEnvelope();
      } else {
        await sendFullEnvelope("UPDATE_CASE");
      }
    });
  });

  // --- Dynamic row buttons
  const addRowButtons = document.querySelectorAll(".add-row-btn");
  addRowButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      addRow(btn);
    });
  });

  // -------- helpers --------
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function simpleMarkdown(text) {
    if (typeof text !== "string") return String(text);
    return text
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/^#{1,3}\s(.+)$/gm, "<h4>$1</h4>")
      .replace(/^[•\-]\s(.+)$/gm, "<li>$1</li>")
      .replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>")
      .replace(/\n\n/g, "</p><p>")
      .replace(/\n/g, "<br>")
      .replace(/^(?!<)/, "<p>")
      .replace(/(?<!>)$/, "</p>");
  }

  function setAiResponse(message, isError) {
    if (!aiResponseOutput) return;
    // Only overwrite when the conversation history is empty (no exchanges yet).
    // Once the user has exchanges, validation messages must not wipe them.
    const hasHistory = aiResponseOutput.querySelector(".ai-exchange") !== null;
    if (hasHistory) return;
    aiResponseOutput.innerHTML = simpleMarkdown(message);
    aiResponseOutput.classList.toggle("error", Boolean(isError));
  }

  const SEND_ICON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <line x1="22" y1="2" x2="11" y2="13"></line>
    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
  </svg>`;

  const SPINNER_SVG = `<svg class="ai-spinner" viewBox="0 0 24 24" fill="none" stroke="white"
    stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" stroke-dasharray="30" stroke-dashoffset="10"/>
  </svg>`;

  function setAiLoading(isLoading) {
    if (!aiSendBtn) return;
    aiSendBtn.disabled = isLoading;
    aiSendBtn.innerHTML = isLoading ? SPINNER_SVG : SEND_ICON_SVG;
  }

  // ── Bug 1 + Bug 2: append a question+answer exchange block ─────────
  function appendAiExchange(question, caseId, bodyHtml, isError, suggestions, nodeType) {
    if (!aiResponseOutput) return;
    suggestions = Array.isArray(suggestions) ? suggestions : [];
    // Remove empty state if present
    const emptyState = aiResponseOutput.querySelector(".ai-empty-state");
    if (emptyState) emptyState.remove();
    // Clear any plain validation-error text left behind (no .ai-exchange children)
    if (!aiResponseOutput.querySelector(".ai-exchange")) {
      aiResponseOutput.innerHTML = "";
    }
    aiResponseOutput.classList.remove("error");

    const caseLabel = (caseId && String(caseId).trim()) ? escapeHtml(caseId) : "No case loaded";
    const isStrategy = nodeType === "strategy";

    const teamSuggestions = suggestions.filter((s) => s.type === "team");
    const coSolveSuggestions = suggestions.filter((s) => s.type === "cosolve");
    const loadCaseSuggestions = suggestions.filter((s) => s.type === "load_case");
    const coSolveChipClass = isStrategy
      ? "ai-suggestion-chip ai-chip-cosolve strategy-chip"
      : "ai-suggestion-chip ai-chip-cosolve";
    const suggestionsBarHtml = suggestions.length > 0 ? (
      `<div class="ai-suggestions-bar">` +
      `<div class="ai-suggestions-label">Explore next:</div>` +
      `<div class="ai-suggestions-chips">` +
      (teamSuggestions.length > 0 ?
        `<div class="ai-suggestions-group">` +
        `<span class="ai-suggestions-group-label">Ask your team:</span>` +
        teamSuggestions.map((s) =>
          `<div class="ai-suggestion-chip ai-chip-team" data-question="${escapeHtml(s.question)}">${escapeHtml(s.label)}</div>`
        ).join("") +
        `</div>`
        : "") +
      (coSolveSuggestions.length > 0 ?
        `<div class="ai-suggestions-group">` +
        `<span class="ai-suggestions-group-label">Ask CoSolve:</span>` +
        coSolveSuggestions.map((s) =>
          `<div class="${coSolveChipClass}" data-question="${escapeHtml(s.question)}">${escapeHtml(s.label)}</div>`
        ).join("") +
        `</div>`
        : "") +
      (loadCaseSuggestions.length > 0 ?
        `<div class="ai-suggestions-group">` +
        `<span class="ai-suggestions-group-label">Load a case first:</span>` +
        loadCaseSuggestions.map((s) =>
          `<div class="ai-suggestion-chip ai-chip-load-case" data-question="">${escapeHtml(s.label)}</div>`
        ).join("") +
        `</div>`
        : "") +
      `</div>` +
      `</div>`
    ) : "";

    const exchange = document.createElement("div");
    exchange.className = "ai-exchange";
    exchange.innerHTML =
      `<div class="ai-question-header">` +
      `<span class="ai-case-ref">Case: ${caseLabel}</span>` +
      `<span class="ai-question-text">${escapeHtml(question)}</span>` +
      `</div>` +
      `<div class="ai-answer-body${isError ? " error" : ""}">${bodyHtml}</div>` +
      suggestionsBarHtml;
    aiResponseOutput.appendChild(exchange);
    exchange.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  const AI_WELCOME_HTML =
    `<div class="ai-empty-state">` +
    `<div class="ai-welcome">` +
    `<div class="ai-welcome-title">Welcome to CoSolve AI Reasoning</div>` +
    `<div class="ai-welcome-subtitle">Collaborative problem solving, powered by AI</div>` +
    `<div class="ai-welcome-section">` +
    `<div class="ai-welcome-section-label">WORKING ON AN ACTIVE PROBLEM?</div>` +
    `<div class="ai-welcome-section-hint">Load a case from the left panel first, then try:</div>` +
    `<div class="ai-welcome-suggestions">` +
    `<div class="ai-suggestion-chip">What should we focus on right now?</div>` +
    `<div class="ai-suggestion-chip">Are there any gaps we might have missed?</div>` +
    `<div class="ai-suggestion-chip">What should we prepare for the next step?</div>` +
    `</div>` +
    `</div>` +
    `<div class="ai-welcome-section">` +
    `<div class="ai-welcome-section-label">HOW ARE WE DOING?</div>` +
    `<div class="ai-welcome-section-hint">Ask performance and KPI questions:</div>` +
    `<div class="ai-welcome-suggestions">` +
    `<div class="ai-suggestion-chip strategy-chip">Show me incident counts, resolution times, and performance trends across the case portfolio.</div>` +
    `<div class="ai-suggestion-chip strategy-chip">Which areas have the most open cases right now?</div>` +
    `<div class="ai-suggestion-chip strategy-chip">How long do cases typically take to resolve?</div>` +
    `</div>` +
    `</div>` +
    `<div class="ai-welcome-section">` +
    `<div class="ai-welcome-section-label">HAVE WE SEEN THIS BEFORE?</div>` +
    `<div class="ai-welcome-section-hint">Look through past resolved cases:</div>` +
    `<div class="ai-welcome-suggestions">` +
    `<div class="ai-suggestion-chip">Have we dealt with a problem like this before?</div>` +
    `<div class="ai-suggestion-chip">Has anything similar come up in other parts of the operation?</div>` +
    `</div>` +
    `</div>` +
    `<div class="ai-welcome-section">` +
    `<div class="ai-welcome-section-label">LOOKING AT THE BIGGER PICTURE?</div>` +
    `<div class="ai-welcome-section-hint">Ask strategy and trend questions:</div>` +
    `<div class="ai-welcome-suggestions">` +
    `<div class="ai-suggestion-chip strategy-chip">What are the most recurring failure types we face?</div>` +
    `<div class="ai-suggestion-chip strategy-chip">How are we trending on unplanned failures this year?</div>` +
    `<div class="ai-suggestion-chip strategy-chip">Which areas need organisational attention?</div>` +
    `</div>` +
    `</div>` +
    `<div class="ai-welcome-hint">` +
    `Load a case from the left panel to get case-specific guidance, ` +
    `or ask any question directly to reason across the knowledge base.` +
    `</div>` +
    `</div>` +
    `</div>`;

  // ── Clear conversation (explicit user action or new case load) ──────
  // Fully resets the AI panel: removes all exchange blocks, wipes the
  // case ID header, and clears any error state — ready for a fresh context.
  function clearAiConversation() {
    if (!aiResponseOutput) return;
    aiResponseOutput.innerHTML = AI_WELCOME_HTML;
    aiResponseOutput.classList.remove("error");
  }

  // ── Dynamic AI suggestions for loaded case ─────────────────────────
  async function generateCaseSuggestions(caseId, caseContext) {
    // Only replace the welcome screen if no conversation has started yet
    const welcome = aiResponseOutput ? aiResponseOutput.querySelector(".ai-welcome") : null;
    if (!welcome) return;

    // Closed cases get retrospective chips — skip the dynamic-suggestions API call entirely
    const isClosed =
      (caseContext?.case?.status ?? caseContext?.case?.case_status ?? caseContext?.case_status ?? caseContext?.status ?? "").toLowerCase() === "closed";
    if (isClosed) {
      welcome.innerHTML =
        `<div class="ai-welcome-title">Case loaded: ${escapeHtml(caseId)}</div>` +
        `<div class="ai-welcome-subtitle">This case is closed — review what happened and what was learned</div>` +

        `<div class="ai-welcome-section">` +
        `<div class="ai-welcome-section-label">ASK COSOLVE</div>` +
        `<div class="ai-welcome-section-hint">Retrospective questions about this resolved case:</div>` +
        `<div class="ai-welcome-suggestions">` +
        `<div class="ai-suggestion-chip ai-chip-cosolve">What was the root cause?</div>` +
        `<div class="ai-suggestion-chip ai-chip-cosolve">What corrective actions were taken?</div>` +
        `<div class="ai-suggestion-chip ai-chip-cosolve">Are there similar cases in the portfolio?</div>` +
        `<div class="ai-suggestion-chip ai-chip-cosolve">How long did this case take to resolve?</div>` +
        `</div></div>` +

        `<div class="ai-welcome-section">` +
        `<div class="ai-welcome-section-label">ASK YOUR TEAM</div>` +
        `<div class="ai-welcome-section-hint">Follow-up questions to verify closure quality:</div>` +
        `<div class="ai-welcome-suggestions">` +
        `<div class="ai-suggestion-chip ai-chip-team">Were all corrective actions fully implemented?</div>` +
        `<div class="ai-suggestion-chip ai-chip-team">Have we seen this problem recur since closure?</div>` +
        `</div></div>` +

        `<div class="ai-welcome-hint">or type your own question below</div>`;
      return;
    }

    const hint = welcome.querySelector(".ai-welcome-hint");
    if (hint) hint.textContent = "Generating suggestions for this case...";

    try {
      const res = await fetch(`${API_BASE}/entry/suggestions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId, case_context: caseContext })
      });
      if (!res.ok) return; // silently fall back to static chips
      const data = await res.json();
      const suggestions = data?.suggestions ?? [];
      if (suggestions.length === 0) return;
      renderDynamicChips(welcome, suggestions, caseId, caseContext);
    } catch (e) {
      // silent fallback — static chips remain, restore hint text
      if (hint) {
        hint.textContent =
          "Load a case from the left panel to get case-specific guidance, " +
          "or ask any question directly to reason across the knowledge base.";
      }
    }
  }

  function renderDynamicChips(welcome, suggestions, caseId, caseContext) {
    const operational = suggestions.filter((_, i) => i < 2);
    const similarity = suggestions.filter((_, i) => i >= 2 && i < 4);
    const broader = suggestions.filter((_, i) => i >= 4);

    function chipHtml(s) {
      return (
        `<div class="ai-suggestion-chip" data-question="${escapeHtml(s.question)}">` +
        escapeHtml(s.label) +
        `</div>`
      );
    }

    welcome.innerHTML =
      `<div class="ai-welcome-title">Case loaded: ${escapeHtml(caseId)}</div>` +
      `<div class="ai-welcome-subtitle">Suggested questions based on this case</div>` +

      `<div class="ai-welcome-section">` +
      `<div class="ai-welcome-section-label">CURRENT INVESTIGATION</div>` +
      `<div class="ai-welcome-section-hint">Questions about the active case state and next steps:</div>` +
      `<div class="ai-welcome-suggestions">` +
      operational.map(chipHtml).join("") +
      `</div></div>` +

      `<div class="ai-welcome-section">` +
      `<div class="ai-welcome-section-label">HAVE WE SEEN THIS BEFORE?</div>` +
      `<div class="ai-welcome-section-hint">Look through past resolved cases for anything similar:</div>` +
      `<div class="ai-welcome-suggestions">` +
      similarity.map(chipHtml).join("") +
      `</div></div>` +

      `<div class="ai-welcome-section">` +
      `<div class="ai-welcome-section-label">LOOKING AT THE BIGGER PICTURE?</div>` +
      `<div class="ai-welcome-section-hint">Patterns and trends across all areas and teams:</div>` +
      `<div class="ai-welcome-suggestions">` +
      broader.map(chipHtml).join("") +
      `</div></div>` +

      `<div class="ai-welcome-hint">` +
      `<button id="ai_refresh_suggestions" class="ai-refresh-btn">↻ Refresh suggestions</button>` +
      `or type your own question below` +
      `</div>`;

    // Re-wire chip clicks (delegation lost after innerHTML replace)
    welcome.addEventListener("click", (e) => {
      const chip = e.target.closest(".ai-suggestion-chip");
      if (chip) {
        const input = document.getElementById("ai_question_input");
        if (input) {
          input.value = chip.dataset.question || chip.textContent.trim();
          input.focus();
        }
      }
      const refresh = e.target.closest("#ai_refresh_suggestions");
      if (refresh) {
        generateCaseSuggestions(caseId, caseContext);
      }
    });
  }

  function buildStatsHtml(sd) {
    const nodeNames = Object.keys(sd.call_volume || {});
    const shortName = n => n.replace("_reasoning", "").replace("_reflection", " \u21a9").replace(/_/g, " ");
    const chartId = () => "chart-" + Math.random().toString(36).slice(2, 8);

    // \u2500\u2500 Pie chart \u2014 call distribution \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const pieId = chartId();
    const pieLabels = nodeNames.map(shortName);
    const pieData = nodeNames.map(n => sd.call_volume[n]);
    const pieColors = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
      "#edc948", "#b07aa1", "#ff9da7", "#9c755f"];

    // \u2500\u2500 Bar \u2014 call volume \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const volId = chartId();

    // \u2500\u2500 Bar \u2014 avg response time \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const rtId = chartId();
    const rtNodes = Object.keys(sd.response_time || {});
    const rtAvg = rtNodes.map(n => sd.response_time[n].avg);
    const rtMin = rtNodes.map(n => sd.response_time[n].min);
    const rtMax = rtNodes.map(n => sd.response_time[n].max);

    // \u2500\u2500 Bar \u2014 token counts \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const tokId = chartId();
    const tokNodes = Object.keys(sd.token_counts || {});
    const tokPrompt = tokNodes.map(n => sd.token_counts[n].prompt);
    const tokCompletion = tokNodes.map(n => sd.token_counts[n].completion);

    const lineId = chartId();
    const timeSeries = sd.time_series || [];
    const tsLabels = timeSeries.map(t => t.hour.slice(11) + ":00");
    const tsCalls = timeSeries.map(t => t.calls);

    // \u2500\u2500 Cost table \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    const cost = sd.cost || {};
    const regen = sd.regeneration || {};
    const slow = sd.slow_calls || [];

    const html = `
<div class="stats-dashboard" style="font-family:inherit;padding:0 0 12px">
  <div style="font-size:1.1em;font-weight:700;color:#1a3a5c;margin-bottom:4px">
    &#9881;&#65039; LLM Performance Stats
  </div>
  <div style="font-size:0.82em;color:#666;margin-bottom:16px">
    ${sd.total_calls} calls &middot; ${sd.date_range}
  </div>

  <!-- Row 0: Call volume over time -->
  <div style="background:#f8fafc;border-radius:8px;padding:12px;margin-bottom:16px">
    <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
      CALL VOLUME OVER TIME
    </div>
    <canvas id="${lineId}" height="80"></canvas>
  </div>

  <!-- Row 1: Pie + Call Volume -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
    <div style="background:#f8fafc;border-radius:8px;padding:12px">
      <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
        CALL DISTRIBUTION
      </div>
      <canvas id="${pieId}" height="200"></canvas>
    </div>
    <div style="background:#f8fafc;border-radius:8px;padding:12px">
      <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
        CALL VOLUME PER NODE
      </div>
      <canvas id="${volId}" height="200"></canvas>
    </div>
  </div>

  <!-- Row 2: Response Time -->
  <div style="background:#f8fafc;border-radius:8px;padding:12px;margin-bottom:16px">
    <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
      RESPONSE TIME PER NODE (ms)
    </div>
    <canvas id="${rtId}" height="140"></canvas>
  </div>

  <!-- Row 3: Token Counts -->
  <div style="background:#f8fafc;border-radius:8px;padding:12px;margin-bottom:16px">
    <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
      AVG TOKEN COUNTS PER NODE
    </div>
    <canvas id="${tokId}" height="140"></canvas>
  </div>

  <!-- Row 4: Cost + Regeneration -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
    <div style="background:#f8fafc;border-radius:8px;padding:12px">
      <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
        ESTIMATED COST
      </div>
      <table style="width:100%;font-size:0.82em;border-collapse:collapse">
        <tr><td style="padding:3px 0;color:#555">Total (window)</td>
            <td style="text-align:right;font-weight:600">$${cost.total?.toFixed(4)}</td></tr>
        <tr><td style="padding:3px 0;color:#555">Per call</td>
            <td style="text-align:right;font-weight:600">$${cost.per_call?.toFixed(5)}</td></tr>
        <tr><td colspan="2" style="padding-top:6px;font-size:0.78em;color:#999">
            ${cost.disclaimer || ""}</td></tr>
      </table>
    </div>
    <div style="background:#f8fafc;border-radius:8px;padding:12px">
      <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
        REGENERATION RATE
      </div>
      <div style="font-size:1.8em;font-weight:700;color:#4e79a7">
        ${regen.rate_pct}%
      </div>
      <div style="font-size:0.8em;color:#666;margin-top:4px">
        ${regen.reflection_calls} reflection calls / ${regen.total_calls} total
      </div>
    </div>
  </div>

  <!-- Row 5: Slowest calls -->
  <div style="background:#f8fafc;border-radius:8px;padding:12px">
    <div style="font-size:0.8em;font-weight:600;color:#444;margin-bottom:8px">
      SLOWEST 5 CALLS
    </div>
    <table style="width:100%;font-size:0.8em;border-collapse:collapse">
      <tr style="color:#888;font-size:0.78em">
        <th style="text-align:left;padding:3px 6px 3px 0">ms</th>
        <th style="text-align:left;padding:3px 6px">node</th>
        <th style="text-align:left;padding:3px 0">question</th>
      </tr>
      ${slow.map(s => `
      <tr style="border-top:1px solid #eee">
        <td style="padding:4px 6px 4px 0;font-weight:600;color:#e15759">${s.ms}</td>
        <td style="padding:4px 6px;color:#555">${shortName(s.node)}</td>
        <td style="padding:4px 0;color:#333">${s.question}</td>
      </tr>`).join("")}
    </table>
  </div>
</div>
<div data-stats-pending="1"
     data-pie="${pieId}" data-vol="${volId}"
     data-rt="${rtId}" data-tok="${tokId}"
     data-line="${lineId}"
     data-ts-labels='${JSON.stringify(tsLabels)}'
     data-ts-calls='${JSON.stringify(tsCalls)}'
     data-pie-labels='${JSON.stringify(pieLabels)}'
     data-pie-data='${JSON.stringify(pieData)}'
     data-rt-nodes='${JSON.stringify(rtNodes)}'
     data-rt-avg='${JSON.stringify(rtAvg)}'
     data-rt-min='${JSON.stringify(rtMin)}'
     data-rt-max='${JSON.stringify(rtMax)}'
     data-tok-nodes='${JSON.stringify(tokNodes)}'
     data-tok-prompt='${JSON.stringify(tokPrompt)}'
     data-tok-completion='${JSON.stringify(tokCompletion)}'
     data-vol-data='${JSON.stringify(pieData)}'
     data-labels='${JSON.stringify(nodeNames.map(n => n.replace("_reasoning", "").replace("_reflection", " \u21a9").replace(/_/g, " ")))}'     style="display:none"></div>`;
    return html;
  }

  function initStatsCharts() {
    const sentinel = document.querySelector("[data-stats-pending='1']");
    if (!sentinel) return;
    if (typeof Chart === "undefined") {
      setTimeout(initStatsCharts, 100);
      return;
    }
    sentinel.removeAttribute("data-stats-pending");

    const colors = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
      "#edc948", "#b07aa1", "#ff9da7", "#9c755f"];
    const shortLabels = JSON.parse(sentinel.dataset.labels);
    const pieData = JSON.parse(sentinel.dataset.pieData);
    const volData = JSON.parse(sentinel.dataset.volData);
    const rtNodes = JSON.parse(sentinel.dataset.rtNodes).map(
      n => n.replace("_reasoning", "").replace("_reflection", " \u21a9").replace(/_/g, " "));
    const rtAvg = JSON.parse(sentinel.dataset.rtAvg);
    const rtMin = JSON.parse(sentinel.dataset.rtMin);
    const rtMax = JSON.parse(sentinel.dataset.rtMax);
    const tokNodes = JSON.parse(sentinel.dataset.tokNodes).map(
      n => n.replace("_reasoning", "").replace("_reflection", " \u21a9").replace(/_/g, " "));
    const tokPrompt = JSON.parse(sentinel.dataset.tokPrompt);
    const tokCompletion = JSON.parse(sentinel.dataset.tokCompletion);

    const opts = (extra) => Object.assign({
      responsive: true,
      plugins: { legend: { labels: { font: { size: 10 } } } },
      scales: {
        y: { beginAtZero: true, ticks: { font: { size: 10 } } },
        x: { ticks: { font: { size: 9 } } }
      }
    }, extra || {});

    // Doughnut
    new Chart(document.getElementById(sentinel.dataset.pie), {
      type: "doughnut",
      data: { labels: shortLabels, datasets: [{ data: pieData, backgroundColor: colors }] },
      options: {
        responsive: true,
        plugins: { legend: { position: "right", labels: { font: { size: 10 } } } }
      }
    });

    // Call volume
    new Chart(document.getElementById(sentinel.dataset.vol), {
      type: "bar",
      data: {
        labels: shortLabels,
        datasets: [{ label: "calls", data: volData, backgroundColor: "#4e79a7" }]
      },
      options: opts({ plugins: { legend: { display: false } } })
    });

    // Response time
    new Chart(document.getElementById(sentinel.dataset.rt), {
      type: "bar",
      data: {
        labels: rtNodes, datasets: [
          { label: "avg ms", data: rtAvg, backgroundColor: "#4e79a7" },
          { label: "min ms", data: rtMin, backgroundColor: "#59a14f" },
          { label: "max ms", data: rtMax, backgroundColor: "#e15759" },
        ]
      },
      options: opts()
    });

    // Token counts
    new Chart(document.getElementById(sentinel.dataset.tok), {
      type: "bar",
      data: {
        labels: tokNodes, datasets: [
          { label: "prompt", data: tokPrompt, backgroundColor: "#4e79a7" },
          { label: "completion", data: tokCompletion, backgroundColor: "#f28e2b" },
        ]
      },
      options: opts()
    });

    // Call volume over time
    const tsLabels2 = JSON.parse(sentinel.dataset.tsLabels);
    const tsCalls2 = JSON.parse(sentinel.dataset.tsCalls);
    if (tsLabels2.length > 0) {
      new Chart(document.getElementById(sentinel.dataset.line), {
        type: "line",
        data: {
          labels: tsLabels2,
          datasets: [{
            label: "calls",
            data: tsCalls2,
            borderColor: "#4e79a7",
            backgroundColor: "rgba(78,121,167,0.1)",
            tension: 0.3,
            fill: true,
            pointRadius: 4,
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            y: { beginAtZero: true, ticks: { font: { size: 10 } } },
            x: { ticks: { font: { size: 10 } } }
          }
        }
      });
    }
  }

  function formatAiResponse(envelope) {
    if (envelope?.data?.status === "stats") {
      const sd = envelope?.data?.stats_data;
      // Fallback: plain text answer (no records case)
      if (!sd || typeof sd !== "object") {
        const answer = envelope?.data?.answer || "No stats available.";
        return `<div class="ai-section"><pre style="white-space:pre-wrap;font-family:inherit;font-size:0.92em;line-height:1.6">${answer}</pre></div>`;
      }
      return buildStatsHtml(sd);
    }

    // Guard: envelope missing entirely
    if (!envelope) return '<em>No response received.</em>';

    // Guard: top-level error signalled by FastAPI wrapper
    if (envelope.status === "error" || envelope.status === "failed") {
      const errMsg = envelope?.data?.error
        ?? envelope?.data?.message
        ?? envelope?.message
        ?? "An error occurred. Please try again.";
      return `<p><strong>Error:</strong> ${errMsg}</p>`;
    }

    const payload = envelope?.data;
    if (!payload) return '<em>No response data received.</em>';
    if (payload.status === "usage") return `<p>${payload.message || "Provide a non-empty question."}</p>`;

    const intent = payload.classification?.intent ?? "UNKNOWN";
    const result = payload.result;

    // DIAGNOSTIC — remove after validation confirms all 4 intents render correctly
    console.group(`[AI Response] intent: ${intent}`);
    console.log("full envelope:", envelope);
    console.log("data:", payload);
    console.log("result:", result);
    console.log("result type:", typeof result);
    if (result && typeof result === "object") {
      console.log("result keys:", Object.keys(result));
    }
    console.groupEnd();

    // Guard: result missing or empty
    if (result === null || result === undefined) {
      console.warn("[formatAiResponse] result is null/undefined. Full envelope:", envelope);
      return "<em>The system returned a response but no answer content was found. Check the browser console for details.</em>";
    }
    if (typeof result === "object" && Object.keys(result).length === 0) {
      return '<em>AI request completed with no content.</em>';
    }

    // Extract the main structured text per intent type.
    // For OPERATIONAL_CASE the full LLM response is in current_state_recommendations.
    // For all other intents it is in summary.
    let mainText = "";
    switch (intent) {
      case "OPERATIONAL_CASE":
        mainText = result?.current_state_recommendations ?? result?.current_state ?? result?.summary ?? "";
        break;
      case "SIMILARITY_SEARCH":
        mainText = result?.summary ?? "";
        break;
      case "STRATEGY_ANALYSIS":
        mainText = result?.summary ?? "";
        break;
      case "KPI_ANALYSIS":
        // KPI has rich structured rendering — bypass formatAiText
        return formatKpiResult(result);
      default:
        if (typeof result === "string") mainText = result;
        else mainText = result?.summary ?? result?.answer ?? result?.result ?? JSON.stringify(result, null, 2);
    }

    return formatAiText(mainText);
  }

  // ── KPI rendering ─────────────────────────────────────────────────

  // Chart.js dynamic loading state
  let _chartJsLoaded = typeof Chart !== "undefined";
  let _chartJsLoading = false;
  let _chartJsCallbacks = [];
  const CHART_JS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
  const _kpiChartInstances = new Map();

  function ensureChartJs(callback) {
    if (_chartJsLoaded) { callback(); return; }
    _chartJsCallbacks.push(callback);
    if (_chartJsLoading) return;
    _chartJsLoading = true;
    const script = document.createElement("script");
    script.src = CHART_JS_CDN;
    script.onload = () => {
      _chartJsLoaded = true;
      _chartJsLoading = false;
      _chartJsCallbacks.forEach((cb) => cb());
      _chartJsCallbacks = [];
    };
    script.onerror = () => {
      _chartJsLoading = false;
      _chartJsCallbacks = [];
      console.error("[KPI] Chart.js failed to load.");
    };
    document.head.appendChild(script);
  }

  function initPendingKpiCharts() {
    const canvases = document.querySelectorAll(".kpi-bar-chart.pending-chart");
    if (!canvases.length) return;
    ensureChartJs(() => {
      canvases.forEach((canvas) => {
        canvas.classList.remove("pending-chart");
        let chartConfig;
        try {
          chartConfig = JSON.parse(canvas.dataset.chartConfig);
        } catch (e) {
          console.error("[KPI] Invalid chart config", e);
          return;
        }
        // Assign stable id and destroy any prior instance on this canvas
        if (!canvas.id) canvas.id = "kpi-chart-" + Date.now() + "-" + Math.floor(Math.random() * 1e6);
        if (_kpiChartInstances.has(canvas.id)) {
          _kpiChartInstances.get(canvas.id).destroy();
          _kpiChartInstances.delete(canvas.id);
        }
        const chart = new Chart(canvas, {
          type: "bar",
          data: {
            labels: chartConfig.labels,
            datasets: [{
              label: "Avg. Days to Close",
              data: chartConfig.values,
              backgroundColor: "rgba(59, 130, 246, 0.55)",
              borderColor: "rgba(59, 130, 246, 0.9)",
              borderWidth: 1,
              borderRadius: 4,
            }]
          },
          options: {
            responsive: true,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (ctx) => ctx.parsed.y + " days" } }
            },
            scales: {
              y: { beginAtZero: true, title: { display: true, text: "Days" } }
            }
          }
        });
        _kpiChartInstances.set(canvas.id, chart);
      });
    });
  }

  function formatKpiResult(result) {
    if (!result) return '<em>No performance data available.</em>';
    const renderHint = result.render_hint ?? result.metrics?.render_hint ?? "summary_text";
    const scopeLabel = result.scope_label ?? result.metrics?.scope_label ?? "";
    const metrics = result.metrics ?? {};
    const summary = result.summary ?? "";
    const insights = Array.isArray(result.insights) ? result.insights : [];

    let html = "";

    // Scope header
    if (scopeLabel) {
      html += '<div class="ai-section"><div class="ai-section-title">' + escapeHtml(scopeLabel) + '</div></div>';
    }

    // LLM summary paragraph
    if (summary && renderHint !== "summary_text") {
      html += '<div class="ai-section-body"><p>' + escapeHtml(summary) + '</p></div>';
    }

    // Key insights
    if (insights.length > 0) {
      html += '<div class="ai-section"><div class="ai-section-title">Key Insights</div><div class="ai-section-body"><ul>';
      insights.forEach((ins) => { html += '<li>' + escapeHtml(ins) + '</li>'; });
      html += '</ul></div></div>';
    }

    // Metric block dispatched by render_hint
    switch (renderHint) {
      case "table": html += _kpiRenderTable(metrics); break;
      case "bar_chart": html += _kpiRenderBarChart(metrics); break;
      case "gauge": html += _kpiRenderGauge(metrics); break;
      case "summary_text":
      default:
        if (summary) html += '<div class="ai-section-body"><p>' + escapeHtml(summary) + '</p></div>';
        break;
    }

    return html || '<em>No performance data available.</em>';
  }

  function _kpiMetricRows(metrics) {
    const rows = [];
    if (metrics.total_cases_opened_ytd != null) rows.push(["Cases Opened (Year to Date)", metrics.total_cases_opened_ytd]);
    if (metrics.total_cases_closed_ytd != null) rows.push(["Cases Closed (Year to Date)", metrics.total_cases_closed_ytd]);
    if (metrics.avg_closure_days_ytd != null) rows.push(["Average Days to Close (Year to Date)", metrics.avg_closure_days_ytd + " days"]);
    if (metrics.avg_closure_days_rolling_12m != null) rows.push(["Average Days to Close (12-Month Rolling)", metrics.avg_closure_days_rolling_12m + " days"]);
    if (metrics.overdue_count != null) rows.push(["Overdue Cases", metrics.overdue_pct != null ? metrics.overdue_count + " (" + metrics.overdue_pct + "%)" : String(metrics.overdue_count)]);
    if (metrics.first_closure_rate != null) rows.push(["Resolved Without Reopening", Math.round(metrics.first_closure_rate * 100) + "%"]);
    return rows;
  }

  function _kpiRenderTable(metrics) {
    let html = "";
    const rows = _kpiMetricRows(metrics);
    if (rows.length > 0) {
      html += '<div class="ai-section"><div class="ai-section-title">Performance Summary</div><div class="ai-section-body">';
      html += '<table class="kpi-table"><tbody>';
      rows.forEach(([label, value]) => {
        html += '<tr><td class="kpi-label">' + escapeHtml(label) + '</td><td class="kpi-value">' + escapeHtml(String(value)) + '</td></tr>';
      });
      html += '</tbody></table></div></div>';
    }
    if (metrics.d_stage_distribution && Object.keys(metrics.d_stage_distribution).length > 0) {
      html += '<div class="ai-section"><div class="ai-section-title">Active Cases by Stage</div><div class="ai-section-body">';
      html += '<table class="kpi-table"><tbody>';
      Object.entries(metrics.d_stage_distribution).forEach(([stage, count]) => {
        html += '<tr><td class="kpi-label">' + escapeHtml(stage) + '</td><td class="kpi-value">' + escapeHtml(String(count)) + '</td></tr>';
      });
      html += '</tbody></table></div></div>';
    }
    if (Array.isArray(metrics.country_ranking) && metrics.country_ranking.length > 0) {
      html += '<div class="ai-section"><div class="ai-section-title">Performance by Country</div><div class="ai-section-body">';
      html += '<table class="kpi-table"><thead><tr><th>Country</th><th>Avg. Days to Close</th><th>Cases Closed</th></tr></thead><tbody>';
      metrics.country_ranking.forEach((row) => {
        html += '<tr><td>' + escapeHtml(String(row.country ?? "")) + '</td><td>' + escapeHtml(String(row.avg_closure_days ?? "")) + '</td><td>' + escapeHtml(String(row.total_closed ?? "")) + '</td></tr>';
      });
      html += '</tbody></table></div></div>';
    }
    return html;
  }

  function _kpiRenderBarChart(metrics) {
    // Render summary metrics + stage distribution (suppress ranking table — chart covers it)
    const metricsWithoutRanking = Object.assign({}, metrics, { country_ranking: null });
    let html = _kpiRenderTable(metricsWithoutRanking);
    const ranking = Array.isArray(metrics.country_ranking) ? metrics.country_ranking : [];
    if (ranking.length > 0) {
      const chartData = JSON.stringify({ labels: ranking.map((r) => r.country), values: ranking.map((r) => r.avg_closure_days) });
      html += '<div class="ai-section"><div class="ai-section-title">Average Days to Close by Country</div><div class="ai-section-body"><div class="kpi-chart-container"><canvas class="kpi-bar-chart pending-chart" data-chart-config="' + escapeHtml(chartData) + '" aria-label="Average days to close by country"></canvas></div></div></div>';
    }
    return html;
  }

  function _kpiRenderGauge(metrics) {
    let html = "";
    const elapsed = metrics.days_elapsed;
    const benchmark = metrics.category_benchmark_days;
    if (elapsed != null && benchmark != null && benchmark > 0) {
      const maxDays = Math.max(benchmark * 1.5, elapsed);
      const pct = Math.min(100, Math.round((elapsed / maxDays) * 100));
      const r = 45;
      const circumference = +(2 * Math.PI * r).toFixed(2);
      const dashOffset = +((circumference * (1 - pct / 100)).toFixed(2));
      const color = pct <= 60 ? "#22c55e" : pct <= 90 ? "#f59e0b" : "#ef4444";
      const gaugeTitle = metrics.gauge_label ? "Case Resolution" : "Case Progress";
      html += '<div class="ai-section"><div class="ai-section-title">' + gaugeTitle + '</div><div class="ai-section-body">';
      html += '<div class="kpi-gauge-container">';
      html += '<svg class="kpi-gauge-svg" viewBox="0 0 100 100" width="140" height="140" role="img" aria-label="' + pct + '% of expected resolution time">';
      html += '<circle cx="50" cy="50" r="' + r + '" fill="none" stroke="#e5e7eb" stroke-width="8"/>';
      html += '<circle cx="50" cy="50" r="' + r + '" fill="none" stroke="' + color + '" stroke-width="8" stroke-linecap="round" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + dashOffset + '" transform="rotate(-90 50 50)"/>';
      html += '<text x="50" y="47" text-anchor="middle" font-size="18" font-weight="700" fill="currentColor">' + pct + '%</text>';
      html += '<text x="50" y="62" text-anchor="middle" font-size="8" fill="#6b7280">of expected</text>';
      html += '</svg>';
      if (metrics.gauge_label) {
        html += '<div class="kpi-gauge-legend"><span>' + escapeHtml(metrics.gauge_label) + '</span></div>';
      } else {
        html += '<div class="kpi-gauge-legend"><span>' + escapeHtml(String(elapsed)) + ' days open</span><span>Typical: ' + escapeHtml(String(Math.round(benchmark))) + ' days</span></div>';
      }
      html += '</div></div></div>';
    }
    const detailRows = [];
    if (metrics.current_stage) detailRows.push(["Current Stage", metrics.current_stage]);
    if (metrics.responsible_leader) detailRows.push(["Responsible Leader", metrics.responsible_leader]);
    if (metrics.department) detailRows.push(["Department", metrics.department]);
    if (metrics.days_elapsed != null) detailRows.push([metrics.gauge_label ? "Days to Closure" : "Days Open", metrics.days_elapsed + " days"]);
    if (metrics.category_benchmark_days != null) detailRows.push(["Typical Resolution", Math.round(metrics.category_benchmark_days) + " days"]);
    if (detailRows.length > 0) {
      html += '<div class="ai-section"><div class="ai-section-title">Case Details</div><div class="ai-section-body">';
      html += '<table class="kpi-table"><tbody>';
      detailRows.forEach(([label, value]) => {
        html += '<tr><td class="kpi-label">' + escapeHtml(label) + '</td><td class="kpi-value">' + escapeHtml(String(value)) + '</td></tr>';
      });
      html += '</tbody></table></div></div>';
    }
    return html;
  }

  function formatAiText(text) {
    if (!text) return '<em>No response received.</em>';

    // Define section labels and their display titles
    const sections = [
      { marker: '[SIMILAR CASES FOUND]', title: 'Similar Cases Found' },
      { marker: '[PATTERNS ACROSS CASES]', title: 'Patterns Across Cases' },
      { marker: '[WHAT THIS MEANS FOR YOUR INVESTIGATION]', title: 'What This Means For Your Investigation' },
      { marker: '[WHAT THIS REVEALS]', title: 'What This Reveals' },
      { marker: '[SIMILAR CASES — CHECK FIRST]', title: 'Check If This Has Happened Before' },
      { marker: '[IF THIS IS A NEW PROBLEM — HOW TO START]', title: 'How To Start' },
      { marker: '[CURRENT STATE]', title: 'Current State' },
      { marker: '[GAPS IN PREVIOUS STATES]', title: 'Gaps to Address' },
      { marker: '[NEXT STATE PREVIEW]', title: 'Next Steps Preview' },
      // Strategy-specific sections
      { marker: '[SYSTEMIC PATTERNS IDENTIFIED]', title: 'Systemic Patterns Identified' },
      { marker: '[ROOT CAUSE CATEGORIES]', title: 'Root Cause Categories' },
      { marker: '[ORGANISATIONAL WEAKNESSES]', title: 'Organisational Weaknesses' },
      // Closed case summary sections
      { marker: '[RESOLUTION SUMMARY]', title: 'Resolution Summary' },
      { marker: '[ROOT CAUSE]', title: 'Root Cause' },
      { marker: '[ACTIONS TAKEN]', title: 'Actions Taken' },
      { marker: '[LESSONS LEARNED]', title: 'Lessons Learned' },
      { marker: '[GENERAL ADVICE]', title: null },  // render as callout, no header
      { marker: '[WHAT TO EXPLORE NEXT]', title: null },  // rendered as chips only
      { marker: '[KNOWLEDGE REFERENCES]', title: 'Knowledge References' },
    ];

    // Strip [WHAT TO EXPLORE NEXT] and everything after — chips handle that section
    const exploreMarker = '[WHAT TO EXPLORE NEXT]';
    const exploreIndex = text.indexOf(exploreMarker);
    const mainText = exploreIndex > -1 ? text.substring(0, exploreIndex) : text;

    // Build a regex that splits on any known marker
    const allMarkers = sections
      .filter((s) => s.marker !== exploreMarker)
      .map((s) => s.marker.replace(/[\[\]]/g, '\\$&'))
      .join('|');
    const splitRegex = new RegExp(`(${allMarkers})`, 'g');

    const parts = mainText.trim().split(splitRegex).filter((p) => p.trim());

    let html = '';
    let i = 0;
    while (i < parts.length) {
      const part = parts[i].trim();
      const sectionDef = sections.find((s) => s.marker === part);

      if (sectionDef) {
        const content = (parts[i + 1] || '').trim();
        i += 2;

        if (sectionDef.marker === '[GENERAL ADVICE]') {
          // Render general advice as an amber callout block
          html += `<div class="ai-section-callout">${formatSectionContent(content)}</div>`;
        } else if (sectionDef.marker === '[KNOWLEDGE REFERENCES]') {
          const lines = content.split('\n').filter(l => l.trim());
          let innerHtml = '';
          const refLines = lines.filter(l => l.startsWith('KNOWLEDGEREF|'));
          const otherLines = lines.filter(l => !l.startsWith('KNOWLEDGEREF|'));

          if (refLines.length > 0) {
            innerHtml += '<ul class="knowledge-refs-list" style="list-style:none;padding:0;margin:0;">';
            refLines.forEach(line => {
              const parts = line.split('|');
              // parts: [0]=KNOWLEDGEREF [1]=filename [2]=section [3]=page [4+]=excerpt
              const filename = parts[1] || '';
              const section = parts[2] || '';
              const page = parts[3] || '';
              const scorePct = (parts[5] && parts[5].match(/^\d+%$/)) ? parts[5] : '';
              const excerpt = parts[4] || '';

              let meta = '';
              if (section) meta += ` | \u00a7${section}`;
              if (page) meta += ` (p.${page})`;

              innerHtml +=
                '<li style="margin-bottom:12px;">' +
                `<a href="${API_BASE}/knowledge/file/${encodeURIComponent(filename)}" ` +
                `target="_blank" rel="noopener noreferrer" class="knowledge-file-link" ` +
                `data-filename="${filename}" style="font-weight:600;">` +
                `${filename}</a>` +
                `<span style="color:#666;">${meta}</span>` +
                (excerpt
                  ? `<div class="knowledge-excerpt" style="margin-top:4px;font-style:italic;` +
                  `color:#444;font-size:0.9em;">"${excerpt}"` +
                  (scorePct ? `<span class="kb-score-badge">${scorePct}</span>` : '') +
                  `</div>`
                  : '') +
                '</li>';
            });
            innerHtml += '</ul>';
          } else {
            // No relevant knowledge documents passed the relevance threshold
            innerHtml += '<div class="knowledge-empty">No relevant knowledge found for this problem.</div>';
          }

          // Fallback: render any non-KNOWLEDGEREF lines as plain text
          if (otherLines.length > 0) {
            innerHtml += `<p style="margin-top:8px;">${otherLines.join('<br>')}</p>`;
          }

          html +=
            '<div class="ai-section">' +
            `<div class="ai-section-title">Knowledge References</div>` +
            `<div class="ai-section-body">${innerHtml}</div>` +
            '</div>';

        } else if (sectionDef.title) {
          // Render as a titled section
          html +=
            '<div class="ai-section">' +
            `<div class="ai-section-title">${sectionDef.title}</div>` +
            `<div class="ai-section-body">${formatSectionContent(content)}</div>` +
            '</div>';
        }
      } else {
        // Unlabelled text before first section — render as intro paragraph
        if (part.length > 0) {
          html += `<div class="ai-section-body">${formatSectionContent(part)}</div>`;
        }
        i++;
      }
    }

    return html || '<em>No structured response received.</em>';
  }

  function formatSectionContent(text) {
    if (!text) return '';

    let html = text
      // Sub-bullet: bullet line whose content starts with [ — indicates a case ID citation
      // e.g. • [France][Lyon] TRM-20250301-0001  (no indentation required)
      .replace(/^[ \t]*[•\-]\s+(\[.+)$/gm, '<li class="sub-bullet">$1</li>')
      // Top-level bullet: bullet line whose content does NOT start with [ (category name)
      .replace(/^[ \t]*[•\-]\s+([^\[].*)$/gm, '<li>$1</li>')
      // Convert numbered lines (1. 2. etc.) to list items
      .replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>')
      // Wrap consecutive sub-bullet <li> runs in their own <ul class="sub-bullet-list">
      .replace(/(<li class="sub-bullet">(?:[\s\S]*?)<\/li>(?:\s*<li class="sub-bullet">(?:[\s\S]*?)<\/li>)*)/g, '<ul class="sub-bullet-list">$1</ul>')
      // Wrap remaining consecutive plain <li> runs in <ul>
      .replace(/(<li>(?:[\s\S]*?)<\/li>(?:\s*<li>(?:[\s\S]*?)<\/li>)*)/g, '<ul>$1</ul>')
      // Convert **bold** markdown
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      // Double newline → paragraph break
      .replace(/\n\n+/g, '</p><p>')
      // Single newline → <br>
      .replace(/\n/g, '<br>')
      // Strip <br> injected between </li> and <li> by the pass above
      .replace(/(<\/li>)\s*<br\s*\/?>\s*(<li)/g, '$1$2')
      // Wrap the whole thing in <p> tags
      .replace(/^(.+)$/, '<p>$1</p>');

    // Clean up artefacts
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>(<ul>)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');
    html = html.replace(/<p>(<ul class="sub-bullet-list">)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');

    return html;
  }

  function getCurrentState() {
    const phases = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"];
    for (let i = phases.length - 1; i >= 0; i -= 1) {
      const phase = phases[i];
      const status = caseState?.d_states?.[phase]?.status;
      if (status && status !== "not_started") return phase;
    }
    return "D1_2";
  }

  function buildCaseContext() {
    const caseId = caseIdInput?.value.trim() || caseState?.case_id || "";
    return {
      case_id: caseId,
      case_status: caseState?.case_status || "open",
      opened_at: caseState?.opened_at || "",
      closed_at: caseState?.closed_at || null,
      d_states: caseState?.d_states || {}
    };
  }

  function buildFullEnvelope() {
    const base = buildCaseContext();
    const phases = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"];
    const normalized = {};
    phases.forEach((phase) => {
      const dState = ensureDState(phase);
      normalized[phase] = {
        status: dState.status || "not_started",
        data: dState.data || {},
        closure_date: dState.closure_date ?? null,
        confirmed_at: dState.confirmed_at ?? null
      };
    });
    return {
      case_id: base.case_id,
      case_status: base.case_status,
      opened_at: base.opened_at,
      closed_at: base.closed_at,
      d_states: normalized
    };
  }

  function clearPendingSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = null;
    pendingPatch = {};
  }

  async function sendFullEnvelope(entryMode) {
    const caseId = caseState?.case_id || caseIdInput.value.trim();
    if (!incidentIdRegex.test(caseId)) return;
    const envelope = buildFullEnvelope();
    try {
      await fetch(`${API_BASE}/entry/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildEntryEnvelope(entryMode, caseId, envelope))
      });
    } catch (err) {
      console.warn("Full envelope submit failed", err);
    }
  }

  async function sendCaseClosureEnvelope() {
    const caseId = caseState?.case_id || caseIdInput.value.trim();
    if (!incidentIdRegex.test(caseId)) return;
    const envelope = buildFullEnvelope();
    try {
      await fetch(`${API_BASE}/entry/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...buildEntryEnvelope("CLOSE_CASE", caseId, envelope),
          event: "CASE_CLOSED"
        })
      });
    } catch (err) {
      console.warn("Case closure submit failed", err);
    }
  }

  function collectKnowledgeReferences() {
    const listEl = document.getElementById("knowledge_upload_list");
    if (!listEl) return [];
    const rows = Array.from(listEl.querySelectorAll(".doc-row"));
    return rows
      .map((row) => {
        const filename = row.firstChild?.textContent?.trim() || "";
        const uploadedAt = row.querySelector(".doc-meta")?.textContent?.trim() || "";
        const status = row.querySelector(".evidence-link")?.textContent?.trim() || "";
        return { filename, uploaded_at: uploadedAt, status };
      })
      .filter((ref) => ref.filename);
  }

  async function submitAiQuestion() {
    const inputEl = document.getElementById("ai_question_input");
    if (!inputEl || inputEl.disabled) return;
    const question = inputEl.value.trim();
    console.log("[AI] submitAiQuestion: question =", JSON.stringify(question));
    const errorEl = document.getElementById("ai_input_error");
    if (!question) {
      if (errorEl) errorEl.textContent = "Please enter a question.";
      return;
    }
    if (errorEl) errorEl.textContent = "";
    await runAiQuestion(question);
  }

  function parseWhatToExploreNext(text) {
    const suggestions = [];
    const marker = "[WHAT TO EXPLORE NEXT]";
    if (!text.includes(marker)) return suggestions;
    const section = text.split(marker)[1] || "";
    const lines = section.split("\n");
    const emojiMap = {
      "\u{1F50D}": { label: "Similar cases", type: "cosolve" },
      "\u2699\uFE0F": { label: "Operational", type: "cosolve" },
      "\u{1F4CA}": { label: "Strategic view", type: "cosolve" },
      "\u{1F4C8}": { label: "KPI & trends", type: "cosolve" }
    };
    for (const line of lines) {
      const trimmed = line.trim();
      // Strategy-style TEAM: / COSOLVE: prefix format
      if (/^TEAM:/i.test(trimmed)) {
        const q = trimmed.replace(/^TEAM:\s*/i, "").replace(/^"|"$/g, "");
        if (q.length > 5) {
          suggestions.push({
            label: q.length > 40 ? q.substring(0, 40) + "..." : q,
            question: q,
            type: "team"
          });
        }
        continue;
      }
      if (/^COSOLVE:/i.test(trimmed)) {
        const q = trimmed.replace(/^COSOLVE:\s*/i, "").replace(/^"|"$/g, "");
        if (q.length > 5) {
          suggestions.push({
            label: q.length > 40 ? q.substring(0, 40) + "..." : q,
            question: q,
            type: "cosolve"
          });
        }
        continue;
      }
      // Team question bullets
      if (trimmed.startsWith("\u2022") || trimmed.startsWith("-")) {
        const q = trimmed.replace(/^[\u2022\-]\s*/, "").replace(/^"|"$/g, "");
        if (q.length > 10) {
          suggestions.push({
            label: q.length > 40 ? q.substring(0, 40) + "..." : q,
            question: q,
            type: "team"
          });
        }
      }
      // CoSolve emoji questions
      for (const [emoji, meta] of Object.entries(emojiMap)) {
        if (trimmed.startsWith(emoji)) {
          const parts = trimmed.split(":", 2);
          if (parts[1]) {
            const q = parts[1].trim().replace(/^"|"$/g, "");
            if (q.length > 10) {
              suggestions.push({ label: meta.label, question: q, type: meta.type });
            }
          }
        }
      }
    }
    return suggestions;
  }

  async function runAiQuestion(question) {
    const caseContext = buildFullEnvelope();

    // Capture identifiers now so they are always available in the exchange header
    // case_id may be null when no case is loaded — backend handles this gracefully
    const activeCaseId = caseContext.case_id || null;

    const inputEl = document.getElementById("ai_question_input");
    if (inputEl) inputEl.disabled = true;
    setAiLoading(true);
    // Bug 2 fix: do NOT overwrite history with a status string.
    // The spinner on the send button already signals "in progress".

    const payload = {
      intent: "AI_REASONING",
      case_id: activeCaseId,
      payload: {
        question,
        case_context: caseContext,
        evidence_metadata: evidenceMetadata,
        knowledge_references: collectKnowledgeReferences()
      }
    };

    try {
      console.log("[UI_DEBUG] sending payload:", JSON.stringify(payload));
      const res = await fetch(`${API_BASE}/entry/reasoning`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        let errText = "";
        try { errText = await res.text(); } catch (_) { }
        console.error("[AI] FastAPI error:", res.status, errText);
        appendAiExchange(question, activeCaseId,
          simpleMarkdown("Something went wrong. Please try rephrasing your question."), true);
        return;
      }

      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        const rawText = await res.text();
        appendAiExchange(question, activeCaseId,
          simpleMarkdown(rawText || "AI request completed with no response."), false);
        return;
      }

      const envelope = await res.json();
      console.log("[AI] response envelope:", envelope);

      // envelope = { intent, status, data: FinalResponsePayload }
      const output = formatAiResponse(envelope);

      // Determine node type for chip colouring
      const responseIntent = envelope?.data?.classification?.intent ?? "";
      const nodeType = responseIntent === "STRATEGY_ANALYSIS" ? "strategy" : "";

      // Extract structured suggestions; fall back to text parsing
      let suggestions = envelope?.data?.result?.suggestions ?? [];
      if (!Array.isArray(suggestions) || suggestions.length === 0) {
        const text = envelope?.data?.result?.current_state_recommendations ?? envelope?.data?.result?.summary ?? "";
        suggestions = parseWhatToExploreNext(text);
      }

      // KPI suggestions are plain strings — convert to chip objects
      if (responseIntent === "KPI_ANALYSIS" && Array.isArray(suggestions) && suggestions.length > 0 && typeof suggestions[0] === "string") {
        suggestions = suggestions.map((s) => ({
          label: s.length > 40 ? s.substring(0, 40) + "..." : s,
          question: s,
          type: "cosolve"
        }));
      }

      appendAiExchange(question, activeCaseId, output, false, suggestions, nodeType);
      // Initialise any bar-chart canvases appended above
      initPendingKpiCharts();
      initStatsCharts();
    } catch (err) {
      console.error("[AI] fetch error:", err);
      appendAiExchange(question, activeCaseId,
        simpleMarkdown("Could not reach the server. Check the console for details."), true);
    } finally {
      const inputElFinal = document.getElementById("ai_question_input");
      if (inputElFinal) {
        inputElFinal.value = "";
        inputElFinal.disabled = false;
      }
      setAiLoading(false);
    }
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function nowIsoDate() {
    return new Date().toISOString().slice(0, 10);
  }

  function updateCaseIdAttention() {
    if (!caseIdInput) return;
    const isEmpty = caseIdInput.value.trim().length === 0;
    caseIdInput.classList.toggle("case-id-attention", isEmpty);
  }

  function buildEmptyCaseState(caseId) {
    return {
      case_id: caseId,
      case_status: "open",
      opened_at: nowIsoDate(),
      closed_at: null,
      d_states: {
        D1_2: { status: "not_started", closure_date: null, confirmed_at: null, data: {} },
        D3:   { status: "not_started", closure_date: null, confirmed_at: null, data: {} },
        D4:   { status: "not_started", closure_date: null, confirmed_at: null, data: {} },
        D5:   { status: "not_started", closure_date: null, confirmed_at: null, data: {} },
        D6:   { status: "not_started", closure_date: null, confirmed_at: null, data: {} },
        D7:   { status: "not_started", closure_date: null, confirmed_at: null, data: {} },
        D8:   { status: "not_started", closure_date: null, confirmed_at: null, data: {} }
      }
    };
  }

  function applyClosedState(isClosed) {
    // Show/hide the closed case banner
    const banner = document.getElementById("case-closed-banner");
    if (banner) {
      if (isClosed) banner.removeAttribute("hidden");
      else banner.setAttribute("hidden", "");
    }

    // Mark nav bar as closed (opacity signal) but leave tabs clickable
    const dNavBar = document.getElementById("d-nav-bar");
    if (dNavBar) dNavBar.classList.toggle("is-closed", isClosed);

    // Disable / enable all form controls inside the stage detail panel only
    // (nav bar buttons are outside #phase-detail-panel and are unaffected)
    const detailPanel = document.getElementById("phase-detail-panel");
    if (detailPanel) {
      detailPanel
        .querySelectorAll("input, textarea, select, button")
        .forEach((el) => {
          if (el.id === "case-id-input") return; // always keep case-id editable
          el.disabled = isClosed;
        });
    }

    if (caseIdInput) caseIdInput.disabled = caseIdInput.disabled || isClosed;

    if (uploadBtn) uploadBtn.disabled = isClosed;
    if (fileInput) fileInput.disabled = isClosed;
    if (knowledgeUploadBtn) knowledgeUploadBtn.disabled = isClosed;
    if (knowledgeUploadInput) knowledgeUploadInput.disabled = isClosed;
    if (docBulkImportBtn) docBulkImportBtn.disabled = isClosed;
    if (docBulkImportInput) docBulkImportInput.disabled = isClosed;
  }

  async function loadCaseById(caseId) {
    if (!incidentIdRegex.test(caseId)) {
      alert("Invalid Incident ID format.");
      return;
    }

    caseIdInput.value = caseId;
    updateCaseIdAttention();
    if (createBtn) createBtn.disabled = true;

    try {
      const response = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`);
      if (!response.ok) {
        alert("Case not found");
        return;
      }

      const caseDoc = await response.json();
      if (saveTimer) clearTimeout(saveTimer);
      pendingPatch = {};

      hydrateCase(caseDoc);
      caseIdInput.disabled = true;
      if (caseState?.case_status !== "closed") {
        editFields.forEach(el => el.disabled = false);
        actionButtons.forEach(btn => btn.disabled = false);
      }

      applyClosedState(Boolean(caseState?.case_status === "closed"));
      document.getElementById("section-evidence")?.classList.remove("is-collapsed");
      loadEvidence(caseId);
      // Reset AI panel: clear old exchanges, conversation history (DOM), and case ID header
      // before generating new suggestions for the newly loaded case.
      clearAiConversation();
      generateCaseSuggestions(caseId, caseDoc);
    } catch (err) {
      alert("Backend not reachable");
    }
  }

  // Expose for inline onclick handlers in search result cards
  window.loadCaseById = loadCaseById;

  function renderCaseSearchResults(payload) {
    if (!caseSearchResults) return;

    let results = [];
    if (Array.isArray(payload)) {
      results = payload;
    } else if (Array.isArray(payload?.results)) {
      results = payload.results;
    } else if (Array.isArray(payload?.items)) {
      results = payload.items;
    } else if (Array.isArray(payload?.cases)) {
      results = payload.cases;
    }

    if (!results.length) {
      caseSearchResults.innerHTML = "<div class='muted empty-state'>No results found.</div>";
      return;
    }

    caseSearchResults.innerHTML = results.map((c) => {
      const id = c?.case_id ?? c?.case_number ?? (typeof c === "string" ? c : "");
      const status = (c?.case_status ?? c?.status ?? "").toLowerCase();
      const statusLabel = status || "unknown";
      const title = c?.problem_description || c?.title || "No description";
      const country = c?.country || c?.organization_country || "";
      const site = c?.site || c?.organization_site || "";
      const date = (c?.opening_date || "").slice(0, 10);
      const summary = c?.summary || c?.ai_summary || "";
      const locationStr = country
        ? `<span>&#x1F4CD; ${country}${site ? " &middot; " + site : ""}</span>`
        : "";
      const dateStr = date ? `<span>&#x1F4C5; ${date}</span>` : "";

      return `
        <div class="case-result-card">
          <div class="case-result-header">
            <span class="case-id-tag">${id || "—"}</span>
            <span class="case-status-badge status-${statusLabel}">${statusLabel}</span>
          </div>
          <div class="case-result-title">${title}</div>
          ${locationStr || dateStr
          ? `<div class="case-result-meta">${locationStr}${dateStr}</div>`
          : ""}
          ${summary
          ? `<div class="case-result-summary">${summary}</div>`
          : ""}
          ${id
          ? `<button class="open-case-btn" onclick="(async()=>{ await loadCaseById('${id}'); })()">Open Case &rarr;</button>`
          : ""}
        </div>`;
    }).join("");
  }

  function bindJsonField(el) {
    const eventName = el.type === "checkbox" ? "change" : "input";
    el.addEventListener(eventName, () => handleJsonFieldChange(el));
  }

  /**
   * Normalise a case document to the native d_states format before hydration.
   * Handles legacy schema variants produced by seed scripts and the backend workflow.
   * All transforms are idempotent: existing fields are never overwritten.
   *
   * Transform 1 — Lift case status to top level
   *   doc.status or doc.case.status → doc.case_status
   *
   * Transform 2 — Flatten organisation sub-object onto D1_2.data
   *   d_states.D1_2.data.organization.{country,site,unit} → d_states.D1_2.data.*
   *   Original organization object is preserved in place.
   *
   * Transform 3 — Rename mismatched field names inside d_states
   *   D3:   why_problem→why_is_problem, when→when_detected, who→who_detected,
   *         how_identified→how_detected, impact→quantified_impact
   *   D1_2: team_members→involved_people_teams (array joined to string)
   *
   * Transform 4 — Lift phase status from header to root of each d_state entry
   *   d_states[key].header.status → d_states[key].status
   *
   * Original phases→d_states rename logic (D1_D2→D1_2) is retained.
   */
  function normalizeCaseDoc(doc) {
    let result = { ...doc };

    // ── Transform 1 — Lift case status to top level ───────────────────────
    if (result.case_status === undefined) {
      if (result.status !== undefined) {
        result.case_status = result.status;
      } else if (result.case && result.case.status !== undefined) {
        result.case_status = result.case.status;
      }
    }

    // ── Phases → d_states rename (original logic, kept intact) ───────────
    if (!result.d_states || typeof result.d_states !== "object" || Object.keys(result.d_states).length === 0) {
      if (result.phases && typeof result.phases === "object" && Object.keys(result.phases).length > 0) {
        const normalized = {};
        Object.entries(result.phases).forEach(([k, v]) => {
          const normKey = k === "D1_D2" ? "D1_2" : k;
          normalized[normKey] = v;
        });
        result.d_states = normalized;
      }
    }

    if (!result.d_states || typeof result.d_states !== "object") {
      return result;
    }

    // ── Transform 2 — Flatten organisation fields inside D1_2 ────────────
    const d12 = result.d_states.D1_2;
    if (d12 && d12.data && d12.data.organization && typeof d12.data.organization === "object") {
      const org = d12.data.organization;
      if (org.country !== undefined && d12.data.country === undefined) {
        d12.data.country = org.country;
      }
      if (org.site !== undefined && d12.data.site === undefined) {
        d12.data.site = org.site;
      }
      if (org.unit !== undefined && d12.data.unit === undefined) {
        d12.data.unit = org.unit;
      }
    }

    // ── Transform 3 — Rename mismatched field names inside d_states ───────
    const d3 = result.d_states.D3;
    if (d3 && d3.data) {
      const d3Renames = [
        ["why_problem", "why_is_problem"],
        ["when", "when_detected"],
        ["who", "who_detected"],
        ["how_identified", "how_detected"],
        ["impact", "quantified_impact"],
      ];
      d3Renames.forEach(([oldKey, newKey]) => {
        if (d3.data[oldKey] !== undefined && d3.data[newKey] === undefined) {
          d3.data[newKey] = d3.data[oldKey];
        }
      });
    }
    if (d12 && d12.data) {
      if (d12.data.team_members !== undefined && d12.data.involved_people_teams === undefined) {
        const val = d12.data.team_members;
        d12.data.involved_people_teams = Array.isArray(val) ? val.join(", ") : val;
      }
    }

    // ── Transform 4 — Lift phase status from header to root of each d_state
    //    and normalise legacy status values to the three values the UI recognises.
    const phaseStatusMap = {
      confirmed: "completed",
      done: "completed",
      complete: "completed",
      "in-progress": "in_progress",
      active: "in_progress",
      started: "in_progress",
    };
    const phaseKeys = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"];
    phaseKeys.forEach((key) => {
      const phase = result.d_states[key];
      if (phase && phase.header && phase.header.status !== undefined && phase.status === undefined) {
        const raw = phase.header.status;
        phase.status = phaseStatusMap[raw] ?? (
          raw === "completed" || raw === "in_progress" || raw === "not_started" ? raw : "not_started"
        );
      }
    });

    // ── Transform 5 — Lift root-level date fields ─────────────────────────
    // The UI reads opened_at and closed_at at the document root; the seeded
    // JSON stores them inside doc.case.opening_date / closure_date.
    // HTML <input type="date"> requires yyyy-MM-dd; ISO strings carry a time
    // component, so truncate to the date part only.
    const toDateOnly = (iso) => iso ? iso.split("T")[0] : iso;
    if (result.opened_at === undefined && result.case && result.case.opening_date !== undefined) {
      result.opened_at = toDateOnly(result.case.opening_date);
    }
    if (result.closed_at === undefined && result.case && result.case.closure_date !== undefined) {
      result.closed_at = toDateOnly(result.case.closure_date);
    }
    // D8 Closure & Learnings panel reads d_states.D8.closure_date; the seeded
    // JSON stores the value one level deeper at d_states.D8.data.closure_date.
    const d8 = result.d_states.D8;
    if (d8 && d8.closure_date === undefined && d8.data && d8.data.closure_date !== undefined) {
      d8.closure_date = toDateOnly(d8.data.closure_date);
    }

    // ── Transform 6 — Fishbone field-name rename ──────────────────────────
    // Seeded JSON uses short keys; the UI reads compound keys.
    const d5 = result.d_states.D5;
    if (d5 && d5.data && d5.data.fishbone && typeof d5.data.fishbone === "object") {
      const fb = d5.data.fishbone;
      const fbRenames = [
        ["people", "people_organization"],
        ["process", "process_workflow"],
        ["tools", "tools_systems"],
        ["environment", "environment_context"],
        ["management", "policy_management"],
      ];
      fbRenames.forEach(([oldKey, newKey]) => {
        if (fb[oldKey] !== undefined && fb[newKey] === undefined) {
          fb[newKey] = fb[oldKey];
        }
      });
    }

    return result;
  }

  function hydrateCase(caseDoc) {
    caseState = normalizeCaseDoc(caseDoc || {});

    const dynamicArrays = [
      { arrayPath: "d_states.D4.data.actions", templateId: "d4-action-row" },
      { arrayPath: "d_states.D5.data.investigation_tasks", templateId: "d5-task-row" },
      { arrayPath: "d_states.D5.data.factors", templateId: "d5-factor-row" },
      { arrayPath: "d_states.D6.data.actions", templateId: "d6-action-row" }
    ];

    dynamicArrays.forEach(({ arrayPath, templateId }) => {
      const arr = getByPath(caseState, parsePath(arrayPath));
      const desired = Array.isArray(arr) ? Math.max(arr.length, 1) : 1;
      ensureRows(arrayPath, templateId, desired);
    });

    document.querySelectorAll("[data-json-path]").forEach((el) => {
      const value = getByPath(caseState, parsePath(el.dataset.jsonPath));
      // Always call setElementValue — pass "" when field absent so stale values are cleared
      setElementValue(el, value !== undefined ? value : "");
    });

    Object.keys(PHASE_META).forEach((phase) => {
      const status = caseState?.d_states?.[phase]?.status || "not_started";
      setPhaseStatus(phase, status);
    });

    setActivePhaseFromCase();
    applyClosedState(Boolean(caseState?.case_status === "closed"));
    // Re-check overdue dates after case data is loaded
    document.querySelectorAll("input[type='date'][data-json-path*='due_date'], input[type='date'][data-field='due_date']")
      .forEach(checkDueDateOverdue);
    updateWfDurations();
  }

  function setElementValue(el, value) {
    if (el.type === "checkbox") {
      el.checked = Boolean(value);
      return;
    }
    if (Array.isArray(value) && el.dataset.jsonArray === "true") {
      el.value = value.join(", ");
      return;
    }
    // <input type="date"> requires yyyy-MM-dd; strip any ISO time component
    if (el.type === "date" && typeof value === "string" && value.includes("T")) {
      el.value = value.split("T")[0];
      return;
    }
    el.value = value ?? "";
  }

  function updateIncidentOverviewClosure(value) {
    const closureInput = document.querySelector('[data-json-path="closed_at"]');
    if (closureInput) closureInput.value = value || "";
  }

  function updateIncidentOverviewStatus(statusValue) {
    const statusInput = document.querySelector('[data-json-path="case_status"]');
    if (statusInput) statusInput.value = statusValue || "";
  }

  function formatStatus(status) {
    return status.replace(/_/g, " ");
  }

  function setPhaseStatus(phase, status) {
    const card = document.querySelector(`.phase-card[data-phase="${phase}"]`);
    if (!card) return;
    card.dataset.status = status;
    const isConfirmed = status === "completed";
    const statusEl = card.querySelector("[data-phase-status]");
    if (statusEl) {
      statusEl.textContent = isConfirmed ? "Confirmed" : "Mark confirmed";
      statusEl.classList.toggle("confirmed-lbl", isConfirmed);
      statusEl.classList.toggle("unconfirmed-lbl", !isConfirmed);
    }
    const confirmBtn = card.querySelector(".confirm-phase-btn");
    if (confirmBtn) {
      confirmBtn.classList.toggle("confirmed", isConfirmed);
      confirmBtn.classList.toggle("unconfirmed", !isConfirmed);
    }
    updateNavStatusForPhase(phase, status);
  }

  function normalizePhaseKey(phaseKey) {
    if (phaseKey === "D1" || phaseKey === "D2") return "D1_2";
    return phaseKey;
  }

  function setActivePhase(dState) {
    const phaseKey = normalizePhaseKey(dState);
    phaseCards.forEach((card) => {
      card.classList.toggle("is-active", card.dataset.phase === phaseKey);
    });
    navButtons.forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.dState === dState);
    });
  }

  function setActivePhaseFromCase() {
    const current = getCurrentState();
    const normalized = normalizePhaseKey(current);
    const defaultButton = normalized === "D1_2" ? "D1" : current;
    setActivePhase(defaultButton);
  }

  function getStatusPresentation(status) {
    if (status === "completed") return { label: "Completed", className: "status-completed" };
    if (status === "in_progress") {
      return { label: "In Progress", className: "status-in-progress" };
    }
    return { label: "Not Started", className: "status-not-started" };
  }

  function updateNavStatusForPhase(phase, status) {
    const { label, className } = getStatusPresentation(status || "not_started");
    const targets = phase === "D1_2" ? ["D1", "D2"] : [phase];
    targets.forEach((dState) => {
      const btn = document.querySelector(`.d-state-btn[data-d-state="${dState}"]`);
      if (!btn) return;
      // Drive green-check circle via .done class
      btn.classList.toggle("done", status === "completed");
      // Sync the status dot
      const dotEl = btn.querySelector(".d-dot");
      if (dotEl) {
        dotEl.classList.remove("dot-done", "dot-active", "dot-pending");
        if (status === "completed")        dotEl.classList.add("dot-done");
        else if (status === "in_progress") dotEl.classList.add("dot-active");
        else                               dotEl.classList.add("dot-pending");
      }
      const statusEl = btn.querySelector(".d-status");
      if (!statusEl) return;
      statusEl.textContent = label;
      statusEl.classList.remove("status-not-started", "status-in-progress", "status-completed");
      statusEl.classList.add(className);
    });
  }

  function ensureDState(phase) {
    if (!caseState.d_states) caseState.d_states = {};
    if (!caseState.d_states[phase]) {
      caseState.d_states[phase] = {
        status: "not_started",
        data: {},
        closure_date: null
      };
    }
    if (!caseState.d_states[phase].status) {
      caseState.d_states[phase].status = "not_started";
    }
    if (!caseState.d_states[phase].data) {
      caseState.d_states[phase].data = {};
    }
    if (caseState.d_states[phase].closure_date === undefined) {
      caseState.d_states[phase].closure_date = null;
    }
    if (caseState.d_states[phase].confirmed_at === undefined) {
      caseState.d_states[phase].confirmed_at = null;
    }
    return caseState.d_states[phase];
  }

  // Phase order for duration calculation
  const PHASE_ORDER = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"];

  function daysBetween(isoStart, isoEnd) {
    if (!isoStart) return null;
    const start = new Date(isoStart);
    const end = isoEnd ? new Date(isoEnd) : new Date();
    const diff = Math.round((end - start) / 86400000);
    return diff >= 0 ? diff : null;
  }

  function updateWfDurations() {
    if (!caseState) return;
    const openedAt = caseState.opened_at || null;
    const ds = caseState.d_states || {};

    PHASE_ORDER.forEach((phase, i) => {
      const phaseData = ds[phase];
      const status = phaseData?.status || "not_started";
      if (status === "not_started") return; // leave as "—"

      // start = previous phase confirmed_at, or opened_at for D1_2
      const prevPhase = i > 0 ? PHASE_ORDER[i - 1] : null;
      const startAt = prevPhase ? (ds[prevPhase]?.confirmed_at || openedAt) : openedAt;
      const endAt = phaseData?.confirmed_at || null; // null = in progress → use today

      const days = daysBetween(startAt, endAt);
      const label = days !== null ? `${days}d` : "—";

      // Update nav card(s)
      const navKeys = phase === "D1_2" ? ["D1", "D2"] : [phase];
      navKeys.forEach((navKey) => {
        const tab = document.querySelector(`.d-state-btn[data-d-state="${navKey}"]`);
        if (!tab) return;
        const durEl = tab.querySelector(".d-duration");
        if (durEl) {
          durEl.innerHTML = `<svg width="9" height="9" viewBox="0 0 9 9" fill="none"><circle cx="4.5" cy="4.5" r="3.5" stroke="currentColor" stroke-width="1"/><path d="M4.5 2.5v2.2l1.3.8" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg> ${label}`;
        }
      });
    });

    // Total elapsed
    const totalEl = document.getElementById("wf-total-val");
    const subEl   = document.getElementById("wf-total-sub");
    if (totalEl && openedAt) {
      const endAt = caseState.closed_at || null;
      const totalDays = daysBetween(openedAt, endAt);
      totalEl.textContent = totalDays !== null ? `${totalDays}d` : "—";
      if (subEl) {
        const d = new Date(openedAt);
        const formatted = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
        subEl.textContent = `since ${formatted}`;
      }
    }
  }

  function getPhaseFromPath(path) {
    if (path.startsWith("d_states.")) {
      const parts = path.split(".");
      return parts[1] || null;
    }
    return null;
  }

  function handleJsonFieldChange(el) {
    const path = el.dataset.jsonPath;
    if (!path) return;
    if (el.type === "file") return;

    if (caseState?.case_status === "closed") return;

    const value = getElementValue(el);
    setByPath(caseState, path, value);

    if (path === "case_id") return;

    const phase = getPhaseFromPath(path);
    let immediate = false;
    let statePatch = null;

    if (phase) {
      const dState = ensureDState(phase);
      const prevStatus = dState.status || "not_started";

      if (prevStatus !== "in_progress") {
        dState.status = "in_progress";
      }

      setPhaseStatus(phase, dState.status);

      statePatch = buildDStatePatch(phase, {
        status: dState.status
      });
    }

    let patch;
    let casePatch = null;
    if (path === "d_states.D8.closure_date") {
      // closed_at is derived on D8 confirmation only
    }
    const tokens = parsePath(path);
    const lastIndexPos = tokens.reduce((pos, token, idx) => (typeof token === "number" ? idx : pos), -1);
    if (lastIndexPos >= 0) {
      const arrayTokens = tokens.slice(0, lastIndexPos);
      const arrayPath = tokensToPath(arrayTokens);
      const domArray = buildObjectArrayFromDom(arrayPath);
      if (domArray) {
        patch = buildPatch(arrayPath, domArray);
      } else {
        const arrValue = getByPath(caseState, arrayTokens);
        const filled = fillArrayForPatch(arrValue);
        patch = buildPatch(arrayPath, filled);
      }
    } else {
      patch = buildPatch(path, value);
    }
    if (casePatch) {
      patch = deepMerge(patch, casePatch);
    }
    if (statePatch) {
      patch = deepMerge(patch, statePatch);
    }

    scheduleSave(patch, immediate);
  }

  function getElementValue(el) {
    if (el.type === "file") return null;
    if (el.type === "checkbox") return el.checked;
    const raw = el.value;
    if (el.dataset.jsonArray === "true") {
      return raw.split(",").map(v => v.trim()).filter(Boolean);
    }
    return raw;
  }

  function parsePath(path) {
    const tokens = [];
    path.split(".").forEach((part) => {
      const match = part.match(/(\w+)|\[(\d+)\]/g);
      if (match) {
        match.forEach((m) => {
          if (m.startsWith("[")) tokens.push(Number(m.replace(/[\[\]]/g, "")));
          else tokens.push(m);
        });
      }
    });
    return tokens;
  }

  function tokensToPath(tokens) {
    let out = "";
    tokens.forEach((t) => {
      if (typeof t === "number") {
        out += `[${t}]`;
      } else {
        out += out ? `.${t}` : t;
      }
    });
    return out;
  }

  function getByPath(obj, tokens) {
    let current = obj;
    for (const t of tokens) {
      if (current == null) return undefined;
      current = current[t];
    }
    return current;
  }

  function fillArrayForPatch(arr) {
    if (!Array.isArray(arr)) return [];
    const normalized = Array.from({ length: arr.length }, (_, i) => arr[i]);
    const sample = normalized.find((v) => v !== undefined && v !== null);
    const isObjectArray = sample && typeof sample === "object" && !Array.isArray(sample);
    return normalized.map((v) => {
      if (v === undefined) return isObjectArray ? {} : "";
      return v;
    });
  }

  function escapeRegex(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function buildObjectArrayFromDom(arrayPath) {
    const tbody = document.querySelector(`tbody[data-array-path="${arrayPath}"]`);
    if (!tbody) return null;

    const rows = tbody.querySelectorAll("tr");
    const escaped = escapeRegex(arrayPath);
    const result = [];

    rows.forEach((row, index) => {
      const obj = {};
      const inputs = row.querySelectorAll("[data-json-path]");
      inputs.forEach((input) => {
        const path = input.dataset.jsonPath;
        if (!path) return;
        const match = path.match(new RegExp(`^${escaped}\\[${index}\\]\\.(.+)$`));
        if (!match) return;
        const key = match[1];
        obj[key] = getElementValue(input);
      });
      result.push(obj);
    });

    return result;
  }

  function addRow(btn) {
    const templateId = btn.dataset.templateId;
    const arrayPath = btn.dataset.arrayPath;
    addRowByConfig(templateId, arrayPath, btn.disabled);
  }

  function ensureRows(arrayPath, templateId, desiredCount) {
    const tbody = document.querySelector(`tbody[data-array-path="${arrayPath}"]`);
    if (!tbody) return;
    // Trim extra rows from previous case first
    const rows = Array.from(tbody.querySelectorAll("tr"));
    while (rows.length > desiredCount) {
      tbody.removeChild(rows.pop());
    }
    const current = tbody.querySelectorAll("tr").length;
    for (let i = current; i < desiredCount; i += 1) {
      addRowByConfig(templateId, arrayPath, false);
    }
  }

  function addRowByConfig(templateId, arrayPath, isDisabled) {
    if (!templateId || !arrayPath) return;

    const template = document.getElementById(templateId);
    const tbody = document.querySelector(`tbody[data-array-path="${arrayPath}"]`);
    if (!template || !tbody) return;

    const index = tbody.querySelectorAll("tr").length;
    const fragment = template.content.cloneNode(true);
    const inputs = fragment.querySelectorAll("[data-field]");

    inputs.forEach((input) => {
      const field = input.dataset.field;
      if (!field) return;
      input.dataset.jsonPath = `${arrayPath}[${index}].${field}`;
      input.disabled = isDisabled;
      bindJsonField(input);
    });

    tbody.appendChild(fragment);
  }

  function setByPath(obj, path, value) {
    const tokens = parsePath(path);
    let current = obj;
    tokens.forEach((token, index) => {
      const isLast = index === tokens.length - 1;
      const nextToken = tokens[index + 1];

      if (isLast) {
        current[token] = value;
        return;
      }

      if (current[token] === undefined) {
        current[token] = typeof nextToken === "number" ? [] : {};
      }

      current = current[token];
    });
  }

  function buildPatch(path, value) {
    const tokens = parsePath(path);
    const root = {};
    let current = root;
    tokens.forEach((token, index) => {
      const isLast = index === tokens.length - 1;
      const nextToken = tokens[index + 1];
      if (isLast) {
        current[token] = value;
        return;
      }
      if (current[token] === undefined) {
        current[token] = typeof nextToken === "number" ? [] : {};
      }
      current = current[token];
    });
    return root;
  }

  function buildDStatePatch(phase, fields) {
    return {
      d_states: {
        [phase]: fields
      }
    };
  }

  function deepMerge(target, source) {
    if (Array.isArray(source)) {
      return source;
    }

    if (source && typeof source === "object") {
      if (!target || typeof target !== "object") target = {};
      Object.keys(source).forEach((key) => {
        target[key] = deepMerge(target[key], source[key]);
      });
      return target;
    }

    return source;
  }

  function scheduleSave(patch, immediate) {
    pendingPatch = deepMerge(pendingPatch, patch);
    if (immediate) {
      void flushSave();
      return;
    }
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void flushSave(), DEBOUNCE_MS);
  }

  async function flushSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = null;

    const caseId = caseState?.case_id || caseIdInput.value.trim();
    if (!incidentIdRegex.test(caseId)) return;

    const payload = pendingPatch;
    pendingPatch = {};
    if (!payload || Object.keys(payload).length === 0) return;

    await patchCase(caseId, payload);
  }

  async function savePatchImmediately(patch) {
    const caseId = caseState?.case_id || caseIdInput.value.trim();
    if (!incidentIdRegex.test(caseId)) return;
    await patchCase(caseId, patch);
  }

  async function patchCase(caseId, patch) {
    try {
      await fetch(`${API_BASE}/entry/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildEntryEnvelope("UPDATE_CASE", caseId, patch))
      });
    } catch (err) {
      // Keep UI responsive even if save fails
      console.warn("Autosave failed", err);
    }
  }

  async function uploadBulkClosedCases(files) {
    const listEl = document.getElementById("doc_bulk_import_list");
    if (!listEl) return;

    const rows = Array.from(listEl.querySelectorAll(".doc-row"));
    const byName = new Map();
    rows.forEach((row) => {
      const name = row.firstChild?.textContent || "";
      const statusEl = row.querySelector(".status-badge");
      if (name && statusEl) byName.set(name, statusEl);
    });

    const cases = [];
    for (const f of files) {
      const statusEl = byName.get(f.name);
      if (statusEl) {
        statusEl.textContent = "Uploading";
        statusEl.className = "status-badge status-pending";
      }
      try {
        const text = await f.text();
        const lowerName = f.name.toLowerCase();

        if (lowerName.endsWith(".csv")) {
          const rows = parseCsvToObjects(text);
          const validRows = rows.filter((row) => row?.case_id || row?.case_number);
          if (!validRows.length) {
            throw new Error("Missing case identifier in CSV");
          }
          validRows.forEach((row) => {
            const inferredCaseId = row.case_id || row.case_number;
            cases.push({
              case_id: inferredCaseId,
              case_doc: row,
              filename: f.name
            });
          });
        } else {
          const doc = JSON.parse(text);
          const inferredCaseId = doc?.case?.case_number || doc?.case_number || doc?.case_id;
          if (!inferredCaseId) {
            throw new Error("Missing case identifier in JSON");
          }
          cases.push({ case_id: inferredCaseId, case_doc: doc, filename: f.name });
        }
      } catch (e) {
        if (statusEl) {
          statusEl.textContent = "Failed";
          statusEl.className = "status-badge status-failed";
        }
      }
    }

    if (!cases.length) return;

    try {
      const res = await fetch(`${API_BASE}/entry/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildEntryEnvelope("UPDATE_CASE", null, { cases }))
      });
      const ok = res.ok;
      cases.forEach((c) => {
        const statusEl = byName.get(c.filename);
        if (!statusEl) return;
        statusEl.textContent = ok ? "Uploaded" : "Failed";
        statusEl.className = ok
          ? "status-badge status-success"
          : "status-badge status-failed";
      });
    } catch (e) {
      cases.forEach((c) => {
        const statusEl = byName.get(c.filename);
        if (!statusEl) return;
        statusEl.textContent = "Failed";
        statusEl.className = "status-badge status-failed";
      });
    }
  }

  async function uploadKnowledgeDocuments(files) {
    const listEl = document.getElementById("knowledge_upload_list");
    if (!listEl) return;

    // Match placeholder rows rendered by the companion change listener.
    // Each row is <div class="kb-doc-row"> whose .kb-doc-name last child text
    // node holds the raw filename; status is updated via .kb-status-badge.
    const rows = Array.from(listEl.querySelectorAll(".kb-doc-row"));
    const byName = new Map();
    rows.forEach((row) => {
      const nameEl = row.querySelector(".kb-doc-name");
      const badgeEl = row.querySelector(".kb-status-badge");
      const name = nameEl?.lastChild?.textContent?.trim() || "";
      if (name && badgeEl) byName.set(name, badgeEl);
    });

    const documents = [];
    for (const f of files) {
      const linkEl = byName.get(f.name);
      if (linkEl) linkEl.textContent = "Uploading";
      try {
        const data_base64 = await readFileAsBase64(f);
        documents.push({
          filename: f.name,
          content_type: f.type || "application/octet-stream",
          data_base64
        });
      } catch (e) {
        if (linkEl) linkEl.textContent = "Failed";
      }
    }

    if (!documents.length) return;

    try {
      const res = await fetch(`${API_BASE}/entry/case`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildEntryEnvelope("UPLOAD_KNOWLEDGE", null, { documents }))
      });
      const ok = res.ok;
      documents.forEach((d) => {
        const linkEl = byName.get(d.filename);
        if (!linkEl) return;
        linkEl.textContent = ok ? "Uploaded" : "Failed";
      });
      if (ok) {
        // Wait briefly so Azure Search has time to commit the new document
        // before we query the index — indexing is eventually consistent.
        console.log("[KB] upload success, triggering refresh");
        await new Promise((r) => setTimeout(r, 1500));
        await refreshKnowledgeList();
      }
    } catch (e) {
      documents.forEach((d) => {
        const linkEl = byName.get(d.filename);
        if (!linkEl) return;
        linkEl.textContent = "Failed";
      });
    }
  }

  // Hook the two ingestion-only document actions into ENTRY.
  docBulkImportInput?.addEventListener("change", async () => {
    const files = Array.from(docBulkImportInput.files || []);
    if (!files.length) return;
    await uploadBulkClosedCases(files);
  });

  knowledgeUploadInput?.addEventListener("change", async () => {
    const files = Array.from(knowledgeUploadInput.files || []);
    if (!files.length) return;
    await uploadKnowledgeDocuments(files);
  });

  // ── Collapsible left-panel sections ──────────────────────────────
  // Clicking a .section-title inside .section-collapsible toggles its
  // .section-body with a smooth max-height CSS transition.
  (function initCollapsibles() {
    const leftCol = document.querySelector(".column[data-column='left']");
    if (!leftCol) return;
    leftCol.querySelectorAll(".section-collapsible").forEach((section) => {
      const title = section.querySelector(":scope > .section-title");
      if (!title) return;
      section.classList.add("is-collapsed");
      title.addEventListener("click", () => {
        const nowCollapsed = section.classList.toggle("is-collapsed");
        if (!nowCollapsed) {
          leftCol.querySelectorAll(".section-collapsible").forEach((other) => {
            if (other !== section) other.classList.add("is-collapsed");
          });
        }
      });
    });
  })();

});

// ══════════════════════════════════════════════════════════════════════════════
// PANEL SYSTEM — 5-panel tab-rail layout
// States: board | case | ai | kpi | admin
// ══════════════════════════════════════════════════════════════════════════════

let panelState = 'board';
const LP_GROUPS = ['grp-case', 'grp-docs', 'grp-admin'];

function clearAllPanels() {
  ['lp', 'kpi-panel', 'rp'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open', 'maximized', 'collapsed', 'fullscreen');
  });
  document.getElementById('center')?.classList.remove('hidden');
  document.getElementById('lp')?.classList.remove('admin-mode', 'case-mode');
}

function updateTabRail() {
  ['tab-lp', 'tab-admin', 'tab-kpi', 'tab-center', 'tab-rp'].forEach(id =>
    document.getElementById(id)?.classList.remove('active'));
  const map = { board: 'tab-center', case: 'tab-lp', ai: 'tab-rp', kpi: 'tab-kpi', admin: 'tab-admin' };
  document.getElementById(map[panelState] || 'tab-center')?.classList.add('active');
}

function setPanelState(newState) {
  if (panelState === newState && newState !== 'board') {
    panelState = 'board';
    clearAllPanels();
    updateTabRail();
    return;
  }
  panelState = newState;
  clearAllPanels();
  if (newState === 'case') {
    document.getElementById('lp')?.classList.add('open', 'case-mode');
  } else if (newState === 'ai') {
    document.getElementById('rp')?.classList.add('open', 'fullscreen');
    document.getElementById('center')?.classList.add('hidden');
  } else if (newState === 'kpi') {
    document.getElementById('kpi-panel')?.classList.add('open', 'fullscreen');
    document.getElementById('center')?.classList.add('hidden');
    setTimeout(() => { renderCaseKPIs(); renderTokenChart(); onPerfOpen(); }, 150);
  } else if (newState === 'admin') {
    document.getElementById('lp')?.classList.add('open', 'admin-mode');
    LP_GROUPS.forEach(gid => {
      const g = document.getElementById(gid);
      if (g) g.classList.toggle('open', gid === 'grp-admin');
    });
  }
  updateTabRail();
}

function toggleLP()    { setPanelState(panelState === 'case' ? 'board' : 'case'); }
function focusCenter() { setPanelState('board'); }
function focusRP()     { setPanelState('ai'); }
function focusKPI()    { setPanelState('kpi'); }

function focusLP(groupId) {
  panelState = groupId === 'grp-admin' ? 'admin' : 'case';
  clearAllPanels();
  const lp = document.getElementById('lp');
  lp?.classList.add('open');
  if (groupId === 'grp-admin') lp?.classList.add('admin-mode');
  else lp?.classList.add('case-mode');
  LP_GROUPS.forEach(gid => {
    const g = document.getElementById(gid);
    if (g) g.classList.toggle('open', gid === groupId);
  });
  updateTabRail();
}

function toggleGroup(id) {
  const target = document.getElementById(id);
  if (!target) return;
  const isOpen = target.classList.contains('open');
  LP_GROUPS.forEach(gid => {
    const g = document.getElementById(gid);
    if (g) g.classList.remove('open');
  });
  if (!isOpen) target.classList.add('open');
}

function toggleKPISection(id) {
  document.getElementById(id)?.classList.toggle('collapsed');
}

function onKPISearch(val) {
  const trimmed = (val || '').trim();
  if (!trimmed) return;

  // PREFIX-YYYYMMDD-NNN(N) pattern = case ID (INC, TRM, VIE, etc.)
  const isCaseId = /^[A-Za-z]{2,4}-\d{8}-\d{3,4}$/i.test(trimmed);

  const url = isCaseId
    ? `${API_BASE}/cases/kpi?scope=case&case_id=${encodeURIComponent(trimmed)}`
    : `${API_BASE}/cases/kpi?scope=country&country=${encodeURIComponent(trimmed)}`;

  const block  = document.getElementById('agent-insight');
  const textEl = document.getElementById('agent-text');
  if (block && textEl) {
    textEl.textContent = 'Calculating\u2026';
    block.classList.remove('hidden');
  }

  fetch(url)
    .then(r => r.json())
    .then(data => {
      currentKpiData = data;
      if (data.scope !== 'case') {
        currentKpiCountry = null;
        renderKpiChips(data);
      }
      renderCaseKPIs(data);
      renderKpiAssessment(data);
    })
    .catch(() => {
      if (block && textEl) textEl.textContent = 'Assessment unavailable.';
    });
}

function setKPIScope(scope, btn) {
  document.querySelectorAll('.kpi-chip').forEach(c => c.classList.remove('active'));
  if (btn) btn.classList.add('active');

  if (scope === 'global') {
    currentKpiCountry = null;
    document.getElementById('kpi-search').value = '';

    const block = document.getElementById('agent-insight');
    const textEl = document.getElementById('agent-text');
    if (block && textEl) {
      textEl.textContent = 'Calculating\u2026';
      block.classList.remove('hidden');
    }

    fetch(`${API_BASE}/cases/kpi?scope=global`)
      .then(r => r.json())
      .then(data => {
        currentKpiData = data;
        renderKpiChips(data);
        renderCaseKPIs(data);
        renderKpiAssessment(data);
      })
      .catch(() => {
        if (block && textEl) {
          textEl.textContent = 'Assessment unavailable.';
        }
      });
    return;
  }

  // Country scope — fetch scoped data from backend
  currentKpiCountry = scope;
  document.getElementById('kpi-search').value = '';
  const url = `${API_BASE}/cases/kpi?scope=country&country=${encodeURIComponent(scope)}`;
  const block  = document.getElementById('agent-insight');
  const textEl = document.getElementById('agent-text');
  if (block && textEl) { textEl.textContent = 'Calculating\u2026'; block.classList.remove('hidden'); }

  fetch(url)
    .then(r => r.json())
    .then(data => {
      renderCaseKPIs(data);
      renderKpiAssessment(data);
    })
    .catch(() => {
      if (block && textEl) textEl.textContent = 'Assessment unavailable.';
    });
}

// ── KPI STATE ─────────────────────────────────────────────────────────────────

let perfChartInst = null, trendChartInst = null, tokenChartInst = null, stageChartInst = null;
let currentKpiData = null;    // last fetched KPIResult from /cases/kpi
let currentKpiCountry = null; // null = global view, else country name string

const CHART_DEFAULTS = {
  plugins: {
    legend: { display: false },
    tooltip: { enabled: true, bodyFont: { family: 'Geist Mono', size: 10 }, titleFont: { family: 'Geist', size: 9 } }
  },
  animation: { duration: 600, easing: 'easeOutQuart' }
};

function destroyChart(inst) { try { inst && inst.destroy(); } catch (e) {} }

function renderCaseKPIs(kpiData) {
  if (!kpiData) return;

  // ── Case scope: show single-case metrics, hide bar/stage charts ───────────
  if (kpiData.scope === 'case') {
    const barCtx = document.getElementById('perf-chart');
    if (barCtx) { destroyChart(perfChartInst); barCtx.style.display = 'none'; }
    const lbl = document.getElementById('chart-label');
    if (lbl) lbl.textContent = '';
    const stageBlock = document.getElementById('stage-chart-block');
    if (stageBlock) { destroyChart(stageChartInst); stageChartInst = null; stageBlock.style.display = 'none'; }

    const fmtDays = v => (v != null ? Math.round(v) + 'd' : '—');
    const sr = document.getElementById('kpi-summary-row');
    if (sr) sr.innerHTML = `
      <div class="kpi-stat accent"><div class="kpi-stat-val">${fmtDays(kpiData.days_elapsed)}</div><div class="kpi-stat-lbl">Days elapsed</div></div>
      <div class="kpi-stat green"><div class="kpi-stat-val">${kpiData.current_stage || '—'}</div><div class="kpi-stat-lbl">Current stage</div></div>
      <div class="kpi-stat"><div class="kpi-stat-val">${fmtDays(kpiData.category_benchmark_days)}</div><div class="kpi-stat-lbl">Benchmark</div></div>
    `;
    if (kpiData.stage_timeline && kpiData.stage_timeline.length) {
      renderStageTimeline(kpiData.stage_timeline);
    } else {
      document.getElementById('kpi-stage-timeline')?.classList.add('hidden');
    }
    return;
  }

  // ── Hide stage timeline for global/country scope ───────────────────────────
  document.getElementById('kpi-stage-timeline')?.classList.add('hidden');

  // Restore bar chart visibility for global/country scope
  const barCtxRestore = document.getElementById('perf-chart');
  if (barCtxRestore) barCtxRestore.style.display = '';

  const ranking = kpiData.country_ranking || [];

  // When a country chip is active, filter stats to that country's ranking entry
  let statsAvg = kpiData.avg_closure_days_ytd;
  let statsClosed = kpiData.total_cases_closed_ytd;
  let statsOverdue = kpiData.overdue_count;
  let statsOpen = kpiData.open_count;
  let statsInProgress = kpiData.in_progress_count;
  let displayRanking = ranking;

  if (currentKpiCountry) {
    const entry = ranking.find(r => r.country === currentKpiCountry);
    // All countries shown for comparison.
    // Selected country highlighted via bar colour.
    displayRanking = ranking;
    statsAvg = entry ? entry.avg_closure_days : null;
    statsClosed = entry ? entry.total_closed : null;
    statsOverdue = kpiData.overdue_count ?? null;
    statsOpen = kpiData.open_count ?? null;
    statsInProgress = kpiData.in_progress_count ?? null;
  }

  const fmtDays = v => (v != null ? Math.round(v) + 'd' : '—');
  const fmtNum  = v => (v != null ? v : '—');

  const sr = document.getElementById('kpi-summary-row');
  if (sr) sr.innerHTML = `
    <div class="kpi-stat"><div class="kpi-stat-val">${fmtNum(statsOpen)}</div><div class="kpi-stat-lbl">Open</div></div>
    <div class="kpi-stat green"><div class="kpi-stat-val">${fmtNum(statsInProgress)}</div><div class="kpi-stat-lbl">In Progress</div></div>
    <div class="kpi-stat accent"><div class="kpi-stat-val">${fmtNum(statsOverdue)}</div><div class="kpi-stat-lbl">Overdue</div></div>
    <div class="kpi-stat"><div class="kpi-stat-val">${fmtNum(statsClosed)}</div><div class="kpi-stat-lbl">Closed YTD</div></div>
  `;

  const barCtx = document.getElementById('perf-chart');
  if (!barCtx) return;
  destroyChart(perfChartInst);
  const lbl = document.getElementById('chart-label');
  if (lbl) lbl.textContent = 'Avg. days to close · by country';

  if (displayRanking.length > 0) {
    const barLabels = displayRanking.map(r => r.country);
    const barValues = displayRanking.map(r => r.avg_closure_days);
    const barBg = displayRanking.map(r =>
      currentKpiCountry && r.country === currentKpiCountry
        ? 'rgba(239, 100, 97, 0.8)'   // highlight colour (red)
        : 'rgba(114, 158, 220, 0.8)'  // default blue
    );
    const barBorder = displayRanking.map(r =>
      currentKpiCountry && r.country === currentKpiCountry
        ? '#ef6461' : '#7298dc'
    );
    perfChartInst = new Chart(barCtx, {
      type: 'bar',
      data: {
        labels: barLabels,
        datasets: [{ data: barValues, backgroundColor: barBg, borderColor: barBorder, borderWidth: 1.5, borderRadius: 4 }]
      },
      options: {
        ...CHART_DEFAULTS,
        scales: {
          x: { ticks: { font: { family: 'Geist', size: 8 }, color: '#8b93ad' }, grid: { display: false } },
          y: { ticks: { font: { family: 'Geist Mono', size: 8 }, color: '#8b93ad' }, grid: { color: '#eef0f7' }, beginAtZero: true }
        }
      }
    });
  }

  // Stage duration chart
  if (kpiData.avg_days_per_stage && Object.keys(kpiData.avg_days_per_stage).length > 0) {
    renderStageDurationChart(kpiData.avg_days_per_stage);
  } else {
    const stageBlock = document.getElementById('stage-chart-block');
    if (stageBlock) { destroyChart(stageChartInst); stageChartInst = null; stageBlock.style.display = 'none'; }
  }

  // Trend chart — no time-series data in KPIResult; leave empty
  const trendCtx = document.getElementById('trend-chart');
  if (trendCtx) destroyChart(trendChartInst);
}

function renderStageDurationChart(stageData) {
  const PHASE_ORDER = ['D1_2', 'D3', 'D4', 'D5', 'D6', 'D7', 'D8'];
  const stageBlock = document.getElementById('stage-chart-block');
  const stageCtx = document.getElementById('stage-chart');
  if (!stageBlock || !stageCtx) return;
  destroyChart(stageChartInst);
  stageChartInst = null;
  const labels = PHASE_ORDER.filter(p => stageData[p] != null);
  const values = labels.map(p => stageData[p]);
  if (!labels.length) { stageBlock.style.display = 'none'; return; }
  stageBlock.style.display = '';
  const blue = '#3b82f6';
  stageChartInst = new Chart(stageCtx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: blue + '99', borderColor: blue, borderWidth: 1.5, borderRadius: 4 }]
    },
    options: {
      ...CHART_DEFAULTS,
      scales: {
        x: { ticks: { font: { family: 'Geist Mono', size: 8 }, color: '#8b93ad' }, grid: { display: false } },
        y: { ticks: { font: { family: 'Geist Mono', size: 8 }, color: '#8b93ad' }, grid: { color: '#eef0f7' }, beginAtZero: true }
      }
    }
  });
}

function renderStageTimeline(timeline) {
  const el = document.getElementById('kpi-stage-timeline');
  if (!el) return;
  const rows = timeline.map(entry => {
    const isCompleted = entry.completed === true;
    const daysLbl = (isCompleted && entry.days != null)
      ? `${entry.days}d`
      : isCompleted
        ? '—'
        : 'pending';
    const icon = isCompleted ? '✓' : '○';
    const cls = isCompleted ? 'stage-tl-row completed' : 'stage-tl-row pending';
    return `<div class="${cls}"><span class="stage-tl-key">${entry.stage}</span><span class="stage-tl-days">${daysLbl}</span><span class="stage-tl-icon">${icon}</span></div>`;
  }).join('');
  el.innerHTML = rows;
  el.classList.remove('hidden');
}

function renderKpiAssessment(data) {
  const block  = document.getElementById('agent-insight');
  const textEl = document.getElementById('agent-text');
  if (!block || !textEl) return;

  if (data.summary) {
    let html = `<p>${data.summary}</p>`;
    if (data.insights && data.insights.length) {
      html += '<ul>' + data.insights.map(i => `<li>${i}</li>`).join('') + '</ul>';
    }
    textEl.innerHTML = html;
    block.classList.remove('hidden');
  } else {
    textEl.innerHTML = '';
    block.classList.add('hidden');
  }
}

function renderKpiChips(kpiData) {
  const container = document.getElementById('kpi-country-chips');
  if (!container) return;
  const countries = (kpiData.country_ranking || []).map(r => r.country);
  let html = `<button class="kpi-chip active" onclick="setKPIScope('global',this)">Global</button>`;
  countries.forEach(country => {
    html += `<button class="kpi-chip" onclick="setKPIScope('${country.replace(/'/g, "\\'")}',this)">${country}</button>`;
  });
  container.innerHTML = html;
}

function renderTokenChart() {
  // Token chart requires time-series data not yet exposed via REST endpoint.
  const ctx = document.getElementById('token-chart');
  if (ctx) destroyChart(tokenChartInst);
}

async function onPerfOpen() {
  const kpiPanel = document.getElementById('kpi-panel');
  if (!kpiPanel || !kpiPanel.classList.contains('open')) return;

  const dot    = document.getElementById('agent-dot');
  const lbl    = document.getElementById('agent-lbl');
  const insight = document.getElementById('agent-insight');
  const sr     = document.getElementById('kpi-summary-row');

  if (dot) dot.classList.add('active');
  if (lbl) lbl.innerHTML = '<strong>Reasoning agent</strong> — loading…';
  if (sr)  sr.innerHTML  = '<span style="color:var(--text-3);font-size:11px;padding:8px 0;display:block">Loading…</span>';
  // Hide assessment until fetch resolves with a summary
  if (insight) insight.classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/cases/kpi?scope=global`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    currentKpiData = await res.json();
    currentKpiCountry = null;
    renderKpiChips(currentKpiData);
    renderCaseKPIs(currentKpiData);
    renderTokenChart();
    renderKpiAssessment(currentKpiData);
    if (dot) dot.classList.remove('active');
    if (lbl) lbl.innerHTML = '<strong>Reasoning agent</strong> — data loaded';
  } catch (err) {
    console.error('[KPI] fetch error', err);
    if (sr)  sr.innerHTML = '<span style="color:var(--text-3);font-size:11px;padding:8px 0;display:block">Data unavailable</span>';
    if (dot) dot.classList.remove('active');
    if (lbl) lbl.innerHTML = '<strong>Reasoning agent</strong> — unavailable';
  }
}

// ── INIT ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('tab-center')?.classList.add('active');
});

