const checkpoints = [
  { id: "boot", label: "Boot swarm", detail: "Load target map and project context." },
  { id: "probe", label: "Probe surfaces", detail: "Exercise routes, files, config, and likely failure paths." },
  { id: "cluster", label: "Cluster evidence", detail: "Group signals into bug candidates." },
  { id: "verify", label: "Verify findings", detail: "Prefer reproducible failures over loose suspicion." },
  { id: "report", label: "Build report", detail: "Write artifacts, links, and next debugging moves." },
];

const brandMotto = "Rapid Recursive Bug Hunter";
const swarmPulseSteps = 9;
const swarmPulseMs = 150;
const feedbackStages = [
  { id: "probe", label: "Probe", detail: "surface" },
  { id: "capture", label: "Capture", detail: "evidence" },
  { id: "critique", label: "Critique", detail: "rank" },
  { id: "retest", label: "Retest", detail: "verify" },
  { id: "tighten", label: "Tighten", detail: "next pass" },
];

const crt = {
  bg: "#000300",
  ink: "#c9ffd0",
  muted: "#6f8f72",
  green: "#39ff14",
  cyan: "#7dff8c",
  amber: "#a6b35a",
  red: "#ff3434",
  fixed: "#9b5cff",
  line: "#214626",
};

const state = {
  chart: null,
  telemetryChart: null,
  speedometerChart: null,
  feedbackLoopChart: null,
  reportChart: null,
  reportReplayChart: null,
  phase: 0,
  pulseStep: 0,
  loopHeat: 0,
  runStartedAt: 0,
  telemetryProgress: 0,
  timer: null,
  running: false,
  telemetry: null,
  submission: null,
  target: null,
  pendingHunt: null,
  mode: "find",
};

const els = {
  status: document.querySelector("#status"),
  introView: document.querySelector("#introView"),
  issueView: document.querySelector("#issueView"),
  huntView: document.querySelector("#huntView"),
  reportView: document.querySelector("#reportView"),
  huntFull: document.querySelector("#huntFull"),
  findAndFix: document.querySelector("#findAndFix"),
  describeIssue: document.querySelector("#describeIssue"),
  targetDialog: document.querySelector("#targetDialog"),
  closeTarget: document.querySelector("#closeTarget"),
  targetPath: document.querySelector("#targetPath"),
  targetApply: document.querySelector("#targetApply"),
  targetMeta: document.querySelector("#targetMeta"),
  backToIntro: document.querySelector("#backToIntro"),
  issueForm: document.querySelector("#issueForm"),
  issueText: document.querySelector("#issueText"),
  issueFiles: document.querySelector("#issueFiles"),
  fileList: document.querySelector("#fileList"),
  huntMode: document.querySelector("#huntMode"),
  swarmReadout: document.querySelector("#swarmReadout"),
  swarmGraph: document.querySelector("#swarmGraph"),
  feedbackLoopReadout: document.querySelector("#feedbackLoopReadout"),
  feedbackLoopGraph: document.querySelector("#feedbackLoopGraph"),
  telemetryReadout: document.querySelector("#telemetryReadout"),
  runTelemetryGraph: document.querySelector("#runTelemetryGraph"),
  tokenSpeedometer: document.querySelector("#tokenSpeedometer"),
  checkpointList: document.querySelector("#checkpointList"),
  checkpointCount: document.querySelector("#checkpointCount"),
  reportBugCount: document.querySelector("#reportBugCount"),
  reportHeadline: document.querySelector("#reportHeadline"),
  reportGraph: document.querySelector("#reportGraph"),
  reportReplayGraph: document.querySelector("#reportReplayGraph"),
  reportGraphLabel: document.querySelector("#reportGraphLabel"),
  reportSummary: document.querySelector("#reportSummary"),
  reportTabs: [...document.querySelectorAll(".report-tab")],
  reportPanels: [...document.querySelectorAll(".report-panel")],
  overviewPanel: document.querySelector("#overviewPanel"),
  evidencePanel: document.querySelector("#evidencePanel"),
  categoriesPanel: document.querySelector("#categoriesPanel"),
  findingsPanel: document.querySelector("#findingsPanel"),
  fixedPanel: document.querySelector("#fixedPanel"),
  agentSummary: document.querySelector("#agentSummary"),
  copyAgentSummary: document.querySelector("#copyAgentSummary"),
  openReport: document.querySelector("#openReport"),
  newHunt: document.querySelector("#newHunt"),
  infoButton: document.querySelector("#infoButton"),
  infoDialog: document.querySelector("#infoDialog"),
  closeInfo: document.querySelector("#closeInfo"),
};

function setView(name) {
  for (const view of [els.introView, els.issueView, els.huntView, els.reportView]) view.hidden = true;
  ({ intro: els.introView, issue: els.issueView, hunt: els.huntView, report: els.reportView })[name].hidden = false;
  window.scrollTo(0, 0);
  window.setTimeout(() => {
    state.chart?.resize();
    state.telemetryChart?.resize();
    state.speedometerChart?.resize();
    state.feedbackLoopChart?.resize();
    state.reportChart?.resize();
    state.reportReplayChart?.resize();
  }, 0);
}

function setStatus(text, tone = "") {
  els.status.textContent = text;
  els.status.className = `status ${tone}`.trim();
}

function openInfoDialog() {
  if (!els.infoDialog) return;
  els.infoDialog.hidden = false;
  els.infoDialog.querySelector(".info-card")?.focus();
}

function closeInfoDialog() {
  if (!els.infoDialog) return;
  els.infoDialog.hidden = true;
  els.infoButton?.focus();
}

function openTargetDialog(pendingHunt = null) {
  if (!els.targetDialog) return;
  state.pendingHunt = pendingHunt;
  els.targetDialog.hidden = false;
  if (els.targetApply) {
    els.targetApply.textContent = pendingHunt ? targetActionLabel(pendingHunt.mode) : "Set Target";
    els.targetApply.disabled = false;
  }
  renderProjectTarget();
  els.targetPath?.focus();
}

function closeTargetDialog() {
  if (!els.targetDialog) return;
  els.targetDialog.hidden = true;
  state.pendingHunt = null;
  els.huntFull?.focus();
}

async function fetchJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const response = await fetch(url, { ...options, headers });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

async function validateTarget(target) {
  const payload = await fetchJson("/api/buglab/target", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ target }),
  });
  return payload.target || target;
}

function selectedFiles() {
  return [...els.issueFiles.files].map((file) => ({
    name: file.name,
    size: file.size,
    type: file.type || "unknown",
  }));
}

function renderFileList() {
  const files = selectedFiles();
  if (!files.length) {
    els.fileList.textContent = "No files selected.";
    return;
  }
  els.fileList.innerHTML = files.map((file) => `<span>${escapeHtml(file.name)} (${formatBytes(file.size)})</span>`).join("");
}

function selectedProjectTarget() {
  const localPath = (els.targetPath?.value || "").trim();
  const pathLabel = localPath.split(/[\\/]/).filter(Boolean).pop() || localPath;
  return {
    selected: Boolean(localPath),
    name: localPath ? pathLabel : "No target selected",
    localPath,
    fileCount: 0,
    sampleFiles: [],
    extensions: [],
    browserFolder: "",
  };
}

function renderProjectTarget() {
  const target = selectedProjectTarget();
  state.target = target;
  if (!els.targetMeta) return;
  els.targetMeta.textContent = target.localPath
    ? `Target: ${target.name}. BugLab will scan this path from the local server.`
    : "Enter the local project path BugLab should scan.";
  if (target.localPath && els.status?.textContent === "Select target") setStatus("Ready");
}

async function loadSubmissionSummary() {
  if (!els.liveEvidence) return;
  try {
    const payload = await fetchJson("/api/buglab/submission", { cache: "no-store" });
    state.submission = payload;
    renderSubmissionSummary(payload);
  } catch (error) {
    els.liveEvidence.innerHTML = "<span>Evidence pipeline unavailable.</span>";
  }
}

