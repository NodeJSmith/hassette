# Upgrading Hassette

## Check Your Current Version

Before upgrading, confirm what version you're running. The CLI reports it directly:

```bash
hassette --version
```

To check the version installed in your project:

```bash
uv pip show hassette
```

## Upgrade

How you upgrade depends on how you installed Hassette.

**pip**

```bash
pip install --upgrade hassette
```

**uv (project dependency)**

```bash
uv add hassette@latest
```

This updates `pyproject.toml` and installs the new version into your project environment. If you installed Hassette as a uv tool rather than a project dependency, run `uv tool upgrade hassette` instead.

**Docker**

Pull the latest image and restart your container:

```bash
docker compose pull
docker compose up -d
```

This pulls whatever tag is configured in your `docker-compose.yml`. To pin a specific version, change the `image:` tag there.

## Reading the Changelog

The changelog lives in two places: `CHANGELOG.md` at the root of the repository, and the [GitHub Releases page](https://github.com/NodeJSmith/hassette/releases). Both contain the same content. GitHub Releases is easier to browse by version; `CHANGELOG.md` is useful if you have the repo checked out.

Before upgrading, scan the entries between your current version and the target version. Pay attention to two signals:

- A `BREAKING CHANGE:` footer in a release note means something in your app code may need to change. The footer describes what changed and what you need to do.
- A `!` after the commit type (for example, `feat!:` or `fix!:`) marks a breaking change. If the entry has a `BREAKING CHANGE:` footer, that footer has the details. If it does not, the summary line is all you have. Read it carefully.

Entries without either signal are safe to take without changes to your app code.

## Major Version Upgrades

Hassette includes the major version in its data directory path. The current data directory is `~/.local/share/hassette/v0/`. A future v1 release will use `~/.local/share/hassette/v1/` and start with an empty database.

!!! warning "Back up before major upgrades"
    Copy your data directory (`~/.local/share/hassette/v0/` on Linux) to a safe location before upgrading across major versions. The new version starts with an empty database if paths are not explicitly set.

If you want to carry your history forward across a major version bump, set `data_dir` and `config_dir` explicitly in your `hassette.toml` before upgrading:

```toml
[hassette]
data_dir = "/home/youruser/.local/share/hassette/v0"
config_dir = "/home/youruser/.config/hassette/v0"
```

With explicit paths set, Hassette uses them regardless of the built-in version default. You control when the data moves.

Docker installations are unaffected. Mount points are version-independent. Your volume mounts stay the same across major versions.
