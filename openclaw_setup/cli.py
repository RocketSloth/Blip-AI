"""
CLI argument parsing for clawup / openclaw quickstart.

Entry point: cli_main()
"""

import argparse
import sys

from .manifests import CHANNELS, PROFILES, PROVIDERS
from .orchestrator import run_setup


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clawup",
        description="OpenClaw guided setup orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  clawup                          Interactive guided setup
  clawup --profile telegram_bot   Skip profile question
  clawup --provider openai        Skip provider question
  clawup --dry-run                Show plan without making changes
  clawup --fix                    Run doctor/repair only
  clawup --no-service             Skip service install
  clawup --non-interactive        Use defaults, no prompts
""",
    )

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

    parser.add_argument(
        "--no-service",
        action="store_true",
        default=False,
        help="Skip background service installation",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show the install plan without executing anything",
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Repair mode: run openclaw doctor without full setup",
    )

    parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Non-interactive mode: use defaults or supplied flags, no prompts",
    )

    parser.add_argument(
        "--config-path",
        default=None,
        metavar="PATH",
        help="Override default config file path (~/.openclaw/config.yaml)",
    )

    return parser


def cli_main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    install_service: bool | None = None
    if args.no_service:
        install_service = False

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
