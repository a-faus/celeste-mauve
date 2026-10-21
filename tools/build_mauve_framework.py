"""Build the clean, prepatched Everest support package used by Mauve Pages.

The archive source is the existing browser-compatible Randomizer runtime bundle.
Only Everest runtime files and the repaired CustomCeleste.dll are copied; no
Randomizer mod archive, saves, cache files, or debug symbols are included.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "public-site"
PACKAGE_ID = "mauve-framework-v1"
ALLOWED_EXTENSIONS = {".dll", ".xml", ".json", ".yaml", ".png"}


def clean_name(raw: str) -> str:
    name = raw.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in raw:
        raise ValueError(f"Unsafe archive path: {raw!r}")
    return name


def private(name: str) -> bool:
    path = PurePosixPath(name)
    parts = {part.lower() for part in path.parts}
    return bool(
        parts.intersection({"saves", "cache", "logs", "backups", ".git"})
        or name.lower().endswith((".celeste", ".pdb", ".log", ".sum", ".check"))
        or any(part.startswith(".personal") or "repairbackups" in part for part in parts)
    )


def include(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        name.startswith("Celeste/Everest/")
        and len(path.parts) == 3
        and path.suffix.lower() in ALLOWED_EXTENSIONS
    ) or name in {"FNA.dll", "Microsoft.Xna.Framework.dll"}


def add_bytes(dest: tarfile.TarFile, name: str, data: bytes) -> None:
    if private(name):
        raise ValueError(f"Private file rejected: {name}")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    dest.addfile(info, io.BytesIO(data))


def build(archive: Path, custom_celeste: Path) -> dict:
    output = SITE / "data" / "mauve-framework.tar.gz"
    output.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []

    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as dest,
        tarfile.open(archive, mode="r:*") as source,
    ):
        for member in source:
            name = clean_name(member.name)
            if not member.isfile() or private(name) or not include(name):
                continue
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError(f"Could not read runtime file: {name}")
            info = tarfile.TarInfo(name)
            info.size = member.size
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            dest.addfile(info, stream)
            included.append(name)

        add_bytes(dest, "CustomCeleste.dll", custom_celeste.read_bytes())
        included.append("CustomCeleste.dll")

    required = {"CustomCeleste.dll", "Celeste/Everest/Celeste.Mod.mm.dll"}
    if not required.issubset(included):
        raise ValueError(f"The support archive is missing required files: {sorted(required - set(included))}")
    if any("Randomizer" in name for name in included):
        raise ValueError("The public Mauve support archive must not contain Randomizer files.")
    if any(private(name) for name in included):
        raise ValueError("The public Mauve support archive contains a private path.")

    data = output.read_bytes()
    entry = {
        "id": PACKAGE_ID,
        "bytes": len(data),
        "files": len(included),
        "chunks": [{
            "url": "./data/mauve-framework.tar.gz",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }],
    }
    manifest_path = SITE / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mauveFramework"] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    audit = {
        "frameworkFiles": len(included),
        "randomizerFiles": 0,
        "saveFiles": 0,
        "package": entry,
    }
    (ROOT / ".mauve-framework-audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(included)} clean Everest runtime files ({len(data):,} compressed bytes).")
    print(f"SHA-256: {entry['chunks'][0]['sha256']}")
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--everest-archive", required=True, type=Path)
    parser.add_argument("--custom-celeste", required=True, type=Path)
    args = parser.parse_args()
    build(args.everest_archive, args.custom_celeste)


if __name__ == "__main__":
    main()
