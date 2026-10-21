"""Build the clean Everest 1.6531 runtime package used by Mauve Pages.

The source is an official Everest stable archive. Only its managed runtime
assemblies, dependency manifest, FNA support assembly and MIT notice are copied,
along with the browser compatibility patch. No map mods, saves or debug symbols
are included.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "public-site"
PACKAGE_ID = "mauve-framework-v3"
EVEREST_VERSION = "1.6531.0"


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


def include_browser_runtime(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        name.startswith("Celeste/Everest/")
        and len(path.parts) == 3
        and path.suffix.lower() in {".dll", ".json", ".xml", ".yaml", ".png"}
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


def build(archive: Path, browser_runtime: Path, custom_celeste: Path) -> dict:
    output = SITE / "data" / "mauve-framework.tar.gz"
    output.parent.mkdir(parents=True, exist_ok=True)
    selected: dict[str, bytes] = {}
    included: list[str] = []

    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as dest,
    ):
        # Keep the prepatched browser runtime pieces (including its generated
        # Celeste hooks), then overlay Everest's current managed assemblies.
        with tarfile.open(browser_runtime, mode="r:*") as source:
            for member in source:
                name = clean_name(member.name)
                if not member.isfile() or private(name) or not include_browser_runtime(name):
                    continue
                stream = source.extractfile(member)
                if stream is None:
                    raise ValueError(f"Could not read browser runtime file: {name}")
                selected[name] = stream.read()

        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                name = clean_name(member.filename)
                if member.is_dir() or private(name):
                    continue

                parts = PurePosixPath(name).parts
                target = None
                if len(parts) == 2 and parts[0] == "main" and parts[1].lower().endswith(".dll"):
                    if parts[1] != "MiniInstaller.dll":
                        # Everest's loader assemblies are colocated with Celeste.exe.
                        # The Celeste/Everest directory is user-data, not the game root.
                        target = parts[1]
                elif name == "main/Celeste.Mod.mm.deps.json":
                    target = "Celeste.Mod.mm.deps.json"
                elif name == "main/EverestSplash/EverestSplash.dll":
                    target = "EverestSplash/EverestSplash.dll"
                if target is None:
                    continue

                selected[target] = source.read(member)

        selected["Celeste/Everest/LICENSE.txt"] = (SITE / "EVEREST-LICENSE.txt").read_bytes()
        selected["CustomCeleste.dll"] = custom_celeste.read_bytes()
        browser_hook = selected.get("Celeste/Everest/MMHOOK_Celeste.dll")
        if browser_hook is None:
            raise ValueError("The prepatched browser runtime is missing MMHOOK_Celeste.dll")
        selected["MMHOOK_Celeste.dll"] = browser_hook
        for name, data in sorted(selected.items()):
            add_bytes(dest, name, data)
            included.append(name)

    required = {
        "CustomCeleste.dll",
        "Celeste.Mod.mm.dll",
        "MMHOOK_Celeste.dll",
        "Celeste/Everest/MMHOOK_Celeste.dll",
        "Celeste.Mod.mm.deps.json",
        "MonoMod.RuntimeDetour.dll",
        "MonoMod.Core.dll",
        "EverestSplash/EverestSplash.dll",
        "Celeste/Everest/LICENSE.txt",
    }
    if not required.issubset(included):
        raise ValueError(f"The support archive is missing required files: {sorted(required - set(included))}")
    if any("Randomizer" in name for name in included):
        raise ValueError("The public Mauve support archive must not contain Randomizer files.")
    if any(private(name) for name in included):
        raise ValueError("The public Mauve support archive contains a private path.")

    data = output.read_bytes()
    entry = {
        "id": PACKAGE_ID,
        "version": EVEREST_VERSION,
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
        "everestVersion": EVEREST_VERSION,
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
    parser.add_argument("--browser-runtime", required=True, type=Path)
    parser.add_argument("--custom-celeste", required=True, type=Path)
    args = parser.parse_args()
    build(args.everest_archive, args.browser_runtime, args.custom_celeste)


if __name__ == "__main__":
    main()
