// Builds and signs the release zip that installed copies update from. Run on Julian's PC (needs Node and gh):
//   gh release create v1.3.2 --generate-notes        (bump VERSION in hush.py first, push the commit)
//   node scripts/sign-release.js --upload            zips tag v<VERSION>, signs it, uploads zip + .sig
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
const keyFile = process.env.RELEASE_SIGNING_KEY || path.join(os.homedir(), '.release-keys', 'updates-ed25519.pem');

fs.mkdirSync(path.join(root, 'dist'), { recursive: true });
const zip = path.join(root, 'dist', `hush-${tag}.zip`);
execFileSync('git', ['-C', root, 'archive', '--format=zip', '--prefix=hush/', '-o', zip, ref], { stdio: 'inherit' });
const text = Buffer.from(`Hush ${version} ${crypto.createHash('sha256').update(fs.readFileSync(zip)).digest('hex')}\n`);
const sig = crypto.sign(null, text, fs.readFileSync(keyFile));
const key = crypto.createPublicKey({ key: Buffer.from('302a300506032b6570032100' + pub, 'hex'), format: 'der', type: 'spki' });
if (!crypto.verify(null, text, key, sig)) throw new Error('this key does not match PUBKEY in hush.py');
fs.writeFileSync(zip + '.sig', sig.toString('base64') + '\n');
console.log(`signed ${path.basename(zip)}`);
if (process.argv.includes('--upload')) execFileSync('gh', ['release', 'upload', tag, zip, zip + '.sig', '--clobber', '-R', 'gigolajulian/hush'], { stdio: 'inherit' });
