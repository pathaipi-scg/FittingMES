const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('app/templates/logger.html', 'utf8');
const timeInputSource = fs.readFileSync('app/static/time-input.js', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
assert.equal(scripts.length, 1);
const source = timeInputSource + '\n' + scripts[0].replace('{{ form|tojson }}', '{}') +
  '\nglobalThis.loggerTest = { chooseUniqueCandidate, causeSubRelatedCandidates,' +
  ' causeCandidates, causeCandidatesForOptions, compatibleOptionsForCause,' +
  ' causeMatchesOption, causeMEO, durationDefaultStopId,' +
  ' classificationAfterCause, classificationAfterManualChange, durationDisplay,' +
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
assert.match(source, /causeCandidates\(causes, selectedOption, subMachines, stopId, subStopId, isSmdt\(stopId\)\)/);
assert.match(source, /type\.addEventListener\('change'/);
assert.match(source, /subType\.addEventListener\('change'/);
assert.doesNotMatch(source, /type\.value = selectedCause\.StopId/);
assert.match(source, /manualStopTypeOverride/);
assert.match(source, /clearCause\(\);/);
assert.match(source, /form\.elements\.meo\.value = ''/);

const context = { document: { getElementById: () => null }, window: {} };
vm.runInNewContext(source, context);
const { chooseUniqueCandidate, causeSubRelatedCandidates, classificationAfterCause,
  causeCandidates, causeCandidatesForOptions, compatibleOptionsForCause,
  causeMatchesOption, causeMEO, durationDefaultStopId, classificationAfterManualChange,
  subTypeCandidates, previewDuration, durationDisplay } = context.loggerTest;
const machineOptions = [{ value: '7', dataset: { instance: '1' } },
  { value: '7', dataset: { instance: '2' } }];
assert.equal(chooseUniqueCandidate(machineOptions), null);
assert.equal(chooseUniqueCandidate([machineOptions[0]]), machineOptions[0]);
const relatedOptions = [
  { related_mc_id: 5, sub_mc_id: null, display_label: 'LINE1' },
  { related_mc_id: 5, sub_mc_id: null, display_label: 'LINE2' },
  { related_mc_id: 4, sub_mc_id: null, display_label: 'Robot1' },
];
const subMachines = [
  { SubMcId: 22, McId: 3, IsActive: true, IsRelated: true },
  { SubMcId: 24, McId: 5, IsActive: true, IsRelated: true },
  { SubMcId: 9, McId: 5, IsActive: true, IsRelated: false },
  { SubMcId: 5, McId: 7, IsActive: true, IsRelated: false },
];
assert.equal(causeSubRelatedCandidates(relatedOptions, { McId: 5, SubMcId: null }).length, 2);
assert.equal(chooseUniqueCandidate(causeSubRelatedCandidates(relatedOptions,
  { McId: 4, SubMcId: null })).display_label, 'Robot1');
assert.deepEqual(causeCandidates([
  { CauseId: 1, McId: 5, SubMcId: 9, StopId: 6, SubStopId: 20 },
  { CauseId: 2, McId: 5, SubMcId: 9, StopId: 2, SubStopId: 2 },
  { CauseId: 3, McId: 4, SubMcId: 23, StopId: 6, SubStopId: 20 },
], { sub_mc_id: 9, related_mc_id: null }, subMachines, 6, 20).map(item => item.CauseId), [1]);
assert.deepEqual(causeCandidates([
  { CauseId: 1, McId: 5, SubMcId: null, StopId: 6, SubStopId: 20 },
  { CauseId: 2, McId: 5, SubMcId: 9, StopId: 6, SubStopId: 20 },
  { CauseId: 3, McId: 5, SubMcId: 24, StopId: 6, SubStopId: 20 },
  { CauseId: 4, McId: 5, SubMcId: 5, StopId: 6, SubStopId: 20 },
], { sub_mc_id: null, related_mc_id: 5 }, subMachines, 6, 20).map(item => item.CauseId), [1, 3]);
assert.deepEqual(causeCandidates([
  { CauseId: 11, McId: 3, SubMcId: 22, StopId: 6, SubStopId: 20 },
], { sub_mc_id: null, related_mc_id: 3 }, subMachines, 6, 20).map(item => item.CauseId), [11]);
const fOptions = [
  { sub_mc_id: 3, related_mc_id: null, display_label: 'Mould1' },
  { sub_mc_id: 5, related_mc_id: null, display_label: 'ถ้วยจ่าย1' },
  { sub_mc_id: null, related_mc_id: 3, display_label: 'CABLE CAR1' },
  { sub_mc_id: null, related_mc_id: 3, display_label: 'CABLE CAR2' },
];
const reverseCauses = [
  { CauseId: 20, McId: 7, SubMcId: 3, StopId: 7, SubStopId: 21 },
  { CauseId: 21, McId: 7, SubMcId: 5, StopId: 7, SubStopId: 21 },
  { CauseId: 11, McId: 3, SubMcId: 22, StopId: 6, SubStopId: 20 },
];
assert.equal(causeMatchesOption(reverseCauses[0], fOptions[0], subMachines), true);
assert.deepEqual(compatibleOptionsForCause(reverseCauses, fOptions, subMachines, 20, 7, 21, false), [fOptions[0]]);
assert.deepEqual(compatibleOptionsForCause(reverseCauses, fOptions, subMachines, 11, 6, 20, true), [fOptions[2], fOptions[3]]);
assert.deepEqual(causeCandidatesForOptions(reverseCauses, fOptions.slice(0, 2), subMachines, 7, 21, false)
  .map(item => item.CauseId), [20, 21]);
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
], { sub_mc_id: null, related_mc_id: 5 }, subMachines, 6, '', true).map(item => item.CauseId), [1]);
assert.equal(classificationAfterCause(), 'false');
assert.equal(classificationAfterManualChange(), 'true');
assert.deepEqual(subTypeCandidates([{ StopId: 1 }, { StopId: 2 }], 1), [{ StopId: 1 }]);
const midnight = previewDuration('23:55', '00:05');
assert.equal(midnight.minutes, 10);
assert.equal(midnight.equal, false);
const equalTimes = previewDuration('10:00', '10:00');
assert.equal(equalTimes.minutes, null);
assert.equal(equalTimes.equal, true);
const normalizeManualHHmm = context.window.FittingMES.normalizeManualHHmm;
assert.equal(normalizeManualHHmm('7:00'), '07:00');
assert.equal(normalizeManualHHmm('7:41'), '07:41');
assert.equal(normalizeManualHHmm('8:05'), '08:05');
assert.equal(normalizeManualHHmm('07:00'), '07:00');
assert.equal(normalizeManualHHmm('15:30'), '15:30');
assert.equal(normalizeManualHHmm('24:00'), null);
assert.equal(normalizeManualHHmm('12:60'), null);
assert.equal(normalizeManualHHmm('abc'), null);
assert.equal(previewDuration(normalizeManualHHmm('7:00'), normalizeManualHHmm('7:09')).minutes, 9);
assert.equal(durationDefaultStopId(stopTypes, previewDuration('07:00', '07:09').minutes), 6);
assert.equal(previewDuration(normalizeManualHHmm('7:00'), normalizeManualHHmm('7:10')).minutes, 10);
assert.equal(durationDefaultStopId(stopTypes, previewDuration('07:00', '07:10').minutes), 7);
assert.equal(durationDisplay('07:10', '07:11'), '1');
assert.equal(durationDisplay('07:10', '07:19'), '9');
assert.equal(durationDisplay('07:10', '07:20'), '10');
assert.equal(durationDisplay('07:41', '07:42'), '1');
assert.equal(durationDisplay('07:10', ''), '-');
assert.match(source, /duration\.textContent = durationDisplay\(stop, start\)/);
assert.match(source, /if \(\/\^\\d\{1,2\}:\\d\{2\}\$\/\.test\(input\.value\)\) timeNormalizers\.get\(input\)\(\)/);
assert.match(source, /input\.addEventListener\('change', updateDuration\)/);
console.log('LOGGER inline JavaScript syntax and operator-form contracts passed.');
