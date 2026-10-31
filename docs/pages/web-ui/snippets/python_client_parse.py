from pathlib import Path

from hassette_client import parse_response
from hassette_wire import SystemStatusResponse

body = Path("health.json").read_bytes()
health = parse_response(SystemStatusResponse, body)
print(health.status)
