"""
CLI argument parsing for clawup.

Supports two invocation styles:
    clawup                    # terminal wizard (interactive)
    clawup serve              # browser wizard (GUI)
    clawup <flags>            # legacy flat style still works

Both styles share the same planner/installer/verifier underneath.
"""

import argparse
import sys

from .manifests import PROFILES, PROVIDERS
from .orchestrator import run_setup


def _add_setup_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        metavar="PROFILE",
        help=(
            "Setup profile: "
            + ", ".join(f"{k} ({v.label})" for k, v in PROFILES.items())
        ),
    )
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS.keys()),
        metavar="PROVIDER",
        help=(
            "Model provider: "
            + ", ".join(f"{k} ({v.label})" for k, v in PROVIDERS.items())
        ),
    )
    parser.add_argument("--no-service", action="store_true", default=False,
                        help="Skip background service installation")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Show the install plan without executing anything")
    parser.add_argument("--fix", action="store_true", default=False,
                        help="Repair mode: run openclaw doctor without full setup")
    parser.add_argument("--non-interactive", action="store_true", default=False,
                        help="Non-interactive mode: use defaults, no prompts")
    parser.add_argument("--config-path", default=None, metavar="PATH",
                        help="Override default config file path (~/.openclaw/config.yaml)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clawup",
        description="OpenClaw guided setup orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  clawup                          Interactive terminal wizard
  clawup serve                    Browser wizard (opens your browser)
  clawup --profile telegram_bot   Skip profile question
  clawup --provider openai        Skip provider question
  clawup --dry-run                Show plan without making changes
  clawup --fix                    Run doctor/repair only
""",
    )

    sub = parser.add_subparsers(dest="command", metavar="[command]")

    # ---- serve ----
    serve_p = sub.add_parser(
        "serve",
        help="Open the browser wizard (friendliest for non-technical users)",
    )
    serve_p.add_argument("--port", type=int, default=7999,
                         help="Port to bind on localhost (default: 7999)")
    serve_p.add_argument("--no-browser", action="store_true", default=False,
                         help="Don't open the browser automatically")
    serve_p.add_argument("--host", default="127.0.0.1",
                         help="Bind address (default: 127.0.0.1)")

    # ---- setup (default, shown as `clawup setup`) ----
    setup_p = sub.add_parser("setup", help="Terminal wizard (default)")
    _add_setup_flags(setup_p)

    # Legacy flat flags on top-level parser so `clawup --dry-run` still works
    _add_setup_flags(parser)

    return parser


def cli_main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        try:
            from .web.server import serve
        except ImportError as e:
            print(f"Error: web wizard requires FastAPI/uvicorn ({e})", file=sys.stderr)
            print("Install with: pip install fastapi uvicorn", file=sys.stderr)
            return 1
        return serve(
            port=args.port,
            open_browser=not args.no_browser,
            host=args.host,
        )

    # Default: terminal wizard (also handles `clawup setup`)
    install_service = False if args.no_service else None

    return run_setup(
        profile_id=args.profile,
        provider_id=args.provider,
        install_service=install_service,
        dry_run=args.dry_run,
        fix_only=args.fix,
        non_interactive=args.non_interactive,
        config_path=args.config_path,
    )


if __name__ == "__main__":
    sys.exit(cli_main())
