# Git UI

Panel web local para gestionar un repositorio Git desde Termux — ahora es
un panel de uso diario, no solo un asistente de primer commit.

## Uso en Termux

```bash
pkg update
pkg install git python
cd ~/git-ui
python -m pip install -r requirements.txt --break-system-packages
python app.py
```

Abre `http://127.0.0.1:5000` en el navegador del teléfono. Puedes tocar
"Agregar a pantalla de inicio" en el navegador para instalarlo como app
(PWA) con su propio ícono y sin la barra de direcciones.

Para las notificaciones de Push (opcional):

```bash
pkg install termux-api
```

y también instala la app **Termux:API** desde F-Droid o Play Store. Si no
la tienes instalada, la app funciona igual, simplemente no habrá
notificación al terminar un Push.

## Novedades de esta versión

**Flujo de Commit + Push más claro.** El botón "Push" ahora avisa si tienes
cambios sin preparar o sin commitear que no se van a subir. Y hay un botón
nuevo, "Commit + Push", que hace ambas cosas en un solo paso — pensado
justo para la duda de "¿necesito hacer commit antes?".

**Conflictos de fusión, ya no un mensaje de error críptico.** Si un Pull
encuentra un conflicto, la app lista los archivos afectados, te explica qué
buscar (`<<<<<<<`, `=======`, `>>>>>>>`) y te deja terminarlo desde ahí:
"Ya resolví, continuar" (verifica que ya quitaste las marcas antes de dejarte
seguir) o "Cancelar merge" para volver atrás sin aplicar nada. Si cierras la
app a medio resolver, al volver a abrirla el panel te lo recuerda.

**El token de GitHub se puede recordar por la sesión.** Al hacer Push hay un
casillero "Recordar el token para esta sesión" — si lo marcas, no hace falta
pegarlo de nuevo mientras la pestaña siga abierta. Nunca se guarda en disco;
se pierde en cuanto recargas la página o cierras el navegador.

**Soporte para SSH, no solo HTTPS.** Si configuras origin con una URL SSH
(`git@github.com:usuario/repo.git`), la app detecta el esquema y usa
directamente la llave que ya tengas configurada en Termux — no te pide
ningún token. Todo lo de HTTPS + token sigue funcionando igual que antes
para quien no use SSH.

**Se puede instalar como app (PWA).** Ícono propio (el "$" naranja de la
barra superior) tanto en la pestaña del navegador como en la pantalla de
inicio si la agregas ahí.

**Notificación de Termux al terminar un Push**, si tienes `termux-api`
instalado (ver arriba). Sin eso, todo sigue funcionando, solo sin la
notificación nativa.

## Qué cambió respecto a la versión anterior

**Ya no es un asistente de un solo uso.** Antes, cada vez que abrías la app
tenías que repetir los 9 pasos del asistente aunque el repositorio ya
estuviera configurado. Ahora:

- Recuerda los proyectos que abriste antes (guardado en
  `~/.config/git-ui/recents.json`), con acceso rápido desde la pantalla de
  inicio.
- Al abrir un proyecto, la app detecta qué falta configurar y **salta
  automáticamente** los pasos ya hechos (Git instalado, repo inicializado,
  identidad, remoto). El asistente solo aparece para lo que realmente falta.
- Una vez configurado, entras directo a un **Panel** con pestañas: Estado,
  Ramas, Historial, Config — no a un asistente lineal.

**Panel nuevo (antes no existía nada de esto):**
- Ver archivos preparados / sin preparar / sin seguimiento por separado,
  con acciones individuales (preparar, quitar, descartar, eliminar).
- Ver el diff de cualquier archivo tocándolo.
- Pull, además del Push que ya existía.
- Ramas: crear, cambiar, eliminar, ver cuál está activa.
- Stash: guardar, aplicar, borrar.
- Historial de commits (hash, autor, fecha, mensaje).
- Editor rápido de `.gitignore`.
- Clonar un repositorio de GitHub existente, no solo inicializar uno nuevo.
- Confirmación antes de cualquier acción destructiva (descartar cambios,
  eliminar archivo sin seguimiento, eliminar rama, borrar stash).

**Bugs corregidos:**
- El Push estaba fijo a la rama `main` sin importar en qué rama estuvieras;
  ahora empuja la rama actual real.
- Si el Push era rechazado por *non-fast-forward*, el error de Git se
  mostraba tal cual, sin indicar qué hacer; ahora se detecta y sugiere usar
  Pull primero (o forzar, con confirmación).
- Un mensaje de relleno para salidas vacías de Git terminaba, en ciertos
  casos, interpretado como si fuera parte del estado del repositorio, lo
  que producía archivos y ramas "fantasma" en un repo limpio. Corregido.
- El parseo de `git status` recortaba el espacio inicial de cada línea,
  lo que desplazaba el nombre de cada archivo un carácter (`main.py` se
  leía como `ain.py`) y podía marcar como "preparado" un archivo que en
  realidad no lo estaba. Corregido.
- El estado del proyecto ya no se pierde al cerrar Termux: se guarda en
  disco en vez de vivir solo en memoria.

**Estructura del código** — ahora modular en vez de un solo archivo:
- `app.py` — rutas Flask (capa fina).
- `gitops.py` — toda la lógica de Git/subprocess.
- `store.py` — persistencia de proyectos recientes.
- `templates/index.html` + `static/style.css` + `static/app.js` — antes
  todo estaba en una sola plantilla con CSS y JS en línea.

## Notas de seguridad (igual que antes, sin cambios de fondo)

- El token de GitHub nunca se guarda en la URL del remoto ni en disco;
  se usa solo en memoria durante el Push/Clone vía `GIT_ASKPASS` temporal.
  Si activas "recordar para esta sesión", sigue siendo solo memoria del
  navegador — se pierde al recargar o cerrar la pestaña.
- Las URLs remotas con credenciales se muestran siempre ocultando el
  secreto.
- `debug` desactivado.
- Push admite remotos `https://` (con token) o `git@`/`ssh://` (con tu
  llave SSH ya configurada en Termux) — se detecta automáticamente según
  la URL de origin.
