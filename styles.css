function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

function addRow(tableId, evt) {
  evt.stopPropagation();
  const table = document.getElementById(tableId);
  const cols = table.querySelectorAll("thead th").length;

  const tr = document.createElement("tr");
  tr.innerHTML = Array(cols)
    .fill(0)
    .map(() => `<td><input oninput="updateState()"></td>`)
    .join("");

  table.querySelector("tbody").appendChild(tr);
  updateState();
}

function readTable(id, fields) {
  return [...document.querySelectorAll(`#${id} tbody tr`)].map(tr => {
    const obj = {};
    fields.forEach((f,i)=> obj[f] = tr.querySelectorAll("input")[i]?.value || "");
    return obj;
  });
}

function determineCaseStatus(payload) {
  const hasIncident = Object.values(payload.incident).some(v => v);
  const corrective = payload.corrective_actions;

  if (!hasIncident && corrective.length === 0) return "new";

  const ready =
    corrective.length > 0 &&
    corrective.every(a => a.action && a.owner && a.due && a.verification);

  return ready ? "ready" : "in_progress";
}

function updateSectionState(section) {
  const inputs = section.querySelectorAll("input, textarea");
  const filled = [...inputs].filter(i => i.value.trim());

  section.classList.remove("started", "completed");

  if (filled.length === 0) return;

  if (filled.length === inputs.length) {
    section.classList.add("completed");
  } else {
    section.classList.add("started");
  }
}

function updateState() {
  document.querySelectorAll(".section").forEach(updateSectionState);

  const payload = {
    meta: { timestamp: new Date().toISOString() },
    case_information: {},
    incident: {},
    corrective_actions: readTable("correctiveActions", ["action","owner","due","verification"])
  };

  document.querySelectorAll("[data-section]").forEach(sec => {
    payload[sec.dataset.section] ||= {};
    sec.querySelectorAll("[data-field]").forEach(f => {
      payload[sec.dataset.section][f.dataset.field] = f.value || "";
    });
  });

  const status = determineCaseStatus(payload);
  const statusEl = document.getElementById("caseStatus");

  statusEl.className = `case-status ${status}`;
  statusEl.innerText =
    status === "new" ? "Status: New" :
    status === "ready" ? "Status: Ready for Closure" :
    "Status: In Progress";

  document.getElementById("jsonPreview").value =
    JSON.stringify(payload, null, 2);

  window.currentPayload = payload;
}

function runAI() {
  console.log(window.currentPayload);
  alert("Payload ready for backend");
}

window.addEventListener("DOMContentLoaded", updateState);
