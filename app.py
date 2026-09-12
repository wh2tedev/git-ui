from flask import Flask, render_template, request, jsonify
import os
import re
import shutil
import subprocess
import tempfile

app = Flask(__name__)
CURRENT_REPO = ""


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
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode != 0 and not allow_error:
            return False, error or output or f"El comando terminó con código {result.returncode}."
        return result.returncode == 0, output or error or "Completado sin salida."
    except FileNotFoundError:
        return False, "Git no está instalado o no está disponible en PATH."
    except subprocess.TimeoutExpired:
        return False, "El comando tardó demasiado y fue detenido."
    except Exception as exc:
        return False, str(exc)


def git(command, repo_path=None, timeout=60, allow_error=False):
    # Always target the exact path supplied by the user. On Android shared
    # storage, Git may also complain about repository ownership, so explicitly
    # mark this exact worktree as safe for this invocation.
    cmd = ["git"]
    if repo_path:
        cmd += ["-c", f"safe.directory={repo_path}", "-C", repo_path]
    cmd += command
    return run_command(cmd, timeout=timeout, allow_error=allow_error)


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
        return "No configurado"
    return re.sub(r"(https?://)([^/@:]+):([^/@]+)@", r"\1***:***@", url)


def status_data(path):
    data = {
        "path": path,
        "exists": bool(path) and os.path.isdir(path),
        "is_git": valid_repo(path),
        "git_installed": shutil.which("git") is not None,
        "name": "",
        "email": "",
        "remote": "No configurado",
        "branch": "Desconocida",
        "status": "",
        "has_changes": False,
        "has_commits": False,
    }
    if not data["git_installed"] or not data["is_git"]:
        return data

    ok, out = git(["config", "user.name"], path, allow_error=True)
    data["name"] = out if ok else ""
    ok, out = git(["config", "user.email"], path, allow_error=True)
    data["email"] = out if ok else ""
    ok, out = git(["remote", "get-url", "origin"], path, allow_error=True)
    data["remote"] = mask_url(out) if ok else "No configurado"
    ok, out = git(["branch", "--show-current"], path, allow_error=True)
    data["branch"] = out if ok and out else "(sin rama)"
    ok, out = git(["status", "--short"], path, allow_error=True)
    data["status"] = out
    data["has_changes"] = bool(out.strip()) if ok else False
    ok, out = git(["rev-parse", "--verify", "HEAD"], path, allow_error=True)
    data["has_commits"] = ok
    return data


@app.route("/")
def index():
    return render_template("index.html", repo_path=CURRENT_REPO, data=status_data(CURRENT_REPO), feedback="")


@app.route("/api/status", methods=["POST"])
def api_status():
    global CURRENT_REPO
    path = request.json.get("repo_path", CURRENT_REPO) if request.is_json else request.form.get("repo_path", CURRENT_REPO)
    path = expand_path(path)
    CURRENT_REPO = path
    return jsonify(status_data(path))


