#!/usr/bin/env python3
"""Deterministic file manifest (relpath/size/sha256) for a directory tree.

Stdlib only. Two modes:

  build :  python tools/science_manifest.py --root DIR [--include-untracked-only] --out manifest.json
  verify:  python tools/science_manifest.py --verify manifest.json [--root DIR]

Build walks DIR (pruning .git/ and __pycache__/), hashes every regular file in
1 MiB chunks (never a whole file in memory), records {relpath, size, sha256}
sorted by relpath, and writes a timestamp-free JSON document -- identical trees
yield byte-identical manifests.  `--include-untracked-only` drops every path
`git -C DIR ls-files` already tracks, so what remains is exactly the local /
git-ignored science input.

Verify needs no git: the paths excluded at build time are recorded in the
manifest (`ignored_relpaths`), so a copy of the tree at any other absolute path
-- inside a repo or not -- compares by relpath alone.  It reports files that are
missing, extra, size-changed or content-changed; any such difference -> exit 1.

Exit codes: 0 = match, 1 = mismatch, 2 = usage or I/O error.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

CHUNK_BYTES = 1 << 20
SKIP_DIRS = (".git", "__pycache__")
MANIFEST_VERSION = 1


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_tracked(root):
    """Paths tracked by git, relative to `root` (POSIX separators)."""
    proc = subprocess.run(
        ["git", "-C", root, "ls-files", "-z", "--", "."],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError("git ls-files failed in %s: %s" % (root, detail or proc.returncode))
    text = proc.stdout.decode("utf-8", "surrogateescape")
    return {name for name in text.split("\0") if name}


def scan(root, ignore=()):
    """Map relpath -> (size, sha256) for every regular file under `root`."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise RuntimeError("not a directory: %s" % root)
    skipped = set(ignore)
    entries = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel in skipped:
                continue
            entries[rel] = (os.stat(full).st_size, sha256_file(full))
    return entries


def build(root, untracked_only=False):
    ignore = _git_tracked(root) if untracked_only else ()
    entries = scan(root, ignore=ignore)
    paths = sorted(entries)
    files = [
        {"relpath": rel, "size": entries[rel][0], "sha256": entries[rel][1]}
        for rel in paths
    ]
    return {
        "version": MANIFEST_VERSION,
        "algorithm": "sha256",
        "chunk_bytes": CHUNK_BYTES,
        "root": os.path.abspath(root),
        "include_untracked_only": bool(untracked_only),
        "skip_dirs": list(SKIP_DIRS),
        "ignored_relpaths": sorted(ignore),
        "file_count": len(files),
        "total_bytes": sum(entry["size"] for entry in files),
        "files": files,
    }


def write_manifest(document, out_path):
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_manifest(manifest_path):
    with open(manifest_path, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("version") != MANIFEST_VERSION:
        raise RuntimeError("unsupported manifest version: %r" % document.get("version"))
    expected = {}
    for entry in document["files"]:
        rel = entry["relpath"]
        if rel in expected:
            raise RuntimeError("duplicate relpath in manifest: %s" % rel)
        expected[rel] = (entry["size"], entry["sha256"])
    return document, expected


def diff(expected, actual):
    """(missing, extra, changed) relpath lists; changed carries both records."""
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = [
        (rel, expected[rel], actual[rel])
        for rel in sorted(set(expected) & set(actual))
        if expected[rel] != actual[rel]
    ]
    return missing, extra, changed


def _describe(expected_entry, actual_entry):
    expected_size, expected_hash = expected_entry
    actual_size, actual_hash = actual_entry
    if expected_size != actual_size:
        return "size %d -> %d" % (expected_size, actual_size)
    return "sha256 %s -> %s" % (expected_hash[:12], actual_hash[:12])


def run_verify(manifest_path, root_override=None, out=sys.stdout):
    document, expected = load_manifest(manifest_path)
    root = root_override or document["root"]
    if not os.path.isdir(root):
        raise RuntimeError("not a directory: %s" % root)
    ignored = document.get("ignored_relpaths", [])
    actual = scan(root, ignore=ignored)
    missing, extra, changed = diff(expected, actual)

    print("manifest: %s (%d files, %d bytes)" % (
        manifest_path, document["file_count"], document["total_bytes"]), file=out)
    print("root:     %s" % os.path.abspath(root), file=out)
    print("scanned:  %d files (%d build-time excluded paths ignored)" % (
        len(actual), len(ignored)), file=out)
    for rel in missing:
        print("MISSING  %s" % rel, file=out)
    for rel in extra:
        print("EXTRA    %s" % rel, file=out)
    for rel, expected_entry, actual_entry in changed:
        print("CHANGED  %s (%s)" % (rel, _describe(expected_entry, actual_entry)), file=out)

    if missing or extra or changed:
        print("FAIL: %d missing, %d extra, %d changed" % (
            len(missing), len(extra), len(changed)), file=out)
        return 1
    print("OK: all %d files match (size + sha256)" % len(expected), file=out)
    return 0


def selfcheck():
    """Round-trip a temp tree: build -> verify OK -> flip one byte -> verify fails."""
    with tempfile.TemporaryDirectory(prefix="science-manifest-selfcheck-") as tmp:
        root = os.path.join(tmp, "tree")
        os.makedirs(os.path.join(root, "sub"))
        payload = b"alpha\n" * 3
        with open(os.path.join(root, "a.bin"), "wb") as handle:
            handle.write(payload)
        with open(os.path.join(root, "sub", "b.txt"), "wb") as handle:
            handle.write(payload)
        manifest = os.path.join(tmp, "manifest.json")
        write_manifest(build(root), manifest)

        document, _ = load_manifest(manifest)
        assert document["file_count"] == 2, document["file_count"]
        assert document["total_bytes"] == 2 * len(payload)
        buf = []
        assert run_verify(manifest, root, out=Collector(buf)) == 0, buf

        target = os.path.join(root, "sub", "b.txt")
        with open(target, "r+b") as handle:
            handle.seek(0)
            handle.write(b"B")
        buf = []
        assert run_verify(manifest, root, out=Collector(buf)) == 1, buf
        assert any(line.startswith("CHANGED") for line in buf), buf

        os.remove(target)
        assert run_verify(manifest, root, out=Collector([])) == 1
        print("selfcheck OK")
    return 0


class Collector:
    def __init__(self, sink):
        self.sink = sink

    def write(self, text):
        self.sink.append(text.rstrip("\n"))

    def flush(self):
        pass


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="directory to scan (build); default: root stored in manifest (verify)")
    parser.add_argument("--include-untracked-only", action="store_true",
                        help="skip files git already tracks (git -C ROOT ls-files)")
    parser.add_argument("--out", help="manifest JSON to write")
    parser.add_argument("--verify", metavar="MANIFEST", help="verify a tree against an existing manifest")
    parser.add_argument("--selfcheck", action="store_true", help="run the built-in round-trip check and exit")
    args = parser.parse_args(argv)

    try:
        if args.selfcheck:
            return selfcheck()
        if args.verify:
            if args.out:
                parser.error("--verify and --out are mutually exclusive")
            return run_verify(args.verify, args.root)
        if not args.out:
            parser.error("build mode needs --out (or use --verify MANIFEST)")
        if not args.root:
            parser.error("build mode needs --root")
        document = build(args.root, untracked_only=args.include_untracked_only)
        write_manifest(document, args.out)
        print("wrote %s: %d files, %d bytes (root %s%s)" % (
            args.out, document["file_count"], document["total_bytes"], document["root"],
            ", untracked only" if args.include_untracked_only else ""))
        return 0
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
