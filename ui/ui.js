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

    const url = `http://127.0.0.1:8000/cases/${safeCaseId}/evidence/${safeFilename}`;
    window.open(url, "_blank");
  };

  async function loadEvidence(caseId) {
    if (!evidenceListEl) return;

    evidenceListEl.textContent = "Loading evidence...";

    try {
      const safeCaseId = encodeURIComponent(caseId);
      const res = await fetch(`http://127.0.0.1:8000/cases/${safeCaseId}/evidence`);
      if (!res.ok) throw new Error("Failed to load evidence");

      const data = await res.json();
      const files = Array.isArray(data) ? data : [];

      

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
      const response = await fetch("http://127.0.0.1:8000/cases/", {
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

});
