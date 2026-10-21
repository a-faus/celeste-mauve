"""Verify the public Mauve package and prepatched boot configuration."""
from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "public-site"


def main() -> None:
    manifest = json.loads((SITE / "package-manifest.json").read_text(encoding="utf-8"))
    framework = manifest["mauveFramework"]
    assert framework["id"] == "mauve-framework-v1"
    assert len(framework["chunks"]) == 1
    chunk = framework["chunks"][0]
    archive_path = SITE / chunk["url"].removeprefix("./")
    data = archive_path.read_bytes()
    assert len(data) == chunk["size"] == framework["bytes"]
    assert hashlib.sha256(data).hexdigest() == chunk["sha256"]

    with gzip.open(archive_path, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|") as archive:
            names = []
            for member in archive:
                name = member.name.removeprefix("./")
                path = PurePosixPath(name)
                assert member.isfile()
                assert not path.is_absolute() and ".." not in path.parts
                assert not {part.lower() for part in path.parts}.intersection(
                    {"saves", "cache", "logs", "backups", ".git"}
                )
                assert not name.lower().endswith((".celeste", ".pdb", ".log", ".sum", ".check"))
                assert "randomizer" not in name.lower()
                names.append(name)

    assert "CustomCeleste.dll" in names
    assert "Celeste/Everest/Celeste.Mod.mm.dll" in names
    assert len(names) == framework["files"]

    mods = manifest["mauveRequiredMods"]
    assert len(mods) == 7 and mods[0]["label"] == "Mauve"
    assert all("randomizer" not in mod["label"].lower() for mod in mods)

    boot = (SITE / "public-boot.mjs").read_text(encoding="utf-8")
    assert "installMauveFramework(root, manifest.mauveFramework)" in boot
    assert "url.searchParams.set('prepatched', '1')" in boot
    assert "url.searchParams.delete('everest')" in boot
    assert "url.searchParams.set('mode', MODE)" in boot
    print(f"PASS: {framework['files']} clean Everest files, no Randomizer or saves, 7 Mauve packages, prepatched launch settings.")


if __name__ == "__main__":
    main()
