(() => {
  "use strict";

  const state = { path: "", bundle: null, activeTab: "estado" };

  // ------------------------------------------------------------- helpers --

  async function api(url, payload) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
      return await res.json();
    } catch (e) {
      return { ok: false, message: "No se pudo comunicar con la app: " + e.message };
    }
  }

  function esc(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function showResult(id, ok, message) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = (ok ? "✓ " : "✕ ") + message;
    el.className = "result show " + (ok ? "success" : "error");
  }

  function showPending(id, text) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text || "Ejecutando...";
    el.className = "result show pending";
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k.startsWith("data-")) node.setAttribute(k, v);
      else if (k === "html") node.innerHTML = v;
      else node.setAttribute(k, v);
    });
    (children || []).forEach((c) => node.appendChild(c));
    return node;
  }
  function text(t) { return document.createTextNode(t); }

  function show(idOrEl) {
    const node = typeof idOrEl === "string" ? document.getElementById(idOrEl) : idOrEl;
    if (node) node.classList.add("active");
  }
  function hideAll(selector) {
    document.querySelectorAll(selector).forEach((n) => n.classList.remove("active"));
  }

  // -------------------------------------------------------------- picker --

  function showPickerView(feedbackMsg, isError) {
    hideAll(".view");
    show("pickerView");
    document.getElementById("pickerPath").value = state.path || "";
    renderRecents((state.bundle && state.bundle.recents) || []);
    const fb = document.getElementById("pickerFeedback");
    if (feedbackMsg) {
      fb.textContent = feedbackMsg;
      fb.className = "feedback show " + (isError ? "error" : "");
    } else {
      fb.className = "feedback";
    }
  }

  function renderRecents(recents) {
    const ul = document.getElementById("recentsList");
    ul.innerHTML = "";
    if (!recents.length) {
      ul.appendChild(el("li", { class: "muted" }, [text("Todavía no hay proyectos recientes.")]));
      return;
    }
    recents.forEach((r) => {
      const pathSpan = el("span", { class: "recent-path" }, [text(r.path)]);
      pathSpan.addEventListener("click", () => openRepo(r.path));
      const rmBtn = el("button", { class: "btn-mini" }, [text("Quitar")]);
      rmBtn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const res = await api("/api/recent/remove", { path: r.path });
        renderRecents(res.recents || []);
      });
      ul.appendChild(el("li", {}, [pathSpan, rmBtn]));
    });
  }

  async function openRepo(path) {
    showPending("pickerFeedback", "Abriendo...");
    document.getElementById("pickerFeedback").className = "feedback show pending";
    const res = await api("/api/open", { repo_path: path });
    if (!res.ok) {
      showPickerView(res.message, true);
      return;
    }
    state.path = res.status.path;
    state.bundle = res;
    decideView(res);
  }

  document.getElementById("pickerOpenBtn").addEventListener("click", () => {
    const path = document.getElementById("pickerPath").value.trim();
    if (!path) { showPickerView("Escribe una ruta primero.", true); return; }
    openRepo(path);
  });

  document.getElementById("cloneBtn").addEventListener("click", async () => {
    const path = document.getElementById("pickerPath").value.trim();
    const url = document.getElementById("cloneUrl").value.trim();
    const token = document.getElementById("cloneToken").value.trim();
    if (!path) { showPickerView("Escribe primero la carpeta destino arriba.", true); return; }
    if (!url) { showPickerView("Pega la URL del repositorio a clonar.", true); return; }
    showPending("pickerFeedback", "Clonando repositorio...");
    document.getElementById("pickerFeedback").className = "feedback show pending";
    const res = await api("/api/step", { step: "clone", repo_path: path, clone_url: url, token });
    if (!res.ok) { showPickerView(res.message, true); return; }
    openRepo(path);
  });

  document.getElementById("repoPill").addEventListener("click", () => showPickerView());
  document.getElementById("changeRepoBtn").addEventListener("click", () => showPickerView());

  function updateRepoPill() {
    const label = document.getElementById("repoPillLabel");
    label.textContent = state.path || "Sin proyecto";
  }

  // -------------------------------------------------------------- wizard --

  const WIZARD_STEPS = { 1: "check_git", 2: "init", 3: "identity", 4: "remote" };

  function showWizardAt(n) {
    hideAll(".view");
    show("wizardView");
    document.getElementById("initPathLabel").textContent = state.path || "";
    document.querySelectorAll(".dot").forEach((d) => {
      const dn = Number(d.dataset.dot);
      d.classList.toggle("active", dn === n);
      d.classList.toggle("done", dn < n);
    });
    document.querySelectorAll(".step").forEach((s) => {
      s.classList.toggle("active", Number(s.dataset.step) === n);
    });
    document.getElementById("wizardDoneBtn").style.display = "none";
  }

  document.querySelectorAll(".step [data-action]").forEach((btn) => {
    btn.addEventListener("click", () => runWizardStep(btn.dataset.action));
  });

  async function runWizardStep(action) {
    const resultId = "result-" + action;
    showPending(resultId);
    const payload = { step: action, repo_path: state.path };
    if (action === "identity") {
      payload.name = document.getElementById("gitName").value.trim();
      payload.email = document.getElementById("gitEmail").value.trim();
    }
    if (action === "remote") {
      payload.remote_url = document.getElementById("remoteUrl").value.trim();
    }
    const res = await api("/api/step", payload);
    showResult(resultId, res.ok, res.message);
    if (!res.ok) return;

    if (action === "check_git") { showWizardAt(2); return; }
    if (action === "init" || action === "identity" || action === "remote") {
      await refreshBundle();
      if (action === "identity" && !state.bundle.status.remote) {
        showWizardAt(4);
        return;
      }
      decideView(state.bundle);
    }
  }

  document.getElementById("skipRemoteBtn").addEventListener("click", async () => {
    await refreshBundle();
    decideView(state.bundle);
  });

  // ------------------------------------------------------------ decision --

  function decideView(data) {
    state.bundle = data;
    state.path = data.status.path;
    updateRepoPill();
    const s = data.status;
    if (!s.path) { showPickerView(); return; }
    if (!s.exists) { showPickerView("La carpeta no existe o no es accesible: " + s.path, true); return; }
    if (!s.git_installed) { showWizardAt(1); return; }
    if (!s.is_git) { showWizardAt(2); return; }
    if (!s.name || !s.email) { showWizardAt(3); return; }
    showDashboard(data);
  }

  async function refreshBundle() {
    const data = await api("/api/bootstrap", { repo_path: state.path });
    state.bundle = data;
    return data;
  }

  async function refreshDashboard() {
    const data = await refreshBundle();
    renderDashboard(data);
  }

  // --------------------------------------------------------------- boot --

  (async () => {
    const initial = document.body.dataset.initialPath || "";
    state.path = initial;
    const data = await api("/api/bootstrap", { repo_path: initial });
    decideView(data);
  })();

  // ----------------------------------------------------------- dashboard --

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeTab = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.classList.toggle("active", p.dataset.tabPanel === tab.dataset.tab);
      });
    });
  });

  function showDashboard(data) {
    hideAll(".view");
    show("dashboardView");
    renderDashboard(data);
  }

  function renderDashboard(data) {
    renderStatusbar(data.status);
    renderFileGroups(data.files);
    renderStashes(data.stashes);
    renderBranches(data.branches);
    renderLog(data.log);
    document.getElementById("cfgName").value = data.status.name || "";
    document.getElementById("cfgEmail").value = data.status.email || "";
    document.getElementById("cfgRemote").value = data.status.remote || "";
    document.getElementById("cfgGitignore").value = data.gitignore || "";
  }

  function renderStatusbar(s) {
    const bar = document.getElementById("statusbar");
    bar.innerHTML = "";
    const parts = [];
    parts.push(el("span", {}, [text("rama "), el("b", {}, [text(s.branch)])]));
    if (s.ahead || s.behind) {
      if (s.ahead) parts.push(el("span", { class: "flag-ahead" }, [text("↑" + s.ahead + " sin subir")]));
      if (s.behind) parts.push(el("span", { class: "flag-behind" }, [text("↓" + s.behind + " sin bajar")]));
    } else if (s.ahead === 0 && s.behind === 0) {
      parts.push(el("span", { class: "flag-clean" }, [text("sincronizado")]));
    }
    parts.push(el("span", {}, [text(s.remote ? "origin: " + s.remote_masked : "sin remoto configurado")]));
    if (!s.has_commits) parts.push(el("span", {}, [text("sin commits todavía")]));
    parts.forEach((p) => bar.appendChild(p));
  }

  function fileRow(item, group) {
    const nameSpan = el("span", { class: "file-name" }, [text(item.file)]);
    nameSpan.title = "Ver diferencias";
    nameSpan.addEventListener("click", () => openDiffModal(item.file, group === "staged"));
    const label = el("span", { class: "file-label" }, [text(item.label)]);
    const actions = el("span", { class: "" }, []);

    if (group === "staged") {
      const btn = el("button", { class: "btn-mini" }, [text("Quitar")]);
      btn.addEventListener("click", () => mutateFiles("/api/unstage", [item.file], "Quitado de preparados."));
      actions.appendChild(btn);
    } else if (group === "unstaged") {
      const addBtn = el("button", { class: "btn-mini" }, [text("Preparar")]);
      addBtn.addEventListener("click", () => mutateFiles("/api/add", [item.file], "Preparado."));
      const discardBtn = el("button", { class: "btn-mini" }, [text("Descartar")]);
      discardBtn.addEventListener("click", () => confirmDestructive(
        "Descartar cambios en " + item.file,
        "Se perderán los cambios sin preparar de este archivo. Esta acción no se puede deshacer.",
        () => mutateFiles("/api/discard", [item.file], "Cambios descartados.")
      ));
      actions.appendChild(addBtn);
      actions.appendChild(discardBtn);
    } else if (group === "untracked") {
      const addBtn = el("button", { class: "btn-mini" }, [text("Preparar")]);
      addBtn.addEventListener("click", () => mutateFiles("/api/add", [item.file], "Preparado."));
      const delBtn = el("button", { class: "btn-mini" }, [text("Eliminar")]);
      delBtn.addEventListener("click", () => confirmDestructive(
        "Eliminar " + item.file,
        "El archivo se borrará del disco porque todavía no tiene seguimiento de Git. Esta acción no se puede deshacer.",
        () => mutateFiles("/api/remove_untracked", [item.file], "Archivo eliminado.")
      ));
      actions.appendChild(addBtn);
      actions.appendChild(delBtn);
    }
    return el("li", {}, [nameSpan, label, actions]);
  }

  function renderFileGroups(files) {
    const stagedUl = document.getElementById("list-staged");
    const unstagedUl = document.getElementById("list-unstaged");
    const untrackedUl = document.getElementById("list-untracked");
    stagedUl.innerHTML = ""; unstagedUl.innerHTML = ""; untrackedUl.innerHTML = "";
    files.staged.forEach((f) => stagedUl.appendChild(fileRow(f, "staged")));
    files.unstaged.forEach((f) => unstagedUl.appendChild(fileRow(f, "unstaged")));
    files.untracked.forEach((f) => untrackedUl.appendChild(fileRow(f, "untracked")));
    const total = files.staged.length + files.unstaged.length + files.untracked.length;
    document.getElementById("noChangesNote").style.display = total === 0 ? "block" : "none";
  }

  async function mutateFiles(url, files, successMsg) {
    const res = await api(url, { repo_path: state.path, files });
    showResult("result-commit", res.ok, res.ok ? successMsg : res.message);
    if (res.ok) refreshDashboard();
  }

  document.querySelectorAll("[data-bulk]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.bulk;
      if (action === "add-all") mutateFiles("/api/add", null, "Todo preparado.");
      if (action === "unstage-all") mutateFiles("/api/unstage", null, "Todo sin preparar.");
    });
  });

  document.getElementById("commitBtn").addEventListener("click", async () => {
    const input = document.getElementById("commitMessage");
    const message = input.value.trim();
    if (!message) { showResult("result-commit", false, "Escribe un mensaje para el commit."); return; }
    showPending("result-commit");
    const res = await api("/api/commit", { repo_path: state.path, message });
    showResult("result-commit", res.ok, res.message);
    if (res.ok) { input.value = ""; refreshDashboard(); }
  });

  document.getElementById("pullBtn").addEventListener("click", async () => {
    showPending("result-syncop", "Descargando cambios...");
    const res = await api("/api/pull", { repo_path: state.path });
    showResult("result-syncop", res.ok, res.message);
    if (res.ok) refreshDashboard();
  });

  document.getElementById("pushBtn").addEventListener("click", () => openPushModal());

  document.getElementById("stashBtn").addEventListener("click", () => openStashModal());

  // -------------------------------------------------------------- branches --

  function renderBranches(branches) {
    const current = branches.find((b) => b.current);
    const hint = document.getElementById("renameMainHint");
    if (current && current.name !== "main" && branches.length === 1) {
      hint.style.display = "flex";
      hint.style.alignItems = "center";
      document.getElementById("renameMainText").textContent =
        "Tu rama principal se llama '" + current.name + "'. GitHub usa 'main' por defecto.";
    } else {
      hint.style.display = "none";
    }
    const ul = document.getElementById("branchList");
    ul.innerHTML = "";
    branches.forEach((b) => {
      const nameSpan = el("span", { class: b.current ? "branch-current" : "" }, [text(b.name + (b.current ? " (actual)" : ""))]);
      const actions = el("span", { class: "branch-actions" }, []);
      if (!b.current) {
        const switchBtn = el("button", { class: "btn-mini" }, [text("Cambiar")]);
        switchBtn.addEventListener("click", async () => {
          const res = await api("/api/branch/switch", { repo_path: state.path, name: b.name });
          showResult("result-branch", res.ok, res.message);
          if (res.ok) refreshDashboard();
        });
        const delBtn = el("button", { class: "btn-mini" }, [text("Eliminar")]);
        delBtn.addEventListener("click", () => confirmDestructive(
          "Eliminar rama " + b.name,
          "Si tiene cambios sin fusionar podrías perderlos. ¿Eliminar de todas formas?",
          async () => {
            let res = await api("/api/branch/delete", { repo_path: state.path, name: b.name });
            if (!res.ok) {
              res = await api("/api/branch/delete", { repo_path: state.path, name: b.name, force: true });
            }
            showResult("result-branch", res.ok, res.message);
            if (res.ok) refreshDashboard();
          }
        ));
        actions.appendChild(switchBtn);
        actions.appendChild(delBtn);
      }
      ul.appendChild(el("li", {}, [nameSpan, actions]));
    });
  }

  document.getElementById("createBranchBtn").addEventListener("click", async () => {
    const input = document.getElementById("newBranchName");
    const name = input.value.trim();
    if (!name) { showResult("result-branch", false, "Escribe un nombre de rama."); return; }
    const res = await api("/api/branch/create", { repo_path: state.path, name });
    showResult("result-branch", res.ok, res.message);
    if (res.ok) { input.value = ""; refreshDashboard(); }
  });

  document.getElementById("renameMainBtn").addEventListener("click", async () => {
    const res = await api("/api/branch/rename", { repo_path: state.path, name: "main" });
    showResult("result-branch", res.ok, res.message);
    if (res.ok) refreshDashboard();
  });

  // ------------------------------------------------------------------ log --

  function renderLog(entries) {
    const ul = document.getElementById("logList");
    ul.innerHTML = "";
    if (!entries.length) {
      ul.appendChild(el("li", { class: "muted" }, [text("Todavía no hay commits.")]));
      return;
    }
    entries.forEach((e) => {
      ul.appendChild(el("li", {}, [
        el("div", {}, [el("span", { class: "log-hash" }, [text(e.hash)]), text(e.subject)]),
        el("div", { class: "log-meta" }, [text(e.author + " · " + e.when)]),
      ]));
    });
  }

  // --------------------------------------------------------------- stash --

  function renderStashes(stashes) {
    const box = document.getElementById("stashList");
    box.innerHTML = "";
    if (!stashes.length) return;
    stashes.forEach((line, i) => {
      const ref = "stash@{" + i + "}";
      const row = el("div", { class: "stash-row" }, [
        el("span", {}, [text(line)]),
      ]);
      const actions = el("span", {}, []);
      if (i === 0) {
        const popBtn = el("button", { class: "btn-mini" }, [text("Aplicar")]);
        popBtn.addEventListener("click", async () => {
          const res = await api("/api/stash/pop", { repo_path: state.path });
          showResult("result-syncop", res.ok, res.message);
          if (res.ok) refreshDashboard();
        });
        actions.appendChild(popBtn);
      }
      const dropBtn = el("button", { class: "btn-mini" }, [text("Borrar")]);
      dropBtn.addEventListener("click", () => confirmDestructive(
        "Borrar " + ref,
        "Este cambio guardado se perderá para siempre.",
        async () => {
          const res = await api("/api/stash/drop", { repo_path: state.path, ref });
          showResult("result-syncop", res.ok, res.message);
          if (res.ok) refreshDashboard();
        }
      ));
      actions.appendChild(dropBtn);
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  function openStashModal() {
    openModal({
      title: "Guardar cambios en stash",
      bodyHtml: '<div class="field-col"><input type="text" id="stashMsgInput" placeholder="Descripción (opcional)"></div>',
      actions: [
        { label: "Cancelar", cls: "btn-ghost", onClick: closeModal },
        {
          label: "Guardar", cls: "btn-primary", onClick: async () => {
            const msg = document.getElementById("stashMsgInput").value.trim();
            closeModal();
            showPending("result-syncop", "Guardando en stash...");
            const res = await api("/api/stash/save", { repo_path: state.path, message: msg });
            showResult("result-syncop", res.ok, res.message);
            if (res.ok) refreshDashboard();
          },
        },
      ],
    });
  }

  // ---------------------------------------------------------------- push --

  function openPushModal() {
    const branch = (state.bundle.status.branch || "main");
    openModal({
      title: "Push a GitHub",
      bodyHtml: `
        <div class="field-col">
          <input type="password" id="pushToken" placeholder="Token de GitHub (PAT)">
          <label style="display:flex;align-items:flex-start;gap:9px;color:var(--amber);font-size:0.85em;cursor:pointer;">
            <input id="pushForce" type="checkbox" style="width:auto;margin-top:3px;">
            <span>Forzar push (sobrescribe la rama <b>${esc(branch)}</b> en GitHub). Úsalo solo si estás seguro.</span>
          </label>
        </div>`,
      actions: [
        { label: "Cancelar", cls: "btn-ghost", onClick: closeModal },
        {
          label: "Hacer Push", cls: "btn-primary", onClick: async () => {
            const token = document.getElementById("pushToken").value.trim();
            const force = document.getElementById("pushForce").checked;
            if (!token) return;
            document.getElementById("modalBody").innerHTML = '<p class="muted">Subiendo a GitHub...</p>';
            document.getElementById("modalActions").innerHTML = "";
            const res = await api("/api/push", { repo_path: state.path, token, force, branch });
            closeModal();
            showResult("result-syncop", res.ok, res.message);
            if (res.ok) refreshDashboard();
          },
        },
      ],
    });
  }

  // ---------------------------------------------------------------- diff --

  function colorizeDiff(diffText) {
    return diffText.split("\n").map((line) => {
      const safe = esc(line);
      if (line.startsWith("+++") || line.startsWith("---")) return safe;
      if (line.startsWith("+")) return '<span class="diff-add">' + safe + "</span>";
      if (line.startsWith("-")) return '<span class="diff-del">' + safe + "</span>";
      if (line.startsWith("@@")) return '<span class="diff-hunk">' + safe + "</span>";
      return safe;
    }).join("\n");
  }

  async function openDiffModal(file, staged) {
    openModal({ title: file, bodyHtml: '<p class="muted">Cargando diferencias...</p>', actions: [{ label: "Cerrar", cls: "btn-ghost", onClick: closeModal }] });
    const res = await api("/api/diff", { repo_path: state.path, file, staged });
    document.getElementById("modalBody").innerHTML = '<pre>' + colorizeDiff(res.diff || "Sin diferencias.") + "</pre>";
  }

  // --------------------------------------------------------------- config --

  document.getElementById("cfgIdentityBtn").addEventListener("click", async () => {
    const name = document.getElementById("cfgName").value.trim();
    const email = document.getElementById("cfgEmail").value.trim();
    const res = await api("/api/step", { step: "identity", repo_path: state.path, name, email });
    showResult("result-cfgIdentity", res.ok, res.message);
    if (res.ok) refreshDashboard();
  });

  document.getElementById("cfgRemoteBtn").addEventListener("click", async () => {
    const url = document.getElementById("cfgRemote").value.trim();
    const res = await api("/api/step", { step: "remote", repo_path: state.path, remote_url: url });
    showResult("result-cfgRemote", res.ok, res.message);
    if (res.ok) refreshDashboard();
  });

  document.getElementById("cfgGitignoreBtn").addEventListener("click", async () => {
    const content = document.getElementById("cfgGitignore").value;
    const res = await api("/api/gitignore/save", { repo_path: state.path, content });
    showResult("result-cfgGitignore", res.ok, res.message);
  });

  // ---------------------------------------------------------------- modal --

  function openModal({ title, bodyHtml, actions }) {
    document.getElementById("modalTitle").textContent = title;
    document.getElementById("modalBody").innerHTML = bodyHtml;
    const actionsBox = document.getElementById("modalActions");
    actionsBox.innerHTML = "";
    actions.forEach((a) => {
      const btn = el("button", { class: "btn " + (a.cls || "btn-outline") }, [text(a.label)]);
      btn.addEventListener("click", a.onClick);
      actionsBox.appendChild(btn);
    });
    document.getElementById("modalBackdrop").classList.add("show");
  }

  function closeModal() {
    document.getElementById("modalBackdrop").classList.remove("show");
  }

  document.getElementById("modalClose").addEventListener("click", closeModal);
  document.getElementById("modalBackdrop").addEventListener("click", (ev) => {
    if (ev.target.id === "modalBackdrop") closeModal();
  });

  function confirmDestructive(title, message, onConfirm) {
    openModal({
      title,
      bodyHtml: '<p>' + esc(message) + '</p>',
      actions: [
        { label: "Cancelar", cls: "btn-ghost", onClick: closeModal },
        { label: "Confirmar", cls: "btn-danger", onClick: async () => { closeModal(); await onConfirm(); } },
      ],
    });
  }
})();
