"""Prove the processor-bucket read before #369 relies on it (archiver#367, D4).

    python -m src.core.tools.check_processor_text <uri> <fingerprint>

Loads one stored text through the reader the service builds: the
``processor-text-reader`` credential from ``$CREDENTIALS_DIRECTORY`` and the
bucket from ``ARCHIVER_PROCESSOR_TEXT_BUCKET``. Prints ``ok <bytes>`` (exit 0),
``unavailable: <reason>`` (exit 1), or why there is no reader (exit 2). **Never
the text**, which is a watched page's. Read-only, and no database.

On the host it runs under ``systemd-run`` with the unit's own credential, user
and bucket, so it proves the unit's path rather than a root read
(docs/NOTIFICATIONS.md § The processor-text reader).
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping

from src.core.notifications.diff_loader import read_stored_text, text_reader_from_environ

EXIT_OK, EXIT_UNAVAILABLE, EXIT_ERROR = 0, 1, 2


def main(
    argv: list[str] | None = None,
    *,
    stdout=None,
    stderr=None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Read one text; print its size or the reason."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description="Read one processor text (archiver#367 D4).")
    parser.add_argument("uri", help="gs://<bucket>/<object>, from a completed process command")
    parser.add_argument("fingerprint", help="sha256:<hex>, the text's digest")
    args = parser.parse_args(argv)

    reader, reason = text_reader_from_environ(environ)
    if reader is None:
        print(f"no processor text reader: {reason}", file=stderr)
        return EXIT_ERROR
    try:
        text, reason = asyncio.run(read_stored_text(reader, args.uri, args.fingerprint))
    finally:
        reader.close()
    if text is None:
        print(f"unavailable: {reason}", file=stdout)
        return EXIT_UNAVAILABLE
    print(f"ok {len(text)}", file=stdout)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
