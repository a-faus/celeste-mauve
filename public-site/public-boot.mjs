// Base data is fetched from a-faus/celeste-browser. Mod ZIPs are fetched from
// their official GameBanana download URLs and are never mirrored in this repo.
import {migrateSharedSaves, installSaveRouting, withSaveSession} from './shared-saves.mjs?mauve-saves-v3';

const MODE = 'mauve';
const NAMESPACE = `public-celeste-${MODE}-v1`;
const MANIFEST_URL = './package-manifest.json?mauve-package-v8';
const status = document.querySelector('#status');
const progress = document.querySelector('#progress');
const title = document.querySelector('#title');
const retry = document.querySelector('#retry');
let phase = 'Starting Mauve';
retry.addEventListener('click', () => location.reload());

function fail(error) {
  title.textContent = 'Could not start Mauve';
  status.textContent = `${phase}: ${error?.message || String(error)}`;
  status.classList.add('error');
  retry.style.display = 'inline-block';
  console.error(error);
}

export class ByteReader {
  constructor(stream) { this.reader = stream.getReader(); this.pending = new Uint8Array(); }
  async piece(limit) {
    if (!this.pending.length) {
      const {value, done} = await this.reader.read();
      if (done) throw new Error('The game download ended unexpectedly. Retry the download.');
      this.pending = value;
    }
    const part = this.pending.subarray(0, limit);
    this.pending = this.pending.subarray(part.length);
    return part;
  }
  async exact(size) {
    const result = new Uint8Array(size);
    let offset = 0;
    while (offset < size) {
      const part = await this.piece(size - offset);
      result.set(part, offset);
      offset += part.length;
    }
    return result;
  }
}

export async function extractTar(stream, root, fileCallback = () => {}) {
  const reader = new ByteReader(stream);
  const decoder = new TextDecoder();
  const field = bytes => decoder.decode(bytes).replace(/\0.*$/, '').trim();
  for (;;) {
    const header = await reader.exact(512);
    if (header.every(byte => byte === 0)) break;
    const prefix = field(header.subarray(345, 500));
    const name = (prefix ? `${prefix}/` : '') + field(header.subarray(0, 100));
    const parts = name.split('/');
    if (!name || parts.some(part => !part || part === '.' || part === '..' || part.includes('\\')) ||
        parts.some(part => ['saves', 'cache', 'backups'].includes(part.toLowerCase())) ||
        /\.(celeste|pdb|log|sum)$/i.test(name)) {
      throw new Error('Unsafe or personal file detected in the game package.');
    }
    let checksum = 0;
    for (let i = 0; i < 512; i++) checksum += i >= 148 && i < 156 ? 32 : header[i];
    if (checksum !== parseInt(field(header.subarray(148, 156)), 8)) throw new Error('Invalid game package header.');
    const size = parseInt(field(header.subarray(124, 136)) || '0', 8);
    if (!Number.isSafeInteger(size) || size < 0 || ![0, 48].includes(header[156])) throw new Error('Unsupported game package entry.');
    let folder = root;
    for (const part of parts.slice(0, -1)) folder = await folder.getDirectoryHandle(part, {create:true});
    const file = await folder.getFileHandle(parts.at(-1), {create:true});
    const writer = await file.createWritable();
    try {
      let left = size;
      while (left) { const data = await reader.piece(left); await writer.write(data); left -= data.length; }
      await writer.close();
    } catch (error) { await writer.abort().catch(() => {}); throw error; }
    if (size % 512) await reader.exact(512 - size % 512);
    fileCallback(name);
  }
  while (!(await reader.reader.read()).done) {}
}

function packageStream(pkg, update) {
  let chunkIndex = 0, current = null, offset = 0, loaded = 0;
  return new ReadableStream({
    async pull(controller) {
      try {
        if (!current || offset >= current.length) {
          if (chunkIndex >= pkg.chunks.length) { controller.close(); return; }
          const chunk = pkg.chunks[chunkIndex++];
          let lastError;
          for (let attempt = 1; attempt <= 3; attempt++) {
            phase = `Downloading Celeste data chunk ${chunkIndex} of ${pkg.chunks.length} (attempt ${attempt}/3)`;
            status.textContent = phase;
            try {
              const response = await fetch(chunk.url, {cache:'no-cache'});
              if (!response.ok) throw new Error(`HTTP ${response.status}`);
              const bytes = new Uint8Array(await response.arrayBuffer());
              if (bytes.length !== chunk.size) throw new Error(`incomplete file (${bytes.length} of ${chunk.size} bytes)`);
              const digest = await crypto.subtle.digest('SHA-256', bytes);
              const hash = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
              if (hash !== chunk.sha256) throw new Error('SHA-256 integrity check failed');
              current = bytes;
              break;
            } catch (error) {
              lastError = error;
              if (attempt === 3) {
                throw new Error(`Could not load base-game chunk ${chunkIndex} of ${pkg.chunks.length} from ${chunk.url}: ${error?.message || String(error)}`);
              }
              await new Promise(resolve => setTimeout(resolve, 500 * attempt));
            }
          }
          offset = 0;
          loaded += current.length;
          update(loaded / pkg.bytes * 100);
        }
        const end = Math.min(offset + 65536, current.length);
        controller.enqueue(current.subarray(offset, end));
        offset = end;
      } catch (error) { controller.error(error); }
    }
  }).pipeThrough(new DecompressionStream('gzip'));
}

