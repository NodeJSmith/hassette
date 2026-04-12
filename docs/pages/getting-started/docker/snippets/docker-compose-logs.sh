# Follow all logs
docker compose logs -f

# Just Hassette
docker compose logs -f hassette

# Last 100 lines
docker compose logs --tail=100 hassette
