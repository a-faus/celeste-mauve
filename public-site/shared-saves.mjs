// Share browser-local saves with the existing Celeste and Randomizer Pages.
// This module never uploads or stores save data in the repository.
export const SHARED_NAMESPACE = 'public-celeste-shared-v1';
export const SAVE_LOCK = 'public-celeste-shared-save-session-v1';
const LEGACY_MODES = ['vanilla', 'randomizer', 'spring-collab'];
const LOCK_MODES = ['vanilla', 'randomizer', 'spring-collab', 'mauve'];
const MAUVE_ROOT = 'public-celeste-mauve-v1';
const ROUTING_MARKER = Symbol.for('a-faus.celeste-mauve.save-routing.v1');
const ORIGINAL_GET_DIRECTORY = Symbol.for('a-faus.celeste-mauve.original-get-directory.v1');
const ORIGINAL_ENTRIES = Symbol.for('a-faus.celeste-mauve.original-entries.v1');
let routed = false;

async function writeFile(folder, name, bytes) {
  const file = await folder.getFileHandle(name, {create:true});
  const writer = await file.createWritable();
  try { await writer.write(bytes); await writer.close(); }
  catch (error) { await writer.abort().catch(() => {}); throw error; }
}

async function collect(folder, prefix = '') {
  const found = [];
  for await (const [name, handle] of folder.entries()) {
    if (handle.kind === 'directory') found.push(...await collect(handle, `${prefix}${name}/`));
    else found.push({path:`${prefix}${name}`, file:await handle.getFile()});
  }
  return found;
}

async function destination(root, path) {
  const parts = path.split('/');
  let folder = root;
  for (const part of parts.slice(0, -1)) folder = await folder.getDirectoryHandle(part, {create:true});
  return {folder, name:parts.at(-1)};
}

export async function migrateSharedSaves(origin) {
  const shared = await origin.getDirectoryHandle(SHARED_NAMESPACE, {create:true});
  const saves = await shared.getDirectoryHandle('Saves', {create:true});
  let firstMigration = false;
  try { await shared.getFileHandle('.MigrationComplete-v1'); }
  catch (error) { if (error.name !== 'NotFoundError') throw error; firstMigration = true; }
  const backups = firstMigration ? await shared.getDirectoryHandle('MigrationBackups', {create:true}) : null;
  const candidates = new Map();
  // Preserve legacy mode files before importing them. Existing shared files are
  // never replaced by older copies; when timestamps conflict, the newest wins.
  for (const mode of LEGACY_MODES) {
    let previous;
    try {
      const root = await origin.getDirectoryHandle(`public-celeste-${mode}-v1`);
      previous = await (await root.getDirectoryHandle('Celeste')).getDirectoryHandle('Saves');
    } catch (error) { if (error.name === 'NotFoundError') continue; throw error; }
    const backup = backups ? await backups.getDirectoryHandle(mode, {create:true}) : null;
    for (const entry of await collect(previous)) {
      if (backup) {
        const bytes = await entry.file.arrayBuffer();
        const target = await destination(backup, entry.path);
        await writeFile(target.folder, target.name, bytes);
        const verified = await (await target.folder.getFileHandle(target.name)).getFile();
        const copy = new Uint8Array(await verified.arrayBuffer());
        const original = new Uint8Array(bytes);
        if (copy.length !== original.length || copy.some((value, index) => value !== original[index])) {
          throw new Error('Save backup verification failed. Existing saves were not changed.');
        }
      }
      const prior = candidates.get(entry.path);
      if (!prior || entry.file.lastModified > prior.file.lastModified) candidates.set(entry.path, entry);
    }
  }
  for (const entry of candidates.values()) {
    const target = await destination(saves, entry.path);
    let current;
    try { current = await (await target.folder.getFileHandle(target.name)).getFile(); }
    catch (error) { if (error.name !== 'NotFoundError') throw error; }
    if (!current || entry.file.lastModified > current.lastModified) {
      await writeFile(target.folder, target.name, await entry.file.arrayBuffer());
    }
  }
  if (firstMigration) {
    await writeFile(shared, '.MigrationComplete-v1', 'Legacy Celeste saves preserved; newest conflicting file selected.');
  }
  return saves;
}

export async function installSaveRouting(origin) {
  if (routed) return;
  // Webleste's WASM worker calls this with its mode string. Resolve OPFS in
  // that worker's own realm before applying the same save routing there.
  if (typeof origin === 'string') origin = await navigator.storage.getDirectory();
  const proto = FileSystemDirectoryHandle.prototype;
  // Different query-string module URLs create separate module instances. A
  // prototype marker prevents one instance from wrapping another instance's
  // wrapper and accidentally forwarding to a stale or cross-realm method.
  if (proto[ROUTING_MARKER]) { routed = true; return; }
  const getDirectory = proto[ORIGINAL_GET_DIRECTORY] || proto.getDirectoryHandle;
  const entries = proto[ORIGINAL_ENTRIES] || proto.entries;
  if (!proto[ORIGINAL_GET_DIRECTORY]) Object.defineProperty(proto, ORIGINAL_GET_DIRECTORY, {value:getDirectory});
  if (!proto[ORIGINAL_ENTRIES]) Object.defineProperty(proto, ORIGINAL_ENTRIES, {value:entries});
  const root = await getDirectory.call(origin, MAUVE_ROOT, {create:true});
  const celeste = await getDirectory.call(root, 'Celeste', {create:true});
  // Keep the real directory for WASM type checks; redirect reads and writes to
  // the same physical Saves handle used by the other a-faus browser pages.
  await getDirectory.call(celeste, 'Saves', {create:true});
  const mods = await getDirectory.call(root, 'Mods', {create:true});
  const shared = await getDirectory.call(origin, SHARED_NAMESPACE, {create:true});
  const saves = await getDirectory.call(shared, 'Saves', {create:true});
  proto.getDirectoryHandle = async function(name, options) {
    if (name === 'Saves' && this.name === 'Celeste' && await this.isSameEntry(celeste)) return saves;
    if (name === 'Mods' && (await this.isSameEntry(root) || await this.isSameEntry(celeste))) return mods;
    return getDirectory.call(this, name, options);
  };
  proto.entries = async function*() {
    const inCeleste = this.name === 'Celeste' && await this.isSameEntry(celeste);
    const inRoot = await this.isSameEntry(root);
    for await (const [name, handle] of entries.call(this)) {
      yield [name, inCeleste && name === 'Saves' ? saves : (inCeleste || inRoot) && name === 'Mods' ? mods : handle];
    }
  };
  proto[Symbol.asyncIterator] = proto.entries;
  proto.values = async function*() { for await (const [, handle] of this.entries()) yield handle; };
  proto.keys = async function*() { for await (const [name] of this.entries()) yield name; };
  Object.defineProperty(proto, ROUTING_MARKER, {value:true});
  routed = true;
}

export async function withSaveSession(locks, action) {
  if (!locks) throw new Error('Shared saves need a current Chrome or Edge browser with Web Locks support.');
  const names = [SAVE_LOCK, ...LOCK_MODES.map(mode => `public-celeste-${mode}-v1`)];
  const acquire = index => index === names.length ? action() : locks.request(names[index], {ifAvailable:true}, lock => {
    if (!lock) throw new Error('Another Celeste page is already open. Close its game tab before starting Mauve so progress is saved safely.');
    return acquire(index + 1);
  });
  return acquire(0);
}
