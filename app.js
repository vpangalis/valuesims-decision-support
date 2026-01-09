function toggleSection(header) {
  header.parentElement.classList.toggle("open");
}

function updateState() {
  document.querySelectorAll(".section").forEach(section => {
    const inputs = section.querySelectorAll("input, textarea");
    const filled = [...inputs].some(el => el.value.trim() !== "");
    section.classList.toggle("completed", filled);
  });
  buildPayload();
}

function addAction() {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input oninput="updateState()"></td>
    <td><input oninput="updateState()"></td>
    <td><input type="date" oninput="updateState()"></td>
  `;
  document.querySelector("#actionsTable tbody").appendChild(row);
}

function addInvestigation() {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input oninput="updateState()"></td>
    <td><input oninput="updateState()"></td>
    <td><input type="date" oninput="updateState()"></td>
  `;
  document.querySelector("#investigationTable tbody").appendChild(row);
}

function openTab(evt, id) {
  document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  evt.target.classList.add("active");
}

function buildPayload() {
  const payload = {
    timestamp: new Date().toISOString(),
    sections_completed: [...document.querySelectorAll(".section.completed")]
      .map(s => s.id)
  };
  document.getElementById("jsonPreview").value = JSON.stringify(payload, null, 2);
}

function runAI() {
  document.getElementById("progress").classList.remove("hidden");
  setTimeout(() => {
    document.getElementById("progress").classList.add("hidden");
    document.getElementById("aiOutput").innerHTML =
      "<strong>AI Recommendation:</strong><br>Focus investigation on process & policy gaps.";
  }, 1500);
}
