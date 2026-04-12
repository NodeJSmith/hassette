# Docker
docker compose exec hassette rm /data/hassette.db
docker compose restart hassette

# Local (replace v0 with your major version, or use your configured db_path)
rm ~/.local/share/hassette/v0/hassette.db
