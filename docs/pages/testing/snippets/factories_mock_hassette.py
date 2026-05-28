from pathlib import Path

from hassette.test_utils import make_mock_hassette

tmp_path = Path("/tmp/test")  # pyright: ignore[reportUnusedVariable]

# Minimal — real config defaults, sealed against phantom attributes
hassette = make_mock_hassette()

# With config overrides — validated by HassetteConfig at construction time
hassette = make_mock_hassette(strict_lifecycle=True)
hassette = make_mock_hassette(database={"retention_days": 14})

# Database-backed tests — pass a real tmp_path for isolation
hassette = make_mock_hassette(data_dir=tmp_path)
