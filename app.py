from flask import Flask, render_template, request, jsonify

import gitops
import store

app = Flask(__name__)

# Single-user, single-active-repo tool (matches how it's actually used on a
# phone: one person, one project open at a time). Persisted recents let it
# survive Termux killing the process.
CURRENT_REPO = store.last_repo()


def _payload():
    return request.get_json(silent=True) or request.form


def _path_from(payload):
    return gitops.expand_path(payload.get("repo_path", CURRENT_REPO))


def bundle(path):
    """Full state needed to render either the wizard or the dashboard."""
    data = gitops.status_data(path)
    staged, unstaged, untracked = gitops.file_changes(path)
    return {
        "status": data,
        "files": {"staged": staged, "unstaged": unstaged, "untracked": untracked},
        "branches": gitops.list_branches(path),
        "log": gitops.log_entries(path, limit=40),
        "stashes": gitops.list_stashes(path),
        "gitignore": gitops.read_gitignore(path) if data["is_git"] else "",
        "recents": store.load_recents(),
    }


@app.route("/")
def index():
    return render_template("index.html", initial_path=CURRENT_REPO)


@app.route("/api/bootstrap", methods=["POST"])
def api_bootstrap():
    """Called on page load. Uses the given path, or falls back to the last one used."""
    global CURRENT_REPO
    payload = _payload()
    requested = (payload.get("repo_path") or "").strip() if hasattr(payload, "get") else ""
    path = gitops.expand_path(requested) if requested else CURRENT_REPO
    CURRENT_REPO = path
    return jsonify(bundle(path))


@app.route("/api/open", methods=["POST"])
def api_open():
    """Explicitly switch the active repo (used by the folder picker / recents list)."""
    global CURRENT_REPO
    payload = _payload()
    path = gitops.expand_path(payload.get("repo_path", ""))
    ok, message = gitops.path_diagnostics(path)
    if not ok:
        return jsonify(ok=False, message=message)
    CURRENT_REPO = path
    if gitops.valid_repo(path):
        store.add_recent(path)
    result = bundle(path)
    result["ok"] = True
    result["message"] = message
    return jsonify(result)


@app.route("/api/recent/remove", methods=["POST"])
def api_recent_remove():
    payload = _payload()
    path = gitops.expand_path(payload.get("path", ""))
    recents = store.remove_recent(path)
    return jsonify(ok=True, recents=recents)


# --------------------------------------------------------------- wizard --
# Only the true one-time setup steps live here: git present, folder chosen,
# repo initialized, identity set, remote linked. Everything else (staging,
# committing, pushing, branches...) is a normal dashboard action available
# any time, not a locked linear step.

@app.route("/api/step", methods=["POST"])
def api_step():
    global CURRENT_REPO
    payload = _payload()
    step = payload.get("step", "")
    path = _path_from(payload)
    CURRENT_REPO = path

    if step == "check_git":
        import shutil
        if shutil.which("git"):
            ok, out = gitops.run_command(["git", "--version"])
            return jsonify(ok=ok, message=out)
        return jsonify(ok=False, message="Git no está instalado. En Termux ejecuta: pkg update && pkg install git")

    if step == "choose_folder":
        ok, message = gitops.path_diagnostics(path)
        if not ok:
            return jsonify(ok=False, message=message)
        return jsonify(ok=True, path=path, message=message)

    if step == "init":
        ok_path, path_message = gitops.path_diagnostics(path)
        if not ok_path:
            return jsonify(ok=False, message=path_message)
        if gitops.valid_repo(path):
            store.add_recent(path)
            return jsonify(ok=True, already=True, message="Git ya estaba inicializado en esta carpeta.")
        ok, out = gitops.git(["init"], path)
        if not ok:
            return jsonify(ok=False, message=f"git init falló en {path}\n\n{out}")
        if not gitops.valid_repo(path):
            return jsonify(ok=False, message=f"Git terminó sin error, pero no se pudo abrir el repositorio en:\n{path}\n\nEsto suele indicar permisos de almacenamiento en Termux. Ejecuta termux-setup-storage.")
        store.add_recent(path)
        return jsonify(ok=True, message=out if out else f"Repositorio Git creado en {path}")

    if step == "clone":
        url = (payload.get("clone_url") or "").strip()
        token = (payload.get("token") or "").strip()
        if not url:
            return jsonify(ok=False, message="Pega la URL HTTPS del repositorio a clonar.")
        ok, out = gitops.clone_repo(path, url, token)
        if ok:
            store.add_recent(path)
        return jsonify(ok=ok, message=out)

    if step == "identity":
        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip()
        if not gitops.valid_repo(path):
            return jsonify(ok=False, message="Esta carpeta todavía no tiene un repositorio Git válido. Vuelve al paso anterior e inicialízalo.")
        if not name or not email:
            return jsonify(ok=False, message="Escribe tu nombre y correo de Git.")
        ok, message = gitops.set_identity(path, name, email)
        return jsonify(ok=ok, message=message)

    if step == "remote":
        url = (payload.get("remote_url") or "").strip()
        if not gitops.valid_repo(path):
            return jsonify(ok=False, message="Primero inicializa Git.")
        if not url.startswith(("https://", "http://", "git@", "ssh://")):
            return jsonify(ok=False, message="Introduce una URL válida de GitHub, por ejemplo https://github.com/usuario/repo.git")
        ok, out = gitops.set_remote(path, url)
        return jsonify(ok=ok, message=out if out else "Repositorio remoto configurado.")

    return jsonify(ok=False, message="Paso desconocido."), 400


