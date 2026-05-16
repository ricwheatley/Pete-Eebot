function readCookie(name) {
  const prefix = `${name}=`;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
}

async function signOut() {
  const csrfToken = readCookie("peteeebot_csrf");
  const response = await fetch("/auth/logout", {
    method: "POST",
    headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    credentials: "same-origin",
  });
  if (response.ok || response.status === 401) {
    window.location.assign("/login");
  }
}

async function signIn(form) {
  const error = form.querySelector("[data-form-error]");
  if (error) {
    error.hidden = true;
    error.textContent = "";
  }

  const formData = new FormData(form);
  const response = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({
      login: formData.get("login"),
      password: formData.get("password"),
    }),
  });

  if (response.ok) {
    window.location.assign(form.dataset.next || "/console");
    return;
  }

  if (error) {
    error.textContent = response.status === 429 ? "Too many attempts. Try again later." : "Sign in failed.";
    error.hidden = false;
  }
}

function commandPayload(form) {
  const formData = new FormData(form);
  const payload = {};
  formData.forEach((value, key) => {
    payload[key] = value;
  });
  return payload;
}

function setCommandResult(form, message, tone = "neutral") {
  const result = form.querySelector("[data-command-result]");
  if (!result) {
    return;
  }
  result.textContent = message;
  result.dataset.tone = tone;
  result.hidden = false;
}

function commandResultMessage(body) {
  const parts = [body.summary || `${body.command || "Command"} ${body.status}.`];
  if (body.source_statuses && typeof body.source_statuses === "object") {
    const statuses = Object.entries(body.source_statuses)
      .map(([source, status]) => `${source}: ${status}`)
      .join(", ");
    if (statuses) {
      parts.push(`Sources: ${statuses}`);
    }
  }
  return parts.join("\n");
}

async function submitCommand(form) {
  const button = form.querySelector("[data-command-submit]");
  const csrfToken = readCookie("peteeebot_csrf");
  const endpoint = form.dataset.endpoint;
  if (!endpoint) {
    return;
  }

  if (button) {
    button.disabled = true;
  }
  setCommandResult(form, "Running...", "neutral");

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      credentials: "same-origin",
      body: JSON.stringify(commandPayload(form)),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.error?.message || body.detail?.message || body.detail || "Command failed.";
      setCommandResult(form, String(detail), "danger");
      return;
    }
    setCommandResult(form, commandResultMessage(body), body.success === false ? "danger" : "ok");
  } catch (error) {
    setCommandResult(form, "Command request failed.", "danger");
  } finally {
    updateCommandButton(form);
  }
}

function updateCommandButton(form) {
  const input = form.querySelector("[data-confirmation-input]");
  const button = form.querySelector("[data-command-submit]");
  if (!input || !button) {
    return;
  }
  button.disabled = input.value.trim() !== form.dataset.confirmation;
}

function initTrendChart() {
  const canvas = document.getElementById("trend-canvas");
  if (!canvas || !Array.isArray(window.trendsSeries) || !Array.isArray(window.trendMetrics)) {
    return;
  }
  const metricA = document.getElementById("metric-a");
  const metricB = document.getElementById("metric-b");
  const range = document.getElementById("trend-range");
  const startInput = document.getElementById("trend-start");
  const endInput = document.getElementById("trend-end");
  if (!metricA || !metricB || !range || !startInput || !endInput) return;

  const metrics = window.trendMetrics;
  metrics.forEach((m) => {
    const optionA = new Option(m.label, m.key);
    const optionB = new Option(m.label, m.key);
    metricA.add(optionA);
    metricB.add(optionB);
  });
  metricA.selectedIndex = 0;
  metricB.selectedIndex = Math.min(1, metrics.length - 1);
  const allDates = window.trendsSeries.map((d) => d.date).sort();
  startInput.value = allDates[0] || "";
  endInput.value = allDates[allDates.length - 1] || "";

  const ctx = canvas.getContext("2d");
  function draw() {
    canvas.width = canvas.clientWidth || 800;
    const days = Number(range.value);
    const latest = new Date(endInput.value || allDates[allDates.length - 1]);
    let start = new Date(startInput.value || allDates[0]);
    let end = latest;
    if (range.value !== "custom" && Number.isFinite(days)) {
      start = new Date(latest);
      start.setDate(start.getDate() - days + 1);
      startInput.value = start.toISOString().slice(0, 10);
    }
    const rows = window.trendsSeries.filter((r) => {
      const d = new Date(r.date);
      return d >= start && d <= end;
    });
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const keys = [metricA.value, metricB.value].filter(Boolean);
    if (!rows.length || !keys.length) return;
    const values = rows.flatMap((r) => keys.map((k) => Number(r[k])).filter((v) => !Number.isNaN(v)));
    if (!values.length) return;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = 24;
    const w = canvas.width || canvas.clientWidth;
    const h = canvas.height;
    const x = (i) => pad + (i * (w - pad * 2)) / Math.max(1, rows.length - 1);
    const y = (v) => h - pad - ((v - min) * (h - pad * 2)) / Math.max(1, max - min || 1);
    [["#3b82f6", keys[0]], ["#ef4444", keys[1]]].forEach(([color, key]) => {
      if (!key) return;
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      let started = false;
      rows.forEach((r, i) => {
        const v = Number(r[key]);
        if (Number.isNaN(v)) return;
        const px = x(i);
        const py = y(v);
        if (!started) {
          ctx.moveTo(px, py);
          started = true;
        } else {
          ctx.lineTo(px, py);
        }
      });
      ctx.stroke();
    });
  }
  [metricA, metricB, range, startInput, endInput].forEach((el) => el.addEventListener("change", draw));
  draw();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-logout]").forEach((button) => {
    button.addEventListener("click", () => {
      signOut();
    });
  });

  document.querySelectorAll("[data-login-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      signIn(form);
    });
  });

  document.querySelectorAll("[data-command-form]").forEach((form) => {
    updateCommandButton(form);
    form.addEventListener("input", () => {
      updateCommandButton(form);
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitCommand(form);
    });
  });
  initTrendChart();
});
