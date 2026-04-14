# Container status
docker compose ps

# Full logs
docker compose logs hassette > hassette.log

# Environment
docker compose exec hassette env | grep HASSETTE

# File structure - example uses fdfind to automatically exclude pycache/pyc/etc.
docker compose exec hassette fdfind . /apps /config -t f