function renderSubmissionSummary(payload) {
  if (!payload?.available) {
    els.liveEvidence.innerHTML = "<span>Evidence package pending.</span>";
    return;
  }
  const summary = payload.summary || {};
  const validation = payload.validation || {};
  const latest = payload.latestEvents || [];
  const stableCases = summary.stableOracleCases ?? 0;
  const unstableCases = summary.unstableOracleCases ?? 0;
  const stablePrecision = displayMetricValue(rateLike(summary.stablePrecision));
  const stablePrecisionLower = displayMetricValue(rateLike(summary.stablePrecisionWilsonLower95));
  const headlinePrecision = displayMetricValue(rateLike(summary.precision));
  const evidenceCompleteRate = displayMetricValue(rateLike(summary.evidenceCompletionRate));
  const evidenceIncomplete = summary.evidenceIncompleteEntries ?? 0;
  const replayRate = displayMetricValue(rateLike(summary.replayReproductionRate));
  const uniqueReplayRate = displayMetricValue(rateLike(summary.uniqueReplayReproductionRate));
  const replayProblems = (summary.replayNotReproduced || 0) + (summary.replayErrors || 0);
  const replayTriage = summary.replayTriage || {};
  const hardReplayIssues = (replayTriage.artifact_contradicts_signal || 0) + (replayTriage.command_output_changed || 0);
  const uniqueReplayProblems = summary.uniqueReplayNotReproduced || 0;
  const collapsedPackets = summary.uniqueReplayDuplicatePacketsCollapsed || 0;
  const calibrationLedger = renderCalibrationLedger(payload.calibrationLedger || {});
  const promotionTriage = renderPromotionTriagePack(payload.promotionTriagePack || {});
  const promotionQueue = renderPromotionQueue(payload.promotionQueue || []);
  const replayMissDossiers = renderReplayMissDossiers(payload.replayMisses || []);
  const freezeDelta = renderFreezeDelta(payload.freeze || {});
  const latestText = latest[0]
    ? `${latest[0].kind}: ${latest[0].target} / ${latest[0].summary}`
    : "no eval events yet";
  const packageHref = payload.packageHref || "";
  const validationText = validation.ok === true
    ? `truth checks PASS (${formatNumber(validation.checks || 0)})`
    : validation.ok === false
      ? `truth checks FAIL (${formatNumber((validation.failures || []).length)})`
      : "truth checks pending";
  els.liveEvidence.innerHTML = `
    <div class="live-evidence-head">
      <strong>Evidence Pipeline</strong>
      <span>${escapeHtml(payload.updatedAt || "")}</span>
    </div>
    <div class="live-evidence-metrics">
      <span><b>${escapeHtml(formatNumber(summary.events || 0))}</b> evals</span>
      <span><b>${escapeHtml(formatNumber(summary.oracleCases || 0))}</b> oracle cases</span>
      <span><b>${escapeHtml(formatNumber(stableCases))}</b> stable</span>
      <span class="${unstableCases ? "evidence-warn" : "evidence-good"}"><b>${escapeHtml(formatNumber(unstableCases))}</b> unstable</span>
      <span><b>${escapeHtml(formatNumber(summary.markedEntries || 0))}</b> evidence entries</span>
      <span><b>${escapeHtml(evidenceCompleteRate)}</b> proof complete</span>
      <span class="${evidenceIncomplete ? "evidence-warn" : "evidence-good"}"><b>${escapeHtml(formatNumber(evidenceIncomplete))}</b> incomplete packets</span>
      <span><b>${escapeHtml(formatNumber(summary.replayChecked || 0))}</b> replayed</span>
      <span><b>${escapeHtml(replayRate)}</b> replay rate</span>
      <span><b>${escapeHtml(formatNumber(summary.uniqueReplayClaims || 0))}</b> unique claims</span>
      <span><b>${escapeHtml(uniqueReplayRate)}</b> claim replay</span>
      <span class="${uniqueReplayProblems ? "evidence-warn" : "evidence-good"}"><b>${escapeHtml(formatNumber(uniqueReplayProblems))}</b> claim misses</span>
      <span><b>${escapeHtml(formatNumber(collapsedPackets))}</b> collapsed packets</span>
      <span class="${replayProblems ? "evidence-warn" : "evidence-good"}"><b>${escapeHtml(formatNumber(replayProblems))}</b> replay issues</span>
      <span class="${hardReplayIssues ? "evidence-bad" : "evidence-good"}"><b>${escapeHtml(formatNumber(hardReplayIssues))}</b> hard triage</span>
      <span><b>${escapeHtml(formatNumber(summary.rejected || 0))}</b> rejected</span>
      <span><b>${escapeHtml(stablePrecision)}</b> stable precision</span>
      <span><b>${escapeHtml(stablePrecisionLower)}</b> stable 95% LB</span>
      <span><b>${escapeHtml(headlinePrecision)}</b> latest precision</span>
      <span class="${validation.ok === false ? "evidence-bad" : "evidence-good"}">${escapeHtml(validationText)}</span>
    </div>
    ${freezeDelta}
    ${calibrationLedger}
    ${promotionTriage}
    ${promotionQueue}
    ${replayMissDossiers}
    <p>${escapeHtml(latestText)}</p>
    ${packageHref ? `<a href="${escapeAttr(packageHref)}" target="_blank" rel="noreferrer">Open submission package</a>` : ""}
  `;
}

function renderFreezeDelta(freeze) {
  if (!freeze?.available) return "";
  const delta = freeze.delta || {};
  const metricRows = [...(delta.metrics || [])].filter(Boolean);
  const changed = [...(delta.changedMetrics || [])].filter(Boolean);
  const metricByName = new Map(metricRows.map((metric) => [metric.name, metric]));
  const status = freeze.liveAdvancedAfterFreeze
    ? "live heartbeat ahead of last freeze"
    : freeze.ok
      ? "last freeze valid"
      : "freeze needs review";
  const rows = changed.length
    ? changed.map((item) => freezeMetricChip(item, metricByName.get(item.name))).join("")
    : `<article class="flat"><span>No scored change</span><strong>0</strong><em>checkpoint stable</em></article>`;
  const interpretation = (delta.interpretation || []).map((item) => humanMetricLabel(item)).join(", ");
  return `
    <div class="freeze-delta" aria-label="Submission freeze delta">
      <div class="freeze-delta-head">
        <strong>Freeze Delta</strong>
        <span>${escapeHtml(status)}</span>
      </div>
      <div class="freeze-delta-grid">${rows}</div>
      <p>${escapeHtml(interpretation || "No scored metric changed since the previous freeze.")}</p>
    </div>
  `;
}

function freezeMetricChip(item, metric) {
  const delta = Number(item.delta || 0);
  const tone = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const current = metric ? metric.current : "";
  return `
    <article class="${tone}">
      <span>${escapeHtml(humanMetricLabel(item.name))}</span>
      <strong>${escapeHtml(formatSignedNumber(delta))}</strong>
      <em>${current === "" ? "current n/a" : `current ${formatNumber(current)}`}</em>
    </article>
  `;
}

function renderPromotionTriagePack(pack) {
  const buckets = [...(pack.actionBuckets || [])].filter(Boolean).slice(0, 4);
  const moves = [...(pack.topMoves || [])].filter(Boolean).slice(0, 3);
  if (!buckets.length && !moves.length) return "";
  return `
    <div class="promotion-triage" aria-label="Promotion triage pack">
      <div class="promotion-triage-title">
        <strong>Promotion Triage</strong>
        <span>${escapeHtml(formatNumber(pack.candidateCount || 0))} unverified leads</span>
      </div>
      ${buckets.length ? `
        <div class="promotion-triage-buckets">
          ${buckets.map((bucket) => `
            <article>
              <span>${escapeHtml(bucket.label || bucket.id || "lane")}</span>
              <strong>${escapeHtml(formatNumber(bucket.count || 0))}</strong>
              <em>${escapeHtml(formatNumber(bucket.packetsSeen || 0))} packets</em>
            </article>
          `).join("")}
        </div>
      ` : ""}
      ${moves.map((move) => `
        <article class="promotion-triage-move">
          <b>#${escapeHtml(move.rank || 0)} ${escapeHtml(move.repo || "repo")} / ${escapeHtml(move.findingId || "finding")}</b>
          <span>${escapeHtml(move.target || "target pending")}</span>
          <code>${escapeHtml(move.verificationCommand || "Replay before scoring.")}</code>
        </article>
      `).join("")}
      <p>${escapeHtml(pack.policy || "Suspected leads remain excluded from accuracy until replay or oracle promotion.")}</p>
    </div>
  `;
}

