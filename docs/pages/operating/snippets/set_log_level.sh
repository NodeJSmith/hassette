curl -X PUT http://127.0.0.1:8126/api/logs/level \
  -H "Authorization: Bearer $(cat /path/to/data_dir/.web_api_token)" \
  -H "Content-Type: application/json" \
  -d '{"logger": "hassette.SchedulerService", "level": "DEBUG"}'
