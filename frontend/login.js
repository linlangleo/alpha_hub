document.querySelector("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const message = document.querySelector("#message");
  message.textContent = "正在登录…";
  try {
    const result = await Api.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.querySelector("#username").value,
        password: document.querySelector("#password").value,
      }),
    });
    Api.saveLogin(result.access_token, result.username);
    location.href = "/dashboard.html";
  } catch (error) {
    message.textContent = error.message;
  }
});
