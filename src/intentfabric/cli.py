"""Presenta los seis casos de uso del pipeline mediante argparse y JSON."""

import argparse
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
import json
import sys
from typing import TextIO

from intentfabric import bootstrap
from intentfabric.domain.errors import IntentFabricError


def build_argument_parser() -> argparse.ArgumentParser:
    """Define subcomandos y opciones comunes con transporte predeterminado por uso."""
    parser = argparse.ArgumentParser(prog="intentfabric")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "generate", "deploy", "verify", "run", "teardown"):
        subparser = subcommands.add_parser(command)
        subparser.add_argument("--intent", "-i", required=True)
        subparser.add_argument("--topology", "-t", default="inventory/topology.yaml")
        subparser.add_argument("--variant", "-v", default="default")
        subparser.add_argument("--transport", choices=("none", "simulated", "ssh"),
                               default="none" if command in ("validate", "generate") else "simulated")
        subparser.add_argument("--json-out")
        subparser.add_argument("--csv-out")
        if command == "generate":
            subparser.add_argument("--operation", choices=("provision", "teardown"), default="provision")
    return parser


def main(
    argv: Sequence[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None,
) -> int:
    """Ejecuta el caso solicitado y retorna 0, 1 o 2 segun su resultado."""
    output = stdout if stdout is not None else sys.stdout
    errors = stderr if stderr is not None else sys.stderr
    with redirect_stdout(output), redirect_stderr(errors):
        try:
            args = build_argument_parser().parse_args(argv)
        except SystemExit as error:
            return int(error.code)
    try:
        topology = bootstrap.load_default_topology(args.topology)
        catalog = bootstrap.build_plugin_catalog(topology)
        intent = catalog.parse_intent(bootstrap.load_intent_file(args.intent))
        transport = None
        if args.transport == "simulated":
            transport = bootstrap.build_simulated_transport_for_intent(intent, topology=topology, variant=args.variant)
        elif args.transport == "ssh":
            transport = bootstrap.build_ssh_transport()
        orchestrator = bootstrap.build_orchestrator(
            topology=topology, catalog=catalog, transport=transport,
            logger=bootstrap.build_execution_logger(json_path=args.json_out, csv_path=args.csv_out),
        )
        if args.command == "generate":
            record = orchestrator.generate(intent, operation=args.operation, variant=args.variant)
        else:
            record = getattr(orchestrator, args.command)(intent, variant=args.variant)
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False), file=output)
        return 0 if record.is_successful else 1
    except (IntentFabricError, OSError) as error:
        print(str(error), file=errors)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
