function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

/* ---------- TABS ---------- */
function openTab(evt, id) {
  const sectionBody = evt.target.closest(".section-body");
  if (!sectionBody) return;

  sectionBody.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  sectionBody.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

  evt.target.classList.add("active");
  const content = sectionBody.querySelector("#" + id);
  if (content) content.classList.add("active");
}

/* ---------- DYNAMIC ROWS ---------- */
function addRow(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const tbody = table.querySelector("tbody");
  const cols = table.querySelectorAll("thead th").length;

  const tr = document.createElement("tr");
  tr.innerHTML = Array(cols)
    .fill(0)
    .map(() => `<td><input oninput="updateState()"></td>`)
    .join("");

  tbody.appendChild(tr);
  updateState();
}

function addListItem(id) {
  const list = document.getElementById(id);
  if (!list) return;

  const li = document.createElement("li");
  li.innerHTML = `<input oninput="updateState()">`;
  list.appendChild(li);

  updateState();
}

function addWhyChain() {
  const container = document.getElementById("fiveWhyContainer");
  if (!container) return;

  const div = document.createElement("div");
  div.className = "why-chain";
  div.innerHTML = `
    ${[1,2,3,4,5].map(i => `Why ${i}: <input oninput="updateState()">`).join("<br>")}
    <hr>
  `;
  container.appendChild(div);
  updateState();
}

/* ---------- SAFE READERS ---------- */
function readTable(id) {
  const table = document.getElementById(id);
  if (!table) return [];

  const rows = [];
  table.querySelectorAll("tbody tr").forEach(tr => {
    const values = [...tr.querySelectorAll("input")].map(i => i.value || "");
    rows.push(values);
  });
  return rows;
}

function readList(id) {
  const list = document.getElementById(id);
  if (!list) return [];
  return [...list.querySelectorAll("input")].map(i => i.value || "");
}

function readWhyChains() {
  return [...document.querySelectorAll(".why-chain")].map(chain =>
    [...chain.querySelectorAll("input")].map(i => i.value || "")
  );
}

/* ---------- PAYLOAD ---------- */
function updateState() {
  buildPayload();
}

function buildPayload() {
  const payload = {
    meta: {
      timestamp: new Date().toISOString()
    },
    case_information: {},
    incident: {},
    immediate_actions: readTable("immediateActions"),
    investigation: {
      tasks: readTable("investigationTasks"),
      fishbone: {
        people: readList("fish-people"),
        process: readList("fish-process"),
        product: readList("fish-product"),
        procedure: readList("fish-procedure"),
        policy: readList("fish-policy"),
        place: readList("fish-place")
      },
      factors: readTable("factorTable"),
      five_whys: readWhyChains()
    },
    corrective_actions: readTable("correctiveActions")
  };

  document.querySelectorAll("[data-section]").forEach(section => {
    const key = section.dataset.section;
    const fields = section.querySelectorAll("[data-field]");
    if (!fields.length) return;

    payload[key] = {};
    fields.forEach(f => {
      payload[key][f.dataset.field] = f.value || "";
    });
  });

  const preview = document.getElementById("jsonPreview");
  if (preview) {
    preview.value = JSON.stringify(payload, null, 2);
  }
}

/* ---------- DEMO ACTION ---------- */
function runAI() {
  alert("This would send the JSON payload to FastAPI on Azure.");
}
