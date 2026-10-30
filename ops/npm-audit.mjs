// Reads `npm audit --json` and fails on every advisory but the ones accepted in
// npm-accepted.txt. An acceptance is for an advisory nobody can act on yet, so
// it fails too once npm can fix it without a breaking upgrade, and once nothing
// carries it any more: either way the line has served its purpose and goes.
import { readFileSync } from 'node:fs';

const [report, acceptedPath] = process.argv.slice(2);
const audit = JSON.parse(readFileSync(report, 'utf8'));
if (!audit.vulnerabilities) {
	console.error(`npm audit gave no report: ${JSON.stringify(audit).slice(0, 400)}`);
	process.exit(1);
}

const accepted = new Map(
	readFileSync(acceptedPath, 'utf8')
		.split('\n')
		.map((line) => line.replace(/#.*/, '').trim())
		.filter(Boolean)
		.map((line) => [line.split(/\s+/)[0], line])
);

const found = new Set();
const failures = [];
for (const [name, entry] of Object.entries(audit.vulnerabilities)) {
	for (const via of entry.via) {
		if (typeof via !== 'object') continue;
		const id = via.url.split('/').pop();
		found.add(id);
		if (!accepted.has(id)) failures.push(`${name}: ${via.severity} ${id} ${via.title}`);
		else if (entry.fixAvailable === true) failures.push(`${name}: ${id} is accepted but npm can now fix it`);
	}
}
for (const id of accepted.keys()) {
	if (!found.has(id)) failures.push(`${id} is accepted but no dependency carries it any more`);
}

for (const id of found) if (accepted.has(id)) console.log(`npm audit: accepted ${accepted.get(id)}`);
if (failures.length) {
	console.error(failures.join('\n'));
	process.exit(1);
}
console.log('npm audit: clean');
