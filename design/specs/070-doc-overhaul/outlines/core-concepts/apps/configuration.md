# Apps — Configuration

**Status:** ABSORBED into `apps/overview.md`. Content becomes an H2 in the Apps overview.

At 34 lines (3 base fields + env prefix + secrets), this doesn't justify its own page. The Apps overview already has "Defining an App" — config class definition belongs there.

Content to fold into apps/overview.md:
- AppConfig subclass with SettingsConfigDict and env_prefix
- Base fields: `instance_name`, `log_level`, `app_key` (+ reserved prefix validator)
- `extra="allow"` behavior, `env_ignore_empty=True`
- Secrets & env vars via Pydantic BaseSettings

See decision in outline audit (2026-06-02).
