# Managing Dependencies

Your apps can use any Python package. Hassette installs them at startup
when you tell it to. `requirements.txt` works for most projects.
`pyproject.toml` works when your project already has one.

## Using requirements.txt

```txt
--8<-- "pages/getting-started/docker/snippets/requirements-example.txt"
```

Place this file at `config/requirements.txt` on your host. That maps to
`/config/requirements.txt` inside the container. Hassette also finds a
`requirements.txt` inside your apps directory.

Add `HASSETTE_DOCKER_INSTALL_DEPS: "1"` to your compose file:

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-install-deps-env.yml"
```

Without `HASSETTE_DOCKER_INSTALL_DEPS`, Hassette installs no `requirements.txt` files (a locked project is still installed, see below).
The `uv_cache` volume keeps downloaded packages across restarts.
Only the first startup is slow.

Restart the container — the install runs during startup, and you can watch it with `docker compose logs -f hassette`. Your packages are then available:

```python
--8<-- "pages/getting-started/docker/snippets/deps-app-using-package.py"
```

The app imports `apprise` directly. No extra configuration needed.

!!! tip
    After adding new packages to `requirements.txt`, restart the container
    with `docker compose restart hassette`. Hassette re-runs the install on
    every startup when `HASSETTE_DOCKER_INSTALL_DEPS` is set.

## Using pyproject.toml

```toml
--8<-- "pages/getting-started/docker/snippets/pyproject-example.toml"
```

If you already have a `pyproject.toml`, place it in your `config/apps/`
directory alongside your app files. You also need a `uv.lock` next to it —
a file recording the exact version of every package, so the container
installs the same versions you tested locally. Generate one by running
this in your `config/apps/` directory before starting the container:

```bash
uv lock
```

Your compose file stays the same as the [Docker Setup](index.md) page. No extra
environment variables are needed:

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-pyproject-compose.yml"
```

On startup, Hassette looks for the project directory: the nearest
directory at or above your apps directory that contains a
`pyproject.toml`, falling back to the config directory. If that
directory has a `uv.lock`, Hassette installs the locked dependencies
automatically. `HASSETTE_DOCKER_INSTALL_DEPS` is not needed.

The walk-up supports a project mounted outside the config directory. Mount
the project at `/apps` and point the apps directory inside it with
`HASSETTE__APPS__DIRECTORY=/apps/src/mypkg`; Hassette finds the project at
`/apps`:

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-project-mount-compose.yml"
```

To skip the search, set `HASSETTE_DOCKER_PROJECT_DIR` to the directory and
mount it.

### Installing your project vs. loading your apps

The project install and app loading are two separate import paths.

The install exports your locked dependencies, installs them against
Hassette's constraints, then installs a copy of your project into the
container with `--no-deps`. Your apps use the dependencies from this step.

Your apps themselves don't come from that installed copy. Hassette loads them
straight from the apps directory, under a package named after that
directory's last path segment. With `HASSETTE__APPS__DIRECTORY=/apps/src/mypkg`,
the package is `mypkg`, so `from mypkg.helpers import notify` inside an app
reads the mounted files, not the copy in `site-packages`. Hassette also puts
the apps directory and its parent at the front of `sys.path`, so a package
sitting next to the apps directory (`/apps/src/mylib` in this example) is
read from the mounted files too.

Any other package your project ships resolves to the installed copy. If the
apps directory is `/apps/automations` and your wheel contains `mylib` from
`/apps/src/mylib`, an app's `import mylib` reads `site-packages`.

Either way, `docker compose restart hassette` picks up an edit on the host:
the startup reinstalls the project copy on every start. A reload alone is not
enough for anything but the app's own module. It re-imports only that module,
and Python keeps already-imported modules like `mypkg.helpers` cached.

The installed copy matters for those other packages, and for any code that
imports your project as an installed package. If your build backend is
misconfigured (for example, a wrong `module-name` or `module-root` under
`[tool.uv.build-backend]`), the installed copy can end up under the wrong
name, and nothing fails at startup when your apps never import it that way.
To check, run `uv build --wheel` locally and confirm the wheel's top-level
directory matches your package name.

Hassette pins its own dependencies via a constraints file. Your packages
cannot conflict with packages Hassette depends on. If a conflict occurs,
the install fails at startup — see
[Troubleshooting](troubleshooting.md#dependencies-wont-install).

!!! note
    Commit `uv.lock` to version control. Hassette uses it to reproduce the
    exact package versions you tested locally.

## Known Limitations

**Local path dependencies don't work inside Docker.** If your `pyproject.toml`
or `requirements.txt` contains a `file:///...` dependency, installation fails
because the host path does not exist inside the container. Mount the shared
code as a volume with a relative path that matches the container layout,
or publish it as a package.

**First startup is slower with new dependencies.** Hassette runs
`uv pip install` on every start when `HASSETTE_DOCKER_INSTALL_DEPS` is set.
New packages download on the first run. The `uv_cache` volume persists
the cache, so subsequent starts skip the download. If your cache volume
is missing or was pruned, the next startup downloads everything again.

If installation fails at startup, see [Troubleshooting](troubleshooting.md#dependencies-wont-install)
for common causes and fixes.
