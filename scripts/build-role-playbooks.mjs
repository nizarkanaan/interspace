import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const args = process.argv.slice(2);
assert(args.length === 0 || (args.length === 1 && args[0] === '--check'), 'Usage: node scripts/build-role-playbooks.mjs [--check]');
const contracts = JSON.parse(await readFile(new URL('../design/agents/role-contracts.json', import.meta.url), 'utf8'));
const source = await readFile(new URL('../design/agents/role-catalog.js', import.meta.url), 'utf8');
const root = { interspaceContracts: contracts };
// Inspect our own catalog with a minimal DOM stub. No provider, network or agent execution.
runInNewContext(source, { document: { getElementById: () => root } }, { timeout: 1000 });
const roles = Array.from(root.interspaceRoles.list());
assert.equal(new Set(roles.map(role => role.id)).size, roles.length, 'Role IDs must be unique');
assert.deepEqual(Object.keys(contracts.roles).sort(), roles.map(role => role.id).sort(), 'Every catalog role needs exactly one contract');
assert.match(contracts.status, /not run/i, 'Draft status must not imply model validation');
let cases = 0;
for (const role of roles) {
  const contract = contracts.roles[role.id];
  for (const key of ['mission', 'useWhen']) assert(typeof contract[key] === 'string' && contract[key].trim(), `${role.id}: missing ${key}`);
  for (const key of ['requiredInputs', 'workflow', 'qualityChecks', 'stopWhen', 'handoffs', 'mustNot', 'sources']) {
    assert(Array.isArray(contract[key]) && contract[key].length && contract[key].every(value => typeof value === 'string' && value.trim()), `${role.id}: incomplete ${key}`);
  }
  assert(Object.keys(contract.outputFields).length >= 3, `${role.id}: missing deliverable fields`);
  assert(Object.values(contract.outputFields).every(value => typeof value === 'string' && value.trim()), `${role.id}: undocumented output`);
  assert.deepEqual(contract.evaluations.map(test => test.kind).sort(), ['boundary', 'edge', 'normal'], `${role.id}: missing evaluation category`);
  for (const test of contract.evaluations) {
    assert(test.scenario && Array.isArray(test.expected) && test.expected.length >= 2, `${role.id}: incomplete evaluation case`);
    cases++;
  }
}

const bullets = values => values.map(value => `- ${value}`).join('\n');
let markdown = `# Interspace agent playbooks\n\nGenerated from design/agents/role-contracts.json and role-catalog.js. Edit those sources, then run node scripts/build-role-playbooks.mjs.\n\nVersion: ${contracts.version}. **${contracts.status}.** These are provider-independent candidate instructions, not installed skills or an executable agent runtime.\n\n`;
markdown += `## Shared execution contract\n\nA future runner supplies these inputs and enforces tool permissions, budgets and exact action approvals. Prompt text alone is not enforcement.\n\n${bullets(contracts.common.requiredContext)}\n\n${bullets(contracts.common.rules)}\n\n### Result envelope\n\n${Object.entries(contracts.common.resultEnvelope).map(([key, value]) => `- **${key}:** ${value}`).join('\n')}\n\n${contracts.common.evaluation}\n\n`;
markdown += `## Evaluating the candidates\n\nThe ${cases} scenarios below are seed case specifications, not a benchmark or an executed suite. Before a pilot: build synthetic fixtures and independent expected results; use isolated tool adapters; capture actual reads, writes, outputs, errors and measured usage; run repeated trials and held-out cases. Score role correctness, claim support, coverage, tool effects and appropriate abstention separately. Have a domain expert calibrate research/statistics judgments. Do not reduce everything to an agent's self-rating or promote a template based on this file's structural validation.\n\n`;
for (const role of roles) {
  const c = role.contract;
  markdown += `## ${role.name}\n\nID: ${role.id} · Department: ${role.department} · Draft, not evaluated\n\n### Mission\n\n${c.mission}\n\n### Use when\n\n${c.useWhen}\n\n### Required inputs\n\n${bullets(c.requiredInputs)}\n\n### Workflow\n\n${c.workflow.map((step, i) => `${i + 1}. ${step}`).join('\n')}\n\n### Output fields\n\n${Object.entries(c.outputFields).map(([key, value]) => `- **${key}:** ${value}`).join('\n')}\n\n`;
  for (const [heading, values] of [['Quality checks', c.qualityChecks], ['Stop conditions', c.stopWhen], ['Outside this role', c.mustNot], ['Proposed handoffs', c.handoffs]]) markdown += `### ${heading}\n\n${bullets(values)}\n\n`;
  markdown += '### Evaluation scenarios — not run\n\n';
  for (const test of c.evaluations) markdown += `**${test.kind}:** ${test.scenario}\n\n${bullets(test.expected)}\n\n`;
  markdown += `### Design provenance\n\n${bullets(c.sources)}\n\n`;
}
markdown += '## Attribution and limits\n\nSee [research record](research/agent-template-design.md) for sources and design decisions. The Code reviewer adapts ECC 2.2.3 review patterns in original wording; its MIT notice is preserved in [ECC-LICENSE.txt](third-party/ECC-LICENSE.txt). Agency Agents was comparison material, not copied prompt content. Other specialty contracts are original Interspace proposals. This document does not establish model accuracy, scientific validity, or runtime permission enforcement.\n';
const output = new URL('../docs/agent-playbooks.md', import.meta.url);
if (args[0] === '--check') {
  assert.equal(await readFile(output, 'utf8'), markdown, 'Playbooks are out of date; run node scripts/build-role-playbooks.mjs');
} else {
  await writeFile(output, markdown);
}
console.log(`${roles.length} role contracts and ${cases} seed scenarios validated structurally; model evaluations NOT RUN.`);
