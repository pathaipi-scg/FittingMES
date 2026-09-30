const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('app/templates/logger.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
assert.equal(scripts.length, 1);
const source = scripts[0].replace('{{ form|tojson }}', '{}') +
  '\nglobalThis.loggerTest = { chooseUniqueCandidate, causeSubRelatedCandidates,' +
  ' classificationAfterCause, classificationAfterManualChange, subTypeCandidates, previewDuration };';
new vm.Script(source);
for (const text of [
  'Sub / Related M/C', 'classification_edited', 'Stop and Start times must differ.',
  'Saving LOGGER entry...'
]) assert.match(html, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
assert.match(html, /duration/);
assert.match(source, /related_mc_id/);

const context = { document: { getElementById: () => null } };
vm.runInNewContext(source, context);
const { chooseUniqueCandidate, causeSubRelatedCandidates, classificationAfterCause,
  classificationAfterManualChange, subTypeCandidates, previewDuration } = context.loggerTest;
const machineOptions = [{ value: '7', dataset: { instance: '1' } },
  { value: '7', dataset: { instance: '2' } }];
assert.equal(chooseUniqueCandidate(machineOptions), null);
assert.equal(chooseUniqueCandidate([machineOptions[0]]), machineOptions[0]);
const relatedOptions = [
  { related_mc_id: 5, sub_mc_id: null, display_label: 'LINE1' },
  { related_mc_id: 5, sub_mc_id: null, display_label: 'LINE2' },
  { related_mc_id: 4, sub_mc_id: null, display_label: 'Robot1' },
];
assert.equal(causeSubRelatedCandidates(relatedOptions, { McId: 5, SubMcId: null }).length, 2);
assert.equal(chooseUniqueCandidate(causeSubRelatedCandidates(relatedOptions,
  { McId: 4, SubMcId: null })).display_label, 'Robot1');
assert.equal(classificationAfterCause(), 'false');
assert.equal(classificationAfterManualChange(), 'true');
assert.deepEqual(subTypeCandidates([{ StopId: 1 }, { StopId: 2 }], 1), [{ StopId: 1 }]);
const midnight = previewDuration('23:55', '00:05');
assert.equal(midnight.minutes, 10);
assert.equal(midnight.equal, false);
const equalTimes = previewDuration('10:00', '10:00');
assert.equal(equalTimes.minutes, null);
assert.equal(equalTimes.equal, true);
console.log('LOGGER inline JavaScript syntax and operator-form contracts passed.');
