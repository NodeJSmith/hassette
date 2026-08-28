from hassette.resources.teardown import RestartSafety, TeardownReport

# A clean teardown attempt: no causes recorded, restart_safety is derived as SAFE.
clean_report = TeardownReport()
assert clean_report.restart_safety is RestartSafety.SAFE
