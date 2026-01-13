function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

window.addEventListener("DOMContentLoaded", () => {
  updateState();
});


function openTab(evt, id) {
  evt.stopPropagation(); // 🔑 PREVENT SECTION COLLAPSE

  const body = evt.target.closest(".section-body");
  if (!body) return;

  body.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  body.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

  evt.target.classList.add("active");
  body.querySelector("#" + id).classList.add("active");
}

function addFishboneCause(id) {
  const ul = document.getElementById(id);
  const li = document.createElement("li");
  li.innerHTML = `<input oninput="updateState()"><button onclick="this.parentElement.remove();updateState()">✕</button>`;
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

function readTable(id, fields) {
  return [...document.querySelectorAll(`#${id} tbody tr`)].map(tr => {
    const obj = {};
    fields.forEach((f,i)=> obj[f] = tr.querySelectorAll("input")[i]?.value || "");
    return obj;
  });
}

function readList(id) {
  return [...document.querySelectorAll(`#${id} input`)].map(i => i.value).filter(Boolean);
}

function determineCaseStatus(payload) {
  // 1️⃣ NEW — nothing meaningful filled yet
  const hasIncidentData = Object.values(payload.incident || {}).some(v => v && v.trim?.());
  const hasActions =
    payload.immediate_actions.length > 0 ||
    payload.corrective_actions.length > 0;

  if (!hasIncidentData && !hasActions) {
    return "new";
  }

  // 2️⃣ READY FOR CLOSURE — ONLY if corrective actions are complete
  const corrective = payload.corrective_actions || [];
  const hasCorrectiveActions = corrective.length > 0;

  const allCorrectiveComplete =
    hasCorrectiveActions &&
    corrective.every(a =>
      a.action &&
      a.owner &&
      a.due &&
      a.verification
    );

  if (allCorrectiveComplete) {
    return "ready";
  }

  // 3️⃣ Otherwise → IN PROGRESS
  return "in-progress";
}


function updateState() {

  // 1️⃣ Update section visual states
  document.querySelectorAll(".section").forEach(updateSectionState);

  // 2️⃣ Build payload
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

  // 3️⃣ Read simple fields
  document.querySelectorAll("[data-section]").forEach(sec => {
    payload[sec.dataset.section] ||= {};
    sec.querySelectorAll("[data-field]").forEach(f => {
      payload[sec.dataset.section][f.dataset.field] = f.value || "";
    });
  });

  // 4️⃣ Determine & render status
  const status = determineCaseStatus(payload);

  const statusEl = document.getElementById("caseStatus");
  statusEl.className = `case-status ${status}`;
  statusEl.innerText =
    status === "new" ? "Status: New" :
    status === "ready" ? "Status: Ready for Closure" :
    "Status: In Progress";

  // 5️⃣ Preview
  document.getElementById("jsonPreview").value =
    JSON.stringify(payload, null, 2);

  window.currentPayload = payload;
}


  document.querySelectorAll("[data-section]").forEach(sec => {
    payload[sec.dataset.section] ||= {};
    sec.querySelectorAll("[data-field]").forEach(f => payload[sec.dataset.section][f.dataset.field] = f.value || "");
  });

  const status = determineCaseStatus(payload);
  document.getElementById("caseStatus").className = `case-status ${status}`;
  document.getElementById("caseStatus").innerText =
    status === "new" ? "Status: New" :
    status === "ready" ? "Status: Ready for Closure" :
    "Status: In Progress";

  document.getElementById("jsonPreview").value = JSON.stringify(payload, null, 2);
  window.currentPayload = payload;
}

function runAI() {
  console.log(window.currentPayload);
  alert("Payload ready for FastAPI");
}

function updateSectionState(section) {
  const inputs = section.querySelectorAll("input, textarea");

  const values = [...inputs].map(i => i.value?.trim()).filter(Boolean);

  section.classList.remove("started", "completed");

  if (values.length === 0) {
    // untouched → no class
    return;
  }

  // Some data entered
  section.classList.add("started");

  // All inputs filled → completed
  const allFilled = [...inputs].every(i => i.value?.trim());

  if (allFilled) {
    section.classList.remove("started");
    section.classList.add("completed");
  }
}

function updateState() {

  // 1️⃣ Update section visual states
  document.querySelectorAll(".section").forEach(updateSectionState);

  // 2️⃣ Build payload
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

  // 3️⃣ Read simple fields
  document.querySelectorAll("[data-section]").forEach(sec => {
    payload[sec.dataset.section] ||= {};
    sec.querySelectorAll("[data-field]").forEach(f => {
      payload[sec.dataset.section][f.dataset.field] = f.value || "";
    });
  });

  // 4️⃣ Determine & render status
  const status = determineCaseStatus(payload);

  const statusEl = document.getElementById("caseStatus");
  statusEl.className = `case-status ${status}`;
  statusEl.innerText =
    status === "new" ? "Status: New" :
    status === "ready" ? "Status: Ready for Closure" :
    "Status: In Progress";

  // 5️⃣ Preview
  document.getElementById("jsonPreview").value =
    JSON.stringify(payload, null, 2);

  window.currentPayload = payload;
}


