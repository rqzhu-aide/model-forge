"""Command-line entry points for the local Method Hub service."""

from __future__ import annotations

import argparse

import uvicorn

from .application.bootstrap import build_application
from .application.settings import ApplicationSettings
from .specification import SpecificationPackage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="method-hub")
    subcommands = parser.add_subparsers(dest="command", required=True)
    serve = subcommands.add_parser("serve", help="Run the local Web application.")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    subcommands.add_parser("validate", help="Validate the architecture package.")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    settings = ApplicationSettings()
    if arguments.command == "validate":
        package = SpecificationPackage.load(settings.resolved_architecture_root())
        print(
            f"Validated {len(package.phases)} phase contracts and "
            f"{len(package.schemas.schema_names)} schemas."
        )
        return 0
    configured = settings.model_dump()
    configured["host"] = arguments.host or settings.host
    configured["port"] = arguments.port or settings.port
    settings = ApplicationSettings.model_validate(configured)
    uvicorn.run(
        build_application(settings), host=settings.host, port=settings.port
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