async function writeText(folder, name, text) {
  const file = await folder.getFileHandle(name, {create:true});
  const writer = await file.createWritable();
  await writer.write(text);
  await writer.close();
}

async function writeBytes(folder, name, bytes) {
  const file = await folder.getFileHandle(name, {create:true});
  const writer = await file.createWritable();
  try { await writer.write(bytes); await writer.close(); }
  catch (error) { await writer.abort().catch(() => {}); throw error; }
}

async function hashHex(bytes) {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

async function backupAndRemoveLegacyCelesteDll(root) {
  let legacy;
  try { legacy = await root.getFileHandle('Celeste.dll'); }
  catch (error) { if (error.name === 'NotFoundError') return; throw error; }

  const original = await legacy.getFile();
  const bytes = await original.arrayBuffer();
  const hash = await hashHex(bytes);
  const backupName = `.PublicLegacyCeleste-${hash.slice(0, 16)}.dll.bak`;
  let backup;
  try { backup = await root.getFileHandle(backupName); }
  catch (error) {
    if (error.name !== 'NotFoundError') throw error;
    await writeBytes(root, backupName, bytes);
    backup = await root.getFileHandle(backupName);
  }

  const preserved = await backup.getFile();
  if (preserved.size !== original.size || await hashHex(await preserved.arrayBuffer()) !== hash) {
    throw new Error('The previous Celeste.dll could not be safely backed up; the original file was left untouched.');
  }
  await root.removeEntry('Celeste.dll');
}

async function installBase(root, pkg) {
  phase = 'Checking local Celeste installation';
  try { await root.getFileHandle(`.PublicPackage-${pkg.id}`); progress.value = 86; return; }
  catch (error) { if (error.name !== 'NotFoundError') throw error; }
  phase = 'Preparing Celeste base game';
  status.textContent = 'Celeste: downloading and installing the base game…';
  const stream = packageStream(pkg, percent => { progress.value = percent * 0.86; });
  let last = 0;
  await extractTar(stream, root, name => {
    if (performance.now() - last > 300) { status.textContent = `Celeste: installing ${name}`; last = performance.now(); }
  });
  await writeText(root, `.PublicPackage-${pkg.id}`, pkg.id);
}

async function installMauveFramework(root, pkg) {
  if (!pkg?.chunks?.length) throw new Error('The browser-compatible Everest runtime package is missing.');
  const marker = `.PublicPackage-${pkg.id}`;
  try { await root.getFileHandle(marker); progress.value = 92; return; }
  catch (error) { if (error.name !== 'NotFoundError') throw error; }
  phase = 'Installing the browser-compatible Everest runtime';
  status.textContent = 'Installing the browser-compatible Everest loader…';
  const stream = packageStream(pkg, percent => { progress.value = 86 + percent * 0.06; });
  let last = 0;
  await extractTar(stream, root, name => {
    if (performance.now() - last > 300) { status.textContent = `Everest: installing ${name}`; last = performance.now(); }
  });
  await writeText(root, marker, pkg.id);
  progress.value = 92;
}

async function waitForGameReady(timeoutMs = 5 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (globalThis.gameState?.ready === true) return;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('The Celeste browser runtime did not finish initializing. Reload to retry.');
}

async function waitForPlayButton(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const button = [...document.querySelectorAll('button')].find(item =>
      item.textContent?.replace(/\s/g, '') === 'Play'
    );
    if (button && !button.disabled) return button;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error('Celeste initialized, but its Play button did not become available.');
}

async function installOfficialMod(root, pkg, index, count) {
  const mods = await root.getDirectoryHandle('Mods', {create:true});
  const file = await mods.getFileHandle(pkg.file, {create:true});
  try {
    const current = await file.getFile();
    if (current.size === pkg.size && await hashHex(await current.arrayBuffer()) === pkg.sha256) {
      progress.value = 92 + ((index + 1) / count) * 8;
      return;
    }
  } catch {}
  phase = index === 0 ? 'Downloading Mauve and required helpers' : `Downloading required helper ${index} of ${count - 1}`;
  progress.value = 92 + (index / count) * 8;
  status.textContent = index === 0
    ? 'Downloading the Mauve map from its official GameBanana file…'
    : `Downloading required helper ${index} of ${count - 1}: ${pkg.label}…`;
  let response;
  try { response = await fetch(pkg.url, {cache:'no-cache'}); }
  catch (error) { throw new Error(`Could not reach the official ${pkg.label} download at ${pkg.url}: ${error?.message || String(error)}`); }
  if (!response.ok) throw new Error(`${pkg.label} download failed (${response.status}). Please retry.`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength !== pkg.size) throw new Error(`${pkg.label} download was incomplete. Please retry.`);
  if (await hashHex(bytes) !== pkg.sha256) throw new Error(`${pkg.label} failed its integrity check. Please retry.`);
  const writer = await file.createWritable();
  try { await writer.write(bytes); await writer.close(); }
  catch (error) { await writer.abort().catch(() => {}); throw error; }
  progress.value = 92 + ((index + 1) / count) * 8;
}

async function removeObsoleteMauveFiles(root) {
  const folders = [];
  folders.push(await root.getDirectoryHandle('Mods', {create:true}));
  try {
    const celeste = await root.getDirectoryHandle('Celeste');
    folders.push(await celeste.getDirectoryHandle('Mods'));
  } catch (error) {
    if (error.name !== 'NotFoundError') throw error;
  }
  for (const folder of folders) {
    for (const name of ['Randomizer.zip', 'gravityhelper.zip']) {
      try { await folder.removeEntry(name); }
      catch (error) { if (error.name !== 'NotFoundError') throw error; }
    }
    try {
      await folder.getDirectoryHandle('Cache');
      await folder.removeEntry('Cache', {recursive:true});
    } catch (error) {
      if (!['NotFoundError', 'TypeMismatchError'].includes(error.name)) throw error;
    }
  }
}

async function start() {
  phase = 'Checking browser requirements';
  if (!isSecureContext || !navigator.storage?.getDirectory || !globalThis.DecompressionStream) {
    throw new Error('Open this HTTPS page in an up-to-date desktop Chrome or Edge browser, outside Incognito.');
  }
  if (!crossOriginIsolated) {
    status.textContent = 'Enabling the browser features needed by the game. This page may reload once…';
    setTimeout(() => {
      if (!crossOriginIsolated) fail(new Error('The game needs service workers and cross-origin isolation. Browser or school restrictions may be blocking them.'));
    }, 15000);
    return;
  }
  const origin = await navigator.storage.getDirectory();
  phase = 'Loading the Mauve package manifest';
  const root = await origin.getDirectoryHandle(NAMESPACE, {create:true});
  const manifestResponse = await fetch(MANIFEST_URL, {cache:'no-cache'});
  if (!manifestResponse.ok) throw new Error('Could not load the base game manifest. Please try again later.');
  const manifest = await manifestResponse.json();
  if (!manifest.base?.chunks?.length || !manifest.mauveFramework?.chunks?.length) {
    throw new Error('The base game or prepatched Everest runtime package is missing.');
  }
  title.textContent = 'Preparing Celeste: Mauve';
  await navigator.storage.persist?.().catch(() => false);
  phase = 'Preparing Celeste base game';
  await installBase(root, manifest.base);
  await installMauveFramework(root, manifest.mauveFramework);
  const mods = manifest.mauveRequiredMods;
  if (!Array.isArray(mods) || mods.length !== 6) throw new Error('The Mauve map and its five declared helper packages are not listed correctly.');
  await removeObsoleteMauveFiles(root);
  for (let i = 0; i < mods.length; i++) await installOfficialMod(root, mods[i], i, mods.length);
  phase = 'Connecting shared saves';
  status.textContent = 'Connecting the existing shared saves…';
  await migrateSharedSaves(origin);
  await installSaveRouting(origin);
  await writeText(root, '.PublicGameReady', 'mauve-ready-v6');
  progress.value = 100;
  status.textContent = 'Starting the browser game runtime…';
  await import('./assets/index-9lMdcnsS.js?mauve-only-v11');
  await waitForGameReady();

  const patchMarker = `.PublicPatch-${manifest.mauveFramework.id}`;
  let patched = false;
  try {
    await root.getFileHandle(patchMarker);
    patched = true;
  } catch (error) {
    if (error.name !== 'NotFoundError') throw error;
  }
  if (!patched) {
    phase = 'Preserving the previous Celeste assembly';
    status.textContent = 'Safely backing up the old game assembly before preparing Everest…';
    await backupAndRemoveLegacyCelesteDll(root);
    phase = 'Patching Celeste for the installed Everest version';
    status.textContent = 'Applying the browser compatibility patch from the clean Celeste executable (first launch only)…';
    const patcher = globalThis.wasm?.exports?.Patcher;
    if (typeof patcher?.PatchCeleste !== 'function') {
      throw new Error('The Webleste patcher was not available after runtime initialization.');
    }
    const success = await patcher.PatchCeleste(true);
    if (!success) throw new Error('Webleste could not patch the clean Celeste executable with the installed Everest runtime.');
    await writeText(root, patchMarker, manifest.mauveFramework.id);
  }

  const play = await waitForPlayButton();
  document.querySelector('#startup').remove();
  document.querySelector('link[href="./public.css"]')?.remove();
  play.click();
}

const url = new URL(location.href);
url.searchParams.set('mode', MODE);
url.searchParams.set('mods', '1');
url.searchParams.set('prepatched', '1');
url.searchParams.delete('everest');
url.searchParams.delete('autoplay');
if (url.href !== location.href) history.replaceState(null, '', url);

withSaveSession(navigator.locks, async () => {
  await start();
  await new Promise(() => {});
}).catch(fail);
