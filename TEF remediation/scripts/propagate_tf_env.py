#!/usr/bin/env python3
"""
Propagate the prod Terraform flat-export to dev-gke and test environments.

Reads all files from {flat_dir}/prod/, copies them into two sibling folders:

    {flat_dir}/prod_dev-gke/   (prod → dev-gke substitution)
    {flat_dir}/prod_test/      (prod → test substitution)

The substitution replaces 'prod' only when it appears as a standalone
environment token — not as part of words like 'production' or 'product'.

Replacement rule:  (?<![a-zA-Z])prod(?![a-zA-Z])

Examples of strings that ARE changed:
    tefde-gcp-fastoss-prod          → tefde-gcp-fastoss-dev-gke
    fastoss-prod-gcs-devops-bucket  → fastoss-dev-gke-gcs-devops-bucket
    group-prod@domain.com           → group-dev-gke@domain.com

Examples of strings that are NOT changed:
    "production"    (followed by 'u' — word boundary rule)
    "product"       (followed by 'u' — word boundary rule)
    "managed-by-cnrm"  (does not contain 'prod')

NOTE: If prod/ files contain cross-project references to tefde-gcp-fastoss-prod-gke,
the substitution turns '-prod-' into '-dev-gke-' producing '...dev-gke-gke'.
Use --dry-run to review before applying, and fix those occurrences manually.

Usage:
    python propagate_tf_env.py --flat-dir /home/nq10083194/terraform-export-flat
    python propagate_tf_env.py --flat-dir /home/nq10083194/terraform-export-flat --dry-run

Options:
    --flat-dir PATH   Parent of the prod/ source folder
                      (default: /home/nq10083194/terraform-export-flat)
    --dry-run         Print planned writes and substitution samples without writing files
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

# Matches 'prod' as a standalone environment token:
#   - not preceded by a letter  (so 'product', 'production' are safe)
#   - not followed by a letter  (same protection)
PROD_RE = re.compile(r'(?<![a-zA-Z])prod(?![a-zA-Z])')

# Source environment and its output folder name per target environment.
TARGETS: dict[str, str] = {
    "dev-gke": "prod_dev-gke",
    "test":    "prod_test",
}


def replace_env(content: str, target_env: str) -> tuple[str, int]:
    """Return (new_content, substitution_count)."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return target_env

    new_content = PROD_RE.sub(_sub, content)
    return new_content, count


def propagate(src_dir: Path, flat_dir: Path, dry_run: bool) -> None:
    all_files = sorted(f for f in src_dir.rglob("*") if f.is_file())
    if not all_files:
        print(f"  [SKIP] No files found under {src_dir}")
        return

    for target_env, folder_name in TARGETS.items():
        dst_root = flat_dir / folder_name
        print(f"\n=== {folder_name}/  (prod → {target_env}) ===")

        total_files = 0
        total_subs = 0

        for src_file in all_files:
            rel = src_file.relative_to(src_dir)
            dst_file = dst_root / rel

            try:
                content = src_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # Binary file — copy unchanged
                if dry_run:
                    print(f"  [DRY-RUN] [binary] {rel}")
                else:
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                total_files += 1
                continue

            new_content, subs = replace_env(content, target_env)

            if dry_run:
                status = f"{subs} substitution(s)" if subs else "no changes"
                print(f"  [DRY-RUN] {rel}  ({status})")
                # Show up to 3 example substitutions per file
                if subs:
                    shown = 0
                    for line_no, (old, new) in enumerate(
                        zip(content.splitlines(), new_content.splitlines()), 1
                    ):
                        if old != new:
                            print(f"    line {line_no}:  {old.strip()}")
                            print(f"          →  {new.strip()}")
                            shown += 1
                            if shown >= 3:
                                break
            else:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                dst_file.write_text(new_content, encoding="utf-8")

            total_files += 1
            total_subs += subs

        print(f"  {'[DRY-RUN] ' if dry_run else ''}Total: {total_files} file(s), "
              f"{total_subs} substitution(s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--flat-dir",
        default="/home/nq10083194/terraform-export-flat",
        help="Parent of the prod/ source folder "
             "(default: /home/nq10083194/terraform-export-flat)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned writes and substitution samples without writing files",
    )
    args = parser.parse_args()

    flat_dir = Path(args.flat_dir)
    src_dir = flat_dir / "prod"

    if not flat_dir.exists():
        print(f"ERROR: flat-dir not found: {flat_dir}")
        sys.exit(1)
    if not src_dir.exists():
        print(f"ERROR: prod/ source folder not found: {src_dir}")
        sys.exit(1)

    print(f"Source      : {src_dir}")
    print(f"Targets     : {', '.join(TARGETS.values())}")
    print(f"Mode        : {'DRY-RUN' if args.dry_run else 'LIVE'}")

    propagate(src_dir, flat_dir, args.dry_run)

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Done.")


if __name__ == "__main__":
    main()
