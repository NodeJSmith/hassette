import typing

import nox

if typing.TYPE_CHECKING:
    from nox.sessions import Session

nox.options.default_venv_backend = "uv|virtualenv"


@nox.session(python=["3.11", "3.12", "3.13"])
def tests(session: "Session"):
    session.run("uv", "run", "--active", "--reinstall-package", "hassette", "pytest", external=True)


@nox.session(python=["3.11", "3.12", "3.13"])
def tests_no_ha(session: "Session"):
    session.run(
        "uv", "run", "--active", "--reinstall-package", "hassette", "pytest", "-m", "not requires_ha", external=True
    )
