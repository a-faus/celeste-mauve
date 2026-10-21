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
    assert framework["id"] == "mauve-framework-v5"
    assert framework["version"] == "known-working Webleste browser runtime"
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

    assert len(names) == len(set(names)), "Runtime archive must not contain duplicate paths."
    assert "CustomCeleste.dll" in names
    assert "Celeste/Everest/Celeste.Mod.mm.dll" in names
    assert "Celeste/Everest/Celeste.Mod.mm.deps.json" in names
    assert "Celeste/Everest/MMHOOK_Celeste.dll" in names
    assert "Celeste/Everest/MonoMod.RuntimeDetour.dll" in names
    assert "Celeste/Everest/MonoMod.Core.dll" in names
    assert "Celeste/Everest/LICENSE.txt" in names
    assert "FNA.dll" in names
    assert "Microsoft.Xna.Framework.dll" in names
    with tarfile.open(archive_path, mode="r:gz") as archive:
        custom_celeste = archive.extractfile("CustomCeleste.dll")
        assert custom_celeste is not None
        assert hashlib.sha256(custom_celeste.read()).hexdigest() == framework["prepatchedCelesteSha256"]
    assert len(names) == framework["files"]

    mods = manifest["mauveRequiredMods"]
    assert [mod["label"] for mod in mods] == [
        "Mauve",
        "Brokemia Helper",
        "Maddie's Helping Hand",
        "Isa's Grab Bag",
        "Contort Helper",
        "VivHelper",
    ]
    assert all("randomizer" not in mod["label"].lower() for mod in mods)
    assert all("gravity" not in mod["label"].lower() for mod in mods)

    boot = (SITE / "public-boot.mjs").read_text(encoding="utf-8")
    assert "installMauveFramework(root, manifest.mauveFramework)" in boot
    assert "url.searchParams.set('prepatched', '1')" in boot
    assert "url.searchParams.delete('everest')" in boot
    assert "url.searchParams.delete('autoplay')" in boot
    assert "prepatchedCelesteSha256" in boot
    assert "patcher.PatchCeleste(true)" not in boot
    assert "url.searchParams.set('mode', MODE)" in boot
    print(f"PASS: {framework['files']} prepatched Webleste runtime files, runtime integrity checks, no Randomizer or saves, Mauve plus its five declared helpers.")


if __name__ == "__main__":
    main()
