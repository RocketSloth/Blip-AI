// clawup wizard — client-side state machine
(() => {
  "use strict";

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------

  const STEPS = ["welcome", "profile", "provider", "keys", "review", "install", "done"];

  const state = {
    current: "welcome",
    showAdvanced: false,
    profile: null,        // { id, title, ... }
    provider: null,       // { id, title, ... }
    channelEnv: [],       // list of env var names needed by channel
    envValues: {},        // { ENV_NAME: value }
    installService: true, // set from profile default
    plan: null,           // from /api/plan
    jobId: null,
    stepEls: [],          // DOM <li> per install step
  };

  // ------------------------------------------------------------------
  // DOM helpers
  // ------------------------------------------------------------------

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function render(templateId) {
    const tpl = $(`#${templateId}`);
    const stage = $("#stage");
    stage.innerHTML = "";
    stage.appendChild(tpl.content.cloneNode(true));
    updateProgressDots();
    wireActionButtons();
  }

  function updateProgressDots() {
    const idx = STEPS.indexOf(state.current);
    $$("#progress-dots .dot").forEach((dot, i) => {
      dot.classList.toggle("active", i === idx);
      dot.classList.toggle("done", i < idx);
    });
  }

  function wireActionButtons() {
    $$("[data-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const action = e.currentTarget.dataset.action;
        handleAction(action);
      });
    });
  }

  function goTo(screen) {
    state.current = screen;
    render(`tpl-${screen}`);
  }

  // ------------------------------------------------------------------
  // API wrappers
  // ------------------------------------------------------------------

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    return res.json();
  }

  // ------------------------------------------------------------------
  // Action router
  // ------------------------------------------------------------------

  async function handleAction(action) {
    switch (action) {
      case "next":
      case "advanced":
        state.showAdvanced = action === "advanced";
        goTo("profile");
        await renderProfiles();
        break;

      case "back":
        goBack();
        break;

      case "review":
        if (!collectKeys()) return;
        goTo("review");
        await renderReview();
        break;

      case "install":
        await startInstall();
        break;

      case "finish":
        await finish();
        break;

      case "restart":
        Object.assign(state, {
          current: "welcome",
          profile: null,
          provider: null,
          channelEnv: [],
          envValues: {},
          jobId: null,
          plan: null,
        });
        goTo("welcome");
        break;
    }
  }

  function goBack() {
    const order = ["welcome", "profile", "provider", "keys", "review"];
    const idx = order.indexOf(state.current);
    if (idx > 0) {
      const prev = order[idx - 1];
      goTo(prev);
      if (prev === "profile") renderProfiles();
      if (prev === "provider") renderProviders();
      if (prev === "keys") renderKeys();
    }
  }

  // ------------------------------------------------------------------
  // Profile screen
  // ------------------------------------------------------------------

  async function renderProfiles() {
    const profiles = await api("/api/profiles");
    const container = $("#profile-cards");
    container.innerHTML = "";

    for (const p of profiles) {
      if (p.advanced && !state.showAdvanced) continue;
      const card = document.createElement("button");
      card.className = "card" + (p.advanced ? " advanced" : "");
      card.innerHTML = `
        <div class="card-icon">${p.icon}</div>
        <div class="card-body">
          <h3 class="card-title">${escapeHtml(p.title)}</h3>
          <p class="card-blurb">${escapeHtml(p.blurb)}</p>
        </div>
        <div class="card-chev">→</div>
      `;
      card.addEventListener("click", async () => {
        state.profile = p;
        state.installService = p.service_default;
        goTo("provider");
        await renderProviders();
      });
      container.appendChild(card);
    }
  }

  // ------------------------------------------------------------------
  // Provider screen
  // ------------------------------------------------------------------

  async function renderProviders() {
    const providers = await api(`/api/providers?profile=${encodeURIComponent(state.profile.id)}`);
    const container = $("#provider-cards");
    container.innerHTML = "";

    for (const pr of providers) {
      const card = document.createElement("button");
      card.className = "card";
      card.innerHTML = `
        <div class="card-icon">${providerIcon(pr.id)}</div>
        <div class="card-body">
          <h3 class="card-title">${escapeHtml(pr.title)}</h3>
          <p class="card-blurb">${escapeHtml(pr.blurb)}</p>
        </div>
        <div class="card-chev">→</div>
      `;
      card.addEventListener("click", async () => {
        state.provider = pr;
        goTo("keys");
        await renderKeys();
      });
      container.appendChild(card);
    }
  }

  function providerIcon(id) {
    return { openai: "🤖", anthropic: "🎭", openrouter: "🔀", local: "🏠" }[id] || "✨";
  }

  // ------------------------------------------------------------------
  // Keys screen
  // ------------------------------------------------------------------

  async function renderKeys() {
    // Figure out which env vars are needed
    const required = [...(state.provider.required_env || [])];
    let channelSteps = [];
    const chInfo = await api(`/api/channel-env?profile=${encodeURIComponent(state.profile.id)}`);
    channelSteps = chInfo.steps || [];
    for (const name of chInfo.required_env || []) {
      if (!required.includes(name)) required.push(name);
    }
    state.channelEnv = chInfo.required_env || [];

    const fieldsHost = $("#key-fields");
    fieldsHost.innerHTML = "";

    if (required.length === 0) {
      // No keys needed — e.g. local provider
      const info = document.createElement("div");
      info.className = "system-note";
      info.textContent = "Nothing to paste! Hit Continue.";
      fieldsHost.appendChild(info);
      $("#keys-lede").textContent = "Good news — no API keys needed for this setup.";
    } else {
      $("#keys-lede").textContent = "We need a few things from you. Click each link, copy the value, paste it here.";

      for (const name of required) {
        const copy = await api(`/api/env-copy?name=${encodeURIComponent(name)}`);
        const field = buildField(name, copy);
        fieldsHost.appendChild(field);
      }
    }

    // Channel-specific extra guidance (e.g. WhatsApp pairing)
    if (channelSteps.length > 0 && state.channelEnv.length === 0) {
      const note = document.createElement("div");
      note.className = "system-note";
      note.innerHTML = "<strong>Heads up:</strong> " + escapeHtml(channelSteps[0]);
      fieldsHost.appendChild(note);
    }
  }

  function buildField(name, copy) {
    const wrap = document.createElement("div");
    wrap.className = "field";

    const label = document.createElement("label");
    label.className = "field-label";
    label.textContent = copy.label || name;
    wrap.appendChild(label);

    const help = document.createElement("div");
    help.className = "field-help";
    const helpText = copy.help || "";
    const urlMatch = helpText.match(/(https?:\/\/\S+)/);
    if (urlMatch) {
      const before = helpText.slice(0, urlMatch.index).trim();
      if (before) {
        help.appendChild(document.createTextNode(before + " "));
      }
      const link = document.createElement("a");
      link.className = "get-key-btn";
      link.href = urlMatch[1];
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open link ↗";
      help.appendChild(link);
    } else {
      help.textContent = helpText;
    }
    wrap.appendChild(help);

    const input = document.createElement("input");
    input.type = "password";
    input.name = name;
    input.placeholder = copy.placeholder || "";
    input.autocomplete = "off";
    input.spellcheck = false;
    if (state.envValues[name]) input.value = state.envValues[name];
    wrap.appendChild(input);

    return wrap;
  }

  function collectKeys() {
    const inputs = $$("#key-fields input");
    for (const inp of inputs) {
      const val = inp.value.trim();
      if (!val) {
        inp.focus();
        inp.style.borderColor = "var(--danger)";
        setTimeout(() => (inp.style.borderColor = ""), 1500);
        return false;
      }
      state.envValues[inp.name] = val;
    }
    return true;
  }

  // ------------------------------------------------------------------
  // Review screen
  // ------------------------------------------------------------------

  async function renderReview() {
    const body = {
      profile: state.profile.id,
      provider: state.provider.id,
      install_service: state.installService,
      env_vars: state.envValues,
    };

    try {
      const plan = await api("/api/plan", {
        method: "POST",
        body: JSON.stringify(body),
      });
      state.plan = plan;
      drawReview(plan);
      $("#install-btn").disabled = false;
    } catch (e) {
      $("#review-panel").innerHTML = `<p style="color:var(--danger)">Couldn't build the plan: ${escapeHtml(e.message)}</p>`;
    }
  }

  function drawReview(plan) {
    const p = $("#review-panel");
    p.innerHTML = "";

    const rows = [
      ["Where", plan.profile.title],
      ["AI service", plan.provider.title],
      ["Background service", plan.install_service ? "Yes" : "No"],
      ["Operating system", `${plan.system.os} (${plan.system.arch})`],
    ];

    for (const [label, value] of rows) {
      const row = document.createElement("div");
      row.className = "review-row";
      row.innerHTML = `<span class="review-label">${escapeHtml(label)}</span><span class="review-value">${escapeHtml(value)}</span>`;
      p.appendChild(row);
    }

    const stepsBlock = document.createElement("div");
    stepsBlock.className = "review-steps";
    stepsBlock.innerHTML = `<div class="review-steps-title">We'll do:</div><ul></ul>`;
    const ul = stepsBlock.querySelector("ul");
    for (const step of plan.steps) {
      const li = document.createElement("li");
      li.textContent = step.label;
      ul.appendChild(li);
    }
    p.appendChild(stepsBlock);

    if (plan.system.openclaw_installed) {
      const note = document.createElement("div");
      note.className = "system-note";
      note.textContent = `OpenClaw is already installed (${plan.system.openclaw_version}) — we'll just configure it.`;
      p.appendChild(note);
    }
  }

  // ------------------------------------------------------------------
  // Install screen
  // ------------------------------------------------------------------

  async function startInstall() {
    goTo("install");

    // Seed the step list from the plan we already have
    const list = $("#install-steps");
    list.innerHTML = "";
    state.stepEls = [];
    for (const step of state.plan.steps) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="step-icon"></span><span class="step-label">${escapeHtml(step.label)}</span>`;
      list.appendChild(li);
      state.stepEls.push(li);
    }

    const body = {
      profile: state.profile.id,
      provider: state.provider.id,
      install_service: state.installService,
      env_vars: state.envValues,
    };

    let start;
    try {
      start = await api("/api/start", { method: "POST", body: JSON.stringify(body) });
    } catch (e) {
      appendLog(`ERROR: ${e.message}`);
      showFailure("Couldn't start installation.", []);
      return;
    }
    state.jobId = start.job_id;

    streamEvents(state.jobId);
  }

  function streamEvents(jobId) {
    const src = new EventSource(`/api/jobs/${jobId}/events`);
    let currentIdx = -1;

    src.addEventListener("message", (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }

      switch (msg.type) {
        case "step_start":
          if (currentIdx >= 0 && state.stepEls[currentIdx] && !state.stepEls[currentIdx].classList.contains("failed")) {
            state.stepEls[currentIdx].classList.remove("active");
            state.stepEls[currentIdx].classList.add("ok");
          }
          currentIdx = msg.index;
          if (state.stepEls[currentIdx]) {
            state.stepEls[currentIdx].classList.add("active");
          }
          appendLog(`▶ ${msg.label}`);
          break;

        case "log":
          appendLog(msg.text);
          if (/FAILED/.test(msg.text) && currentIdx >= 0 && state.stepEls[currentIdx]) {
            state.stepEls[currentIdx].classList.remove("active");
            state.stepEls[currentIdx].classList.add("failed");
          }
          break;

        case "install_done":
          if (currentIdx >= 0 && state.stepEls[currentIdx] && !state.stepEls[currentIdx].classList.contains("failed")) {
            state.stepEls[currentIdx].classList.remove("active");
            state.stepEls[currentIdx].classList.add("ok");
          }
          appendLog(`\nInstalled: ${msg.succeeded}   Failed: ${msg.failed}   Skipped: ${msg.skipped}`);
          if (msg.halted) appendLog(`Halted: ${msg.halt_reason}`);
          break;

        case "verification":
          state.verification = msg;
          break;

        case "error":
          appendLog(`ERROR: ${msg.message}`);
          break;

        case "done":
          src.close();
          finalizeInstall(msg.status);
          break;
      }
    });

    src.onerror = () => {
      src.close();
      appendLog("Connection to server lost.");
      finalizeInstall("failed");
    };
  }

  function appendLog(text) {
    const log = $("#install-log");
    if (!log) return;
    log.textContent += text + "\n";
    log.scrollTop = log.scrollHeight;
  }

  function finalizeInstall(status) {
    if (status === "done") {
      goTo("done");
      drawDone();
    } else {
      showFailure("Setup didn't complete.", state.verification?.checks || []);
    }
  }

  // ------------------------------------------------------------------
  // Done / failed
  // ------------------------------------------------------------------

  function drawDone() {
    const v = state.verification;
    const list = $("#check-list");
    list.innerHTML = "";

    if (v && v.checks) {
      for (const c of v.checks) {
        const row = document.createElement("div");
        const klass = c.status === "ok" ? "ok" : (c.status === "skipped" ? "warn" : "bad");
        row.className = `check-row ${klass}`;
        const icon = c.status === "ok" ? "✓" : (c.status === "skipped" ? "·" : "!");
        row.innerHTML = `
          <span class="icon">${icon}</span>
          <div>
            <div>${escapeHtml(prettyCheckName(c.name))}</div>
            ${c.detail ? `<div class="detail">${escapeHtml(c.detail)}</div>` : ""}
          </div>
        `;
        list.appendChild(row);
      }
    }

    const next = $("#next-steps");
    next.innerHTML = `
      <h3>What's next</h3>
      <p>Start chatting: <code>openclaw chat</code></p>
      <p>Watch the logs: <code>openclaw logs --follow</code></p>
      <p>Run a health check anytime: <code>openclaw doctor</code></p>
    `;

    if (v && !v.fully_ready) {
      $("#done-title").textContent = "Almost there.";
      $("#done-lede").textContent = "A couple of things still need attention — see below.";
      $("#done-badge").textContent = "!";
      $("#done-badge").classList.add("failed");
    }
  }

  function prettyCheckName(name) {
    if (name.startsWith("binary:")) return `${name.slice(7)} is installed`;
    if (name.startsWith("env:")) return `${name.slice(4)} is set`;
    if (name.startsWith("channel:")) return `${name.slice(8)} is working`;
    return {
      "gateway:status": "Gateway is running",
      "openclaw:doctor": "Health check",
    }[name] || name;
  }

  function showFailure(reason, checks) {
    state.current = "done";  // reuse the dot position
    render("tpl-failed");
    $("#failed-reason").textContent = reason;
    const list = $("#failed-checks");
    list.innerHTML = "";
    for (const c of checks) {
      if (c.status === "ok") continue;
      const row = document.createElement("div");
      row.className = "check-row bad";
      row.innerHTML = `
        <span class="icon">!</span>
        <div>
          <div>${escapeHtml(prettyCheckName(c.name))}</div>
          ${c.fix ? `<div class="detail">Fix: ${escapeHtml(c.fix)}</div>` : ""}
        </div>
      `;
      list.appendChild(row);
    }
  }

  async function finish() {
    try { await api("/api/shutdown", { method: "POST" }); } catch {}
    document.body.innerHTML = `
      <div style="max-width:480px;margin:4rem auto;text-align:center;color:#9eb0ca;font-family:inherit">
        <h1 style="color:#eef4ff">All done.</h1>
        <p>You can close this tab now.</p>
      </div>`;
  }

  // ------------------------------------------------------------------
  // utils
  // ------------------------------------------------------------------

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------

  goTo("welcome");
})();
