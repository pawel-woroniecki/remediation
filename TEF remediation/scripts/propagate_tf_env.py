#!/usr/bin/env python3
"""
Propagate the prod Terraform flat-export to dev-gke and test environments.

Reads all files from {flat_dir}/prod/, copies them into two sibling folders:

    {flat_dir}/prod_dev-gke/   (prod → dev-gke substitution)
    {flat_dir}/prod_test/      (prod → test substitution)

The substitution replaces 'prod' only when it appears as a standalone
environment token — not as part of words like 'production' or 'product'.

TWO-PASS REPLACEMENT
Some naming conventions use a shorter alias for certain environments
(e.g. 'dev' instead of 'dev-gke' in label values and KMS key names).
The script handles this with two passes per file:

  Pass 1 — SHORT patterns: 'prod' adjacent to underscores (label values
            like 'prod_live') and any extra patterns given via
            --short-env-pattern.  These use the short env alias
            ('dev' for dev-gke, 'test' for test — same in this case).

  Pass 2 — FULL replacement: all remaining 'prod' tokens use the full
            env name ('dev-gke', 'test').

Examples:
    prod_live                       → dev_live          (pass 1 — underscore)
    ndl-prod-kms-thales-key-ew3    → ndl-dev-kms-...   (pass 1 — custom pattern)
    tefde-gcp-fastoss-prod          → tefde-gcp-fastoss-dev-gke  (pass 2)
    fastoss-prod-gcs-bucket         → fastoss-dev-gke-gcs-bucket (pass 2)
    "production"                    → unchanged  (contains letter after prod)
    "product"                       → unchanged  (contains letter after prod)

Usage:
    python propagate_tf_env.py --flat-dir /home/nq10083194/terraform-export-flat
    python propagate_tf_env.py --flat-dir /home/nq10083194/terraform-export-flat --dry-run
    python propagate_tf_env.py --flat-dir /home/nq10083194/terraform-export-flat \
        --short-env-pattern "ndl-prod"

Options:
    --flat-dir PATH            Parent of the prod/ source folder
                               (default: /home/nq10083194/terraform-export-flat)
    --short-env-pattern REGEX  Extra regex where 'prod' should use the short env alias
                               instead of the full name. Repeatable.
    --dry-run                  Print planned writes and substitution samples without writing
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

# Short env alias used in label values and resource names that don't use the
# full compound environment name (e.g. 'dev' instead of 'dev-gke').
SHORT_ENV: dict[str, str] = {
    "dev-gke": "dev",
    "test":    "test",   # same — no difference for test
}

# Default patterns where the SHORT alias should be used (pass 1).
# These cover 'prod' adjacent to underscores, e.g. prod_live → dev_live.
DEFAULT_SHORT_PATTERNS: list[str] = [
    r"(?<![a-zA-Z_])prod(?=_)",   # prod followed by _  (e.g. prod_live)
    r"(?<=_)prod(?![a-zA-Z_])",   # prod preceded by _  (e.g. status_prod)
]

# Lifecycle block injected into every google_bigquery_dataset resource in
# propagated files so that IAM access and storage_billing_model are never
# overwritten — those settings differ per environment and are managed outside
# of this Terraform code.
DATASET_LIFECYCLE = """
  lifecycle {
    ignore_changes = [
      storage_billing_model,
      access,
    ]
  }"""

# Source environment and its output folder name per target environment.
TARGETS: dict[str, str] = {
    "dev-gke": "prod_dev-gke",
    "test":    "prod_test",
}


def replace_env(
    content: str,
    target_env: str,
    short_patterns: list[re.Pattern],
) -> tuple[str, int]:
    """Two-pass replacement. Return (new_content, substitution_count).

    Pass 1: patterns that use the short env alias (e.g. 'dev' for 'dev-gke').
    Pass 2: remaining 'prod' tokens replaced with the full env name.
    """
    short_env = SHORT_ENV.get(target_env, target_env)
    total = 0

    # Pass 1 — short alias (only meaningful when short differs from full)
    if short_env != target_env and short_patterns:
        for pattern in short_patterns:
            content, n = pattern.subn(
                lambda m, e=short_env: m.group(0).replace("prod", e),
                content,
            )
            total += n

    # Pass 2 — full env name for all remaining 'prod' tokens
    content, n = PROD_RE.subn(lambda m: target_env, content)
    total += n

    return content, total


def inject_dataset_lifecycle(content: str) -> str:
    """Insert a lifecycle ignore_changes block into a google_bigquery_dataset resource.

    Does nothing if the file is not a dataset resource or already has a lifecycle block.
    Inserts before the top-level closing brace (column-0 '}') so nested blocks are safe.
    """
    if 'resource "google_bigquery_dataset"' not in content:
        return content
    if "lifecycle" in content:
        return content  # already present — don't duplicate
    pos = content.rfind("\n}")
    if pos == -1:
        return content
    return content[:pos] + DATASET_LIFECYCLE + content[pos:]


def propagate(
    src_dir: Path,
    flat_dir: Path,
    dry_run: bool,
    short_patterns: list[re.Pattern],
) -> None:
    all_files = sorted(f for f in src_dir.rglob("*") if f.is_file())
    if not all_files:
        print(f"  [SKIP] No files found under {src_dir}")
        return

    for target_env, folder_name in TARGETS.items():
        dst_root = flat_dir / folder_name
        short_env = SHORT_ENV.get(target_env, target_env)
        label = f"prod → {short_env} (short) then → {target_env} (full)" if short_env != target_env else f"prod → {target_env}"
        print(f"\n=== {folder_name}/  ({label}) ===")

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

            new_content, subs = replace_env(content, target_env, short_patterns)
            new_content = inject_dataset_lifecycle(new_content)

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
        "--short-env-pattern",
        action="append",
        dest="short_patterns",
        default=None,
        metavar="REGEX",
        help="Extra regex pattern where 'prod' should be replaced with the short "
             "env alias (e.g. 'dev' for dev-gke) instead of the full env name. "
             "Repeatable. Example: --short-env-pattern 'ndl-prod'",
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

    # Compile short-env patterns (defaults + any user-supplied extras)
    raw_short = list(DEFAULT_SHORT_PATTERNS)
    if args.short_patterns:
        raw_short.extend(args.short_patterns)
    short_patterns = [re.compile(p) for p in raw_short]

    print(f"Source      : {src_dir}")
    print(f"Targets     : {', '.join(TARGETS.values())}")
    print(f"Short alias : {SHORT_ENV}")
    print(f"Mode        : {'DRY-RUN' if args.dry_run else 'LIVE'}")

    propagate(src_dir, flat_dir, args.dry_run, short_patterns)

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Done.")


if __name__ == "__main__":
    main()
