"""Write a real zip archive, and prove it is one before anyone relies on it.

Why this exists instead of `tar -a -f something.zip`: GNU tar does not treat `.zip` as a
compression format, so that command quietly writes a **plain tar with a zip name**. It stays
readable by tar — which is why a `tar -tf` check passes and the mistake survives review — and is
unreadable by every zip reader, PowerShell's `Expand-Archive` included. Worse, `Expand-Archive`
reports success while extracting nothing, so the install directory was mirrored over with
emptiness the first time an update ran end to end. Everything in this file is a consequence of
that afternoon.

    python tools/make-archive.py <output.zip> <source-dir> [entry ...] [--exclude name] [--store]

Entries are named relative to the source directory, so the archive unpacks at the install root.
`--store` skips deflate for data that cannot be compressed anyway (the speech model), turning a
minute of deflating into seconds of copying.

The archive is read back at the end and its entry count checked against what was written: a build
that does not produce a readable zip has to fail here, not on someone's machine.
"""
import argparse
import pathlib
import sys
import zipfile


def excluded(relative, patterns):
    return any(relative == item or relative.startswith(item + "/") for item in patterns)


def main():
    parser = argparse.ArgumentParser(description="Write a zip archive and verify it.")
    parser.add_argument("output", help="the .zip to write")
    parser.add_argument("source", help="directory the entries are named relative to")
    parser.add_argument("entries", nargs="*", help="top-level names to include (default: all)")
    parser.add_argument("--exclude", action="append", default=[], help="path to leave out")
    parser.add_argument("--store", action="store_true", help="do not compress")
    parser.add_argument("--require", action="append", default=[], help="required nonempty archive entry")
    args = parser.parse_args()

    source = pathlib.Path(args.source).resolve()
    output = pathlib.Path(args.output).resolve()
    if not source.is_dir():
        print(f"找不到源目录：{source}", file=sys.stderr)
        return 1
    entries = args.entries or sorted(path.name for path in source.iterdir())

    compression = zipfile.ZIP_STORED if args.store else zipfile.ZIP_DEFLATED
    written = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", compression, compresslevel=6) as archive:
        for entry in entries:
            path = source / entry
            candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
            for file in candidates:
                if not file.is_file():
                    continue
                relative = file.relative_to(source).as_posix()
                if excluded(relative, args.exclude):
                    continue
                archive.write(file, relative)
                written += 1

    with zipfile.ZipFile(output) as check:
        count = len(check.namelist())
        broken = check.testzip()
        missing = [name for name in args.require if name not in check.namelist() or check.getinfo(name).file_size == 0]
    if count != written or broken or missing:
        print(
            f"归档校验失败：写入 {written} 个条目，读回 {count} 个"
            + (f"，首个损坏项 {broken}" if broken else ""),
            file=sys.stderr,
        )
        if missing:
            print("缺少必需的非空文件：" + ", ".join(missing), file=sys.stderr)
        return 1

    print(
        f"  {output.name}  {output.stat().st_size / 1048576:.1f} MB  {count} 个条目"
        f"  {'存储（不压缩）' if args.store else '压缩'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
