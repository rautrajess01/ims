(function () {
  const API_BASE = "/api/v1";
  const TOKEN_ACCESS = "ims_access";
  const TOKEN_REFRESH = "ims_refresh";
  const USERNAME_KEY = "ims_username";
  const USER_ROLE_KEY = "ims_user_role";
  const CURRENT_USER_KEY = "ims_current_user";
  const FLASH_TOAST_KEY = "ims_flash_toast";
  const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed";
  const SIDEBAR_COLLAPSED_LEGACY_KEY = "ims_sidebar_collapsed";
  const SIDEBAR_TREE_KEY = "ims_sidebar_tree_open";

  const raw = axios.create({ baseURL: API_BASE });
  let categoryTreePromise = null;
  let inventoryItemsPromise = null;
  let currentUserPromise = null;

  raw.interceptors.request.use(function (config) {
    var token = localStorage.getItem(TOKEN_ACCESS);
    if (token) config.headers.Authorization = "Bearer " + token;
    return config;
  });

  raw.interceptors.response.use(
    function (response) {
      return response;
    },
    async function (err) {
      var orig = err.config;
      if (err.response && err.response.status === 401 && orig && !orig._retry) {
        orig._retry = true;
        var refresh = localStorage.getItem(TOKEN_REFRESH);
        if (refresh) {
          try {
            var refreshed = await axios.post(API_BASE + "/auth/refresh/", { refresh: refresh });
            localStorage.setItem(TOKEN_ACCESS, refreshed.data.access);
            orig.headers.Authorization = "Bearer " + refreshed.data.access;
            return raw(orig);
          } catch (_) {}
        }
        clearSession();
        if (window.location.pathname !== "/login/" && !window.location.pathname.endsWith("login.html")) {
          window.location.href = "/login/";
        }
      }
      return Promise.reject(err);
    }
  );

  function results(d) {
    return d && d.results !== undefined ? d.results : d;
  }

  function showToast(message, variant) {
    variant = variant || "primary";
    var el = document.getElementById("toastLive");
    if (!el) return;
    var body = el.querySelector(".toast-body");
    ["primary", "success", "danger", "warning", "secondary"].forEach(function (v) {
      el.classList.remove("text-bg-" + v);
    });
    el.classList.add("text-bg-" + variant);
    body.textContent = message;
    bootstrap.Toast.getOrCreateInstance(el).show();
  }

  function queueToast(message, variant) {
    localStorage.setItem(FLASH_TOAST_KEY, JSON.stringify({ message: message, variant: variant || "primary" }));
  }

  function consumeQueuedToast() {
    try {
      var rawToast = localStorage.getItem(FLASH_TOAST_KEY);
      if (!rawToast) return;
      localStorage.removeItem(FLASH_TOAST_KEY);
      var data = JSON.parse(rawToast);
      showToast(data.message, data.variant);
    } catch (_) {
      localStorage.removeItem(FLASH_TOAST_KEY);
    }
  }

  function statusBadge(status) {
    var map = {
      in_stock: ["In stock", "success"],
      deployed: ["Deployed", "primary"],
      out_of_stock: ["Out of stock", "danger"],
      na: ["N/A", "secondary"],
      faulty: ["Faulty", "warning"],
    };
    var data = map[status] || [status, "secondary"];
    return '<span class="badge text-bg-' + data[1] + '">' + data[0] + "</span>";
  }

  function requireAuth() {
    if (!localStorage.getItem(TOKEN_ACCESS)) {
      window.location.href = "/login/";
      return false;
    }
    return true;
  }

  function getUsername() {
    return localStorage.getItem(USERNAME_KEY) || "User";
  }

  function setUsername(username) {
    if (username) localStorage.setItem(USERNAME_KEY, username);
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_ACCESS);
    localStorage.removeItem(TOKEN_REFRESH);
    localStorage.removeItem(USERNAME_KEY);
    localStorage.removeItem(USER_ROLE_KEY);
    localStorage.removeItem(CURRENT_USER_KEY);
    currentUserPromise = null;
  }

  function getInitials(name) {
    return (name || "User")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (part) {
        return part.charAt(0).toUpperCase();
      })
      .join("");
  }

  function getStoredUser() {
    try {
      return JSON.parse(localStorage.getItem(CURRENT_USER_KEY) || "null");
    } catch (_) {
      return null;
    }
  }

  function storeCurrentUser(user) {
    if (!user) return;
    localStorage.setItem(CURRENT_USER_KEY, JSON.stringify(user));
    localStorage.setItem(USERNAME_KEY, user.username || "");
    localStorage.setItem(USER_ROLE_KEY, user.role || "regular");
  }

  function getUserRole(user) {
    return (user && user.role) || localStorage.getItem(USER_ROLE_KEY) || "regular";
  }

  function canManageInventory(user) {
    var role = getUserRole(user);
    return role === "staff" || role === "superuser";
  }

  function isSuperuser(user) {
    return getUserRole(user) === "superuser";
  }

  function flattenCategoryTree(nodes, acc) {
    acc = acc || [];
    (nodes || []).forEach(function (node) {
      acc.push(node);
      flattenCategoryTree(node.children || [], acc);
    });
    return acc;
  }

  function collectLeafCategories(nodes, rootName, trail, groups) {
    groups = groups || {};
    (nodes || []).forEach(function (node) {
      var nextRoot = rootName || node.name;
      var nextTrail = trail ? trail.concat([node.name]) : [node.name];
      if (node.is_leaf) {
        if (!groups[nextRoot]) groups[nextRoot] = [];
        groups[nextRoot].push({
          id: node.id,
          label: nextTrail.slice(1).join(" > ") || node.name,
          full_name: node.full_name || nextTrail.join(" > "),
        });
        return;
      }
      collectLeafCategories(node.children || [], nextRoot, nextTrail, groups);
    });
    return groups;
  }

  function buildCategoryIndexes(nodes) {
    var descendantsById = {};
    var nodeById = {};

    function visit(node) {
      nodeById[String(node.id)] = node;
      var ids = [String(node.id)];
      (node.children || []).forEach(function (child) {
        visit(child);
        ids = ids.concat(descendantsById[String(child.id)] || []);
      });
      descendantsById[String(node.id)] = ids;
    }

    (nodes || []).forEach(visit);
    return {
      descendantsById: descendantsById,
      nodeById: nodeById,
    };
  }

  function countItemsByCategory(items) {
    var counts = {};
    (items || []).forEach(function (item) {
      if (!item.category || item.category.id === undefined || item.category.id === null) return;
      var key = String(item.category.id);
      counts[key] = (counts[key] || 0) + 1;
    });
    return counts;
  }

  function categoryContains(nodes, targetId) {
    var found = false;
    (nodes || []).forEach(function (node) {
      if (found) return;
      if (String(node.id) === String(targetId)) {
        found = true;
        return;
      }
      if (categoryContains(node.children || [], targetId)) found = true;
    });
    return found;
  }

  function getCategoryTree(force) {
    if (force) categoryTreePromise = null;
    if (!categoryTreePromise) {
      categoryTreePromise = raw.get("/categories/tree/").then(function (res) {
        return results(res.data);
      });
    }
    return categoryTreePromise;
  }

  function getInventoryItems(force) {
    if (force) inventoryItemsPromise = null;
    if (!inventoryItemsPromise) {
      inventoryItemsPromise = raw.get("/items/?page_size=1000&ordering=specs").then(function (res) {
        return results(res.data);
      });
    }
    return inventoryItemsPromise;
  }

  function loadCurrentUser(force) {
    if (force) currentUserPromise = null;
    if (!currentUserPromise) {
      currentUserPromise = raw
        .get("/auth/me/")
        .then(function (res) {
          storeCurrentUser(res.data);
          return res.data;
        })
        .catch(function (err) {
          currentUserPromise = null;
          throw err;
        });
    }
    return currentUserPromise;
  }

  function isMobileSidebar() {
    return window.matchMedia("(max-width: 991.98px)").matches;
  }

  function getSidebarCollapsed() {
    var modern = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (modern !== null) return modern === "true";
    return localStorage.getItem(SIDEBAR_COLLAPSED_LEGACY_KEY) === "1";
  }

  function setSidebarCollapsed(collapsed) {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "true" : "false");
    localStorage.setItem(SIDEBAR_COLLAPSED_LEGACY_KEY, collapsed ? "1" : "0");
    document.documentElement.classList.toggle("sidebar-collapsed", !!collapsed);
  }

  function getOpenTreeIds() {
    try {
      return JSON.parse(localStorage.getItem(SIDEBAR_TREE_KEY) || "[]");
    } catch (_) {
      return [];
    }
  }

  function setOpenTreeIds(ids) {
    localStorage.setItem(SIDEBAR_TREE_KEY, JSON.stringify(ids));
  }

  async function logout() {
    var refresh = localStorage.getItem(TOKEN_REFRESH);
    try {
      if (refresh) await raw.post("/auth/logout/", { refresh: refresh });
    } catch (_) {}
    clearSession();
    window.location.href = "/login/";
  }

  function enforcePageAccess(user, options) {
    options = options || {};
    if (options.requireSuperuser && !isSuperuser(user)) {
      queueToast("Access Denied", "danger");
      window.location.href = "/";
      return false;
    }
    if (options.requireWrite && !canManageInventory(user)) {
      queueToast("Access Denied", "danger");
      window.location.href = "/";
      return false;
    }
    return true;
  }

  function toggleHidden(el, hidden) {
    if (!el) return;
    el.classList.toggle("d-none", !!hidden);
  }

  function initSidebar(options) {
    options = options || {};

    var shell = document.getElementById("appShell");
    var aside = document.getElementById("appSidebar");
    var backdrop = document.getElementById("sidebarBackdrop");
    var main = shell ? shell.querySelector(".app-main") : null;
    if (!shell || !aside || !backdrop) return Promise.resolve(null);

    return Promise.all([
      options.categoryTree ? Promise.resolve(options.categoryTree) : getCategoryTree(),
      options.categoryCounts
        ? Promise.resolve(options.categoryCounts)
        : getInventoryItems().then(function (items) {
            return countItemsByCategory(items);
          }),
      Promise.resolve(options.currentUser || getStoredUser()),
    ]).then(function (payload) {
      var categoryTree = payload[0];
      var categoryCounts = payload[1];
      var currentUser = payload[2] || getStoredUser() || { username: getUsername(), role: getUserRole() };
      var activeNav = options.activeNav || "";
      var activeCategoryId = options.activeCategoryId !== undefined ? String(options.activeCategoryId) : "all";
      var openTreeIds = getOpenTreeIds();
      var mobileOpen = false;
      var treeExpanded = document.getElementById("sidebarTreeExpanded");
      var treeFloating = document.getElementById("sidebarTreeFloating");
      var adminLink = document.getElementById("sidebarAdminLink");
      var userNameEl = document.getElementById("sidebarUserName");
      var userRoleEl = document.getElementById("sidebarUserRole");
      var userAvatarEl = document.getElementById("sidebarUserAvatar");
      var compactLogoutEl = document.getElementById("btnLogoutCompact");
      var toggleIcon = aside.querySelector("[data-sidebar-toggle-icon]");
      var inventoryHead = aside.querySelector(".sidebar-inventory-head");
      var inventoryMain = aside.querySelector(".inventory-head-main");

      aside.classList.add("no-transition");
      window.setTimeout(function () {
        aside.classList.remove("no-transition");
      }, 100);

      function isTreeOpen(node) {
        if (openTreeIds.indexOf(String(node.id)) >= 0) return true;
        return categoryContains(node.children || [], activeCategoryId);
      }

      function renderTreeNodes(nodes) {
        return (nodes || [])
          .map(function (node) {
            var isParent = !!(node.children && node.children.length);
            var isOpen = isParent && isTreeOpen(node);
            var isActive = String(node.id) === activeCategoryId;
            var indentClass = node.depth > 1 ? " tree-indent-" + Math.min(node.depth, 3) : "";
            var rowClass =
              "tree-node-row" +
              (isParent ? " tree-parent" : " tree-leaf") +
              indentClass +
              (isActive ? " active" : "");
            var icon = isParent ? "bi-folder" : "bi-tag";
            var arrow = isParent
              ? '<i class="bi ' + (isOpen ? "bi-chevron-down" : "bi-chevron-right") + ' ms-auto"></i>'
              : '<span class="tree-badge">' + (node.item_count !== undefined ? node.item_count : categoryCounts[String(node.id)] || 0) + "</span>";
            var buttonAttrs = isParent
              ? 'type="button" data-tree-toggle="' + node.id + '"'
              : 'type="button" data-category-id="' + node.id + '"';
            return (
              '<div class="tree-node' +
              (isOpen ? " open" : "") +
              '">' +
              '<button class="' +
              rowClass +
              '" ' +
              buttonAttrs +
              ">" +
              '<i class="bi ' +
              icon +
              '"></i><span class="tree-label-text">' +
              node.name +
              "</span>" +
              arrow +
              "</button>" +
              (isParent ? '<div class="tree-children">' + renderTreeNodes(node.children || []) + "</div>" : "") +
              "</div>"
            );
          })
          .join("");
      }

      function setMobileOpen(nextState) {
        mobileOpen = !!nextState;
        shell.classList.toggle("sidebar-mobile-open", mobileOpen);
        document.body.classList.toggle("sidebar-open-mobile", mobileOpen);
      }

      function updateShellState() {
        var collapsed = getSidebarCollapsed();
        document.documentElement.classList.toggle("sidebar-collapsed", collapsed);
        if (toggleIcon) {
          toggleIcon.className =
            "bi " + (collapsed && !isMobileSidebar() ? "bi-layout-sidebar" : "bi-layout-sidebar-inset");
        }
      }

      function renderSidebar() {
        var username = currentUser.username || getUsername();
        var initials = getInitials(username);
        var role = getUserRole(currentUser);

        aside.querySelectorAll("[data-nav]").forEach(function (el) {
          el.classList.toggle("active", el.getAttribute("data-nav") === activeNav);
        });
        aside.querySelectorAll("[data-nav-link]").forEach(function (el) {
          el.classList.toggle("active", el.getAttribute("data-nav-link") === activeNav);
        });

        if (userNameEl) userNameEl.textContent = username;
        if (userRoleEl) userRoleEl.textContent = role;
        if (userAvatarEl) userAvatarEl.textContent = initials;
        if (compactLogoutEl) compactLogoutEl.textContent = initials;
        if (adminLink) adminLink.classList.toggle("d-none", !isSuperuser(currentUser));
        if (inventoryHead) inventoryHead.classList.toggle("active", activeNav === "inventory");
        if (inventoryMain) inventoryMain.classList.toggle("active", activeNav === "inventory");
        if (treeExpanded) treeExpanded.innerHTML = renderTreeNodes(categoryTree);
        if (treeFloating) treeFloating.innerHTML = renderTreeNodes(categoryTree);

        aside.querySelectorAll("[data-tree-toggle]").forEach(function (btn) {
          btn.onclick = function () {
            var id = String(btn.getAttribute("data-tree-toggle"));
            if (openTreeIds.indexOf(id) >= 0) {
              openTreeIds = openTreeIds.filter(function (value) { return value !== id; });
            } else {
              openTreeIds.push(id);
            }
            setOpenTreeIds(openTreeIds);
            renderSidebar();
          };
        });

        aside.querySelectorAll("[data-category-id]").forEach(function (btn) {
          btn.onclick = function () {
            var categoryId = String(btn.getAttribute("data-category-id"));
            activeCategoryId = categoryId;
            if (typeof options.onCategorySelect === "function") options.onCategorySelect(categoryId);
            else window.location.href = "/inventory.html?category=" + encodeURIComponent(categoryId);
            if (isMobileSidebar()) setMobileOpen(false);
            renderSidebar();
          };
        });

        updateShellState();
      }

      if (main && !document.getElementById("mobileSidebarToggle")) {
        var mobileToggle = document.createElement("button");
        mobileToggle.type = "button";
        mobileToggle.id = "mobileSidebarToggle";
        mobileToggle.className = "mobile-sidebar-toggle";
        mobileToggle.setAttribute("aria-label", "Open sidebar");
        mobileToggle.innerHTML = '<i class="bi bi-layout-sidebar-inset"></i>';
        main.insertBefore(mobileToggle, main.firstChild);
        mobileToggle.addEventListener("click", function () {
          setMobileOpen(true);
        });
      }

      aside.querySelectorAll("#btnLogout, #btnLogoutCompact").forEach(function (btn) {
        btn.addEventListener("click", function () {
          logout();
        });
      });

      aside.querySelector("#sidebarToggle").addEventListener("click", function () {
        if (isMobileSidebar()) {
          setMobileOpen(!mobileOpen);
          return;
        }
        setSidebarCollapsed(!getSidebarCollapsed());
        updateShellState();
      });

      aside.querySelector("#inventoryTreeToggle").addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var rootIds = categoryTree
          .filter(function (node) {
            return node.children && node.children.length;
          })
          .map(function (node) {
            return String(node.id);
          });
        var allOpen = rootIds.length && rootIds.every(function (id) {
          return openTreeIds.indexOf(id) >= 0;
        });
        openTreeIds = allOpen ? [] : rootIds.slice();
        setOpenTreeIds(openTreeIds);
        renderSidebar();
      });

      backdrop.addEventListener("click", function () {
        setMobileOpen(false);
      });

      window.addEventListener("resize", function () {
        if (!isMobileSidebar()) setMobileOpen(false);
        updateShellState();
      });

      renderSidebar();

      return {
        setActiveCategory: function (categoryId) {
          activeCategoryId = categoryId !== undefined && categoryId !== null ? String(categoryId) : "all";
          renderSidebar();
        },
        setCategoryCounts: function (counts) {
          categoryCounts = counts || {};
          renderSidebar();
        },
      };
    });
  }

  function applyPermissionVisibility(root, user) {
    root = root || document;
    var canWrite = canManageInventory(user);
    Array.prototype.slice.call(root.querySelectorAll("[data-requires-write]")).forEach(function (el) {
      toggleHidden(el, !canWrite);
    });
    Array.prototype.slice.call(root.querySelectorAll("[data-requires-superuser]")).forEach(function (el) {
      toggleHidden(el, !isSuperuser(user));
    });
  }

  function bootstrapPage(options) {
    options = options || {};
    if (!requireAuth()) return Promise.resolve(null);
    return loadCurrentUser(true).then(function (user) {
      consumeQueuedToast();
      if (!enforcePageAccess(user, options)) return null;
      applyPermissionVisibility(document, user);
      return Promise.all([
        options.skipSidebar ? Promise.resolve(null) : initSidebar({ activeNav: options.activeNav, currentUser: user }),
        Promise.resolve(user),
      ]).then(function (payload) {
        return {
          sidebar: payload[0],
          user: payload[1],
        };
      });
    });
  }

  window.ims = {
    api: raw,
    results: results,
    showToast: showToast,
    queueToast: queueToast,
    consumeQueuedToast: consumeQueuedToast,
    statusBadge: statusBadge,
    requireAuth: requireAuth,
    logout: logout,
    getUsername: getUsername,
    setUsername: setUsername,
    clearSession: clearSession,
    getStoredUser: getStoredUser,
    getUserRole: getUserRole,
    canManageInventory: canManageInventory,
    isSuperuser: isSuperuser,
    loadCurrentUser: loadCurrentUser,
    flattenCategoryTree: flattenCategoryTree,
    collectLeafCategories: collectLeafCategories,
    buildCategoryIndexes: buildCategoryIndexes,
    countItemsByCategory: countItemsByCategory,
    getCategoryTree: getCategoryTree,
    getInventoryItems: getInventoryItems,
    initSidebar: initSidebar,
    applyPermissionVisibility: applyPermissionVisibility,
    bootstrapPage: bootstrapPage,
    enforcePageAccess: enforcePageAccess,
    TOKEN_ACCESS: TOKEN_ACCESS,
    TOKEN_REFRESH: TOKEN_REFRESH,
    USERNAME_KEY: USERNAME_KEY,
    USER_ROLE_KEY: USER_ROLE_KEY,
  };
})();
