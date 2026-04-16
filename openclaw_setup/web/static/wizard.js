// clawup wizard — 3-step flow for non-technical users
(() => {
  "use strict";

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------

  const STEPS = ["profile", "provider", "install", "done"];

  const state = {
    current: "profile",
    showAdvanced: false,
    profile: null,    // full profile object from /api/profiles
    provider: null,   // full provider object from /api/providers
    envValues: {},    // { ENV_NAME: "value" }
    plan: null,       // from /api/start (step count only)
    stepEls: [],      // DOM <li> per install step
    verification: null,
  };

  // ------------------------------------------------------------------
  // Friendly halt-reason map
  // ------------------------------------------------------------------

  const FRIENDLY_HALT_REASONS = {
    "Install OpenClaw CLI":   "OpenClaw couldn't be installed. Check your internet connection and try again.",
    "Install node":           "Node.js is required but couldn't be installed. Try downloading it from nodejs.org, then run clawup again.",
    "Install ollama":         "Ollama couldn't be installed. Download it from ollama.com, then run clawup again.",
  };

  // ------------------------------------------------------------------
  // Check-name map (used on done screen)
  // ------------------------------------------------------------------

  const CHECK_NAMES = {
    "binary:openclaw":        "OpenClaw is installed",
    "binary:node":            "Node.js is installed",
    "binary:ollama":          "Ollama is installed",
    "env:OPENAI_API_KEY":     "Connected to OpenAI",
    "env:ANTHROPIC_API_KEY":  "Connected to Anthropic",
    "env:OPENROUTER_API_KEY": "Connected to OpenRouter",
    "env:TELEGRAM_BOT_TOKEN": "Telegram bot connected",
    "gateway:status":         "OpenClaw is running",
    "openclaw:doctor":        "Health check passed",
    "channel:telegram":       "Telegram is working",
    "channel:whatsapp":       "WhatsApp is working",
    "channel:local":          "Chat interface is working",
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
    updateCounter();
    wireActionButtons();
  }

  function updateCounter() {
    const el = $("#step-counter");
    if (!el) return;
    const idx = STEPS.indexOf(state.current);
    const total = STEPS.indexOf("done"); // = 3
    if (idx < 0 || state.current === "done") {
      el.textContent = "";
    } else {
      el.textContent = `Step ${idx + 1} of ${total}`;
    }
  }

  function wireActionButtons() {
    $$("[data-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => handleAction(e.currentTarget.dataset.action));
    });
  }

  function goTo(screen) {
    state.current = screen;
    render(`tpl-${screen}`);
  }

  // ------------------------------------------------------------------
  // API
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
      case "back":      goBack(); break;
      case "install":   await startInstall(); break;
      case "finish":    await finish(); break;
      case "restart":
        Object.assign(state, { current: "profile", profile: null, provider: null,
                                envValues: {}, plan: null, verification: null });
        goTo("profile");
        await renderProfiles();
        break;
    }
  }

  function goBack() {
    if (state.current === "provider") {
      goTo("profile");
      renderProfiles();
    }
  }

  // ------------------------------------------------------------------
  // Step 1 — Profile
  // ------------------------------------------------------------------

  async function renderProfiles() {
    const profiles = await api("/api/profiles");
    const container = $("#profile-cards");
    container.innerHTML = "";

    for (const p of profiles) {
      if (p.advanced && !state.showAdvanced) continue;
      const card = document.createElement("button");
      card.className = "card";
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
        goTo("provider");
        await renderProviders();
      });
      container.appendChild(card);
    }

    // Advanced toggle
    const toggle = $("#advanced-toggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        state.showAdvanced = !state.showAdvanced;
        toggle.textContent = state.showAdvanced ? "Hide advanced options ↑" : "Show advanced options ↓";
        renderProfiles();
      });
    }
  }

  // ------------------------------------------------------------------
  // Step 2 — Provider + inline key expansion
  // ------------------------------------------------------------------

  async function renderProviders() {
    const providers = await api(`/api/providers?profile=${encodeURIComponent(state.profile.id)}`);
    const container = $("#provider-cards");
    container.innerHTML = "";

    for (const pr of providers) {
      const card = document.createElement("button");
      card.className = "card";
      card.dataset.providerId = pr.id;
      card.innerHTML = `
        <div class="card-icon">${providerIcon(pr.id)}</div>
        <div class="card-body">
          <h3 class="card-title">${escapeHtml(pr.title)}</h3>
          <p class="card-blurb">${escapeHtml(pr.blurb)}</p>
        </div>
        <div class="card-chev">→</div>
      `;
      card.addEventListener("click", () => selectProvider(pr, card, container, providers));
      container.appendChild(card);
    }
  }

  function providerIcon(id) {
    return { openai: "🤖", anthropic: "🎭", openrouter: "🔀", local: "🏠" }[id] || "✨";
  }

  async function selectProvider(pr, card, container, providers) {
    state.provider = pr;

    // Fade all other cards, select this one
    Array.from(container.children).forEach((el) => {
      if (el.dataset?.providerId === pr.id) {
        el.classList.add("selected");
        el.classList.remove("faded");
        el.disabled = true;
      } else if (el.classList.contains("card")) {
        el.classList.add("faded");
        el.classList.remove("selected");
      }
    });

    // Remove any existing key expand
    const existingExpand = container.parentElement.querySelector(".key-expand");
    if (existingExpand) existingExpand.remove();

    // Build the key-expand panel
    const expand = await buildKeyExpand(pr);
    card.insertAdjacentElement("afterend", expand);
    expand.querySelector("input")?.focus();
  }

  async function buildKeyExpand(pr) {
    // Gather all required env vars: provider + channel
    const required = [...(pr.required_env || [])];
    const chInfo = await api(`/api/channel-env?profile=${encodeURIComponent(state.profile.id)}`);
    for (const name of chInfo.required_env || []) {
      if (!required.includes(name)) required.push(name);
    }

    const expand = document.createElement("div");
    expand.className = "key-expand";

    if (required.length === 0) {
      // No keys needed (local provider)
      expand.innerHTML = `
        <p style="color:var(--accent);margin:0 0 1rem">
          Good news — no account key needed for this option.
        </p>
        ${summaryHtml(pr)}
        <button class="btn primary" id="letsgo-btn">Let's go →</button>
      `;
    } else {
      const fieldsHtml = required.map((name) => fieldPlaceholder(name)).join("");
      expand.innerHTML = `
        <div id="expand-fields">${fieldsHtml}</div>
        ${summaryHtml(pr)}
        <button class="btn primary" id="letsgo-btn">Let's go →</button>
      `;

      // Populate fields asynchronously
      const host = expand.querySelector("#expand-fields");
      host.innerHTML = "";
      for (const name of required) {
        const copy = await api(`/api/env-copy?name=${encodeURIComponent(name)}`);
        host.appendChild(buildKeyField(name, copy));
      }
    }

    expand.querySelector("#letsgo-btn").addEventListener("click", async () => {
      if (!collectKeys(expand)) return;
      await startInstall();
    });

    return expand;
  }

  function summaryHtml(pr) {
    const channel = state.profile.channel
      ? `for ${escapeHtml(channelLabel(state.profile.channel))}`
      : "";
    return `
      <p class="expand-summary">
        We'll set up OpenClaw ${channel} using <strong>${escapeHtml(pr.title)}</strong>.
        This takes about a minute.
      </p>
    `;
  }

  function channelLabel(id) {
    return { local: "on your computer", telegram: "for Telegram", whatsapp: "for WhatsApp" }[id] || id;
  }

  function fieldPlaceholder(name) {
    return `<div class="field-loading" data-name="${escapeHtml(name)}">Loading…</div>`;
  }

  function buildKeyField(name, copy) {
    const wrap = document.createElement("div");
    wrap.style.marginBottom = "1rem";

    const label = document.createElement("label");
    label.className = "field-label";
    label.textContent = copy.label || name;
    wrap.appendChild(label);

    const sub = document.createElement("p");
    sub.className = "field-sub";
    sub.textContent = "This lets OpenClaw use your account.";
    wrap.appendChild(sub);

    // "Get your key" link
    if (copy.help) {
      const urlMatch = copy.help.match(/(https?:\/\/\S+)/);
      if (urlMatch) {
        const link = document.createElement("a");
        link.className = "get-key-link";
        link.href = urlMatch[1];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Get your key here ↗";
        wrap.appendChild(link);
      }
    }

    // Input + reveal toggle
    const row = document.createElement("div");
    row.className = "input-row";

    const input = document.createElement("input");
    input.type = "password";
    input.name = name;
    input.placeholder = copy.placeholder || "";
    input.autocomplete = "off";
    input.spellcheck = false;
    if (state.envValues[name]) input.value = state.envValues[name];
    input.addEventListener("input", () => {
      input.classList.remove("invalid");
      const err = wrap.querySelector(".field-error");
      if (err) err.classList.remove("visible");
    });
    row.appendChild(input);

    const revealBtn = document.createElement("button");
    revealBtn.type = "button";
    revealBtn.className = "reveal-btn";
    revealBtn.title = "Show/hide";
    revealBtn.textContent = "👁";
    revealBtn.addEventListener("click", () => {
      input.type = input.type === "password" ? "text" : "password";
    });
    row.appendChild(revealBtn);
    wrap.appendChild(row);

    // Persistent error
    const err = document.createElement("div");
    err.className = "field-error";
    err.textContent = "Please paste your key here before continuing.";
    wrap.appendChild(err);

    return wrap;
  }

  function collectKeys(expandEl) {
    const inputs = $$("input[name]", expandEl);
    let ok = true;
    for (const inp of inputs) {
      const val = inp.value.trim();
      if (!val) {
        inp.classList.add("invalid");
        const errEl = inp.closest("div[style]")?.querySelector(".field-error")
                   || inp.parentElement?.nextElementSibling;
        if (errEl?.classList.contains("field-error")) errEl.classList.add("visible");
        if (ok) inp.focus();
        ok = false;
      } else {
        state.envValues[inp.name] = val;
      }
    }
    return ok;
  }

  // ------------------------------------------------------------------
  // Step 3 — Install
  // ------------------------------------------------------------------

  async function startInstall() {
    goTo("install");

    const body = {
      profile: state.profile.id,
      provider: state.provider.id,
      install_service: true,
      env_vars: state.envValues,
    };

    let start;
    try {
      start = await api("/api/start", { method: "POST", body: JSON.stringify(body) });
    } catch (e) {
      showFailure("We couldn't start the setup. Check your internet connection and try again.");
      return;
    }

    // Seed step list — use friendly_label when available
    // We don't have a plan yet at this point so build steps from /api/plan first
    let planSteps = [];
    try {
      const plan = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (plan.ok) {
        const pd = await plan.json();
        planSteps = pd.steps || [];
      }
    } catch {}

    const list = $("#install-steps");
    list.innerHTML = "";
    state.stepEls = [];
    for (const step of planSteps) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="step-icon"></span><span class="step-label">${escapeHtml(step.friendly_label || step.label)}</span>`;
      list.appendChild(li);
      state.stepEls.push(li);
    }

    streamEvents(start.job_id, planSteps.length);
  }

  function streamEvents(jobId, totalSteps) {
    const src = new EventSource(`/api/jobs/${jobId}/events`);
    let currentIdx = -1;
    let completedSteps = 0;

    src.addEventListener("message", (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }

      switch (msg.type) {
        case "step_start": {
          if (currentIdx >= 0 && state.stepEls[currentIdx] && !state.stepEls[currentIdx].classList.contains("failed")) {
            state.stepEls[currentIdx].classList.replace("active", "ok");
          }
          currentIdx = msg.index;
          if (state.stepEls[currentIdx]) {
            state.stepEls[currentIdx].classList.add("active");
            // Scroll into view
            state.stepEls[currentIdx].scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
          // Update status headline
          completedSteps++;
          const statusEl = $("#install-status");
          if (statusEl) {
            if (completedSteps === 1) statusEl.textContent = "Making progress…";
            if (totalSteps > 0 && completedSteps >= Math.floor(totalSteps / 2)) statusEl.textContent = "Almost done…";
          }
          appendLog(`▶ ${msg.friendly_label || msg.label}`);
          break;
        }

        case "log":
          appendLog(msg.text);
          if (/FAILED/.test(msg.text) && currentIdx >= 0 && state.stepEls[currentIdx]) {
            state.stepEls[currentIdx].classList.remove("active");
            state.stepEls[currentIdx].classList.add("failed");
          }
          break;

        case "install_done":
          if (currentIdx >= 0 && state.stepEls[currentIdx] && !state.stepEls[currentIdx].classList.contains("failed")) {
            state.stepEls[currentIdx].classList.replace("active", "ok");
          }
          break;

        case "verification":
          state.verification = msg;
          break;

        case "error":
          appendLog(`Error: ${msg.message}`);
          break;

        case "done":
          src.close();
          finalizeInstall(msg.status);
          break;
      }
    });

    src.onerror = () => {
      src.close();
      showFailure("The connection to the setup server was lost. Please try again.");
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
      const halt = state.verification?.halt_reason || "";
      const stepLabel = halt.replace(/^Critical step failed:\s*/, "");
      const msg = FRIENDLY_HALT_REASONS[stepLabel]
        || "Something went wrong during setup. Run openclaw doctor to find out what happened.";
      showFailure(msg);
    }
  }

  // ------------------------------------------------------------------
  // Done screen
  // ------------------------------------------------------------------

  function drawDone() {
    const v = state.verification;

    // First-step callout
    const firstStepEl = $("#done-first-step");
    if (firstStepEl && state.profile?.first_step) {
      firstStepEl.innerHTML = `
        <div class="fsl">Next step</div>
        <div class="fst">${escapeHtml(state.profile.first_step)}</div>
      `;
    }

    // Show up to 3 friendly checks (green only unless something critical failed)
    const list = $("#check-list");
    list.innerHTML = "";

    const summaryChecks = buildSummaryChecks(v);
    for (const c of summaryChecks) {
      const row = document.createElement("div");
      row.className = `check-row ${c.ok ? "ok" : "bad"}`;
      row.innerHTML = `
        <span class="icon">${c.ok ? "✓" : "!"}</span>
        <div>
          <div>${escapeHtml(c.label)}</div>
          ${!c.ok && c.fix ? `<div class="detail">Try: ${escapeHtml(c.fix)}</div>` : ""}
        </div>
      `;
      list.appendChild(row);
    }

    // If anything failed, adjust the headline
    const anyFailed = summaryChecks.some((c) => !c.ok);
    if (anyFailed) {
      const badge = $("#done-badge");
      const title = $("#done-title");
      const lede = $("#done-lede");
      if (badge) { badge.textContent = "!"; badge.classList.add("failed"); }
      if (title) title.textContent = "Almost there.";
      if (lede) lede.textContent = "One thing still needs attention — see below.";
    }
  }

  function buildSummaryChecks(v) {
    if (!v || !v.checks) return [];
    const out = [];

    // 1. Is OpenClaw running?
    const gw = v.checks.find((c) => c.name === "gateway:status");
    out.push({
      ok: gw?.status === "ok",
      label: "OpenClaw is installed and running",
      fix: gw?.fix,
    });

    // 2. Provider connection
    const providerEnvMap = {
      openai:     "env:OPENAI_API_KEY",
      anthropic:  "env:ANTHROPIC_API_KEY",
      openrouter: "env:OPENROUTER_API_KEY",
    };
    const envKey = providerEnvMap[state.provider?.id];
    if (envKey) {
      const ec = v.checks.find((c) => c.name === envKey);
      out.push({
        ok: ec?.status === "ok",
        label: CHECK_NAMES[envKey] || "AI service connected",
        fix: ec?.fix,
      });
    }

    // 3. Channel (if applicable)
    const chId = state.profile?.channel;
    if (chId && chId !== "local") {
      const cc = v.checks.find((c) => c.name === `channel:${chId}`);
      out.push({
        ok: cc?.status === "ok",
        label: CHECK_NAMES[`channel:${chId}`] || `${chId} is working`,
        fix: cc?.fix,
      });
    }

    return out;
  }

  // ------------------------------------------------------------------
  // Failed screen
  // ------------------------------------------------------------------

  function showFailure(reason) {
    state.current = "done";
    render("tpl-failed");
    const el = $("#failed-reason");
    if (el) el.textContent = reason;
  }

  // ------------------------------------------------------------------
  // Finish
  // ------------------------------------------------------------------

  async function finish() {
    try { await api("/api/shutdown", { method: "POST" }); } catch {}
    document.body.innerHTML = `
      <div style="max-width:480px;margin:5rem auto;text-align:center;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#9eb0ca">
        <div style="font-size:3rem;margin-bottom:1rem">🐾</div>
        <h1 style="color:#eef4ff;margin:0 0 0.5rem">All done.</h1>
        <p>You can close this tab now.</p>
      </div>`;
  }

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------

  goTo("profile");
  renderProfiles();
})();
