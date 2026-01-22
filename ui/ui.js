// ===== API CONFIG (single source of truth) =====
const API_BASE = "http://127.0.0.1:8000";

let caseState = {};

const PHASE_META = {
  D1_D2: { name: "Problem Initiation", discipline: ["D1", "D2"] },
  D3: { name: "Problem Definition", discipline: "D3" },
  D4: { name: "Immediate Actions", discipline: "D4" },
  D5: { name: "Root Cause Analysis", discipline: "D5" },
  D6: { name: "Permanent Actions", discipline: "D6" },
  D7: { name: "Prevention / Standardization", discipline: "D7" },
  D8: { name: "Closure", discipline: "D8" }
};

const DEBOUNCE_MS = 900;
let pendingPatch = {};
let saveTimer = null;



document.addEventListener("DOMContentLoaded", () => {




  const caseIdInput = document.getElementById("case-id-input");
  const createBtn = document.getElementById("create-incident-btn");

  const actionButtons = document.querySelectorAll(
    "[data-action='upload-evidence'], [data-action='run-agent']"
  );

  const editFields = document.querySelectorAll(
    ".column:not(.col-d0) input, .column:not(.col-d0) textarea"
  );

  const incidentIdRegex = /^INC-\d{8}-\d{4}$/;

  const uploadBtn = document.getElementById("upload-evidence-btn");
  const fileInput = document.getElementById("evidence-file-input");
  const uploadStatus = document.getElementById("upload-status");


  // --- Safety check
  if (!caseIdInput || !createBtn) {
    console.warn("Incident ID input or Create button not found");
    return;
  }

  // --- Initial state (page load)
  createBtn.disabled = true;
  actionButtons.forEach(btn => btn.disabled = true);
  editFields.forEach(el => el.disabled = true);

  Object.keys(PHASE_META).forEach((phase) => {
    setPhaseStatus(phase, "not_started");
  });

  // --- Case ID typing
  caseIdInput.addEventListener("input", () => {
    const value = caseIdInput.value.trim();
    const isValid = incidentIdRegex.test(value);

    // Enable Create Incident when ID is valid
    createBtn.disabled = !isValid;
  });

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



      if (!files.length) {
        evidenceListEl.innerHTML = "<em>No evidence uploaded</em>";
        return;
      }

      evidenceListEl.innerHTML = "";
      files.forEach((f) => {
        const row = document.createElement("div");
        row.className = "evidence-row";

        const fileNameEl = document.createElement("a");
        fileNameEl.textContent = f.filename || "(unnamed)";
        fileNameEl.href = `${API_BASE}/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(f.filename)}`;
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
      const response = await fetch(`${API_BASE}/cases/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_number: incidentId })
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

      setByPath(caseState, "case.case_number", incidentId);

      loadEvidence(incidentId);

      alert(`Incident ${incidentId} created successfully`);

    } catch (err) {
      alert("Backend not reachable");
      createBtn.disabled = false;
    }
  });


  // --- Track edits + autosave
  const jsonFields = document.querySelectorAll("[data-json-path]");
  jsonFields.forEach((el) => {
    const eventName = el.type === "checkbox" ? "change" : "input";
    el.addEventListener(eventName, () => handleJsonFieldChange(el));
  });

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

    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));

    try {
      const xhr = new XMLHttpRequest();

      xhr.open(
        "POST",
        `${API_BASE}/cases/${encodeURIComponent(caseId)}/evidence`
      );

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

      xhr.send(formData);
    } catch (err) {
      if (uploadStatus) uploadStatus.textContent = "Unexpected upload error";
      if (uploadBtn) uploadBtn.disabled = false;
    }
  });

  // --- Confirm Phase buttons
  const confirmButtons = document.querySelectorAll(".confirm-phase-btn");
  confirmButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const phase = btn.dataset.phase;
      if (!phase) return;
      const header = ensurePhaseHeader(phase);
      header.completed = true;
      header.status = "confirmed";
      header.confirmed_at = nowIso();
      header.last_updated = nowIso();
      setPhaseStatus(phase, header.status);

      const patch = buildHeaderPatch(phase, {
        completed: header.completed,
        status: header.status,
        confirmed_at: header.confirmed_at,
        last_updated: header.last_updated
      });

      await savePatchImmediately(patch);
    });
  });

  // -------- helpers --------
  function nowIso() {
    return new Date().toISOString();
  }

  function formatStatus(status) {
    return status.replace(/_/g, " ");
  }

  function setPhaseStatus(phase, status) {
    const col = document.querySelector(`.column[data-phase="${phase}"]`);
    if (!col) return;
    col.dataset.status = status;
    const statusEl = col.querySelector("[data-phase-status]");
    if (statusEl) statusEl.textContent = formatStatus(status);
  }

  function ensurePhaseHeader(phase) {
    if (!caseState.phases) caseState.phases = {};
    if (!caseState.phases[phase]) caseState.phases[phase] = {};
    if (!caseState.phases[phase].header) {
      caseState.phases[phase].header = {
        name: PHASE_META[phase]?.name || phase,
        discipline: PHASE_META[phase]?.discipline || phase,
        completed: false,
        last_updated: "",
        confirmed_at: null,
        status: "not_started"
      };
    }
    if (!caseState.phases[phase].header.status) {
      caseState.phases[phase].header.status = "not_started";
    }
    if (caseState.phases[phase].header.completed === undefined) {
      caseState.phases[phase].header.completed = false;
    }
    return caseState.phases[phase].header;
  }

  function getPhaseFromPath(path) {
    if (!path.startsWith("phases.")) return null;
    const parts = path.split(".");
    return parts[1] || null;
  }

  function handleJsonFieldChange(el) {
    const path = el.dataset.jsonPath;
    if (!path) return;
    if (el.type === "file") return;

    const value = getElementValue(el);
    setByPath(caseState, path, value);

    const phase = getPhaseFromPath(path);
    let immediate = false;
    let headerPatch = null;

    if (phase) {
      const header = ensurePhaseHeader(phase);
      const prevStatus = header.status || "not_started";
      header.last_updated = nowIso();

      if (prevStatus === "not_started") {
        header.status = "in_progress";
      } else if (prevStatus === "confirmed") {
        header.status = "reopened";
        header.completed = false;
        header.confirmed_at = null;
        immediate = true;
      }

      setPhaseStatus(phase, header.status);

      headerPatch = buildHeaderPatch(phase, {
        status: header.status,
        completed: header.completed,
        confirmed_at: header.confirmed_at,
        last_updated: header.last_updated
      });
    }

    let patch;
    const tokens = parsePath(path);
    if (typeof tokens[tokens.length - 1] === "number") {
      const parentTokens = tokens.slice(0, -1);
      const parentPath = tokensToPath(parentTokens);
      const arrValue = getByPath(caseState, parentTokens);
      const filled = fillScalarArray(arrValue);
      patch = buildPatch(parentPath, filled);
    } else {
      patch = buildPatch(path, value);
    }
    if (headerPatch) {
      patch = deepMerge(patch, headerPatch);
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

  function fillScalarArray(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.map((v) => (v === undefined ? "" : v));
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

  function buildHeaderPatch(phase, headerFields) {
    return {
      phases: {
        [phase]: {
          header: headerFields
        }
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

    const caseId = caseIdInput.value.trim();
    if (!incidentIdRegex.test(caseId)) return;

    const payload = pendingPatch;
    pendingPatch = {};
    if (!payload || Object.keys(payload).length === 0) return;

    await patchCase(caseId, payload);
  }

  async function savePatchImmediately(patch) {
    const caseId = caseIdInput.value.trim();
    if (!incidentIdRegex.test(caseId)) return;
    await patchCase(caseId, patch);
  }

  async function patchCase(caseId, patch) {
    try {
      await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      });
    } catch (err) {
      // Keep UI responsive even if save fails
      console.warn("Autosave failed", err);
    }
  }

});

