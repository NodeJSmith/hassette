Hassette searches for `hassette.toml` in:

1. `/config/hassette.toml`
2. `./hassette.toml` (current working directory)
3. `./config/hassette.toml`

`.env` files are searched in:

1. `/config/.env`
2. `./.env` (current working directory)
3. `./config/.env`

`--config-file / -c` and `--env-file / -e` override either path.
