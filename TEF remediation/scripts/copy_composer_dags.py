#!/usr/bin/env python3
"""
One-off script: clone the dags/ folder from the prod Composer GCS bucket into
the dags2/ folder of the test or dev Composer bucket.

- Folder structure is preserved (dags/a/b/c.py → dags2/a/b/c.py).
- YAML files (.yml / .yaml) have every occurrence of "prod" replaced with the
  target word ("test" or "dev") before upload.
- All other file types are copied server-side without downloading.

Usage:
  python copy_composer_dags.py --target test
  python copy_composer_dags.py --target dev

Override bucket names if the actual GCS bucket name differs from the default
(e.g. the Composer bucket includes a hash suffix):
  python copy_composer_dags.py \\
      --target     test \\
      --src-bucket europe-west3-fastoss-prod-composer-3-abc123-bucket \\
      --dst-bucket europe-west3-fastoss-test-composer-3-def456-bucket

Dry run (lists actions without writing):
  python copy_composer_dags.py --target test --dry-run
"""
import argparse
import sys

from google.cloud import storage

DEFAULT_SRC_BUCKET = "fastoss-prod-composer-3"
DEFAULT_DST_BUCKETS = {
    "test": "fastoss-test-composer-3",
    "dev":  "fastoss-dev-composer-3",
}

SRC_PREFIX = "dags/"
DST_PREFIX = "dags2/"
YAML_EXTENSIONS = {".yml", ".yaml"}


def copy_dags(
    src_bucket_name: str,
    dst_bucket_name: str,
    target_word: str,
    dry_run: bool,
) -> None:
    client = storage.Client()
    src_bucket = client.bucket(src_bucket_name)
    dst_bucket = client.bucket(dst_bucket_name)

    blobs = list(client.list_blobs(src_bucket_name, prefix=SRC_PREFIX))
    if not blobs:
        print(f"No blobs found under gs://{src_bucket_name}/{SRC_PREFIX}")
        sys.exit(1)

    print(f"Source      : gs://{src_bucket_name}/{SRC_PREFIX}")
    print(f"Destination : gs://{dst_bucket_name}/{DST_PREFIX}")
    print(f"Target word : {target_word!r}  (replacing 'prod' in YAML files)")
    print(f"Dry run     : {dry_run}")
    print(f"Files found : {len(blobs)}\n")

    yaml_count   = 0
    copied_count = 0

    for blob in blobs:
        # Skip folder pseudo-objects (trailing slash)
        if blob.name.endswith("/"):
            continue

        relative = blob.name[len(SRC_PREFIX):]
        dst_name = DST_PREFIX + relative

        ext = "." + blob.name.rsplit(".", 1)[-1].lower() if "." in blob.name else ""
        is_yaml = ext in YAML_EXTENSIONS

        if is_yaml:
            action = f"[yaml] {blob.name}  →  {dst_name}  (replace 'prod'→'{target_word}')"
        else:
            action = f"[copy] {blob.name}  →  {dst_name}"

        print(action)

        if not dry_run:
            if is_yaml:
                content = blob.download_as_text(encoding="utf-8")
                patched = content.replace("prod", target_word)
                dst_blob = dst_bucket.blob(dst_name)
                dst_blob.upload_from_string(patched, content_type=blob.content_type or "text/plain")
                yaml_count += 1
            else:
                src_bucket.copy_blob(blob, dst_bucket, dst_name)

        copied_count += 1

    print(f"\n{'─' * 60}")
    if dry_run:
        print(f"Dry run complete — {copied_count} file(s) would be processed "
              f"({sum(1 for b in blobs if not b.name.endswith('/') and '.' in b.name and b.name.rsplit('.', 1)[-1].lower() in {'yml', 'yaml'})} YAML).")
    else:
        print(f"Done — {copied_count} file(s) copied ({yaml_count} YAML patched).")
        print(f"Destination: gs://{dst_bucket_name}/{DST_PREFIX}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target", required=True, choices=["test", "dev"],
        help="Destination environment: 'test' or 'dev'",
    )
    parser.add_argument(
        "--src-bucket", default=DEFAULT_SRC_BUCKET,
        help=f"Source GCS bucket name (default: {DEFAULT_SRC_BUCKET})",
    )
    parser.add_argument(
        "--dst-bucket", default=None,
        help="Destination GCS bucket name (default: derived from --target)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned actions without writing anything",
    )
    args = parser.parse_args()

    dst_bucket = args.dst_bucket or DEFAULT_DST_BUCKETS[args.target]
    copy_dags(
        src_bucket_name=args.src_bucket,
        dst_bucket_name=dst_bucket,
        target_word=args.target,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