function renderPromotionQueue(queue) {
  const rows = [...(queue || [])].filter(Boolean).slice(0, 5);
  if (!rows.length) return "";
  return `
    <div class="promotion-queue" aria-label="Promotion queue">
      <div class="promotion-queue-title">
        <strong>Promotion Queue</strong>
        <span>${escapeHtml(formatNumber(rows.length))} verification targets</span>
      </div>
      ${rows.map((item) => {
        const signal = (item.signals || []).slice(0, 2).join(", ") || "signal pending";
        return `
          <article>
            <b>#${escapeHtml(item.rank || 0)} ${escapeHtml(item.repo || "repo")} / ${escapeHtml(item.findingId || "finding")}</b>
            <strong>${escapeHtml(item.severity || "unknown")}</strong>
            <p>${escapeHtml(item.claim || "Unverified lead")}</p>
            <span>${escapeHtml(signal)}</span>
            <em>${escapeHtml(item.promotionAction || "Replay before scoring.")}</em>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function humanMetricLabel(value) {
  const labels = {
    marked_entries: "marked evidence",
    suspected_entries: "suspected leads",
    unique_oracle_cases: "oracle cases",
    stable_oracle_cases: "stable cases",
    unstable_oracle_cases: "unstable cases",
    incomplete_evidence_packets: "incomplete packets",
    replay_checked: "replay checked",
    replay_reproduced: "replay reproduced",
    replay_not_reproduced: "replay misses",
    unique_replay_claims: "unique claims",
    unique_replay_reproduced: "unique replay wins",
    unique_replay_not_reproduced: "unique replay misses",
    promotion_queue_candidates: "promotion queue",
    rejected_case_results: "rejected oracle rows",
    marked_evidence_volume_changed: "marked evidence volume changed",
    unverified_suspected_leads_changed: "unverified suspected leads changed",
    replay_reproduced_evidence_changed: "replay reproduced evidence changed",
    oracle_accuracy_case_count_changed: "oracle accuracy case count changed",
    evidence_completeness_changed: "evidence completeness changed",
    no_scored_metric_change_since_previous_freeze: "no scored metric change since previous freeze",
    non_headline_metric_changed: "non-headline metric changed",
  };
  const key = String(value || "");
  return labels[key] || key.replaceAll("_", " ");
}

function renderCalibrationLedger(ledger) {
  const buckets = [...(ledger.buckets || [])].filter(Boolean);
  if (!buckets.length) return "";
  const policy = ledger.policy || "Only oracle-scored cases contribute to accuracy.";
  return `
    <div class="calibration-ledger" aria-label="Calibration ledger">
      <div class="calibration-ledger-head">
        <strong>Calibration Ledger</strong>
        <span>${escapeHtml(ledger.accuracyBasis || "oracle_scored_accuracy")}</span>
      </div>
      <div class="calibration-ledger-grid">
        ${buckets.map((bucket) => {
          const included = bucket.contributesToAccuracy === true;
          return `
            <article class="${included ? "accuracy" : "excluded"}">
              <span>${escapeHtml(bucket.label || bucket.id || "bucket")}</span>
              <strong>${escapeHtml(formatNumber(bucket.count || 0))}</strong>
              <em>${included ? "accuracy" : "excluded"}</em>
            </article>
          `;
        }).join("")}
      </div>
      <p>${escapeHtml(policy)}</p>
    </div>
  `;
}

function renderReplayMissDossiers(misses) {
  const rows = [...(misses || [])].filter(Boolean);
  if (!rows.length) return "";
  return `
    <div class="replay-miss-dossiers" aria-label="Unique replay miss dossiers">
      <div class="replay-miss-title">
        <strong>Replay Miss Dossier</strong>
        <span>${escapeHtml(formatNumber(rows.length))} quarantined unique claims</span>
      </div>
      ${rows.map((miss) => {
        const missing = (miss.missingSignals || []).slice(0, 2).join(", ") || "no matched signal";
        return `
          <article>
            <div>
              <b>${escapeHtml(miss.repo || "repo")} / ${escapeHtml(miss.findingId || "claim")}</b>
              <span>${escapeHtml(miss.target || "target unknown")}</span>
            </div>
            <strong>${escapeHtml(miss.triageClass || miss.verdict || "not_reproduced")}</strong>
            <p>${escapeHtml(missing)}</p>
            <em>${escapeHtml(formatNumber(miss.packetsCollapsed || 0))} packets collapsed / ${escapeHtml(miss.policy || "excluded")}</em>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

async function startHunt(mode, context = {}) {
  if (state.running) return;
  const target = context.target || selectedProjectTarget();
  if (!target.localPath) {
    renderProjectTarget();
    setStatus("Select target", "error");
    openTargetDialog({ mode, context });
    return;
  }
  state.target = target;
  state.running = true;
  state.phase = 0;
  state.pulseStep = 0;
  state.runStartedAt = performance.now();
  state.telemetryProgress = 0;
  state.telemetry = null;
  state.mode = mode === "find_fix" ? "find_and_fix" : "find";
  setView("hunt");
  setStatus("Hunting", "busy");
  els.huntMode.textContent = `${modeLabel(mode)} / ${target.name}`;
  renderCheckpoints();
  renderSwarm();
  renderFeedbackLoop();
  renderRunTelemetry(0);
  renderTokenSpeedometer(0, 0);
  startSequence();

  const action = mode === "guided" ? "hunt_guided" : mode === "find_fix" ? "find_and_fix" : "hunt_full";
  const runtimeRequest = fetchJson("/api/buglab/runtime")
    .then((runtime) => {
      state.telemetry = runtime;
      renderRunTelemetry(telemetryProgressRatio());
      return runtime;
    })
    .catch(() => null);
  const request = fetchJson("/api/buglab/action", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, issue: context.issue || "", files: context.files || [], target }),
  });

  try {
    const [payload] = await Promise.all([request, runtimeRequest, minimumAnimation()]);
    state.telemetry = payload.result?.telemetry || payload.result?.presentation?.telemetry || state.telemetry;
    state.phase = checkpoints.length;
    renderCheckpoints();
    renderSwarm();
    renderFeedbackLoop();
    state.telemetryProgress = 1;
    renderRunTelemetry(1);
    stopSequence();
    showReport(payload.result, mode, { ...context, target });
    setStatus("Ready");
  } catch (error) {
    stopSequence();
    state.running = false;
    setStatus("Error", "error");
    showError(error);
  }
}

function modeLabel(mode) {
  if (mode === "guided") return "Guided find";
  if (mode === "find_fix") return "Find + fix";
  return "Detector-only find";
}

function targetActionLabel(mode) {
  if (mode === "guided") return "Start Guided Hunt";
  if (mode === "find_fix") return "Start Find + Fix";
  return "Start Find Bugs";
}

function startSequence() {
  stopSequence();
  state.timer = window.setInterval(() => {
    state.pulseStep = (state.pulseStep + 1) % swarmPulseSteps;
    state.loopHeat = (state.loopHeat + 1) % 1000;
    if (state.pulseStep === 0) state.phase = Math.min(checkpoints.length - 1, state.phase + 1);
    renderCheckpoints();
    renderSwarm();
    renderFeedbackLoop();
    renderRunTelemetry(telemetryProgressRatio());
  }, swarmPulseMs);
}

function stopSequence() {
  if (state.timer) window.clearInterval(state.timer);
  state.timer = null;
}

function minimumAnimation() {
  return new Promise((resolve) => window.setTimeout(resolve, 5200));
}

function renderCheckpoints() {
  els.checkpointList.innerHTML = "";
  checkpoints.forEach((checkpoint, index) => {
    const li = document.createElement("li");
    li.className = index < state.phase ? "done" : index === state.phase ? "active" : "";
    li.innerHTML = `<strong>${escapeHtml(checkpoint.label)}</strong><span>${escapeHtml(checkpoint.detail)}</span>`;
    els.checkpointList.append(li);
  });
  els.checkpointCount.textContent = `${Math.min(state.phase + 1, checkpoints.length)}/${checkpoints.length}`;
}

function progressRatio() {
  const fractionalPhase = state.phase + state.pulseStep / swarmPulseSteps;
  return Math.min(1, Math.max(0, fractionalPhase / Math.max(1, checkpoints.length - 1)));
}

function telemetryProgressRatio() {
  if (!state.running) return state.telemetryProgress || progressRatio();
  const elapsed = Math.max(0, performance.now() - (state.runStartedAt || performance.now()));
  const elapsedCurve = 1 - Math.exp(-elapsed / 7400);
  const checkpointFloor = progressRatio() * 0.72;
  const pulseNudge = ((state.loopHeat % 9) / 9) * 0.012;
  const target = Math.min(0.985, Math.max(checkpointFloor, elapsedCurve + pulseNudge));
  state.telemetryProgress = Math.max(state.telemetryProgress || 0, target);
  return state.telemetryProgress;
}

function renderSwarm() {
  if (!window.echarts) {
    els.swarmGraph.innerHTML = "<div class=\"chart-fallback\">Apache ECharts unavailable. The bug hunt still runs and reports normally.</div>";
    return;
  }
  if (!state.chart) state.chart = echarts.init(els.swarmGraph, null, { renderer: "canvas" });
  const phase = Math.min(state.phase, checkpoints.length - 1);
  const activeSources = ["planner", "runner", "visual", "logs", "project", "runner", "visual", "logs", "report"];
  const activeSource = activeSources[state.pulseStep % activeSources.length];
  const activeCategory = (id, fallback) => (id === activeSource ? 3 : fallback);
  const nodes = [
    node("project", "Project", 76, activeCategory("project", 0), 48, 52),
    node("planner", "Planner", 48, activeCategory("planner", 1), 22, 22),
    node("runner", "Runner", 50, activeCategory("runner", 1), 20, 76),
    node("visual", "Visual", 46, activeCategory("visual", 1), 76, 24),
    node("logs", "Logs", 44, activeCategory("logs", 1), 80, 74),
    node("report", "Report", 46, phase >= 4 ? 3 : activeCategory("report", 1), 50, 90),
  ];
  const links = [
    edge("planner", "project", activeSource === "planner" || activeSource === "project"),
    edge("runner", "project", activeSource === "runner" || activeSource === "project"),
    edge("visual", "project", activeSource === "visual" || activeSource === "project"),
    edge("logs", "project", activeSource === "logs" || activeSource === "project"),
  ];
  const evidence = [
    ["routes", "Routes", "runner", 10, 50],
    ["ui", "UI", "visual", 90, 45],
    ["config", "Config", "planner", 40, 12],
    ["error", "Errors", "logs", 66, 60],
    ["bug", "Bug Report", "report", 50, 38],
  ].slice(0, phase + 1);
  let pulseNodeCount = 0;
  evidence.forEach(([id, label, source, x, y], index) => {
    const active = index === phase || source === activeSource;
    nodes.push(node(id, label, 34 + index * 3, active ? 3 : 2, x, y));
    links.push(edge(source, id, active));
    links.push(edge(id, "project", active));
    if (active) {
      const pulses = swarmPulseNodes(source, x, y, id === "bug", tokenRateLabel(source));
      pulseNodeCount += pulses.length;
      nodes.push(...pulses);
    }
  });
  if (phase >= 4) links.push(edge("project", "report", true));
  els.swarmReadout.textContent = checkpoints[phase].label;
  els.swarmGraph.dataset.pulseNodes = String(pulseNodeCount);
  els.swarmGraph.dataset.pulseStep = String(state.pulseStep);
  els.swarmGraph.dataset.tokenRate = tokenRateLabel(activeSource);
  state.chart.setOption({
    backgroundColor: "transparent",
    color: [crt.green, crt.cyan, crt.amber, crt.red],
    textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    tooltip: {
      backgroundColor: crt.bg,
      borderColor: crt.green,
      textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    },
    series: [
      {
        type: "graph",
        layout: "none",
        animation: true,
        animationDuration: 260,
        animationDelay: (idx) => idx * 28,
        animationDurationUpdate: 180,
        animationDelayUpdate: (idx) => (idx % 9) * 18,
        animationEasing: "quarticOut",
        animationEasingUpdate: "linear",
        roam: false,
        categories: [{ name: "target" }, { name: "agent" }, { name: "evidence" }, { name: "active" }],
        data: nodes,
        links,
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: [0, 9],
        label: {
          show: true,
          position: "bottom",
          color: crt.ink,
          fontSize: 16,
          fontWeight: 800,
          fontFamily: "Consolas, monospace",
          textBorderColor: crt.bg,
          textBorderWidth: 3,
        },
        labelLayout: {
          hideOverlap: true,
        },
        lineStyle: {
          color: "source",
          opacity: 0.62,
          width: 2.6,
          curveness: 0.18,
          shadowBlur: 8,
          shadowColor: "rgba(57, 255, 20, 0.28)",
        },
        emphasis: {
          scale: true,
          focus: "adjacency",
          label: { fontSize: 18 },
          lineStyle: { width: 4, opacity: 0.98 },
        },
      },
    ],
  });
}

