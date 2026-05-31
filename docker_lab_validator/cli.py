from __future__ import annotations

import argparse
import sys
from pathlib import Path
from .models import TestStatus
from .parser import MarkdownLabParser
from .runner import ValidationRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Docker networking/security Markdown lab guides.")
    parser.add_argument("documents", nargs="+", help="Markdown documents to validate")
    parser.add_argument("--output-dir", default="reports", help="Directory for reports, logs, and checkpoints")
    parser.add_argument("--timeout", type=int, default=120, help="Per-code-block timeout in seconds")
    parser.add_argument("--resume", action="store_true", help="Skip tests already stored in checkpoint.json")
    parser.add_argument("--chapter", help="Only run tests whose chapter contains this text")
    parser.add_argument("--section", help="Only run tests whose section/subsection contains this text")
    parser.add_argument("--test-id", help="Only run a single test id")
    parser.add_argument("--no-cleanup", action="store_true", help="Disable automatic cleanup")
    parser.add_argument("--list-tests", action="store_true", help="Parse and list tests without executing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    documents = [Path(p) for p in args.documents]
    if args.list_tests:
        parser = MarkdownLabParser()
        for document in documents:
            for test in parser.parse_file(document):
                print(f"{test.id}\t{test.full_section}\t{test.line_start}")
        return 0
    runner = ValidationRunner(output_dir=args.output_dir, timeout=args.timeout, cleanup=not args.no_cleanup)
    results = runner.run_documents(documents, resume=args.resume, chapter=args.chapter, section=args.section, test_id=args.test_id)
    bad = {TestStatus.FAIL, TestStatus.ERROR, TestStatus.TIMEOUT}
    return 1 if any(result.status in bad for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
