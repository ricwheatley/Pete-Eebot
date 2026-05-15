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
    setCommandResult(form, body.summary || `${body.command || "Command"} ${body.status}.`, "ok");
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
});