function renderFeedbackLoop() {
  const totalTick = state.phase * swarmPulseSteps + state.pulseStep;
  const activeIndex = totalTick % feedbackStages.length;
  const previousIndex = (activeIndex + feedbackStages.length - 1) % feedbackStages.length;
  const loopNumber = Math.floor(totalTick / feedbackStages.length) + 1;
  const activeStage = feedbackStages[activeIndex];
  els.feedbackLoopReadout.textContent = `loop ${loopNumber} / ${activeStage.label.toLowerCase()} -> ${activeStage.detail}`;
  els.feedbackLoopGraph.dataset.loopStage = activeStage.id;
  els.feedbackLoopGraph.dataset.loopNumber = String(loopNumber);
  if (!window.echarts) {
    els.feedbackLoopGraph.innerHTML = "<div class=\"chart-fallback\">Recursive feedback loop: probe, capture, critique, retest, tighten.</div>";
    return;
  }
  if (!state.feedbackLoopChart) state.feedbackLoopChart = echarts.init(els.feedbackLoopGraph, null, { renderer: "canvas" });
  const box = els.feedbackLoopGraph.getBoundingClientRect();
  const width = Math.max(520, box.width || 760);
  const height = Math.max(84, box.height || 110);
  const centerX = width * 0.52;
  const centerY = height * 0.5;
  const nodes = feedbackStages.map((stage, index) => {
    const angle = -Math.PI / 2 + (index / feedbackStages.length) * Math.PI * 2;
    const radiusX = width * 0.34;
    const radiusY = height * 0.28;
    const x = centerX + Math.cos(angle) * radiusX;
    const y = centerY + Math.sin(angle) * radiusY;
    const active = index === activeIndex;
    const justFired = index === previousIndex;
    return {
      id: stage.id,
      name: `${stage.label}\n${stage.detail}`,
      x,
      y,
      fixed: true,
      symbolSize: active ? 34 : justFired ? 25 : 18,
      itemStyle: {
        color: active ? crt.ink : justFired ? crt.green : "#102b13",
        borderColor: active ? crt.green : justFired ? crt.green : crt.line,
        borderWidth: active ? 3 : 1,
        shadowBlur: active ? 20 : 0,
        shadowColor: active ? "rgba(57,255,20,0.55)" : "transparent",
      },
      label: {
        color: active ? crt.ink : justFired ? crt.green : crt.muted,
        fontSize: active ? 12 : 11,
        fontWeight: 800,
      },
    };
  });
  const transfer = {
    id: "loop-transfer",
    name: `${tokenRateLabel(activeStage.id)}\nfeedback`,
    x: centerX + Math.cos(-Math.PI / 2 + ((activeIndex + 0.45) / feedbackStages.length) * Math.PI * 2) * width * 0.2,
    y: centerY + Math.sin(-Math.PI / 2 + ((activeIndex + 0.45) / feedbackStages.length) * Math.PI * 2) * height * 0.22,
    fixed: true,
    symbolSize: 14 + (state.loopHeat % 3) * 3,
    itemStyle: {
      color: crt.green,
      borderColor: crt.ink,
      borderWidth: 1,
      shadowBlur: 18,
      shadowColor: "rgba(57,255,20,0.55)",
    },
    label: {
      show: true,
      position: "top",
      color: crt.ink,
      fontFamily: "Consolas, monospace",
      fontSize: 10,
      fontWeight: 800,
      lineHeight: 12,
      textBorderColor: crt.bg,
      textBorderWidth: 3,
    },
  };
  nodes.push(transfer);
  const links = feedbackStages.map((stage, index) => {
    const targetIndex = (index + 1) % feedbackStages.length;
    const active = index === activeIndex || targetIndex === activeIndex;
    return {
      source: stage.id,
      target: feedbackStages[targetIndex].id,
      lineStyle: {
        color: active ? crt.green : "rgba(57,255,20,0.16)",
        width: active ? 3 : 1,
        opacity: active ? 0.92 : 0.42,
        curveness: targetIndex === 0 ? 0.34 : 0.12,
        type: active ? "solid" : "dotted",
        shadowBlur: active ? 12 : 0,
        shadowColor: active ? "rgba(57,255,20,0.42)" : "transparent",
      },
    };
  });
  state.feedbackLoopChart.setOption({
    backgroundColor: "transparent",
    animation: true,
    animationDuration: 220,
    animationDurationUpdate: 150,
    animationDelayUpdate: (idx) => idx * 20,
    animationEasingUpdate: "linear",
    textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: false,
        data: nodes,
        links,
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: [0, 8],
        label: {
          show: true,
          position: "bottom",
          formatter: "{b}",
          fontFamily: "Consolas, monospace",
          lineHeight: 13,
          textBorderColor: crt.bg,
          textBorderWidth: 3,
        },
        emphasis: { disabled: true },
      },
    ],
  });
}

function renderRunTelemetry(progress = progressRatio()) {
  const telemetry = state.telemetry || {
    activeAgents: 0,
    locProcessed: 0,
    estimatedTokens: 0,
    tokenProvenance: "waiting for backend runtime telemetry",
  };
  const activeAgents = Math.ceil(Number(telemetry.activeAgents || 0) * progress);
  const locProcessed = Math.ceil(Number(telemetry.locProcessed || 0) * progress);
  const estimatedTokens = Math.ceil(Number(telemetry.estimatedTokens || 0) * progress);
  const tokensPerSecond = tokenSpeed(Number(telemetry.estimatedTokens || 0), progress);
  els.telemetryReadout.textContent = `${activeAgents}/${telemetry.activeAgents || 0} agents | ${formatNumber(estimatedTokens)} tokens`;
  els.runTelemetryGraph.dataset.tokensProcessed = String(estimatedTokens);
  els.runTelemetryGraph.dataset.tokenProgress = String(Math.round(progress * 100));
  els.runTelemetryGraph.dataset.tokensPerSecond = String(tokensPerSecond);
  renderTokenSpeedometer(tokensPerSecond, progress);
  if (!window.echarts) {
    els.runTelemetryGraph.innerHTML = "<div class=\"chart-fallback\">Apache ECharts unavailable. Telemetry still records in the final report.</div>";
    return;
  }
  if (!state.telemetryChart) state.telemetryChart = echarts.init(els.runTelemetryGraph, null, { renderer: "canvas" });
  const pct = Math.round(progress * 100);
  const rows = [
    { name: "Agents", value: pct, label: `${activeAgents}/${telemetry.activeAgents || 0}`, color: crt.green },
    { name: "LOC", value: pct, label: formatNumber(locProcessed), color: crt.cyan },
    { name: "Tokens", value: pct, label: formatNumber(estimatedTokens), color: crt.ink },
  ];
  state.telemetryChart.setOption({
    backgroundColor: "transparent",
    color: [crt.green, crt.cyan, crt.amber],
    animation: true,
    animationDuration: 340,
    animationDelay: (idx) => idx * 70,
    animationDurationUpdate: 240,
    animationDelayUpdate: (idx) => idx * 34,
    animationEasingUpdate: "quarticOut",
    textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line" },
      formatter: () => [
        `Active agents: ${activeAgents}/${telemetry.activeAgents || 0}`,
        `LOC processed: ${formatNumber(locProcessed)}`,
        `Est. tokens: ${formatNumber(estimatedTokens)}`,
        String(telemetry.tokenProvenance || ""),
      ].join("<br>"),
      backgroundColor: crt.bg,
      borderColor: crt.green,
      textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    },
    grid: { left: 54, right: 26, top: 22, bottom: 42 },
    xAxis: {
      type: "category",
      data: rows.map((row) => row.name),
      axisLine: { lineStyle: { color: crt.line } },
      axisTick: { show: false },
      axisLabel: { color: crt.ink, fontSize: 15, fontWeight: 800 },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: 100,
      axisLine: { lineStyle: { color: crt.line } },
      splitLine: { lineStyle: { color: "rgba(57,255,20,0.08)" } },
      axisLabel: { show: false },
    },
    series: [
      {
        type: "bar",
        data: rows.map((row) => ({ value: row.value, labelText: row.label, itemStyle: { color: row.color } })),
        barWidth: 42,
        showBackground: true,
        backgroundStyle: { color: "rgba(57, 255, 20, 0.07)" },
        itemStyle: {
          borderColor: crt.ink,
          borderWidth: 1,
          shadowBlur: 14,
          shadowColor: "rgba(57, 255, 20, 0.34)",
        },
        label: {
          show: true,
          position: "top",
          color: crt.ink,
          fontFamily: "Consolas, monospace",
          fontSize: 20,
          fontWeight: 800,
          formatter: (params) => params.data.labelText,
        },
      },
    ],
  });
}

