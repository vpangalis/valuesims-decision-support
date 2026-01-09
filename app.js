function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

function addRow(tableId) {
  const tbody = document.getElementById(tableId).querySelector("tbody");
  const cols = document.getElementById(tableId).querySelectorAll("thead th").length;
  const tr = document.createElement("tr");
  tr.innerHTML = Array(cols).fill(0).map(() => `<td><input oninput="updateState()"></td>`).join("");
  tbody.appendChild(tr);
  updateState();
}

function addListItem(id) {
  const li = document.createElement("li");
  li.innerHTML = `<input oninput="updateState()">`;
  document.getElementById(id).appendChild(li);
  updateState();
}

function addWhyChain() {
  const container = document.getElementById("fiveWhyContainer");
  const div = document.createElement("div");
  div.className = "why-chain";
  div.innerHTML = `
    ${[1,2,3,4,5].map(i => `Why ${i}: <input oninput="updateState()">`).join("<br>")}
    <hr>`;
  container.appendChild(div);
  updateState();
}

function updateState() {
  buildPayload();
}

function buildPayload() {
  const payload = {
    meta: {
      timestamp: new Date().toISOString(),
      completed_sections: []
    },
    case_information: {},
    incident: {},
    immediate_actions: [],
    investigation: {
      tasks: [],
      fishbone: {
        people: getList("fish-people"),
        process: getList("fish-process"),
        product: getList("fish-product"),
        procedure: getList("fish-procedure"),
        policy: getList("fish-policy"),
        place: getList("fish-place")
      },
      five_whys: getWhyChains()
    },
    corrective_actions: []
  };

  document.querySelectorAll("[data-section]").forEach(section => {
    const key = section.dataset.section;
    const fields = section.querySelectorAll("[data-field]");
    if (fields.length) {
      payload[key] = {};
      fields.forEach(f => payload[key][f.dataset.field] = f.value);
    }
  });

  payload.immediate_actions = readTable("immediateActions");
  payload.investigation.tasks = readTable("investigationTasks");
  payload.corrective_actions = readTable("correctiveActions");

  document.getElementById("jsonPreview").value =
    JSON.stringify(payload, null, 2);
}

function readTable(id) {
  const rows = [];
  document.querySelectorAll(`#${id} tbody tr`).forEach(tr => {
    const cells = [...tr.querySelectorAll("input")].map(i => i.value);
    rows.push(cells);
  });
  return rows;
}

function getList(id) {
  return [...document.querySelectorAll(`#${id} input`)].map(i => i.value);
}

function getWhyChains() {
  return [...document.querySelectorAll(".why-chain")].map(chain =>
    [...chain.querySelectorAll("input")].map(i => i.value)
  );
}

function runAI() {
  alert("This would POST the JSON payload to FastAPI on Azure.");
}
