// Builds and signs the release zip that installed copies update from. Run on Julian's PC (needs Node and gh):
//   gh release create v1.3.2 --generate-notes        (bump VERSION in hush.py first, push the commit)
//   .venv\Scripts\python scripts/build.py            builds dist\Hush.exe for this version
//   node scripts/sign-release.js --upload            zips tag v<VERSION>, signs zip + exe, uploads them with their .sig
// Old copies still update from GitHub's source zip; this one adds hush-<tag>.zip and its .sig next to it.
// Key: RELEASE_SIGNING_KEY (a file path) or ~/.release-keys/updates-ed25519.pem. Never in a repo, never printed.
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'hush.py'), 'utf8');
const version = /^VERSION = "([^"]+)"/m.exec(src)[1];
const pub = /^PUBKEY = bytes\.fromhex\("([0-9a-f]{64})"\)/m.exec(src)[1];
const tag = `v${version}`;
const ref = process.env.HUSH_REF || tag; // HUSH_REF=HEAD for a dry run before the tag exists
const keyDir = path.join(os.homedir(), '.release-keys');
const keyFile = process.env.RELEASE_SIGNING_KEY ||
  ['updates-ed25519.pem', 'updates-ed25519.enc.pem'].map((f) => path.join(keyDir, f)).find(fs.existsSync);

fs.mkdirSync(path.join(root, 'dist'), { recursive: true });
const zip = path.join(root, 'dist', `hush-${tag}.zip`);
execFileSync('git', ['-C', root, 'archive', '--format=zip', '--prefix=hush/', '-o', zip, ref], { stdio: 'inherit' });
// The installed Windows app updates from hush-<tag>.exe, built by install.ps1 (or scripts/build.py) into dist\Hush.exe.
// An exe that reports an older version would see this release as new and reinstall itself forever, so check it.
const built = path.join(root, 'dist', 'Hush.exe');
if (!fs.existsSync(built)) throw new Error('no dist\\Hush.exe: run scripts/build.py from this tag first');
const exeVersion = execFileSync('powershell', ['-NoProfile', '-Command', `(Get-Item '${built}').VersionInfo.ProductVersion`]).toString().trim();
if (exeVersion !== version) throw new Error(`dist\\Hush.exe is ${exeVersion}, not ${version}: rebuild it`);
const exe = path.join(root, 'dist', `hush-${tag}.exe`);
fs.copyFileSync(built, exe);

// An encrypted key asks for its passphrase in the terminal, hidden; it is never stored or printed.
const pem = fs.readFileSync(keyFile, 'utf8');
const passphrase = pem.includes('ENCRYPTED') ? execFileSync('powershell', ['-NoProfile', '-Command',
  "[Net.NetworkCredential]::new('', (Read-Host 'Release key passphrase' -AsSecureString)).Password"],
  { stdio: ['inherit', 'pipe', 'inherit'] }).toString().replace(/\r?\n$/, '') : undefined;
const privateKey = crypto.createPrivateKey({ key: pem, passphrase });
const key = crypto.createPublicKey({ key: Buffer.from('302a300506032b6570032100' + pub, 'hex'), format: 'der', type: 'spki' });
for (const file of [zip, exe]) {
  const text = Buffer.from(`Hush ${version} ${crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')}\n`);
  const sig = crypto.sign(null, text, privateKey);
  if (!crypto.verify(null, text, key, sig)) throw new Error('this key does not match PUBKEY in hush.py');
  fs.writeFileSync(file + '.sig', sig.toString('base64') + '\n');
  console.log(`signed ${path.basename(file)}`);
}
if (process.argv.includes('--upload')) execFileSync('gh', ['release', 'upload', tag, zip, zip + '.sig', exe, exe + '.sig', '--clobber', '-R', 'loupedesk/hush'], { stdio: 'inherit' });
