# Celeste: Mauve (browser edition)

Play the Celeste map [Mauve by smoothee](https://gamebanana.com/mods/404124) at:

**https://a-faus.github.io/celeste-mauve/**

This is a small, separate GitHub Pages launcher. It does not include Randomizer, Spring Collab, or other map packs. The browser downloads the base-game package from the separate `a-faus/celeste-browser` repository and downloads Mauve plus only its six required helper mods directly from their official GameBanana files at first launch. Their ZIPs are not mirrored in this repository. On first run, click the built-in Everest patch step once to install the mod loader in this site's separate game copy. See the site's credits page for source links and licenses.

## Saves

Mauve routes the game's `Celeste/Saves` directory to the same browser-local OPFS folder used by the compatible Celeste, Randomizer, and Spring Collab pages on `a-faus.github.io`. It can merge older vanilla, Randomizer, and Spring Collab save folders by keeping the newest file and leaving the originals in place. Use the same Chrome/Edge profile and close the other game tab before switching. Save files are never included in this repository or uploaded by this page. Browser storage does not sync across devices or profiles; use the game's folder button to export a backup before clearing browser data.

## First launch

The first run downloads about 830 MiB of base-game data and roughly 9 MiB of Mauve/helper archives from their source hosts. Allow about 1.5 GB of browser storage for the isolated game installation. Current desktop Chrome or Edge with site data, service workers, and threaded WebAssembly enabled is recommended.

This is an unofficial community browser launcher, not an official Celeste release.
