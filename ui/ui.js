document.addEventListener("DOMContentLoaded", () => {

  // 🔧 API base (local dev vs Azure Static Web Apps)
  const API_BASE =
    window.location.hostname.includes("azurestaticapps.net")
      ? "/api"
      : "http://127.0.0.1:8000";


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

        const name = document.createElement("span");
        name.textContent = f.filename || "(unnamed)";

        const size = document.createElement("span");
        const kb = Math.round((f.size_bytes || 0) / 1024);
        size.textContent = `${kb} KB`;

        const button = document.createElement("button");
        button.textContent = "⬇";
        button.addEventListener("click", () => {
          window.downloadEvidence(caseId, f.filename);
        });

        row.appendChild(name);
        row.appendChild(size);
        row.appendChild(button);
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

      loadEvidence(incidentId);

      alert(`Incident ${incidentId} created successfully`);

    } catch (err) {
      alert("Backend not reachable");
      createBtn.disabled = false;
    }
  });


  // --- Track edits (future use)
  document.addEventListener("input", (e) => {
    const col = e.target.closest(".column");
    if (col) col.dataset.edited = "true";
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

});

