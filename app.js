/*********************************
 * SECTION TOGGLING
 *********************************/
function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

/*********************************
 * TABS (INVESTIGATION SECTION)
 *********************************/
function openTab(evt, id) {
  const sectionBody = evt.target.closest(".section-body");
  if (!sectionBody) return;

  sectionBody.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  sectionBody.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

  evt.target.classList.add("active");
  const content = sectionBody.querySelector("#" + id);
  if (content) content.classList.add("active");
}

/*********************************
 * DYNAMIC UI BUILDERS
 *********************************/
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
    ${[1, 2, 3, 4, 5]
      .map(i => `Why ${i}: <input oninput="updateState()">`)
      .join("<br>")}
    <hr>
  `;
  container.appendChild(div);

  updateState();
}

/*********************************
 * SAFE READERS (SEMANTIC)
 *********************************/
function readTableAsObjects(tableId, fields) {
  const table = document.getElementById(tableId);
  if (!table) return [];

  return [...table.querySelectorAll("tbody tr")].map(tr => {
    const inputs = [...tr.querySelectorAll("input")];
    const obj = {};
    fields.forEach((field, i) => {
      obj[field] = inputs[i]?.value || "";
    });
    return obj;
  });
}

function readFishbone(categoryId) {
  const list = document.getElementById(categoryId);
  if (!list) return [];

  return [...list.querySelectorAll("input")]
    .map(i => i.value.trim())
    .filter(v => v !== "")
    .map(v => ({ cause: v }));
}

function readFiveWhyChains() {
  return [...document.querySelectorAll(".why-chain")].map((chain, index) => ({
    chain_id: String.fromCharCode(65 + index), // A, B, C…
    whys: [...chain.querySelectorAll("input")].map(i => i.value || "")
  }));
}

/*********************************
 * STATE & PAYLOAD
 *********************************/
function updateState() {
  buildPayload();
}

function buildPayload() {
  const payload = {
    meta: {
      timestamp: new Date().toISOString(),
      current_stage: "investigation"
    },
    case_information: {},
    incident: {},
    immediate_actions: readTableAsObjects(
      "immediateActions",
      ["action", "owner", "due_date", "status"]
    ),
    investigation: {
      tasks: readTableAsObjects(
        "investigationTasks",
        ["item", "owner", "due_date", "status"]
      ),
      fishbone: {
        people: readFishbone("fish-people"),
        process: readFishbone("fish-process"),
        product: readFishbone("fish-product"),
        procedure: readFishbone("fish-procedure"),
        policy: readFishbone("fish-policy"),
        place: readFishbone("fish-place")
      },
      factors: readTableAsObjects(
        "factorTable",
        ["factor", "expected", "actual", "relevant"]
      ),
      five_whys: readFiveWhyChains()
    },
    corrective_actions: readTableAsObjects(
      "correctiveActions",
      ["action", "owner", "due_date", "verification"]
    )
  };

  // Read simple input fields by section
  document.querySelectorAll("[data-section]").forEach(section => {
    const key = section.dataset.section;
    const fields = section.querySelectorAll("[data-field]");
    if (!fields.length) return;

    payload[key] = payload[key] || {};
    fields.forEach(f => {
      payload[key][f.dataset.field] = f.value || "";
    });
  });

  // Update JSON preview
  const preview = document.getElementById("jsonPreview");
  if (preview) {
    preview.value = JSON.stringify(payload, null, 2);
  }

  // Store globally for button action
  window.currentPayload = payload;
}

/*********************************
 * ACTION BUTTON
 *********************************/
function runAI() {
  console.log("Payload sent to backend:", window.currentPayload);
  alert("This would POST the payload to FastAPI on Azure.");
}