function tokenSpeed(totalTokens, progress = progressRatio()) {
  const total = Number(totalTokens || 0);
  if (!total || progress <= 0) return 0;
  const avgRate = total / 5.2;
  const ramp = 0.18 + Math.sin(Math.min(1, progress) * Math.PI * 0.5) * 0.82;
  const phaseWave = 1 + Math.sin((state.phase * swarmPulseSteps + state.pulseStep) * 0.92) * 0.24;
  const packetWave = 1 + Math.sin((state.loopHeat + state.pulseStep * 17) * 0.13) * 0.15;
  const verifyBoost = state.phase >= 3 ? 1.16 : 1;
  return Math.max(0, Math.round(avgRate * ramp * phaseWave * packetWave * verifyBoost));
}

function renderTokenSpeedometer(tokensPerSecond, progress = progressRatio()) {
  const fixedMode = state.mode === "find_and_fix";
  const accent = fixedMode ? crt.fixed : crt.green;
  els.tokenSpeedometer.dataset.tokensPerSecond = String(tokensPerSecond);
  els.tokenSpeedometer.dataset.mode = fixedMode ? "ponytail_fix" : "ponytail_find";
  if (!window.echarts) {
    els.tokenSpeedometer.innerHTML = `<div class="chart-fallback">${formatNumber(tokensPerSecond)} tok/sec</div>`;
    return;
  }
  if (!state.speedometerChart) state.speedometerChart = echarts.init(els.tokenSpeedometer, null, { renderer: "canvas" });
  const averageRate = Number(state.telemetry?.estimatedTokens || 0) / 5.2;
  const maxRate = Math.max(1000, Math.ceil(Math.max(averageRate * 1.75, tokensPerSecond * 1.28) / 250) * 250);
  state.speedometerChart.setOption({
    backgroundColor: "transparent",
    animation: true,
    animationDuration: 260,
    animationDurationUpdate: 180,
    textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    series: [
      {
        type: "gauge",
        min: 0,
        max: maxRate,
        startAngle: 210,
        endAngle: -30,
        radius: "94%",
        center: ["50%", "58%"],
        progress: {
          show: true,
          roundCap: true,
          width: 12,
          itemStyle: {
            color: accent,
            shadowBlur: 14,
            shadowColor: fixedMode ? "rgba(155,92,255,0.58)" : "rgba(57,255,20,0.42)",
          },
        },
        axisLine: { lineStyle: { width: 12, color: [[1, "rgba(57,255,20,0.1)"]] } },
        splitLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        pointer: {
          show: true,
          length: "58%",
          width: 5,
          itemStyle: { color: accent },
        },
        anchor: {
          show: true,
          showAbove: true,
          size: 8,
          itemStyle: { color: accent, borderColor: crt.ink, borderWidth: 1 },
        },
        detail: {
          valueAnimation: true,
          formatter: () => `${formatNumber(tokensPerSecond)}\ntok/sec`,
          color: accent,
          fontFamily: "Consolas, monospace",
          fontSize: 18,
          fontWeight: 800,
          lineHeight: 22,
          offsetCenter: [0, "45%"],
        },
        title: {
          show: true,
          offsetCenter: [0, "72%"],
          color: crt.muted,
          fontFamily: "Consolas, monospace",
          fontSize: 10,
          fontWeight: 800,
        },
        data: [{ value: tokensPerSecond, name: fixedMode ? "PONYTAIL FIX" : "PONYTAIL FIND" }],
      },
    ],
  });
}

function showReport(result, mode, context) {
  state.running = false;
  setView("report");
  const summary = result?.summary || {};
  const presentation = result?.presentation || fallbackPresentation(summary);
  const html = result?.artifacts?.html?.href || result?.artifacts?.workflow?.href || "";
  els.openReport.href = html || "#";
  els.openReport.textContent = html ? "Open Report" : "No Report Artifact";
  els.reportBugCount.textContent = `${formatNumber(presentation.bugCount || 0)} issues`;
  els.reportHeadline.textContent = presentation.headline || presentation.motto || brandMotto;
  const target = context?.target || state.target || selectedProjectTarget();
  const metrics = target?.selected
    ? [{ label: "Target", value: target.name, tone: "normal" }, ...(presentation.metrics || [])]
    : presentation.metrics || [];
  els.reportSummary.innerHTML = primaryReportMetrics(metrics).map((metric) => `
    <article class="${escapeHtml(metric.tone || "")}">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(displayMetricValue(metric.value))}</strong>
    </article>
  `).join("");
  renderReportGraph(presentation);
  renderReportAssembly(presentation);
  renderOverview(presentation);
  renderEvidence(presentation.truthLedger || {});
  renderCategories(presentation.categories || []);
  renderFindings(presentation.findings || []);
  renderFixedBugs(presentation.fixedBugs || []);
  const targetLine = target?.localPath
    ? `Target folder: ${target.name}\nTarget path: ${target.localPath}\nScan source: local server filesystem\n\n`
    : "";
  els.agentSummary.value = `${targetLine}${presentation.agentSummary || `BugLab Agent Summary\n${brandMotto}\n\nNo report summary was generated.`}`;
  if (mode === "guided" && context.issue) {
    const note = document.createElement("p");
    note.className = "guided-note";
    note.textContent = `Guided by: ${context.issue}`;
    els.categoriesPanel.prepend(note);
  }
  activateReportTab("overview");
}

function showError(error) {
  setView("report");
  els.openReport.href = "#";
  els.openReport.textContent = "No Report Artifact";
  const message = error instanceof Error ? error.message : String(error);
  els.reportBugCount.textContent = "error";
  els.reportHeadline.textContent = "The hunt failed before BugLab could build a report.";
  els.reportSummary.innerHTML = `<article class="error-card"><span>Hunt failed</span><strong>${escapeHtml(message)}</strong></article>`;
  els.overviewPanel.innerHTML = `<p class="empty-note">No report overview is available because the hunt failed.</p>`;
  els.evidencePanel.innerHTML = "";
  els.categoriesPanel.innerHTML = "";
  els.findingsPanel.innerHTML = "";
  els.fixedPanel.innerHTML = "";
  els.reportReplayGraph.innerHTML = "";
  els.agentSummary.value = `BugLab Agent Summary\nHunt failed: ${message}`;
  activateReportTab("agent");
}

function renderEvidence(truthLedger) {
  const summary = truthLedger.summary || {};
  const entries = truthLedger.entries || [];
  const metrics = [
    ["Confirmed", summary.confirmed ?? 0, "confirmed"],
    ["Suspected", summary.suspected ?? 0, "suspected"],
    ["Fixed", summary.fixed ?? 0, "fixed"],
    ["False +", summary.false_positive ?? 0, "false"],
    ["False -", summary.false_negative ?? 0, "false"],
    ["Precision", displayMetricValue(rateLike(summary.precision)), "score"],
    ["Recall", displayMetricValue(rateLike(summary.recall)), "score"],
    ["F1", displayMetricValue(rateLike(summary.f1)), "score"],
  ];
  const metricHtml = metrics.map(([label, value, tone]) => `
    <article class="truth-metric ${escapeHtml(tone)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(displayMetricValue(value))}</strong>
    </article>
  `).join("");
  const cards = entries.map((entry) => evidenceCard(entry)).join("");
  els.evidencePanel.innerHTML = `
    <div class="truth-ledger">
      <div class="truth-metric-grid">${metricHtml}</div>
      ${cards || "<p class=\"empty-note\">No evidence cards were attached to this run.</p>"}
    </div>
  `;
}

