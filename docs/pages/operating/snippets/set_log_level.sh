curl -X PUT http://127.0.0.1:8126/api/logs/level \
  -H "Authorization: Bearer $HASSETTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"logger": "hassette.SchedulerService", "level": "DEBUG"}'
