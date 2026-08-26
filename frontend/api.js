const Api = (() => {
  const tokenKey = "alpha_hub_token";
  const usernameKey = "alpha_hub_username";

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = localStorage.getItem(tokenKey);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, { ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const body = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };
    if (!response.ok) {
      if (response.status === 401) {
        clearLogin();
        if (!location.pathname.endsWith("login.html") && location.pathname !== "/") {
          location.href = "/login.html";
        }
      }
      throw new Error(body.detail || "请求失败");
    }
    return body;
  }

  function saveLogin(token, username) {
    localStorage.setItem(tokenKey, token);
    localStorage.setItem(usernameKey, username);
  }

  function clearLogin() {
    localStorage.removeItem(tokenKey);
    localStorage.removeItem(usernameKey);
  }

  return { request, saveLogin, clearLogin, tokenKey, usernameKey };
})();
