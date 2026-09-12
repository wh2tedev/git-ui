"""
gitops.py — All git/subprocess logic for Git UI.

Kept separate from routes.py so the Flask layer stays thin and the git
plumbing can be tested/reused on its own.
"""
import os
import re
import shutil
import subprocess
import tempfile


# ---------------------------------------------------------------- helpers --

def expand_path(path):
    """Normalize only the path supplied by the user. Never fall back to the app folder."""
    raw = (path or "").strip()
    if not raw:
        return ""
    return os.path.realpath(os.path.abspath(os.path.expanduser(raw)))


def run_command(command, repo_path=None, env=None, timeout=60, allow_error=False):
    try:
        result = subprocess.run(
            command,
            cwd=repo_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        # rstrip only (never lstrip): git's porcelain status format uses a
        # meaningful leading space ("X" index-status column left blank), and
        # stripping it shifts every filename by one character, silently
        # corrupting which files look staged vs. unstaged.
        output = (result.stdout or "").rstrip()
        error = (result.stderr or "").rstrip()
        if result.returncode != 0 and not allow_error:
            return False, error or output or f"El comando terminó con código {result.returncode}."
        # Deliberately no "no output" filler text here: many callers parse
        # this output as data (status, branches, stashes, log...), and empty
        # output on success (e.g. a clean tree) must stay an empty string,
        # not a sentence that then gets mistaken for a real git status/branch
        # entry. Callers that show this as a user-facing message are
        # responsible for supplying their own friendly fallback when out=="".
        return result.returncode == 0, output or error
    except FileNotFoundError:
        return False, "Git no está instalado o no está disponible en PATH."
    except subprocess.TimeoutExpired:
        return False, "El comando tardó demasiado y fue detenido."
    except Exception as exc:
        return False, str(exc)


def git(command, repo_path=None, timeout=60, allow_error=False, env=None):
    # Always target the exact path supplied by the user. On Android shared
    # storage, Git may also complain about repository ownership, so explicitly
    # mark this exact worktree as safe for this invocation.
    cmd = ["git"]
    if repo_path:
        cmd += ["-c", f"safe.directory={repo_path}", "-C", repo_path]
    cmd += command
    return run_command(cmd, env=env, timeout=timeout, allow_error=allow_error)


def valid_repo(path):
    """Check the exact user-selected directory without relying on cwd."""
    if not path or not os.path.isdir(path):
        return False
    git_dir = os.path.join(path, ".git")
    if not (os.path.isdir(git_dir) or os.path.isfile(git_dir)):
        return False
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={path}", "-C", path,
             "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=10, check=False
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def path_diagnostics(path):
    """Return actionable diagnostics for Android/Termux shared storage."""
    if not path:
        return False, "Escribe la ruta de la carpeta del proyecto."
    if not os.path.exists(path):
        return False, f"La ruta no existe: {path}"
    if not os.path.isdir(path):
        return False, f"La ruta existe, pero no es una carpeta: {path}"
    if not os.access(path, os.R_OK):
        return False, f"Termux no puede leer esta carpeta: {path}. Ejecuta termux-setup-storage."
    if not os.access(path, os.W_OK):
        return False, f"Termux no puede escribir en esta carpeta: {path}. Ejecuta termux-setup-storage y vuelve a probar."
    return True, f"Carpeta accesible: {path}"


def mask_url(url):
    if not url:
        return ""
    return re.sub(r"(https?://)([^/@:]+):([^/@]+)@", r"\1***:***@", url)


# ------------------------------------------------------------ status/info --

def current_branch(path):
    ok, out = git(["branch", "--show-current"], path, allow_error=True)
    return out if ok and out else ""


def ahead_behind(path, branch):
    """Returns (ahead, behind) vs the upstream, or (None, None) if there isn't one."""
    if not branch:
        return None, None
    ok, upstream = git(["rev-parse", "--abbrev-ref", f"{branch}@{{u}}"], path, allow_error=True)
    if not ok or not upstream:
        return None, None
    ok, out = git(["rev-list", "--left-right", "--count", f"{upstream}...{branch}"], path, allow_error=True)
    if not ok or not out:
        return None, None
    try:
        behind_s, ahead_s = out.split()
        return int(ahead_s), int(behind_s)
    except (ValueError, AttributeError):
        return None, None


def status_data(path):
    data = {
        "path": path,
        "exists": bool(path) and os.path.isdir(path),
        "is_git": valid_repo(path),
        "git_installed": shutil.which("git") is not None,
        "name": "",
        "email": "",
        "remote": "",
        "remote_masked": "No configurado",
        "remote_scheme": "",
        "branch": "",
        "has_changes": False,
        "has_commits": False,
        "ahead": None,
        "behind": None,
        "merging": False,
    }
    if not data["git_installed"] or not data["is_git"]:
        return data

    ok, out = git(["config", "user.name"], path, allow_error=True)
    data["name"] = out if ok else ""
    ok, out = git(["config", "user.email"], path, allow_error=True)
    data["email"] = out if ok else ""
    ok, out = git(["remote", "get-url", "origin"], path, allow_error=True)
    data["remote"] = out if ok else ""
    data["remote_masked"] = mask_url(out) if ok else "No configurado"
    data["remote_scheme"] = remote_scheme(data["remote"])
    data["merging"] = merge_in_progress(path)
    branch = current_branch(path)
    data["branch"] = branch or "(sin rama)"
    ok, out = git(["status", "--short"], path, allow_error=True)
    data["has_changes"] = bool(out.strip()) if ok else False
    ok, out = git(["rev-parse", "--verify", "HEAD"], path, allow_error=True)
    data["has_commits"] = ok
    data["ahead"], data["behind"] = ahead_behind(path, branch)
    return data


_STATUS_LABELS = {
    "M": "Modificado", "A": "Añadido", "D": "Eliminado", "R": "Renombrado",
    "C": "Copiado", "U": "Conflicto", "?": "Sin seguimiento", "T": "Tipo cambiado",
}


def file_changes(path):
    """Parse `git status --porcelain=v1 -z` into staged/unstaged/untracked lists."""
    staged, unstaged, untracked = [], [], []
    if not valid_repo(path):
        return staged, unstaged, untracked
    ok, out = run_command(
        ["git", "-c", f"safe.directory={path}", "-C", path, "status", "--porcelain=v1", "-z"],
        timeout=30, allow_error=True,
    )
    if not ok or not out:
        return staged, unstaged, untracked
    # -z output is NUL separated; rename entries have an extra NUL-separated
    # "from" field, but we only need the "to" filename for display/actions.
    parts = out.split("\x00")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        index_status, worktree_status = entry[0], entry[1]
        filename = entry[3:]
        if index_status in ("R", "C"):
            i += 1  # skip the "from" filename
        if index_status == "?" and worktree_status == "?":
            untracked.append({"file": filename, "label": "Sin seguimiento"})
            continue
        if index_status not in (" ", "?"):
            staged.append({"file": filename, "label": _STATUS_LABELS.get(index_status, index_status)})
        if worktree_status not in (" ", "?"):
            unstaged.append({"file": filename, "label": _STATUS_LABELS.get(worktree_status, worktree_status)})
    return staged, unstaged, untracked


def diff_text(path, filename=None, staged=False):
    args = ["diff", "--no-color"]
    if staged:
        args.insert(1, "--cached")
    if filename:
        args += ["--", filename]
    ok, out = git(args, path, allow_error=True)
    return out if out else "Sin diferencias."


def log_entries(path, limit=40):
    if not valid_repo(path):
        return []
    fmt = "%h\x1f%an\x1f%ar\x1f%s"
    ok, out = git(["log", f"-{limit}", f"--pretty=format:{fmt}"], path, allow_error=True)
    if not ok or not out:
        return []
    entries = []
    for line in out.split("\n"):
        parts = line.split("\x1f")
        if len(parts) == 4:
            entries.append({"hash": parts[0], "author": parts[1], "when": parts[2], "subject": parts[3]})
    return entries


def list_branches(path):
    if not valid_repo(path):
        return []
    ok, out = git(["branch", "--list"], path, allow_error=True)
    if not ok or not out:
        return []
    branches = []
    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        current = line.startswith("*")
        name = line.lstrip("* ").strip()
        if name and "->" not in name:
            branches.append({"name": name, "current": current})
    return branches


def list_stashes(path):
    if not valid_repo(path):
        return []
    ok, out = git(["stash", "list"], path, allow_error=True)
    if not ok or not out:
        return []
    return [line for line in out.split("\n") if line.strip()]


def read_gitignore(path):
    gi_path = os.path.join(path, ".gitignore")
    if os.path.isfile(gi_path):
        try:
            with open(gi_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""
    return ""


def write_gitignore(path, content):
    gi_path = os.path.join(path, ".gitignore")
    try:
        with open(gi_path, "w", encoding="utf-8") as f:
            f.write(content if content.endswith("\n") or not content else content + "\n")
        return True, "Archivo .gitignore guardado."
    except OSError as exc:
        return False, f"No se pudo guardar .gitignore: {exc}"


# ------------------------------------------------------------- mutations --

def add_files(path, files=None):
    args = ["add", "--"] + files if files else ["add", "."]
    return git(args, path)


def unstage_files(path, files=None):
    args = ["restore", "--staged", "--"] + files if files else ["restore", "--staged", "."]
    return git(args, path)


def discard_files(path, files):
    """Discard unstaged changes to tracked files (does not touch untracked files)."""
    return git(["checkout", "--"] + files, path)


def remove_untracked(path, files):
    """Delete untracked files from disk (git clean, scoped to specific paths)."""
    ok_all = True
    messages = []
    for f in files:
        full = os.path.join(path, f)
        try:
            if os.path.isdir(full) and not os.path.islink(full):
                shutil.rmtree(full)
            elif os.path.exists(full) or os.path.islink(full):
                os.remove(full)
            messages.append(f"Eliminado: {f}")
        except OSError as exc:
            ok_all = False
            messages.append(f"No se pudo eliminar {f}: {exc}")
    return ok_all, "\n".join(messages) if messages else "Nada que eliminar."


def commit(path, message):
    return git(["commit", "-m", message], path)


def set_identity(path, name, email):
    ok1, out1 = git(["config", "--local", "user.name", name], path)
    if not ok1:
        return False, out1
    ok2, out2 = git(["config", "--local", "user.email", email], path)
    if not ok2:
        return False, out2
    return True, "Identidad guardada correctamente en este repositorio."


def set_remote(path, url):
    ok, existing = git(["remote", "get-url", "origin"], path, allow_error=True)
    if ok and existing:
        return git(["remote", "set-url", "origin", url], path)
    return git(["remote", "add", "origin", url], path)


def rename_branch(path, new_name):
    return git(["branch", "-M", new_name], path)


def create_branch(path, name, switch=True):
    return git(["checkout", "-b", name], path) if switch else git(["branch", name], path)


def switch_branch(path, name):
    return git(["checkout", name], path)


def delete_branch(path, name, force=False):
    return git(["branch", "-D" if force else "-d", name], path)


def stash_save(path, message=""):
    args = ["stash", "push"]
    if message:
        args += ["-m", message]
    ok, out = git(args, path)
    return ok, out if out else "Cambios guardados en stash."


def stash_pop(path):
    return git(["stash", "pop"], path)


def stash_drop(path, ref="stash@{0}"):
    return git(["stash", "drop", ref], path)


def pull(path):
    # --no-rebase pins the strategy to a plain merge regardless of the
    # user's global git config. Without this, modern Git refuses to pull at
    # all on diverged branches ("Need to specify how to reconcile divergent
    # branches") before ever attempting a merge — which would hide real
    # conflicts behind a confusing git-config wall of text instead of
    # reaching our conflict-resolution UI.
    ok, out = git(["pull", "--no-rebase"], path, timeout=120)
    return ok, out if out else "Ya estás al día."


def merge_in_progress(path):
    return os.path.isfile(os.path.join(path, ".git", "MERGE_HEAD"))


def conflicted_files(path):
    """Files with unresolved merge conflicts (git diff --diff-filter=U)."""
    ok, out = git(["diff", "--name-only", "--diff-filter=U"], path, allow_error=True)
    if not ok or not out:
        return []
    return [line for line in out.split("\n") if line.strip()]


_CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def files_still_have_markers(path, files):
    """Of the given files, which still contain literal <<<<<<< conflict
    markers in their content — i.e. haven't actually been hand-edited yet,
    even though Git still lists them as unmerged either way."""
    still = []
    for f in files:
        full = os.path.join(path, f)
        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            if any(marker in content for marker in _CONFLICT_MARKERS):
                still.append(f)
        except OSError:
            continue
    return still


def abort_merge(path):
    return git(["merge", "--abort"], path)


def remote_scheme(url):
    """'ssh', 'https', or '' (no remote / unrecognized)."""
    if not url:
        return ""
    if url.startswith(("git@", "ssh://")):
        return "ssh"
    if url.startswith(("https://", "http://")):
        return "https"
    return ""


def clone_repo(path, url, token=""):
    parent = os.path.dirname(path.rstrip("/")) or "/"
    target_name = os.path.basename(path.rstrip("/"))
    if not os.path.isdir(parent):
        return False, f"La carpeta contenedora no existe: {parent}"
    if os.path.exists(path) and os.listdir(path):
        return False, f"La carpeta destino ya existe y no está vacía: {path}"
    env = None
    askpass = None
    if token and remote_scheme(url) == "https":
        askpass, env = _askpass_env(token)
    try:
        ok, out = git(["clone", url, target_name], repo_path=parent, timeout=180, env=env)
    finally:
        if askpass:
            try:
                os.remove(askpass)
            except OSError:
                pass
    return ok, out


def _askpass_env(token):
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        askpass = f.name
        f.write("#!/bin/sh\ncase \"$1\" in\n  *Username*) printf '%s\\n' \"$GIT_USERNAME\" ;;\n  *) printf '%s\\n' \"$GIT_PASSWORD\" ;;\nesac\n")
    os.chmod(askpass, 0o700)
    env = os.environ.copy()
    env["GIT_ASKPASS"] = askpass
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_USERNAME"] = "git"
    env["GIT_PASSWORD"] = token
    return askpass, env


def notify_termux(title, message):
    """Best-effort Termux:API notification. Silently does nothing if not installed."""
    if not shutil.which("termux-notification"):
        return
    try:
        subprocess.run(
            ["termux-notification", "--title", title, "--content", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def push(path, token, branch=None, force=False, set_upstream=True):
    if not branch:
        branch = current_branch(path)
    if not branch:
        return False, "No se pudo determinar la rama actual. Crea un commit primero."
    remote_ok, remote = git(["remote", "get-url", "origin"], path, allow_error=True)
    if not remote_ok or not remote:
        return False, "No hay un remoto 'origin' configurado."

    scheme = remote_scheme(remote)
    if scheme == "":
        return False, "El remoto configurado no es una URL https:// ni ssh:// reconocida."

    env = None
    askpass = None
    if scheme == "https":
        if not token:
            return False, "Introduce tu token de GitHub para hacer Push."
        askpass, env = _askpass_env(token)
    # scheme == "ssh": no token needed — relies on the SSH key already set up
    # in Termux (ssh-agent or a key file Git/OpenSSH is configured to use).

    try:
        push_args = ["push"]
        if set_upstream:
            push_args += ["-u"]
        if force:
            push_args += ["--force"]
        push_args += ["origin", branch]
        ok, out = run_command(
            ["git", "-c", f"safe.directory={path}", "-C", path, *push_args],
            env=env, timeout=120,
        )
    finally:
        if askpass:
            try:
                os.remove(askpass)
            except OSError:
                pass

    if not ok and ("rejected" in out.lower() or "non-fast-forward" in out.lower() or "fetch first" in out.lower()):
        out += "\n\nGitHub tiene commits que no están en tu copia local. Usa «Pull» antes de volver a intentar el Push (o Push forzado si quieres sobrescribir GitHub)."
    if not ok and scheme == "ssh" and ("permission denied" in out.lower() or "publickey" in out.lower()):
        out += "\n\nTermux no pudo autenticarse por SSH. Revisa que tu llave esté cargada (ssh-add) y agregada en GitHub."
    notify_termux("Git UI", ("Push completado: " if ok else "Push falló: ") + branch)
    return ok, out if out else "Push completado."
