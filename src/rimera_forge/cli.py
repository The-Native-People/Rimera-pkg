from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .core import (
    ForgeError,
    download_verified,
    prepare_publication,
    python_selector,
    release_tag_for,
    resolve_release,
    target_matrix,
)
from .index import build_static_index
from .recipes import load_recipe


def _write_json(payload: object, path: Path | None = None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    else:
        print(text, end="")


def _github_output(path: str | None, values: dict[str, str]) -> None:
    if not path:
        return
    output = Path(path)
    with output.open("a") as handle:
        for key, value in values.items():
            marker = f"RIMERA_{key}_{os.getpid()}"
            handle.write(f"{key}<<{marker}\n{value}\n{marker}\n")


def cmd_resolve(args: argparse.Namespace) -> None:
    plan = resolve_release(args.package, args.version)
    _write_json(plan, Path(args.output) if args.output else None)
    _github_output(
        args.github_output,
        {
            "resolved_version": plan["version"],
            "normalized_name": plan["package"]["normalized"],
            "python_selector": python_selector(args.python),
            "matrix": json.dumps(target_matrix(args.target), separators=(",", ":")),
        },
    )


def cmd_prepare(args: argparse.Namespace) -> None:
    out = Path(args.out).resolve()
    plan = resolve_release(args.package, args.version)
    source = plan["source"]
    source_path = out / "source" / str(source["filename"])
    download_verified(str(source["url"]), str(source["sha256"]), source_path)
    _write_json(plan, out / "build-plan.json")
    recipe = load_recipe(Path(args.recipes), args.package, args.target)
    _github_output(
        args.github_output,
        {
            "sdist_path": str(source_path),
            "normalized_name": plan["package"]["normalized"],
            "resolved_version": plan["version"],
            "before_build": recipe["before-build"],
            "test_command": recipe["test-command"],
            "environment": recipe["environment"],
            "skip": recipe["skip"],
        },
    )
    print(f"Verified {source['filename']} sha256={source['sha256']}")


def cmd_publish(args: argparse.Namespace) -> None:
    tag = args.release_tag or release_tag_for(args.package, args.version)
    record, record_path = prepare_publication(
        package=args.package,
        version=args.version,
        wheels_root=Path(args.wheels_root),
        output_dir=Path(args.out),
        registry_root=Path(args.registry),
        repository=args.repository,
        release_tag=tag,
    )
    _github_output(
        args.github_output,
        {
            "release_tag": tag,
            "registry_path": str(record_path),
            "normalized_name": record["package"]["normalized"],
        },
    )
    print(f"Validated {len(record['wheels'])} published wheel record(s)")


def cmd_index(args: argparse.Namespace) -> None:
    packages = build_static_index(Path(args.registry), Path(args.out))
    print(f"Generated Simple pages for {len(packages)} Rimera package(s)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rimera-forge")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="Resolve an exact PyPI release without building it")
    resolve.add_argument("package")
    resolve.add_argument("--version")
    resolve.add_argument("--python", default="3.13")
    resolve.add_argument("--target", default="all")
    resolve.add_argument("--output")
    resolve.add_argument("--github-output")
    resolve.set_defaults(func=cmd_resolve)

    prepare = sub.add_parser("prepare", help="Download and verify the exact PyPI sdist")
    prepare.add_argument("package")
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--target", required=True)
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--recipes", default="recipes")
    prepare.add_argument("--github-output")
    prepare.set_defaults(func=cmd_prepare)

    publish = sub.add_parser("publish", help="Validate generated wheels and build registry records")
    publish.add_argument("package")
    publish.add_argument("--version", required=True)
    publish.add_argument("--wheels-root", required=True)
    publish.add_argument("--out", required=True)
    publish.add_argument("--registry", default="registry")
    publish.add_argument("--repository", required=True)
    publish.add_argument("--release-tag")
    publish.add_argument("--github-output")
    publish.set_defaults(func=cmd_publish)

    index = sub.add_parser("index", help="Generate the static Simple Repository view")
    index.add_argument("--registry", default="registry")
    index.add_argument("--out", default="site")
    index.set_defaults(func=cmd_index)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except ForgeError as exc:
        print(f"rimera-forge: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
