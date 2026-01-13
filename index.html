<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>AI-Assisted Decision Support</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <link rel="stylesheet" href="styles.css"/>
</head>

<body>

<header class="topbar">
  <h1>AI-Assisted Decision Support</h1>
  <p>Structured problem & incident resolution</p>
</header>

<div class="layout">

<!-- LEFT -->
<div class="left-panel">

<!-- 1 -->
<section class="section open" data-section="case_information">
  <div class="section-header" onclick="toggleSection(this)">
    <span class="step">1</span><h2>Case Information</h2>
  </div>
  <div class="section-body">
    <input placeholder="Case ID" data-field="case_id" oninput="updateState()">
    <input type="date" data-field="date" oninput="updateState()">
    <input placeholder="Problem Title" data-field="problem_title" oninput="updateState()">
    <input placeholder="Team Members" data-field="team_members" oninput="updateState()">
  </div>
</section>

<!-- 2 -->
<section class="section" data-section="incident">
  <div class="section-header" onclick="toggleSection(this)">
    <span class="step">2</span><h2>Incident (5W2H)</h2>
  </div>
  <div class="section-body">
    <textarea placeholder="What?" data-field="what" oninput="updateState()"></textarea>
    <textarea placeholder="Why?" data-field="why_problem" oninput="updateState()"></textarea>
    <input placeholder="When?" data-field="when" oninput="updateState()">
    <input placeholder="Where?" data-field="where" oninput="updateState()">
    <input placeholder="Who?" data-field="who" oninput="updateState()">
    <textarea placeholder="How identified?" data-field="how_identified" oninput="updateState()"></textarea>
    <input placeholder="Impact" data-field="impact" oninput="updateState()">
  </div>
</section>

<!-- 3 -->
<section class="section" data-section="immediate_actions">
  <div class="section-header" onclick="toggleSection(this)">
    <span class="step">3</span><h2>Immediate Actions</h2>
  </div>
  <div class="section-body">
    <table id="immediateActions">
      <thead><tr><th>Action</th><th>Owner</th><th>Due</th></tr></thead>
      <tbody></tbody>
    </table>
    <button onclick="addRow('immediateActions')">+ Add Action</button>
  </div>
</section>

<!-- 4 -->
<section class="section" data-section="investigation">
  <div class="section-header" onclick="toggleSection(this)">
    <span class="step">4</span><h2>Investigation & Analysis</h2>
  </div>

  <div class="section-body">

    <div class="tabs">
      <button class="tab active" onclick="openTab(event,'tab-tasks')">Tasks</button>
      <button class="tab" onclick="openTab(event,'tab-fishbone')">Fishbone</button>
      <button class="tab" onclick="openTab(event,'tab-factors')">Factors</button>
      <button class="tab" onclick="openTab(event,'tab-why')">5 Whys</button>
    </div>

    <div class="tab-content active" id="tab-tasks">
      <table id="investigationTasks">
        <thead><tr><th>Item</th><th>Owner</th><th>Due</th></tr></thead>
        <tbody></tbody>
      </table>
      <button onclick="addRow('investigationTasks')">+ Add Task</button>
    </div>

    <div class="tab-content" id="tab-fishbone">
      <div class="fishbone-grid">
        <div class="fishbone-card"><h4>People</h4><ul id="fish-people"></ul><button onclick="addFishbone('fish-people')">+</button></div>
        <div class="fishbone-card"><h4>Process</h4><ul id="fish-process"></ul><button onclick="addFishbone('fish-process')">+</button></div>
        <div class="fishbone-card"><h4>Product</h4><ul id="fish-product"></ul><button onclick="addFishbone('fish-product')">+</button></div>
        <div class="fishbone-card"><h4>Procedure</h4><ul id="fish-procedure"></ul><button onclick="addFishbone('fish-procedure')">+</button></div>
        <div class="fishbone-card"><h4>Policy</h4><ul id="fish-policy"></ul><button onclick="addFishbone('fish-policy')">+</button></div>
        <div class="fishbone-card"><h4>Place</h4><ul id="fish-place"></ul><button onclick="addFishbone('fish-place')">+</button></div>
      </div>
    </div>

    <div class="tab-content" id="tab-factors">
      <table id="factorTable">
        <thead><tr><th>Factor</th><th>Expected</th><th>Actual</th><th>Relevant</th></tr></thead>
        <tbody></tbody>
      </table>
      <button onclick="addRow('factorTable')">+ Add Factor</button>
    </div>

    <div class="tab-content" id="tab-why">
      <div id="fiveWhyContainer"></div>
      <button onclick="addWhyChain()">+ Add 5-Why Chain</button>
    </div>

  </div>
</section>

<!-- 5 -->
<section class="section" data-section="corrective_actions">
  <div class="section-header" onclick="toggleSection(this)">
    <span class="step">5</span><h2>Corrective & Preventive Actions</h2>
  </div>
  <div class="section-body">
    <table id="correctiveActions">
      <thead><tr><th>Action</th><th>Owner</th><th>Due</th><th>Verification</th></tr></thead>
      <tbody></tbody>
    </table>
    <button onclick="addRow('correctiveActions')">+ Add Action</button>
  </div>
</section>

</div>

<!-- RIGHT -->
<div class="right-panel">
  <div id="caseStatus" class="case-status new">Status: New</div>
  <button onclick="runAI()">Request AI Decision Support</button>
  <textarea id="jsonPreview" rows="22" readonly></textarea>
</div>

</div>

<script src="app.js"></script>
</body>
</html>
