/* MediNFC — main.js */

// ── Sidebar toggle móvil ──────────────────────────────
const menuBtn = document.getElementById('menu-btn');
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('sidebar-overlay');

if (menuBtn) {
  menuBtn.addEventListener('click', () => {
    sidebar?.classList.toggle('open');
    overlay?.classList.toggle('show');
  });
}
if (overlay) {
  overlay.addEventListener('click', () => {
    sidebar?.classList.remove('open');
    overlay.classList.remove('show');
  });
}

// ── Marcar nav activo ──────────────────────────────────
document.querySelectorAll('.nav-item').forEach(item => {
  if (item.getAttribute('href') === window.location.pathname) {
    item.classList.add('active');
  }
});

// ── Modales ────────────────────────────────────────────
document.querySelectorAll('[data-modal-open]').forEach(btn => {
  btn.addEventListener('click', () => {
    const id = btn.dataset.modalOpen;
    document.getElementById(id)?.classList.add('show');
  });
});
document.querySelectorAll('[data-modal-close]').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.closest('.modal-overlay')?.classList.remove('show');
  });
});
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => {
    if (e.target === overlay) overlay.classList.remove('show');
  });
});

// ── Búsqueda con debounce ──────────────────────────────
function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

const searchInput = document.getElementById('search-input');
if (searchInput) {
  searchInput.addEventListener('input', debounce(e => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('[data-searchable]').forEach(row => {
      const text = row.textContent.toLowerCase();
      row.style.display = text.includes(q) ? '' : 'none';
    });
  }));
}

// ── Tabs ───────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const group = btn.dataset.tabGroup;
    const target = btn.dataset.tab;
    document.querySelectorAll(`[data-tab-group="${group}"] .tab-btn`).forEach(b => b.classList.remove('active'));
    document.querySelectorAll(`[data-tab-panel="${group}"]`).forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(target)?.classList.add('active');
  });
});

// ── Toggle switch ──────────────────────────────────────
document.querySelectorAll('.toggle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.classList.toggle('on');
    const track = btn.querySelector('.toggle-track');
    if (track) track.style.background = btn.classList.contains('on') ? '#1ABC9C' : '#D1D5DB';
  });
});

// ── Auto-dismiss flashes ───────────────────────────────
setTimeout(() => {
  document.querySelectorAll('.flash').forEach(f => {
    f.style.transition = 'opacity .4s';
    f.style.opacity = '0';
    setTimeout(() => f.remove(), 400);
  });
}, 3500);

// ── Fake adherence bars ────────────────────────────────
document.querySelectorAll('.adherence-fill[data-value]').forEach(el => {
  const v = parseInt(el.dataset.value);
  el.style.width = v + '%';
  el.style.background = v >= 80 ? '#1ABC9C' : v >= 50 ? '#F39C12' : '#E74C3C';
});
