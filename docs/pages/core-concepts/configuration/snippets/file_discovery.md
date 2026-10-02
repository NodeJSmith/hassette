Hassette reads `hassette.toml` from every one of these locations that exists, in order:

1. `/config/hassette.toml`
2. `./hassette.toml` (current working directory)
3. `./config/hassette.toml`

`.env` files are read the same way:

1. `/config/.env`
2. `./.env` (current working directory)
3. `./config/.env`

When more than one file exists, they merge and a later file replaces any top-level key or whole `[table]` it sets (tables are not merged key by key). `--config-file / -c` and `--env-file / -e` replace the search list with a single path.
