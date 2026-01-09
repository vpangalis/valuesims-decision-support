function toggleSection(header) {
  const section = header.parentElement;
  section.classList.toggle("active");
}

function updateSection(sectionId) {
  const section = document.getElementById(sectionId);
  const inputs = section.querySelectorAll("input, textarea");
  const filled = Array.from(inputs).some(el => el.value.trim() !== "");
  section.classList.toggle("active", filled);
  buildPayload();
}

function buildPayload() {
  const payload = {};

  document.querySelectorAll(".section").forEach(section => {
    const title = section.querySelector(".section-title").innerText;
    const values = {};
    section.querySelectorAll("input, textarea").forEach((el, i) => {
      values[`field_${i + 1}`] = el.value;
    });
    payload[title] = values;
  });

  document.getElementById("json-preview").value =
    JSON.stringify(payload, null, 2);
}

function runAI() {
  document.getElementById("progress").classList.remove("hidden");

  setTimeout(() => {
    document.getElementById("progress").classList.add("hidden");
    document.getElementById("ai-output").innerHTML = `
      <strong>AI Recommendation</strong>
      <ul>
        <li>Clarify investigation scope</li>
        <li>Assign clear ownership</li>
        <li>Prioritize high-impact hypotheses</li>
      </ul>
    `;
  }, 2000);
}
function addAction() {
  const table = document.getElementById("actions-table");

  const row = document.createElement("div");
  row.className = "action-row";

  row.innerHTML = `
    <input type="text" placeholder="Action description"
           oninput="updateSection('section-actions')" />
    <input type="text" placeholder="Responsible"
           oninput="updateSection('section-actions')" />
    <input type="date"
           oninput="updateSection('section-actions')" />
    <button class="remove-btn" onclick="removeAction(this)">−</button>
  `;

  table.appendChild(row);
}

function removeAction(btn) {
  btn.parentElement.remove();
  updateSection('section-actions');
}
