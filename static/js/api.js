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
        if (window.location.pathname !== "/login/") {
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

  function escapeHtml(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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

  function findCategoryById(nodes, targetId) {
    var match = null;
    (nodes || []).forEach(function (node) {
      if (match) return;
      if (String(node.id) === String(targetId)) {
        match = node;
        return;
      }
      match = findCategoryById(node.children || [], targetId) || match;
    });
    return match;
  }

  function getCategoryCustomFields(nodes, categoryId) {
    var category = findCategoryById(nodes, categoryId);
    return (category && category.custom_fields) || [];
  }

  function formatCategoryPath(category) {
    if (!category) return "—";
    var path = category.full_name || category.fullName || "";
    // Some endpoints may return a brief category object without full_name.
    // Prefer reconstructing at least one parent level when available.
    if (!path) {
      var parentName = category.parent_name || category.parentName || "";
      if (parentName) path = parentName + " > " + (category.name || "");
      else path = category.name || "";
    }
    return path ? String(path).split(" > ").join("/") : "—";
  }

  function formatCategoryLeaf(category) {
    if (!category) return "—";
    return String(category.name || "—");
  }

  function formatItemPath(item) {
    if (!item) return "—";
    // User-facing displays prefer leaf category only.
    var categoryPath = formatCategoryLeaf(item.category);
    var itemName = ((item.display_name || "") + "").trim();
    if (!itemName || itemName.indexOf("Item #") === 0 || itemName === "Inventory item") return categoryPath;
    return categoryPath + "/" + itemName;
  }

  function formatCustomFieldValue(field, customValues) {
    if (!field) return "—";
    customValues = customValues || {};
    var value = customValues[field.name];
    if (value === undefined || value === null || value === "") return "—";
    if (field.type === "boolean") value = value ? "Yes" : "No";
    if (field.unit) return value + " " + field.unit;
    return String(value);
  }

  function renderCustomFieldInputs(container, schema, values) {
    if (!container) return;
    schema = schema || [];
    values = values || {};
    container.innerHTML = "";
    if (!schema.length) {
      container.classList.add("d-none");
      return;
    }
    container.classList.remove("d-none");

    schema.forEach(function (field) {
      var wrapper = document.createElement("div");
      wrapper.className = "mb-3";

      var label = document.createElement("label");
      label.className = "form-label";
      label.textContent = field.label || field.name;
      if (field.required) label.textContent += " *";
      wrapper.appendChild(label);

      var input;
      if (field.type === "choice" || field.type === "boolean") {
        input = document.createElement("select");
        input.className = "form-select";
        var empty = document.createElement("option");
        empty.value = "";
        empty.textContent = field.required ? "Select an option" : "Optional";
        input.appendChild(empty);
        if (field.type === "choice") {
          (field.choices || []).forEach(function (choice) {
            var option = document.createElement("option");
            option.value = choice;
            option.textContent = choice;
            input.appendChild(option);
          });
        } else {
          [{ value: "true", label: "Yes" }, { value: "false", label: "No" }].forEach(function (choice) {
            var option = document.createElement("option");
            option.value = choice.value;
            option.textContent = choice.label;
            input.appendChild(option);
          });
        }
      } else {
        input = document.createElement("input");
        input.className = "form-control";
        input.type = field.type === "integer" || field.type === "float" ? "number" : "text";
        if (field.type === "float") input.step = "any";
        if (field.type === "integer") input.step = "1";
      }

      input.name = "custom__" + field.name;
      input.dataset.customField = field.name;
      if (field.required) input.required = true;
      var currentValue = values[field.name];
      if (field.type === "boolean") {
        input.value = currentValue === true ? "true" : currentValue === false ? "false" : "";
      } else if (currentValue !== undefined && currentValue !== null) {
        input.value = currentValue;
      }
      wrapper.appendChild(input);

      if (field.unit) {
        var help = document.createElement("div");
        help.className = "form-text";
        help.textContent = "Unit: " + field.unit;
        wrapper.appendChild(help);
      }
      container.appendChild(wrapper);
    });
  }

  function collectCustomFieldValues(root, schema) {
    var values = {};
    (schema || []).forEach(function (field) {
      var input = root.querySelector('[name="custom__' + field.name + '"]');
      if (!input) return;
      var rawValue = input.value;
      if (rawValue === "") return;

      if (field.type === "integer") {
        values[field.name] = parseInt(rawValue, 10);
      } else if (field.type === "float") {
        values[field.name] = parseFloat(rawValue);
      } else if (field.type === "boolean") {
        values[field.name] = rawValue === "true";
      } else {
        values[field.name] = rawValue;
      }
    });
    return values;
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
      inventoryItemsPromise = raw.get("/items/?page_size=1000&ordering=-last_updated").then(function (res) {
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
          if (err && err.response && err.response.status === 401) {
            clearSession();
            var path = window.location.pathname;
            if (path !== "/login/") {
              window.location.href = "/login/";
            }
          }
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

  function detectActiveNav() {
    var path = window.location.pathname || "/";
    if (path === "/") return "dashboard";
    if (path === "/inventory/") return "inventory";
    if (path === "/history/") return "history";
    if (path === "/admin-panel/") return "admin";
    return "";
  }

  function initCommandPalette(user) {
    var modalEl = document.getElementById("commandPaletteModal");
    var input = document.getElementById("commandPaletteInput");
    var list = document.getElementById("commandPaletteList");
    if (!modalEl || !input || !list) return;

    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var commands = [
      { label: "Go to Dashboard", hint: "Page", action: function () { window.location.href = "/"; } },
      { label: "Go to Inventory", hint: "Page", action: function () { window.location.href = "/inventory/"; } },
      { label: "Add Item", hint: "Action", action: function () { window.location.href = "/add/"; }, requiresWrite: true },
      { label: "Open Administration", hint: "Page", action: function () { window.location.href = "/admin-panel/"; }, requiresSuperuser: true },
      { label: "Toggle Sidebar", hint: "Action", action: function () {
        var asideToggle = document.getElementById("sidebarToggle");
        if (asideToggle) asideToggle.click();
      } },
      { label: "Logout", hint: "Session", action: logout },
    ];

    function visibleCommands() {
      return commands.filter(function (cmd) {
        if (cmd.requiresSuperuser && !isSuperuser(user)) return false;
        if (cmd.requiresWrite && !canManageInventory(user)) return false;
        return true;
      });
    }

    function renderCommands(term) {
      term = (term || "").toLowerCase().trim();
      list.innerHTML = "";
      var filtered = visibleCommands().filter(function (cmd) {
        return !term || cmd.label.toLowerCase().indexOf(term) >= 0;
      });
      if (!filtered.length) {
        list.innerHTML = '<div class="p-3 text-secondary small">No matching commands.</div>';
        return;
      }
      filtered.forEach(function (cmd) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "list-group-item list-group-item-action command-palette-item";
        btn.innerHTML = "<span>" + cmd.label + "</span><small class='text-secondary'>" + cmd.hint + "</small>";
        btn.addEventListener("click", function () {
          modal.hide();
          cmd.action();
        });
        list.appendChild(btn);
      });
    }

    document.addEventListener("keydown", function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        renderCommands("");
        input.value = "";
        modal.show();
        setTimeout(function () { input.focus(); }, 20);
      }
    });

    input.addEventListener("input", function () {
      renderCommands(input.value);
    });
  }

  function initSidebar(options) {
    options = options || {};

    var shell = document.getElementById("appShell");
    var aside = document.getElementById("appSidebar");
    var backdrop = document.getElementById("sidebarBackdrop");
    var main = shell ? shell.querySelector(".app-main") : null;
    if (!shell || !aside || !backdrop) return Promise.resolve(null);

    // New sidebar v2 handles UI interactions itself.
    if (aside.classList.contains("sidebar-v2") && window.imsSidebar && typeof window.imsSidebar.init === "function") {
      window.imsSidebar.init();
    }

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
      var didInitActivePath = false;
      var mobileOpen = false;
      var treeExpanded = document.getElementById("sidebarTreeExpanded");
      var treeFloating = document.getElementById("sidebarTreeFloating");
      var adminLink = document.getElementById("sidebarAdminLink");
      var userNameEl = document.getElementById("sidebarUserName");
      var userRoleEl = document.getElementById("sidebarUserRole");
      var userAvatarEl = document.getElementById("sidebarUserAvatar");
      var compactLogoutEl = document.getElementById("btnLogoutCompact");
      var brandToggle = aside.querySelector("#sidebarBrandToggle");
      var inventoryHead = aside.querySelector(".sidebar-inventory-head");
      var inventoryMain = aside.querySelector(".inventory-head-main");

      aside.classList.add("no-transition");
      window.setTimeout(function () {
        aside.classList.remove("no-transition");
      }, 100);

      function isTreeOpen(node) {
        return openTreeIds.indexOf(String(node.id)) >= 0;
      }

      function getPathToCategory(nodes, targetId, trail) {
        trail = trail || [];
        for (var i = 0; i < (nodes || []).length; i += 1) {
          var node = nodes[i];
          var nextTrail = trail.concat([String(node.id)]);
          if (String(node.id) === String(targetId)) return nextTrail;
          var nested = getPathToCategory(node.children || [], targetId, nextTrail);
          if (nested.length) return nested;
        }
        return [];
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
            var showLeafCount = !isParent && Number(node.depth) <= 1;
            var arrow = isParent
              ? '<i class="bi ' + (isOpen ? "bi-chevron-down" : "bi-chevron-right") + ' ms-auto"></i>'
              : (showLeafCount
                ? '<span class="tree-badge">' +
                  (node.item_count !== undefined ? node.item_count : categoryCounts[String(node.id)] || 0) +
                  "</span>"
                : "");
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

        // Sidebar v2 active handling (leaf items).
        if (aside.classList.contains("sidebar-v2")) {
          aside.querySelectorAll("[data-nav-id]").forEach(function (el) {
            el.classList.toggle("active", el.getAttribute("data-nav-id") === activeNav);
          });
        }

        if (inventoryHead) inventoryHead.classList.toggle("active", activeNav === "inventory");
        if (inventoryMain) inventoryMain.classList.toggle("active", activeNav === "inventory");
        if (!didInitActivePath && activeCategoryId && activeCategoryId !== "all" && !openTreeIds.length) {
          var path = getPathToCategory(categoryTree, activeCategoryId, []);
          openTreeIds = path.slice(0, -1);
          setOpenTreeIds(openTreeIds);
          didInitActivePath = true;
        }
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
            else window.location.href = "/inventory/?category=" + encodeURIComponent(categoryId);
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
        mobileToggle.innerHTML = '<i class="bi bi-list"></i>';
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

      // Sidebar v2 footer logout.
      var v2User = aside.querySelector("#sidebarUser");
      if (v2User) {
        v2User.addEventListener("click", function () {
          logout();
        });
      }

      if (brandToggle) {
        function toggleFromBrand() {
          if (isMobileSidebar()) {
            setMobileOpen(!mobileOpen);
            return;
          }
          setSidebarCollapsed(!getSidebarCollapsed());
          updateShellState();
        }

        brandToggle.addEventListener("click", function () {
          toggleFromBrand();
        });

        brandToggle.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggleFromBrand();
          }
        });
      }

      var inventoryTreeToggle = aside.querySelector("#inventoryTreeToggle");
      if (inventoryTreeToggle) {
        inventoryTreeToggle.addEventListener("click", function (e) {
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
      }

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
    var readOnlyPill = document.getElementById("readOnlyPill");
    if (readOnlyPill) readOnlyPill.classList.toggle("d-none", canWrite);
  }

  function bootstrapPage(options) {
    options = options || {};
    if (!requireAuth()) return Promise.resolve(null);
    if (!options.activeNav) options.activeNav = detectActiveNav();
    return loadCurrentUser(true).then(function (user) {
      consumeQueuedToast();
      if (!enforcePageAccess(user, options)) return null;
      applyPermissionVisibility(document, user);
      initCommandPalette(user);
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
    escapeHtml: escapeHtml,
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
    findCategoryById: findCategoryById,
    getCategoryCustomFields: getCategoryCustomFields,
    formatCategoryPath: formatCategoryPath,
    formatCategoryLeaf: formatCategoryLeaf,
    formatItemPath: formatItemPath,
    formatCustomFieldValue: formatCustomFieldValue,
    renderCustomFieldInputs: renderCustomFieldInputs,
    collectCustomFieldValues: collectCustomFieldValues,
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