function evidenceCard(entry) {
  const status = normalizeTruthStatus(entry.status);
  const signals = entry.signals || [];
  const steps = entry.reproductionSteps || [];
  return `
    <article class="evidence-card ${escapeHtml(status)}">
      <div class="evidence-card-top">
        <span>${escapeHtml(entry.id || "evidence")}</span>
        <strong>${escapeHtml(statusLabel(status))}</strong>
      </div>
      <h3>${escapeHtml(entry.claim || "Evidence packet")}</h3>
      <dl>
        <div><dt>Outcome</dt><dd>${escapeHtml(entry.outcome || "unscored")}</dd></div>
        <div><dt>Oracle</dt><dd>${escapeHtml(entry.oracleType || "none")} / ${escapeHtml(entry.oracleVerdict || "unverified")}</dd></div>
        <div><dt>Confidence</dt><dd>${escapeHtml(entry.confidence ?? "--")}</dd></div>
        <div><dt>Tokens</dt><dd>${escapeHtml(formatNumber(entry.tokens || 0))}</dd></div>
      </dl>
      ${entry.command ? `<p class="evidence-command"><b>Command:</b> ${escapeHtml(entry.command)}</p>` : ""}
      <div class="evidence-columns">
        <div>
          <h4>Reproduce</h4>
          <ol>${steps.length ? steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("") : "<li>Open the linked artifact and verify manually.</li>"}</ol>
        </div>
        <div>
          <h4>Signals</h4>
          <ul>${signals.length ? signals.map((signal) => `<li>${escapeHtml(signal)}</li>`).join("") : "<li>No signal tail attached.</li>"}</ul>
        </div>
      </div>
      ${entry.oracleNote ? `<p class="oracle-note">${escapeHtml(entry.oracleNote)}</p>` : ""}
      ${entry.artifactHref ? `<a href="${escapeAttr(entry.artifactHref)}" target="_blank" rel="noreferrer">Open evidence artifact</a>` : ""}
    </article>
  `;
}

function renderReportGraph(presentation) {
  const rows = [...(presentation.chart?.series || [])].filter((item) => Number(item.value) > 0);
  els.reportGraphLabel.textContent = `${rows.length} categories`;
  if (!window.echarts) {
    els.reportGraph.innerHTML = "<div class=\"chart-fallback\">Apache ECharts unavailable. Category counts are listed below.</div>";
    return;
  }
  if (!state.reportChart) state.reportChart = echarts.init(els.reportGraph, null, { renderer: "canvas" });
  const ordered = rows.sort((a, b) => Number(a.value) - Number(b.value));
  state.reportChart.setOption({
    backgroundColor: "transparent",
    color: [crt.amber, "#ff8a1f", crt.red],
    animation: true,
    animationDuration: 900,
    animationEasing: "quarticOut",
    animationEasingUpdate: "quarticOut",
    textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: crt.bg,
      borderColor: crt.green,
      textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    },
    grid: { left: 178, right: 58, top: 18, bottom: 28 },
    xAxis: {
      type: "value",
      axisLine: { lineStyle: { color: crt.line } },
      splitLine: { lineStyle: { color: "rgba(57,255,20,0.1)" } },
      axisLabel: { color: crt.muted, fontSize: 13, fontWeight: 800 },
    },
    yAxis: {
      type: "category",
      data: ordered.map((item) => item.name),
      axisLine: { lineStyle: { color: crt.line } },
      axisTick: { show: false },
      axisLabel: { color: crt.ink, width: 160, overflow: "truncate", fontSize: 15, fontWeight: 800 },
    },
    series: [
      {
        name: "Issues",
        type: "bar",
        animationDelay: (idx) => idx * 115,
        animationDelayUpdate: (idx) => idx * 70,
        data: ordered.map((item) => ({
          value: Number(item.value),
          itemStyle: { color: issueSeverityColor(item.value) },
        })),
        barMaxWidth: 36,
        showBackground: true,
        backgroundStyle: { color: "rgba(57, 255, 20, 0.055)" },
        itemStyle: {
          borderColor: crt.ink,
          borderWidth: 1,
          shadowBlur: 14,
          shadowColor: "rgba(255, 52, 52, 0.42)",
        },
        label: {
          show: true,
          position: "right",
          color: crt.ink,
          fontFamily: "Consolas, monospace",
          fontSize: 16,
          fontWeight: 800,
        },
      },
    ],
  });
  window.setTimeout(() => state.reportChart?.resize(), 0);
}

function renderReportAssembly(presentation) {
  const telemetry = presentation.telemetry || {};
  const bugCount = Number(presentation.bugCount || 0);
  const activeCategories = (presentation.categories || []).filter((category) => Number(category.count) > 0).length;
  els.reportReplayGraph.dataset.bugCount = String(bugCount);
  els.reportReplayGraph.dataset.activeCategories = String(activeCategories);
  if (!window.echarts) {
    els.reportReplayGraph.innerHTML = "<div class=\"chart-fallback\">Report assembly: evidence, cluster, severity, fix queue, agent copy.</div>";
    return;
  }
  if (!state.reportReplayChart) state.reportReplayChart = echarts.init(els.reportReplayGraph, null, { renderer: "canvas" });
  const box = els.reportReplayGraph.getBoundingClientRect();
  const width = Math.max(520, box.width || 760);
  const height = Math.max(72, box.height || 92);
  const fixedMode = presentation.mode === "find_and_fix";
  const stages = [
    { id: "evidence", label: "Evidence", value: Number(telemetry.fileCount || 0), color: crt.green },
    { id: "cluster", label: "Cluster", value: activeCategories, color: crt.cyan },
    { id: "severity", label: "Severity", value: bugCount, color: issueSeverityColor(bugCount) },
    { id: "queue", label: "Fix Queue", value: Math.min(8, (presentation.findings || []).length), color: fixedMode ? crt.fixed : crt.amber },
    { id: "copy", label: fixedMode ? "Verified" : "Agent Copy", value: Number(telemetry.estimatedTokens || telemetry.bugHuntTokens || 0), color: fixedMode ? crt.fixed : crt.ink },
  ];
  const nodes = stages.map((stage, index) => {
    const hot = stage.id === "severity" && bugCount > 0;
    const fixed = fixedMode && ["queue", "copy"].includes(stage.id);
    return {
      id: stage.id,
      name: `${stage.label}\n${shortMetric(stage.value)}`,
      x: width * (0.08 + index * 0.21),
      y: height * 0.44,
      fixed: true,
      symbolSize: hot || fixed ? 30 : 24,
      itemStyle: {
        color: stage.color,
        borderColor: fixed ? "#dac8ff" : hot ? crt.red : crt.ink,
        borderWidth: hot || fixed ? 3 : 1,
        shadowBlur: hot || fixed ? 18 : 10,
        shadowColor: fixed ? "rgba(155,92,255,0.62)" : hot ? "rgba(255,52,52,0.55)" : "rgba(57,255,20,0.28)",
      },
      label: {
        color: fixed ? crt.fixed : hot ? crt.red : crt.ink,
        fontFamily: "Consolas, monospace",
        fontSize: 11,
        fontWeight: 800,
        lineHeight: 13,
        textBorderColor: crt.bg,
        textBorderWidth: 3,
      },
    };
  });
  const links = stages.slice(0, -1).map((stage, index) => {
    const next = stages[index + 1];
    const hot = next.id === "severity" && bugCount > 0;
    const fixed = fixedMode && ["queue", "copy"].includes(next.id);
    return {
      source: stage.id,
      target: next.id,
      lineStyle: {
        color: fixed ? crt.fixed : hot ? crt.red : crt.green,
        width: hot || fixed ? 3 : 2,
        opacity: 0.86,
        curveness: 0.08,
        type: hot ? "dashed" : "solid",
        shadowBlur: hot || fixed ? 14 : 8,
        shadowColor: fixed ? "rgba(155,92,255,0.54)" : hot ? "rgba(255,52,52,0.5)" : "rgba(57,255,20,0.28)",
      },
    };
  });
  state.reportReplayChart.setOption({
    backgroundColor: "transparent",
    animation: true,
    animationDuration: 760,
    animationDelay: (idx) => idx * 130,
    animationDurationUpdate: 480,
    animationDelayUpdate: (idx) => idx * 70,
    animationEasing: "quarticOut",
    textStyle: { color: crt.ink, fontFamily: "Consolas, monospace" },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: false,
        data: nodes,
        links,
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: [0, 8],
        label: {
          show: true,
          position: "bottom",
          formatter: "{b}",
          fontFamily: "Consolas, monospace",
          lineHeight: 13,
          textBorderColor: crt.bg,
          textBorderWidth: 3,
        },
        lineStyle: { color: crt.green },
        emphasis: { disabled: true },
      },
    ],
  });
  window.setTimeout(() => state.reportReplayChart?.resize(), 0);
}

