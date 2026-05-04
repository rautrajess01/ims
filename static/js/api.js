(function () {
  const API_BASE = "/api/v1";
  const TOKEN_ACCESS = "ims_access";
  const TOKEN_REFRESH = "ims_refresh";

  const raw = axios.create({ baseURL: API_BASE });

  raw.interceptors.request.use((config) => {
    const t = localStorage.getItem(TOKEN_ACCESS);
    if (t) config.headers.Authorization = "Bearer " + t;
    return config;
  });

  raw.interceptors.response.use(
    (r) => r,
    async (err) => {
      const orig = err.config;
      if (err.response && err.response.status === 401 && orig && !orig._retry) {
        orig._retry = true;
        const refresh = localStorage.getItem(TOKEN_REFRESH);
        if (refresh) {
          try {
            const { data } = await axios.post(API_BASE + "/auth/refresh/", { refresh });
            localStorage.setItem(TOKEN_ACCESS, data.access);
            orig.headers.Authorization = "Bearer " + data.access;
            return raw(orig);
          } catch (_) {}
        }
        localStorage.removeItem(TOKEN_ACCESS);
        localStorage.removeItem(TOKEN_REFRESH);
        const path = window.location.pathname;
        if (path !== "/login/" && !path.endsWith("login.html")) {
          window.location.href = "/login/";
        }
      }
      return Promise.reject(err);
    }
  );

  function showToast(message, variant) {
    variant = variant || "primary";
    const el = document.getElementById("toastLive");
    if (!el) return;
    const body = el.querySelector(".toast-body");
    ["primary", "success", "danger", "warning", "secondary"].forEach(function (v) {
      el.classList.remove("text-bg-" + v);
    });
    el.classList.add("text-bg-" + variant);
    body.textContent = message;
    bootstrap.Toast.getOrCreateInstance(el).show();
  }

  function statusBadge(status) {
    const map = {
      in_stock: ["In stock", "success"],
      deployed: ["Deployed", "primary"],
      out_of_stock: ["Out of stock", "danger"],
      na: ["N/A", "secondary"],
      faulty: ["Faulty", "warning"],
    };
    const m = map[status] || [status, "secondary"];
    return '<span class="badge text-bg-' + m[1] + '">' + m[0] + "</span>";
  }

  function requireAuth() {
    if (!localStorage.getItem(TOKEN_ACCESS)) {
      window.location.href = "/login/";
      return false;
    }
    return true;
  }

  async function logout() {
    const refresh = localStorage.getItem(TOKEN_REFRESH);
    try {
      if (refresh) await raw.post("/auth/logout/", { refresh });
    } catch (_) {}
    localStorage.removeItem(TOKEN_ACCESS);
    localStorage.removeItem(TOKEN_REFRESH);
    window.location.href = "/login/";
  }

  window.ims = {
    api: raw,
    showToast: showToast,
    statusBadge: statusBadge,
    requireAuth: requireAuth,
    logout: logout,
    TOKEN_ACCESS: TOKEN_ACCESS,
    TOKEN_REFRESH: TOKEN_REFRESH,
  };
})();
