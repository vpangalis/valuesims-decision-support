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

    // Unlock entry fields when ID is valid
    editFields.forEach(el => el.disabled = !isValid);

    // Upload Evidence & AI enabled when ID is valid
    actionButtons.forEach(btn => btn.disabled = !isValid);
  });

  // --- Create Incident = formal lock only
  createBtn.addEventListener("click", () => {
    const incidentId = caseIdInput.value.trim();

    if (!incidentIdRegex.test(incidentId)) {
      alert("Invalid Incident ID format.");
      return;
    }

    console.log("Incident created:", incidentId);

    // Lock ID + button
    caseIdInput.disabled = true;
    createBtn.disabled = true;
  });

  // --- Track edits (future use)
  document.addEventListener("input", (e) => {
    const col = e.target.closest(".column");
    if (col) col.dataset.edited = "true";
  });

});
