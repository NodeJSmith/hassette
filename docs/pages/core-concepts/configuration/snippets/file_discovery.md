Hassette reads `hassette.toml` from every one of these locations that exists, in order:

1. `/config/hassette.toml`
2. `./hassette.toml` (current working directory)
3. `./config/hassette.toml`

When more than one file exists, they merge and a later file replaces any top-level key or whole `[table]` it sets (tables are not merged key by key). Each file's `hassette.local.toml` overlay is then merged on top, key by key — see [Local Overrides](#local-overrides).

Hassette checks the same three locations for `.env` files:

1. `/config/.env`
2. `./.env` (current working directory)
3. `./config/.env`

Settings resolution reads them in that order too, so a later `.env` file overrides a value an earlier one set. When `import_dot_env_files` is enabled (the default), each existing `.env` file is also loaded into `os.environ` at startup. That load has no guaranteed order and never overwrites a variable that's already set.

`--config-file / -c` and `--env-file / -e` replace the search list with a single path.
