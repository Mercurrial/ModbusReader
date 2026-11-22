"""Offline authoring CLI: python -m core.authoring_cli --help (stdlib only)."""
import argparse
import json
from pathlib import Path
import sys

from core import authoring, macro_api

MAX_INPUT_BYTES = 8 * 1024 * 1024


def _input(path):
    file = Path(path)
    if file.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 8 MiB authoring limit")
    return file


def _profile(path):
    if not path:
        return None
    doc = authoring.read_json(_input(path))
    if authoring.document_kind(doc) == "project":
        errors = authoring.validate_document(doc)
        if any(d.severity == "error" for d in errors):
            raise ValueError("Profile source project is invalid; validate it first")
        return doc["profile"]
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("describe", help="Print the versioned contract as JSON")
    schema = sub.add_parser("schema", help="Print a self-contained JSON Schema")
    schema.add_argument("kind", choices=("profile", "project", "dashboard"))
    for name, help_text in (("validate", "Strictly validate a current JSON document"),
                            ("check-macro", "Check Python without running it")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("file")
        p.add_argument("--profile", help="Current profile or project for register bindings")
        p.add_argument("--warnings-as-errors", action="store_true")
        if name == "validate":
            p.add_argument("--kind", choices=("profile", "project", "dashboard"))
    complete = sub.add_parser("completions", help="Editor suggestions from the shared API contract")
    complete.add_argument("--profile")
    complete.add_argument("--language", choices=("ru", "en"), default="en")
    args = parser.parse_args(argv)
    status = 0
    try:
        if args.command == "describe":
            payload = authoring.catalog()
        elif args.command == "schema":
            payload = authoring.schemas()[args.kind]
        else:
            profile = _profile(args.profile)
            if args.command == "completions":
                diagnostics = authoring.validate_document(profile, "profile") if profile is not None else []
                if any(d.severity == "error" for d in diagnostics):
                    payload, status = authoring.result(diagnostics), 1
                else:
                    payload = {"contract_version": authoring.CONTRACT_VERSION,
                               "items": macro_api.completion_items(profile["registers"] if profile else (), args.language)}
            else:
                file = _input(args.file)
                if args.command == "validate":
                    diagnostics = authoring.validate_document(authoring.read_json(file), args.kind, profile)
                else:
                    diagnostics = authoring.check_macro(file.read_text(encoding="utf-8-sig"), profile)
                payload = authoring.result(diagnostics)
                status = int(not payload["valid"] or (args.warnings_as_errors and bool(diagnostics)))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        payload = authoring.result([authoring.Diagnostic("input.invalid", str(exc),
                                   line=getattr(exc, "lineno", None), column=getattr(exc, "colno", None))])
        status = 2
    # Windows terminals may not use UTF-8. Escapes keep redirected JSON portable.
    print(json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False))
    return status


if __name__ == "__main__":
    sys.exit(main())
