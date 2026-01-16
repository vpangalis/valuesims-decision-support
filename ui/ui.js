document.addEventListener("DOMContentLoaded", () => {

  const caseIdInput = document.getElementById("case-id-input");
  const createBtn = document.getElementById("create-incident-btn");

  const actionButtons = document.querySelectorAll(
    "[data-action='upload-evidence'], [data-action='run-agent']"
  );

  // --- Safety checks (important during development)
  if (!caseIdInput || !createBtn) {
    console.warn("Incident ID input or Create button not found");
    return;
  }

  // --- Disable everything by default
  createBtn.disabled = true;
  actionButtons.forEach(btn => btn.disabled = true);

  // --- Incident ID validation
  const incidentIdRegex = /^INC-\d{8}-\d{4}$/;

  caseIdInput.addEventListener("input", () => {
    const value = caseIdInput.value.trim();
    const isValid = incidentIdRegex.test(value);

    // Enable only Create Incident when valid
    createBtn.disabled = !isValid;

    // Evidence / AI stay disabled until incident is created
    actionButtons.forEach(btn => btn.disabled = true);
  });

  // --- Create Incident (official moment)
  createBtn.addEventListener("click", () => {
    const incidentId = caseIdInput.value.trim();

    if (!incidentIdRegex.test(incidentId)) {
      alert("Invalid Incident ID format.");
      return;
    }

    console.log("Incident created:", incidentId);

    // Unlock next actions ONLY after creation
    actionButtons.forEach(btn => btn.disabled = false);

    // Lock the Incident ID so it cannot change
    caseIdInput.disabled = true;
    createBtn.disabled = true;
  });

  // --- Track column edits (optional, future use)
  document.addEventListener("input", (e) => {
    const col = e.target.closest(".column");
    if (col) col.dataset.edited = "true";
  });

});
