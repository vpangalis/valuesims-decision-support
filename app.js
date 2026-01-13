function toggleSection(header) {
  const section = header.parentElement;
  document.querySelectorAll(".section").forEach(s => {
    if (s !== section) s.classList.remove("open");
  });
  section.classList.add("open");
}

function addRow(tableId) {
  const table = document.getElementById(tableId);
  const cols = table.querySelectorAll("thead th").length;
  const tr = document.createElement("tr");
  tr.innerHTML = Array(cols).fill(0)
    .map(() => `<td><input oninput="updateState()"></td>`)
    .join("");
  table.querySelector("tbody").appendChild(tr);
  updateState();
}

function determineCaseStatus(payload) {
  const hasData =
    Object.values(payload.case_information).some(Boolean) ||
    Object.values(payload.incident).some(Boolean);

  if (!hasData) return "new";

  const corrective = payload.corrective_actions;
  const ready =
    corrective.length > 0 &&
    corrective.every(a => a.action && a.owner && a.due && a.verification);

  return ready ? "ready" : "in-progress";
}

function updateState() {
  const payload = {
    case_information: {},
    incident: {},
    corrective_actions: []
  };

  document.querySelectorAll("[data-section]").forEach(section => {
    const key = section.dataset.section;
    payload[key] = {};
    section.querySelectorAll("[data-field]").forEach(f => {
      payload[key][f.dataset.field] = f.value || "";
    });
  });

  payload.corrective_actions = [...document.querySelectorAll("#correctiveActions tbody tr")]
    .map(tr => {
      const inputs = tr.querySelectorAll("input");
      return {
        action: inputs[0]?.value || "",
        owner: inputs[1]?.value || "",
        due: inputs[2]?.value || "",
        verification: inputs[3]?.value || ""
      };
    });

  const status = determineCaseStatus(payload);
  const el = document.getElementById("caseStatus");
  el.className = `case-status ${status}`;
  el.textContent =
    status === "new" ? "Status: New" :
    status === "ready" ? "Status: Ready for Closure" :
    "Status: In Progress";

  document.getElementById("jsonPreview").value =
    JSON.stringify(payload, null, 2);
}

window.addEventListener("DOMContentLoaded", updateState);
