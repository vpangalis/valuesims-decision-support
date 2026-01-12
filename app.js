function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

function openTab(evt, id) {
  const body = evt.target.closest(".section-body");
  body.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  body.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  evt.target.classList.add("active");
  body.querySelector("#" + id).classList.add("active");
}

function addRow(tableId) {
  const table = document.getElementById(tableId);
  const cols = table.querySelectorAll("thead th").length;
  const tr = document.createElement("tr");
  tr.innerHTML = Array(cols).fill(0).map(() => `<td><input oninput="updateState()"></td>`).join("");
  table.querySelector("tbody").appendChild(tr);
  updateState();
}

function addFishboneCause(listId) {
  const ul = document.getElementById(listId);
  if (!ul) return;

  const li = document.createElement("li");
  li.className = "fishbone-cause";

  li.innerHTML = `
    <input placeholder="Describe potential cause" oninput="updateState()" />
    <button class="remove-btn" onclick="this.parentElement.remove(); updateState()">✕</button>
  `;

  ul.appendChild(li);
  updateState();
}

function addWhyChain() {
  const div = document.createElement("div");
  div.className = "why-chain";
  div.innerHTML = [1,2,3,4,5].map(i => `Why ${i}: <input oninput="updateState()">`).join("<br>") + "<hr>";
  document.getElementById("fiveWhyContainer").appendChild(div);
  updateState();
}

function readTable(tableId, fields) {
  return [...document.querySelectorAll(`#${tableId} tbody tr`)].map(tr => {
    const obj = {};
    fields.forEach((f,i)=> obj[f] = tr.querySelectorAll("input")[i]?.value || "");
    return obj;
  });
}

function readList(id) {
  return [...document.querySelectorAll(`#${id} input`)].map(i => i.value).filter(Boolean);
}

function updateStatus(state) {
  const el = document.getElementById("caseStatus");
  el.className = "case-status " + state;
  el.textContent =
    state === "ready" ? "Status: Ready for Closure" :
    state === "closed" ? "Status: Closed" :
    "Status: In Progress";
}

function readFishbone(listId) {
  const ul = document.getElementById(listId);
  if (!ul) return [];

  return [...ul.querySelectorAll("input")]
    .map(i => i.value.trim())
    .filter(Boolean)
    .map(v => ({ cause: v }));
}
function buildPayload() {
  const payload = {
    meta: { timestamp: new Date().toISOString() },
    case_information: {},
    incident: {},
    immediate_actions: readTable("immediateActions", ["action","owner","due"]),
    investigation: {
      tasks: readTable("investigationTasks", ["item","owner","due"]),
      fishbone: {
        people: readList("fish-people"),
        process: readList("fish-process"),
        product: readList("fish-product"),
        procedure: readList("fish-procedure"),
        policy: readList("fish-policy"),
        place: readList("fish-place")
      },
      factors: readTable("factorTable", ["factor","expected","actual","relevant"]),
      five_whys: [...document.querySelectorAll(".why-chain")].map(c =>
        [...c.querySelectorAll("input")].map(i => i.value))
    },
    corrective_actions: readTable("correctiveActions", ["action","owner","due","verification"])
  };

  document.querySelectorAll("[data-section]").forEach(sec=>{
    payload[sec.dataset.section] ||= {};
    sec.querySelectorAll("[data-field]").forEach(f=>{
      payload[sec.dataset.section][f.dataset.field]=f.value||"";
    });
  });

  const ready = payload.corrective_actions.length &&
    payload.corrective_actions.every(a=>a.action && a.owner && a.due && a.verification);

  payload.meta.closure_status = ready ? "ready" : "in-progress";
  updateStatus(payload.meta.closure_status);

  document.getElementById("jsonPreview").value = JSON.stringify(payload,null,2);
  window.currentPayload = payload;
}

function updateState(){ buildPayload(); }

function runAI(){
  console.log(window.currentPayload);
  alert("Payload ready for FastAPI");
}
