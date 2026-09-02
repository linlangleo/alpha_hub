const Api = (() => {
  const tokenKey = "alpha_hub_token";
  const usernameKey = "alpha_hub_username";
  const sessionErrorCodes = new Set([2000, 2001]);

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
      : { code: response.status * 100, msg: await response.text(), data: null };
    if (!response.ok || body.code !== 0) {
      if (sessionErrorCodes.has(body.code)) {
        clearLogin();
        if (!location.pathname.endsWith("login.html") && location.pathname !== "/") {
          location.href = "/login.html";
        }
      }
      throw new Error(body.msg || "请求失败");
    }
    return body.data;
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
