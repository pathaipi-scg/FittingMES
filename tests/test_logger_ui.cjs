const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('app/templates/logger.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
assert.equal(scripts.length, 1);
const source = scripts[0].replace('{{ form|tojson }}', '{}') +
  '\nglobalThis.loggerTest = { chooseUniqueCandidate, causeSubRelatedCandidates,' +
  ' causeCandidates, causeMEO, durationDefaultStopId,' +
  ' classificationAfterCause, classificationAfterManualChange,' +
  ' subTypeCandidates, previewDuration };';
new vm.Script(source);
for (const text of [
  'Sub / Related M/C', 'classification_edited', 'Stop and Start times must differ.',
  'Saving LOGGER entry...'
]) assert.match(html, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
assert.match(html, /duration/);
assert.match(source, /related_mc_id/);
assert.ok(html.indexOf('id="logger-sub-related"') < html.indexOf('id="logger-stop-type"'));
assert.ok(html.indexOf('id="logger-stop-type"') < html.indexOf('id="logger-cause"'));
assert.ok(html.indexOf('id="logger-cause"') < html.indexOf('id="logger-sub-stop-type"'));
assert.match(source, /causeCandidates\(causes, selectedOption, stopId, subStopId, isSmdt\(stopId\)\)/);
assert.match(source, /type\.addEventListener\('change'/);
assert.match(source, /subType\.addEventListener\('change'/);
assert.doesNotMatch(source, /type\.value = selectedCause\.StopId/);
assert.match(source, /manualStopTypeOverride/);
assert.match(source, /clearCause\(\);/);
assert.match(source, /form\.elements\.meo\.value = ''/);

const context = { document: { getElementById: () => null } };
vm.runInNewContext(source, context);
const { chooseUniqueCandidate, causeSubRelatedCandidates, classificationAfterCause,
  causeCandidates, causeMEO, durationDefaultStopId, classificationAfterManualChange,
  subTypeCandidates, previewDuration } = context.loggerTest;
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
assert.deepEqual(causeCandidates([
  { CauseId: 1, McId: 5, SubMcId: 9, StopId: 6, SubStopId: 20 },
  { CauseId: 2, McId: 5, SubMcId: 9, StopId: 2, SubStopId: 2 },
  { CauseId: 3, McId: 4, SubMcId: 23, StopId: 6, SubStopId: 20 },
], { sub_mc_id: 9, related_mc_id: null }, 6, 20).map(item => item.CauseId), [1]);
assert.deepEqual(causeCandidates([
  { CauseId: 1, McId: 5, SubMcId: null, StopId: 6, SubStopId: 20 },
  { CauseId: 2, McId: 5, SubMcId: 9, StopId: 6, SubStopId: 20 },
], { sub_mc_id: null, related_mc_id: 5 }, 6, 20).map(item => item.CauseId), [1]);
const stopTypes = [{ StopId: 6, StopType: 'SMDT' }, { StopId: 7, StopType: 'BD' }];
assert.equal(durationDefaultStopId(stopTypes, 1), 6);
assert.equal(durationDefaultStopId(stopTypes, 9), 6);
assert.equal(durationDefaultStopId(stopTypes, 10), 7);
assert.equal(durationDefaultStopId(stopTypes, 11), 7);
const mappedCauses = [{ CauseId: 1, MEO: 'M' }, { CauseId: 2, MEO: 'E' }];
assert.equal(causeMEO(mappedCauses, 1), 'M');
assert.equal(causeMEO(mappedCauses, 2), 'E');
assert.equal(causeMEO(mappedCauses, ''), '');
assert.deepEqual(causeCandidates([
  { CauseId: 1, McId: 5, SubMcId: null, StopId: 6, SubStopId: 20 },
], { sub_mc_id: null, related_mc_id: 5 }, 6, '', true).map(item => item.CauseId), [1]);
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
