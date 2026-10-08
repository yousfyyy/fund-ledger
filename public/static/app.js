// Tab switcher on the "Record a transaction" panel.
document.querySelectorAll('.tab').forEach(function (tab) {
  tab.addEventListener('click', function () {
    var name = tab.dataset.tab;
    tab.closest('.panel').querySelectorAll('.tab').forEach(function (t) {
      t.classList.toggle('is-active', t === tab);
    });
    tab.closest('.panel').querySelectorAll('.tab-panel').forEach(function (p) {
      p.classList.toggle('is-active', p.dataset.panel === name);
    });
  });
});

// Ask before destructive actions.
document.querySelectorAll('[data-confirm]').forEach(function (el) {
  el.addEventListener('submit', function (e) {
    if (!window.confirm(el.dataset.confirm)) e.preventDefault();
  });
});

// Tidy money fields: "1000" -> "1000.00"
document.querySelectorAll('input[inputmode="decimal"]').forEach(function (input) {
  input.addEventListener('blur', function () {
    var raw = (input.value || '').replace(/[,\s$€£]/g, '');
    if (raw === '') return;
    var n = Number(raw);
    if (!isNaN(n)) input.value = n.toFixed(2);
  });
});
