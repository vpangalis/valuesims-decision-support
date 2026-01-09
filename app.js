function toggleSection(header) {
  header.parentElement.classList.toggle("active");
}

function addActionRow() {
  const tbody = document.querySelector("#actions-table tbody");
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><input type="text" oninput="updateState()" /></td>
    <td><input type="text" oninput="updateState()" /></td>
    <td><input type="date" oninput="updateState()" /></td>
  `;
  tbody.appendChild(row);
  updateState();
}

function updateState() {
  document.querySelectorAll(".section").forEach(section => {
    const inputs = section.querySelectorAll("input, textarea");
    const filled = [...inputs].some(el => el.value.trim() !== "");
    section.classList.toggle("active", filled);
  });

  buildPayload();
}

function buildPayload() {
  const payload = {
    case_metadata: {
      case_id: case_id.value,
      title: case_title.value,
      date: case_date.value,
      team: case_team.value
    },
    incident_description: {
      what: what.value,
      why_impact: why_impact.value,
      when: when.value,
      where: where.value,
      who_detected: who.value,
      how_detected: how.value,
      how_many: how_many.value
    },
    immediate_actions: [...document.querySelectorAll("#actions-table tbody tr")].map(r => ({
      action: r.children[0].querySelector("input").value,
      owner: r.children[1].querySelector("input").value,
      due_date: r.children[2].querySelector("input").value
    })),
    investigation_plan: investigation_plan.value,
    corrective_actions: corrective_actions.value,
    current_stage: "investigation"
  };

  document.getElementById("json-preview").value =
    JSON.stringify(payload, null, 2);
}

function runAI() {
  document.getElementById("progress").classList.remove("hidden");
  setTimeout(() => {
    document.getElementById("ai-result").innerHTML =
      "<strong>AI Output</strong><p>Investigation plan is incomplete. Define scope, assign ownership, and validate evidence before root cause analysis.</p>";
  }, 1200);
}
