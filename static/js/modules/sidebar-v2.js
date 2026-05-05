(function () {
  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function isCollapsed() {
    return document.documentElement.classList.contains("sidebar-collapsed");
  }

  function setCollapsed(next) {
    document.documentElement.classList.toggle("sidebar-collapsed", !!next);
    var aside = qs("#appSidebar");
    if (aside) aside.classList.toggle("collapsed", !!next);
    try {
      localStorage.setItem("sidebarCollapsed", next ? "true" : "false");
    } catch (_) {}
  }

  function toggleSidebar() {
    setCollapsed(!isCollapsed());
  }

  function closeAllSubmenus(root) {
    qsa("[data-submenu]", root).forEach(function (submenu) {
      submenu.classList.add("closed");
      var btn = qs('[data-submenu-toggle="' + submenu.getAttribute("data-submenu") + '"]', root);
      if (btn) btn.setAttribute("aria-expanded", "false");
    });
  }

  function setActiveNav(root, activeId) {
    qsa("[data-nav-id]", root).forEach(function (el) {
      el.classList.toggle("active", String(el.getAttribute("data-nav-id")) === String(activeId));
    });
  }

  function initSidebarV2() {
    var root = qs("#appSidebar");
    if (!root) return;

    var toggleBtn = qs("#sidebarToggleBtn", root);
    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        toggleSidebar();
      });
    }

    // Submenu behavior: open/close and ensure only one open at a time.
    qsa("[data-submenu-toggle]", root).forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        if (isCollapsed()) {
          var href = btn.getAttribute("data-href");
          if (href) window.location.href = href;
          return;
        }

        var target = btn.getAttribute("data-submenu-toggle");
        var submenu = qs('[data-submenu="' + target + '"]', root);
        if (!submenu) return;

        var willOpen = submenu.classList.contains("closed");
        closeAllSubmenus(root);
        submenu.classList.toggle("closed", !willOpen);
        btn.setAttribute("aria-expanded", willOpen ? "true" : "false");

        // Parent becomes active when submenu toggled.
        var parentNavId = btn.getAttribute("data-nav-id");
        if (parentNavId) setActiveNav(root, parentNavId);
      });
    });

    // Active state: only one active at a time.
    qsa("[data-nav-id][data-nav-leaf='1']", root).forEach(function (link) {
      link.addEventListener("click", function () {
        setActiveNav(root, link.getAttribute("data-nav-id"));
      });
    });

    // If collapsed, force submenus hidden.
    if (isCollapsed()) closeAllSubmenus(root);
  }

  window.imsSidebar = {
    toggleSidebar: toggleSidebar,
    setCollapsed: setCollapsed,
    init: initSidebarV2,
  };
})();

