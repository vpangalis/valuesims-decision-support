function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

function openTab(evt, id) {
  evt.stopPropagation();
  const body = evt.target.closest(".section-body");
  body.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  body.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  evt.target.classList.add("active");
  body.querySelector("#" + id).classList.add("active");
}

function addRow(id) {
  const table = document.getElementById(id);
  const cols = table.querySelectorAll("thead th").length;
  const tr = document.createElement("tr");
  tr.innerHTML = Array(cols).fill(0).map(() => `<td><input oninput="updateState()"></td>`).join("");
  table.querySelector("tbody").appendChild(tr);
  updateState();
}

function addFishboneCause(id) {
  const ul = document.getElementById(id);
  const li = document.createElement("li");
  li.innerHTML = `<input oninput="updateState()">`;
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
    fields.forEach((f,i)=>obj[f]=tr.querySelectorAll("input")[i]?.value||"");
    return obj;
  });
}

function readList(id) {
  return [...document.querySelectorAll(`#${id} input`)].map(i=>i.value).filter(Boolean);
}

function determineCaseStatus(p) {
  const hasData = Object.values(p.incident).some(v=>v);
  if (!hasData && p.immediate_actions.length===0) return "new";
  const ready = p.corrective_actions.length &&
    p.corrective_actions.every(a=>a.action&&a.owner&&a.due&&a.verification);
  return ready ? "ready" : "in_progress";
}

function updateSectionState(section) {
  const inputs = section.querySelectorAll("input,textarea");
  const filled = [...inputs].filter(i=>i.value.trim()).length;
  section.classList.remove("started","completed");
  if (filled===0) return;
  section.classList.add("started");
  if ([...inputs].every(i=>i.value.trim())) {
    section.classList.replace("started","completed");
  }
}

function updateState() {
  document.querySelectorAll(".section").forEach(updateSectionState);

  const payload = {
    meta:{timestamp:new Date().toISOString()},
    case_information:{},
    incident:{},
    immediate_actions:readTable("immediateActions",["action","owner","due"]),
    investigation:{
      tasks:readTable("investigationTasks",["item","owner","due"]),
      fishbone:{
        people:readList("fish-people"),
        process:readList("fish-process"),
        product:readList("fish-product"),
        procedure:readList("fish-procedure"),
        policy:readList("fish-policy"),
        place:readList("fish-place")
      },
      factors:readTable("factorTable",["factor","expected","actual","relevant"]),
      five_whys:[...document.querySelectorAll(".why-chain")].map(c=>[...c.querySelectorAll("input")].map(i=>i.value))
    },
    corrective_actions:readTable("correctiveActions",["action","owner","due","verification"])
  };

  document.querySelectorAll("[data-section]").forEach(sec=>{
    payload[sec.dataset.section] ||= {};
    sec.querySelectorAll("[data-field]").forEach(f=>{
      payload[sec.dataset.section][f.dataset.field]=f.value||"";
    });
  });

  const status = determineCaseStatus(payload);
  const el=document.getElementById("caseStatus");
  el.className=`case-status ${status}`;
  el.innerText=status==="new"?"Status: New":status==="ready"?"Status: Ready for Closure":"Status: In Progress";

  document.getElementById("jsonPreview").value=JSON.stringify(payload,null,2);
  window.currentPayload=payload;
}

function runAI() {
  console.log(window.currentPayload);
  alert("Payload ready");
}

window.addEventListener("DOMContentLoaded", updateState);