function renderOverview(presentation) {
  const categories = [...(presentation.categories || [])].sort((a, b) => Number(b.count) - Number(a.count));
  const findings = presentation.findings || [];
  const active = categories.filter((category) => Number(category.count) > 0);
  const leader = active[0];
  const bugCount = Number(presentation.bugCount || 0);
  const nextActions = findings.slice(0, 3);
  const topCategories = active.slice(0, 4);
  const leaderText = leader
    ? `${leader.label} is the largest bucket with ${formatNumber(leader.count)} issue signals.`
    : "No category has active issue signals.";
  const severity = priorityLabel(bugCount, active.length);
  els.overviewPanel.innerHTML = `
    <div class="overview-grid">
      <article class="overview-card priority">
        <span class="overview-kicker">30k view</span>
        <strong class="overview-value">${escapeHtml(formatNumber(bugCount))} issues</strong>
        <h3>${escapeHtml(severity)}</h3>
        <p>${escapeHtml(presentation.headline || "BugLab finished the hunt.")}</p>
        <p>${escapeHtml(leaderText)}</p>
      </article>
      <article class="overview-card">
        <span class="overview-kicker">Human read</span>
        <h3>Where to spend attention</h3>
        <p>${escapeHtml(overallImpact(active, findings))}</p>
      </article>
      <div class="overview-list">
        <h3>Top Categories</h3>
        <ol>
          ${topCategories.length ? topCategories.map((category) => `
            <li>
              <strong>${escapeHtml(category.label)}</strong>
              <span>${escapeHtml(formatNumber(category.count))}</span>
            </li>
          `).join("") : "<li><strong>No active categories</strong><span>0</span></li>"}
        </ol>
      </div>
      <div class="overview-list">
        <h3>Next Actions</h3>
        <ol>
          ${nextActions.length ? nextActions.map((finding) => `
            <li>
              <strong>${escapeHtml(finding.nextStep || finding.title || "Verify linked evidence.")}</strong>
              <span>${escapeHtml(finding.severity || "info")}</span>
            </li>
          `).join("") : "<li><strong>No follow-up actions were generated.</strong><span>info</span></li>"}
        </ol>
      </div>
    </div>
  `;
}

function renderCategories(categories) {
  if (!categories.length) {
    els.categoriesPanel.innerHTML = "<p class=\"empty-note\">No issue categories were reported.</p>";
    return;
  }
  els.categoriesPanel.innerHTML = categories.map((category) => {
    const severity = severityForCount(category.count);
    return `
    <details class="category-detail ${escapeHtml(severity)}" ${Number(category.count) > 0 ? "open" : ""}>
      <summary>
        <span>${escapeHtml(category.label)}</span>
        <strong>${escapeHtml(category.count)} issues</strong>
      </summary>
      <dl>
        <div><dt>Priority</dt><dd>${escapeHtml(category.priority || severity)}</dd></div>
        <div><dt>Status</dt><dd>${escapeHtml(category.status || "unknown")}</dd></div>
        <div><dt>Recall</dt><dd>${escapeHtml(category.recall || "--")}</dd></div>
        <div><dt>Signals</dt><dd>${escapeHtml(category.signals ?? "--")}</dd></div>
      </dl>
      <p>${escapeHtml(category.detail || "")}</p>
      ${category.artifactHref ? `<a href="${escapeAttr(category.artifactHref)}" target="_blank" rel="noreferrer">Open category JSON</a>` : ""}
    </details>
  `;
  }).join("");
}

function renderFindings(findings) {
  if (!findings.length) {
    els.findingsPanel.innerHTML = "<p class=\"empty-note\">No findings were available for drill-down.</p>";
    return;
  }
  els.findingsPanel.innerHTML = findings.map((finding) => {
    const severity = normalizeSeverity(finding.severity);
    return `
    <article class="finding-card ${escapeHtml(severity)}">
      <div>
        <span>${escapeHtml(finding.category || "Finding")}</span>
        <strong>${escapeHtml(finding.title || "Untitled finding")}</strong>
      </div>
      <p>${escapeHtml(finding.evidence || "")}</p>
      <p><b>Next:</b> ${escapeHtml(finding.nextStep || "Verify the linked evidence.")}</p>
    </article>
  `;
  }).join("");
}

function renderFixedBugs(fixedBugs) {
  if (!fixedBugs.length) {
    els.fixedPanel.innerHTML = "<p class=\"empty-note\">No verified fixed-bug shortlist was produced in this run.</p>";
    return;
  }
  els.fixedPanel.innerHTML = `
    <div class="fixed-bug-list">
      ${fixedBugs.map((item) => `
        <article class="fixed-bug-card">
          <div>
            <span>${escapeHtml(item.category || "Fixed bug")}</span>
            <strong>${escapeHtml(item.title || "Verified repair")}</strong>
          </div>
          <dl>
            <div><dt>Before</dt><dd>${escapeHtml(item.before ?? "--")}</dd></div>
            <div><dt>After</dt><dd>${escapeHtml(item.after ?? "--")}</dd></div>
            <div><dt>Fixed</dt><dd>${escapeHtml(item.fixedCount ?? "--")}</dd></div>
            <div><dt>Success</dt><dd>${escapeHtml(item.repairSuccessRate || "--")}</dd></div>
          </dl>
          <p>${escapeHtml(item.evidence || "Repair verification cleared this item.")}</p>
          ${item.artifactHref ? `<a href="${escapeAttr(item.artifactHref)}" target="_blank" rel="noreferrer">Open repair JSON</a>` : ""}
        </article>
      `).join("")}
    </div>
  `;
}

function activateReportTab(tabName) {
  els.reportTabs.forEach((tab) => {
    const active = tab.dataset.reportTab === tabName;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  els.reportPanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.reportPanel === tabName));
}

function fallbackPresentation(summary) {
  const signals = summary.total_found_bugs ?? summary.total_unique_signals ?? summary.total_signals ?? 0;
  return {
    bugCount: Number(signals) || 0,
    headline: `${signals || 0} issue signals found. ${brandMotto}`,
    motto: brandMotto,
    metrics: [
      { label: "Issues Found", value: signals || 0, tone: "hot" },
      { label: "Runs", value: summary.runs ?? summary.fixtures ?? "--" },
      { label: "Recall", value: summary.avg_expected_class_recall ?? summary.sector_pass_rate ?? "--" },
    ],
    categories: [{ label: "Uncategorized", count: Number(signals) || 0, status: "unknown", recall: "--", signals, detail: "Raw summary did not include category rows." }],
    findings: [],
    fixedBugs: [],
    truthLedger: {
      summary: { entries: 0, confirmed: 0, suspected: 0, fixed: 0, false_positive: 0, false_negative: 0 },
      entries: [],
    },
    chart: { series: [{ name: "Uncategorized", value: Number(signals) || 0 }] },
    agentSummary: `BugLab Agent Summary\n${brandMotto}\n\nOverall: found ${signals || 0} issue signals.`,
  };
}

function primaryReportMetrics(metrics) {
  const order = [
    "Target",
    "Issues Found",
    "Confirmed Evidence",
    "False Positives",
    "False Negatives",
    "Precision",
    "Fixed Bugs",
    "Repair Pass",
    "Active Agents",
    "LOC Processed",
    "Avg Tok/sec",
    "Bug Hunt Tokens",
    "Repair Crew Tokens",
    "Tokens Processed",
  ];
  const byLabel = new Map(metrics.map((metric) => [metric.label, metric]));
  const selected = order.map((label) => byLabel.get(label)).filter(Boolean);
  const selectedLabels = new Set(selected.map((metric) => metric.label));
  const remaining = metrics.filter((metric) => !selectedLabels.has(metric.label));
  return [...selected, ...remaining].slice(0, 8);
}

function priorityLabel(bugCount, activeCategories) {
  if (bugCount >= 20 || activeCategories >= 4) return "High-review sweep";
  if (bugCount >= 5 || activeCategories >= 2) return "Focused fix pass";
  if (bugCount > 0) return "Small cleanup pass";
  return "Clean run";
}

function overallImpact(categories, findings) {
  if (!categories.length) return "The hunt did not produce active bug buckets. Keep the report artifact for traceability and rerun after code changes.";
  const top = categories[0];
  const next = findings[0]?.nextStep || "Open the category details and verify the highest-signal evidence first.";
  return `${top.label} is the first place to look because it owns the largest share of signals. Start with: ${next}`;
}

function severityForCount(count) {
  const value = Number(count) || 0;
  if (value >= 10) return "high";
  if (value >= 4) return "medium";
  if (value > 0) return "low";
  return "info";
}

function normalizeSeverity(value) {
  const severity = String(value || "info").toLowerCase();
  if (["high", "critical", "error", "hot"].includes(severity)) return "high";
  if (["medium", "warning", "warn"].includes(severity)) return "medium";
  if (["low", "minor"].includes(severity)) return "low";
  return "info";
}

function issueSeverityColor(countOrSeverity) {
  const severity = Number.isFinite(Number(countOrSeverity))
    ? severityForCount(countOrSeverity)
    : normalizeSeverity(countOrSeverity);
  return {
    high: crt.red,
    medium: "#ff8a1f",
    low: "#ffe45c",
    info: crt.green,
  }[severity] || crt.green;
}

const swarmAnchors = {
  project: [48, 52],
  planner: [22, 22],
  runner: [20, 76],
  visual: [76, 24],
  logs: [80, 74],
  report: [50, 90],
};

