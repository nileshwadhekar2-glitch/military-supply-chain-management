// Small progressive enhancements; all core actions work through Flask forms.
document.getElementById('menu-toggle')?.addEventListener('click', () => {
  const expanded = document.body.classList.toggle('nav-open');
  document.getElementById('menu-toggle').setAttribute('aria-expanded', expanded);
});
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.body.classList.remove('nav-open');
});
