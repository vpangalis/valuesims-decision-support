document.addEventListener("input", (e) => {
  const col = e.target.closest(".column[data-edited]");
  if (col) col.dataset.edited = "true";

  const caseId = document.getElementById("case-id-input").value.trim();
  const buttons = document.querySelectorAll(
    "[data-action='upload-evidence'], [data-action='run-agent']"
  );

  buttons.forEach(btn => {
    btn.disabled = caseId === "";
  });
});