# ------------------------------------------------------------- dashboard --

def _require_repo(path):
    return gitops.valid_repo(path)


@app.route("/api/diff", methods=["POST"])
def api_diff():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    filename = payload.get("file") or None
    staged = bool(payload.get("staged", False))
    return jsonify(ok=True, diff=gitops.diff_text(path, filename, staged))


@app.route("/api/add", methods=["POST"])
def api_add():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    files = payload.get("files") or None
    ok, out = gitops.add_files(path, files)
    return jsonify(ok=ok, message=out if out else "Archivos preparados.")


@app.route("/api/unstage", methods=["POST"])
def api_unstage():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    files = payload.get("files") or None
    ok, out = gitops.unstage_files(path, files)
    return jsonify(ok=ok, message=out if out else "Cambios sin preparar.")


@app.route("/api/discard", methods=["POST"])
def api_discard():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    files = payload.get("files") or []
    if not files:
        return jsonify(ok=False, message="No se indicaron archivos.")
    ok, out = gitops.discard_files(path, files)
    return jsonify(ok=ok, message=out if out else "Cambios descartados.")


@app.route("/api/remove_untracked", methods=["POST"])
def api_remove_untracked():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    files = payload.get("files") or []
    if not files:
        return jsonify(ok=False, message="No se indicaron archivos.")
    ok, out = gitops.remove_untracked(path, files)
    return jsonify(ok=ok, message=out)


@app.route("/api/commit", methods=["POST"])
def api_commit():
    payload = _payload()
    path = _path_from(payload)
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify(ok=False, message="Escribe un mensaje para el commit.")
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.commit(path, message)
    return jsonify(ok=ok, message=out)


@app.route("/api/pull", methods=["POST"])
def api_pull():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.pull(path)
    return jsonify(ok=ok, message=out)


@app.route("/api/push", methods=["POST"])
def api_push():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    token = (payload.get("token") or "").strip()
    force = bool(payload.get("force", False))
    branch = (payload.get("branch") or "").strip() or None
    ok, out = gitops.push(path, token, branch=branch, force=force)
    return jsonify(ok=ok, message=out)


@app.route("/api/branch/rename", methods=["POST"])
def api_branch_rename():
    payload = _payload()
    path = _path_from(payload)
    name = (payload.get("name") or "main").strip()
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.rename_branch(path, name)
    return jsonify(ok=ok, message=out if out else f"La rama actual ahora es {name}.")


@app.route("/api/branch/create", methods=["POST"])
def api_branch_create():
    payload = _payload()
    path = _path_from(payload)
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, message="Escribe un nombre de rama.")
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.create_branch(path, name)
    return jsonify(ok=ok, message=out if out else f"Rama {name} creada.")


@app.route("/api/branch/switch", methods=["POST"])
def api_branch_switch():
    payload = _payload()
    path = _path_from(payload)
    name = (payload.get("name") or "").strip()
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.switch_branch(path, name)
    return jsonify(ok=ok, message=out if out else f"Cambiado a {name}.")


@app.route("/api/branch/delete", methods=["POST"])
def api_branch_delete():
    payload = _payload()
    path = _path_from(payload)
    name = (payload.get("name") or "").strip()
    force = bool(payload.get("force", False))
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.delete_branch(path, name, force)
    return jsonify(ok=ok, message=out)


@app.route("/api/stash/save", methods=["POST"])
def api_stash_save():
    payload = _payload()
    path = _path_from(payload)
    message = (payload.get("message") or "").strip()
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.stash_save(path, message)
    return jsonify(ok=ok, message=out)


@app.route("/api/stash/pop", methods=["POST"])
def api_stash_pop():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.stash_pop(path)
    return jsonify(ok=ok, message=out)


@app.route("/api/stash/drop", methods=["POST"])
def api_stash_drop():
    payload = _payload()
    path = _path_from(payload)
    ref = (payload.get("ref") or "stash@{0}").strip()
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    ok, out = gitops.stash_drop(path, ref)
    return jsonify(ok=ok, message=out)


@app.route("/api/gitignore/save", methods=["POST"])
def api_gitignore_save():
    payload = _payload()
    path = _path_from(payload)
    if not _require_repo(path):
        return jsonify(ok=False, message="No hay un repositorio Git válido.")
    content = payload.get("content", "")
    ok, message = gitops.write_gitignore(path, content)
    return jsonify(ok=ok, message=message)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