function swarmPulseNodes(source, evidenceX, evidenceY, bugPulse = false, rateLabel = "") {
  const sourcePoint = swarmAnchors[source] || swarmAnchors.project;
  const projectPoint = swarmAnchors.project;
  const path = [
    [sourcePoint[0], sourcePoint[1]],
    [evidenceX, evidenceY],
    [projectPoint[0], projectPoint[1]],
  ];
  const pulse = state.pulseStep / swarmPulseSteps;
  return [0, 1, 2].map((offset) => {
    const t = (pulse + offset * 0.16) % 1;
    const segment = t < 0.5 ? 0 : 1;
    const localT = segment === 0 ? t / 0.5 : (t - 0.5) / 0.5;
    const from = path[segment];
    const to = path[segment + 1];
    const x = from[0] + (to[0] - from[0]) * localT;
    const y = from[1] + (to[1] - from[1]) * localT;
    return pulseNode(`pulse-${source}-${offset}`, x, y, bugPulse, 18 - offset * 4, rateLabel);
  });
}

function pulseNode(id, x, y, bugPulse, symbolSize, rateLabel = "") {
  const box = els.swarmGraph?.getBoundingClientRect?.();
  const width = Math.max(640, box?.width || 820);
  const height = Math.max(280, box?.height || 420);
  return {
    id,
    name: "",
    symbolSize,
    category: 3,
    x: (width * x) / 100,
    y: (height * y) / 100,
    fixed: true,
    label: {
      show: Boolean(rateLabel),
      formatter: rateLabel,
      position: "top",
      distance: 5,
      color: bugPulse ? crt.red : crt.ink,
      fontFamily: "Consolas, monospace",
      fontSize: 11,
      fontWeight: 800,
      textBorderColor: crt.bg,
      textBorderWidth: 3,
    },
    tooltip: { show: false },
    itemStyle: {
      color: bugPulse ? crt.red : crt.green,
      borderColor: bugPulse ? crt.red : crt.green,
      borderWidth: 0,
      opacity: 0.86,
      shadowBlur: 18,
      shadowColor: bugPulse ? "rgba(255, 52, 52, 0.56)" : "rgba(57, 255, 20, 0.5)",
    },
  };
}

function tokenRateLabel(source) {
  const telemetry = state.telemetry || {};
  const totalTokens = Number(telemetry.estimatedTokens || 0);
  const activeAgents = Math.max(1, Number(telemetry.activeAgents || 1));
  const sourceWeights = {
    planner: 1.08,
    runner: 1.24,
    visual: 0.96,
    logs: 0.88,
    project: 0.74,
    report: 1.16,
  };
  const pulseJitter = 0.92 + (state.pulseStep % 4) * 0.045;
  const baseRate = totalTokens / 5.2 / activeAgents;
  const rate = Math.round(baseRate * (sourceWeights[source] || 1) * pulseJitter);
  return `${formatNumber(rate)} tok/s`;
}

function node(id, name, symbolSize, category, x, y) {
  const colors = [crt.green, crt.cyan, "#9cff9c", "#d8ffd8"];
  const bugNode = id === "bug";
  const active = category === 3 && !bugNode;
  const pulseBoost = active ? 6 + (state.pulseStep % 2) * 3 : 0;
  const box = els.swarmGraph?.getBoundingClientRect?.();
  const width = Math.max(640, box?.width || 820);
  const height = Math.max(280, box?.height || 420);
  return {
    id,
    name,
    symbolSize: symbolSize + pulseBoost,
    category,
    x: x <= 100 ? (width * x) / 100 : x,
    y: y <= 100 ? (height * y) / 100 : y,
    fixed: true,
    itemStyle: {
      color: bugNode ? crt.red : colors[category] || crt.green,
      borderColor: bugNode ? crt.red : crt.ink,
      borderWidth: active || bugNode ? 3 : 2,
      shadowBlur: active || bugNode ? 24 : 10,
      shadowColor: bugNode
        ? "rgba(255, 52, 52, 0.62)"
        : active
          ? "rgba(201, 255, 208, 0.48)"
          : "rgba(57, 255, 20, 0.28)",
    },
  };
}

function edge(source, target, active = false) {
  const bugEdge = source === "bug" || target === "bug";
  return {
    source,
    target,
    lineStyle: active
      ? {
          color: bugEdge ? crt.red : crt.green,
          opacity: 0.95,
          width: 3.4,
          type: "dashed",
          shadowBlur: 14,
          shadowColor: bugEdge ? "rgba(255, 52, 52, 0.58)" : "rgba(57, 255, 20, 0.4)",
        }
      : undefined,
  };
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value) || 0);
}

function formatSignedNumber(value) {
  const number = Number(value) || 0;
  return `${number > 0 ? "+" : ""}${formatNumber(number)}`;
}

function displayMetricValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (typeof value === "number") return formatNumber(value);
  const text = String(value);
  if (text.endsWith("%")) return text;
  const numeric = Number(text);
  return Number.isFinite(numeric) && text.trim() !== "" ? formatNumber(numeric) : text;
}

function rateLike(value) {
  if (value === null || value === undefined || value === "") return "--";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  if (numeric >= 0 && numeric <= 1) return `${Math.round(numeric * 100)}%`;
  return numeric;
}

function shortMetric(value) {
  const number = Number(value) || 0;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${Math.round(number / 1_000)}K`;
  return formatNumber(number);
}

function normalizeTruthStatus(status) {
  const value = String(status || "suspected").toLowerCase().replaceAll(" ", "_");
  if (["confirmed", "fixed", "clean", "false_positive", "false_negative", "invalid_oracle", "planned"].includes(value)) return value;
  return "suspected";
}

function statusLabel(status) {
  return {
    confirmed: "confirmed",
    fixed: "fixed",
    clean: "clean",
    false_positive: "false +",
    false_negative: "false -",
    invalid_oracle: "invalid oracle",
    planned: "planned",
    suspected: "suspected",
  }[status] || "suspected";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

els.huntFull.addEventListener("click", () => startHunt("full"));
els.findAndFix.addEventListener("click", () => startHunt("find_fix"));
els.describeIssue.addEventListener("click", () => {
  setView("issue");
});
els.backToIntro.addEventListener("click", () => setView("intro"));
els.issueFiles.addEventListener("change", renderFileList);
els.issueForm.addEventListener("submit", (event) => {
  event.preventDefault();
  startHunt("guided", { issue: els.issueText.value.trim(), files: selectedFiles(), target: selectedProjectTarget() });
});
els.targetPath?.addEventListener("input", renderProjectTarget);
els.targetApply?.addEventListener("click", async () => {
  const target = selectedProjectTarget();
  const pendingHunt = state.pendingHunt;
  state.target = target;
  setStatus(target.localPath ? "Target set" : "Select target", target.localPath ? "" : "error");
  renderProjectTarget();
  if (!target.localPath) {
    els.targetMeta.textContent = "Enter a local project path before starting BugLab.";
    els.targetPath?.focus();
  } else {
    const originalLabel = els.targetApply.textContent;
    els.targetApply.disabled = true;
    els.targetApply.textContent = "Checking Target";
    els.targetMeta.textContent = "Checking target path on the local server...";
    try {
      const validatedTarget = await validateTarget(target);
      if (validatedTarget.localPath && els.targetPath) els.targetPath.value = validatedTarget.localPath;
      state.target = validatedTarget;
      renderProjectTarget();
      setStatus("Target set");
      if (pendingHunt) state.pendingHunt = pendingHunt;
      els.targetApply.textContent = originalLabel;
      els.targetApply.disabled = false;
      closeTargetDialog();
      if (pendingHunt) startHunt(pendingHunt.mode, { ...pendingHunt.context, target: validatedTarget });
    } catch (error) {
      els.targetApply.disabled = false;
      els.targetApply.textContent = originalLabel;
      els.targetMeta.textContent = error.message || "Target path could not be loaded.";
      setStatus("Target error", "error");
      els.targetPath?.focus();
    }
  }
});
els.closeTarget?.addEventListener("click", closeTargetDialog);
els.targetDialog?.addEventListener("click", (event) => {
  if (event.target instanceof HTMLElement && event.target.hasAttribute("data-close-target")) closeTargetDialog();
});
els.infoButton?.addEventListener("click", openInfoDialog);
els.closeInfo?.addEventListener("click", closeInfoDialog);
els.infoDialog?.addEventListener("click", (event) => {
  if (event.target instanceof HTMLElement && event.target.hasAttribute("data-close-info")) closeInfoDialog();
});
els.reportTabs.forEach((tab) => tab.addEventListener("click", () => activateReportTab(tab.dataset.reportTab)));
els.copyAgentSummary.addEventListener("click", async () => {
  const text = els.agentSummary.value;
  els.agentSummary.focus();
  els.agentSummary.select();
  try {
    await navigator.clipboard.writeText(text);
    els.copyAgentSummary.textContent = "Copied";
  } catch {
    const copied = document.execCommand("copy");
    els.copyAgentSummary.textContent = copied ? "Copied" : "Selected";
  }
  window.setTimeout(() => (els.copyAgentSummary.textContent = "Copy"), 1200);
});
els.newHunt.addEventListener("click", () => {
  state.running = false;
  setStatus("Ready");
  setView("intro");
});
window.addEventListener("resize", () => {
  state.chart?.resize();
  state.telemetryChart?.resize();
  state.speedometerChart?.resize();
  state.feedbackLoopChart?.resize();
  state.reportChart?.resize();
  state.reportReplayChart?.resize();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.infoDialog?.hidden) closeInfoDialog();
  if (event.key === "Escape" && !els.targetDialog?.hidden) closeTargetDialog();
});

setView("intro");
setStatus("Ready");
renderProjectTarget();
