from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from app.main import AgentRuntime


def _runtime() -> AgentRuntime:
    return AgentRuntime()


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blip")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon_parser = subparsers.add_parser("daemon")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    daemon_start = daemon_sub.add_parser("start")
    daemon_start.add_argument("--host", default="127.0.0.1")
    daemon_start.add_argument("--port", type=int, default=8000)

    workspace_parser = subparsers.add_parser("workspace")
    workspace_sub = workspace_parser.add_subparsers(dest="workspace_command", required=True)
    workspace_list = workspace_sub.add_parser("list")
    workspace_import = workspace_sub.add_parser("import")
    workspace_import.add_argument("repo")
    workspace_generate = workspace_sub.add_parser("generate")
    workspace_generate.add_argument("idea_id")

    run_parser = subparsers.add_parser("run")
    run_sub = run_parser.add_subparsers(dest="run_command", required=True)
    run_start = run_sub.add_parser("start")
    run_start.add_argument("workspace_id")
    run_start.add_argument("--yolo", action="store_true")
    run_show = run_sub.add_parser("show")
    run_show.add_argument("run_id")
    run_approve = run_sub.add_parser("approve")
    run_approve.add_argument("run_id")
    run_reject = run_sub.add_parser("reject")
    run_reject.add_argument("run_id")

    skill_parser = subparsers.add_parser("skill")
    skill_sub = skill_parser.add_subparsers(dest="skill_command", required=True)
    skill_sub.add_parser("list")
    skill_enable = skill_sub.add_parser("enable")
    skill_enable.add_argument("skill_id")
    skill_disable = skill_sub.add_parser("disable")
    skill_disable.add_argument("skill_id")
    skill_install = skill_sub.add_parser("install")
    skill_install.add_argument("manifest_path")

    recipe_parser = subparsers.add_parser("recipe")
    recipe_sub = recipe_parser.add_subparsers(dest="recipe_command", required=True)
    recipe_sub.add_parser("list")

    args = parser.parse_args(argv)

    if args.command == "daemon" and args.daemon_command == "start":
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
        return 0

    runtime = _runtime()

    if args.command == "workspace":
        if args.workspace_command == "list":
            _print_json(runtime.list_workspaces())
            return 0
        if args.workspace_command == "import":
            _print_json(runtime.import_workspace(args.repo))
            return 0
        if args.workspace_command == "generate":
            _print_json(runtime.generate_workspace(args.idea_id))
            return 0

    if args.command == "run":
        if args.run_command == "start":
            _print_json(runtime.start_workspace_run(args.workspace_id, yolo=args.yolo))
            return 0
        if args.run_command == "show":
            _print_json(runtime.run_detail(args.run_id))
            return 0
        if args.run_command == "approve":
            _print_json(runtime.approve_run(args.run_id))
            return 0
        if args.run_command == "reject":
            _print_json(runtime.reject_run(args.run_id))
            return 0

    if args.command == "skill":
        if args.skill_command == "list":
            _print_json(runtime.list_skills())
            return 0
        if args.skill_command == "enable":
            _print_json(runtime.update_skill(args.skill_id, True))
            return 0
        if args.skill_command == "disable":
            _print_json(runtime.update_skill(args.skill_id, False))
            return 0
        if args.skill_command == "install":
            skill = runtime.platform_store.install_skill_manifest(args.manifest_path)
            _print_json({"skill": skill.model_dump()})
            return 0

    if args.command == "recipe" and args.recipe_command == "list":
        _print_json(runtime.list_recipes())
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
