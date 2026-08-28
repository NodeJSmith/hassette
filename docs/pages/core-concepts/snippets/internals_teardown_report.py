from hassette.resources.teardown import TeardownReport

# A clean teardown attempt: no causes recorded, is_restart_safe is derived as True.
clean_report = TeardownReport()
assert clean_report.is_restart_safe is True
