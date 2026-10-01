(function () {
  function normalizeManualHHmm(value) {
    const trimmed = String(value || '').trim();
    const match = /^(\d{1,2}):(\d{2})$/.exec(trimmed);
    if (!match) return null;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (hours > 23 || minutes > 59) return null;
    return String(hours).padStart(2, '0') + ':' + match[2];
  }

  function attachManualHHmm(input) {
    function normalize() {
      const normalized = normalizeManualHHmm(input.value);
      input.setCustomValidity(normalized === null && input.value ? 'Enter a valid time as HH:mm.' : '');
      if (normalized !== null) input.value = normalized;
    }
    input.addEventListener('blur', normalize);
    input.addEventListener('change', normalize);
    normalize();
    return normalize;
  }

  window.FittingMES = window.FittingMES || {};
  window.FittingMES.normalizeManualHHmm = normalizeManualHHmm;
  window.FittingMES.attachManualHHmm = attachManualHHmm;
}());