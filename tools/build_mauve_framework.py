"""Build a save-free, prepatched Webleste runtime from the known-good browser package."""
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
PACKAGE_ID = "mauve-framework-v5"
RUNTIME_VERSION = "known-working Webleste browser runtime"


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


def include_working_runtime(name: str) -> bool:
    path = PurePosixPath(name)
    if name == "CustomCeleste.dll":
        return True
    if name in {"FNA.dll", "Microsoft.Xna.Framework.dll"}:
        return True
    return (
        name.startswith("Celeste/Everest/")
        and len(path.parts) == 3
        and path.suffix.lower() in {".dll", ".json", ".xml", ".yaml", ".png"}
    )


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


def build(working_package: Path) -> dict:
    output = SITE / "data" / "mauve-framework.tar.gz"
    output.parent.mkdir(parents=True, exist_ok=True)
    selected: dict[str, bytes] = {}

    with tarfile.open(working_package, mode="r:*") as source:
        for member in source:
            name = clean_name(member.name)
            if not member.isfile() or private(name) or not include_working_runtime(name):
                continue
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError(f"Could not read working runtime file: {name}")
            selected[name] = stream.read()

    selected["Celeste/Everest/LICENSE.txt"] = (SITE / "EVEREST-LICENSE.txt").read_bytes()
    required = {
        "CustomCeleste.dll",
        "Celeste/Everest/Celeste.Mod.mm.dll",
        "Celeste/Everest/Celeste.Mod.mm.deps.json",
        "Celeste/Everest/MMHOOK_Celeste.dll",
        "Celeste/Everest/MonoMod.RuntimeDetour.dll",
        "Celeste/Everest/MonoMod.Core.dll",
        "Celeste/Everest/LICENSE.txt",
        "FNA.dll",
        "Microsoft.Xna.Framework.dll",
    }
    if not required.issubset(selected):
        raise ValueError(f"The known-good browser runtime is missing required files: {sorted(required - selected.keys())}")
    if any("Randomizer" in name for name in selected):
        raise ValueError("The public Mauve support archive must not contain Randomizer files.")
    if any(private(name) for name in selected):
        raise ValueError("The public Mauve support archive contains a private path.")

    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as dest,
    ):
        for name, data in sorted(selected.items()):
            add_bytes(dest, name, data)

    data = output.read_bytes()
    custom_sha256 = hashlib.sha256(selected["CustomCeleste.dll"]).hexdigest()
    entry = {
        "id": PACKAGE_ID,
        "version": RUNTIME_VERSION,
        "bytes": len(data),
        "files": len(selected),
        "prepatchedCelesteSha256": custom_sha256,
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
        "runtime": RUNTIME_VERSION,
        "frameworkFiles": len(selected),
        "randomizerFiles": 0,
        "saveFiles": 0,
        "prepatchedCelesteSha256": custom_sha256,
        "package": entry,
    }
    (ROOT / ".mauve-framework-audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(selected)} prepatched Webleste runtime files ({len(data):,} compressed bytes).")
    print(f"CustomCeleste SHA-256: {custom_sha256}")
    print(f"Package SHA-256: {entry['chunks'][0]['sha256']}")
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--working-package",
        required=True,
        type=Path,
        help="Existing known-working browser game package; only runtime files are copied, never mods or saves.",
    )
    args = parser.parse_args()
    build(args.working_package)


if __name__ == "__main__":
    main()
