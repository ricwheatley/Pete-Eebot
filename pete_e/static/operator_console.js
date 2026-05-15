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
});