@app.route("/api/step", methods=["POST"])
def api_step():
    global CURRENT_REPO
    payload = request.get_json(silent=True) or request.form
    step = payload.get("step", "")
    path = expand_path(payload.get("repo_path", CURRENT_REPO))
    CURRENT_REPO = path

    if step == "check_git":
        if shutil.which("git"):
            ok, out = run_command(["git", "--version"])
            return jsonify(ok=ok, message=out)
        return jsonify(ok=False, message="Git no está instalado. En Termux ejecuta: pkg update && pkg install git")

    if step == "choose_folder":
        ok, message = path_diagnostics(path)
        if not ok:
            return jsonify(ok=False, message=message)
        return jsonify(ok=True, path=path, message=message)

    if step == "init":
        ok_path, path_message = path_diagnostics(path)
        if not ok_path:
            return jsonify(ok=False, message=path_message)
        if valid_repo(path):
            return jsonify(ok=True, already=True, message="Git ya estaba inicializado en esta carpeta.")
        ok, out = git(["init"], path)
        if not ok:
            return jsonify(ok=False, message=f"git init falló en {path}\n\n{out}")
        # Verify the actual .git directory first; rev-parse is also checked
        # with safe.directory for Android shared-storage ownership quirks.
        if not (os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(os.path.join(path, ".git"))):
            return jsonify(ok=False, message=f"Git terminó sin error, pero no apareció .git en:\n{path}\n\nSalida: {out}")
        if not valid_repo(path):
            return jsonify(ok=False, message=f"Se creó .git, pero Git no puede abrir el repositorio en:\n{path}\n\nEsto suele indicar permisos de almacenamiento en Termux.")
        return jsonify(ok=True, message=out if out else f"Repositorio Git creado en {path}")

    if step == "identity":
        name = payload.get("name", "").strip()
        email = payload.get("email", "").strip()
        if not os.path.isdir(path):
            return jsonify(ok=False, message="La carpeta del proyecto no existe.")
        if not valid_repo(path):
            # The browser progress indicator is only cosmetic; verify the real
            # repository on disk and give a precise recovery action.
            return jsonify(ok=False, message="Esta carpeta todavía no tiene un repositorio Git válido. Vuelve al paso 3 y pulsa «Inicializar Git».")
        if not name or not email:
            return jsonify(ok=False, message="Escribe tu nombre y correo de Git.")
        # Explicitly write to this repository's local .git/config.
        ok1, out1 = git(["config", "--local", "user.name", name], path)
        ok2, out2 = git(["config", "--local", "user.email", email], path) if ok1 else (False, "No se pudo guardar el nombre.")
        if ok1 and ok2:
            return jsonify(ok=True, message="Identidad guardada correctamente en este repositorio.")
        return jsonify(ok=False, message=out1 if not ok1 else out2)

    if step == "remote":
        url = payload.get("remote_url", "").strip()
        if not valid_repo(path):
            return jsonify(ok=False, message="Primero inicializa Git.")
        if not url.startswith(("https://", "http://", "git@", "ssh://")):
            return jsonify(ok=False, message="Introduce una URL válida de GitHub, por ejemplo https://github.com/usuario/repo.git")
        ok, existing = git(["remote", "get-url", "origin"], path, allow_error=True)
        if ok:
            ok, out = git(["remote", "set-url", "origin", url], path)
        else:
            ok, out = git(["remote", "add", "origin", url], path)
        return jsonify(ok=ok, message=out if out else "Repositorio remoto configurado.")

    if step == "add":
        if not valid_repo(path):
            return jsonify(ok=False, message="No hay un repositorio Git válido.")
        ok, out = git(["add", "."], path)
        return jsonify(ok=ok, message=out if out else "Archivos preparados con git add .")

    if step == "commit":
        message = payload.get("message", "").strip()
        if not message:
            return jsonify(ok=False, message="Escribe un mensaje para el commit.")
        if not valid_repo(path):
            return jsonify(ok=False, message="No hay un repositorio Git válido.")
        ok, out = git(["commit", "-m", message], path)
        return jsonify(ok=ok, message=out)

    if step == "branch":
        if not valid_repo(path):
            return jsonify(ok=False, message="No hay un repositorio Git válido.")
        ok, out = git(["branch", "-M", "main"], path)
        return jsonify(ok=ok, message=out if out else "La rama actual ahora es main.")

    if step == "push":
        token = payload.get("token", "").strip()
        force = bool(payload.get("force", False))
        if not valid_repo(path):
            return jsonify(ok=False, message="No hay un repositorio Git válido.")
        if not token:
            return jsonify(ok=False, message="Introduce tu token de GitHub para hacer Push.")
        remote_ok, remote = git(["remote", "get-url", "origin"], path)
        if not remote_ok:
            return jsonify(ok=False, message="No hay un remoto origin configurado.")
        if not remote.startswith(("https://", "http://")):
            return jsonify(ok=False, message="Este asistente usa autenticación por HTTPS. Configura origin con una URL https:// de GitHub.")
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
            askpass = f.name
            f.write("#!/bin/sh\ncase \"$1\" in\n  *Username*) printf '%s\\n' \"$GIT_USERNAME\" ;;\n  *) printf '%s\\n' \"$GIT_PASSWORD\" ;;\nesac\n")
        os.chmod(askpass, 0o700)
        env = os.environ.copy()
        env["GIT_ASKPASS"] = askpass
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_USERNAME"] = "git"
        env["GIT_PASSWORD"] = token
        try:
            push_args = ["push", "-u", "origin", "main"]
            if force:
                push_args.insert(1, "--force")
            ok, out = run_command(["git", "-c", f"safe.directory={path}", "-C", path, *push_args], env=env, timeout=120)
        finally:
            try:
                os.remove(askpass)
            except OSError:
                pass
        return jsonify(ok=ok, message=out)

    return jsonify(ok=False, message="Paso desconocido."), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
