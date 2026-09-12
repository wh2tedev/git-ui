# Git UI

Panel web local para gestionar un repositorio Git desde Termux.

## Termux

```bash
pkg update
pkg install git python
cd ~/git-ui
python -m pip install -r requirements.txt
python app.py
```

Luego abre `http://127.0.0.1:5000`.

## Mejoras

- Validación de repositorios antes de ejecutar comandos.
- Expansión de `~` y rutas absolutas.
- Manejo de errores de Git, Git ausente y timeouts.
- `debug` desactivado por seguridad.
- El PAT de GitHub ya **no se guarda en la URL del remoto**.
- Autenticación de `push` mediante `GIT_ASKPASS` temporal.
- URLs remotas con credenciales se muestran ocultando el secreto.
- Validación de acciones y mensajes de commit vacíos.
- Mantiene el diseño y la estructura visual originales.
