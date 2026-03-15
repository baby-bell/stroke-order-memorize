let _strokeTotal = 0;
let _strokeIndex = 0;
let _keyController = null;

function initStrokes(total) {
  _strokeTotal = total;
  _strokeIndex = 0;
  // Enable rating buttons now that strokes are loaded
  document.querySelectorAll('.rating-btn').forEach(btn => {
    btn.disabled = false;
  });
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = _strokeTotal === 0;
  const prevBtn = document.getElementById('prev-stroke-btn');
  if (prevBtn) prevBtn.disabled = true;

  // Arrow key listeners — abort previous to prevent accumulation across HTMX swaps
  if (_keyController) _keyController.abort();
  _keyController = new AbortController();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); prevStroke(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); nextStroke(); }
  }, { signal: _keyController.signal });
}

function nextStroke() {
  if (_strokeIndex >= _strokeTotal) return;
  document.querySelectorAll(`.stroke[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.opacity = '1';
  });
  document.querySelectorAll(`.stroke-label[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.display = '';
  });
  _strokeIndex++;
  const counter = document.getElementById('stroke-count');
  if (counter) counter.textContent = String(_strokeIndex);
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = _strokeIndex >= _strokeTotal;
  const prevBtn = document.getElementById('prev-stroke-btn');
  if (prevBtn) prevBtn.disabled = false;
}

function prevStroke() {
  if (_strokeIndex <= 0) return;
  _strokeIndex--;
  document.querySelectorAll(`.stroke[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.opacity = '0';
  });
  document.querySelectorAll(`.stroke-label[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.display = 'none';
  });
  const counter = document.getElementById('stroke-count');
  if (counter) counter.textContent = String(_strokeIndex);
  const prevBtn = document.getElementById('prev-stroke-btn');
  if (prevBtn) prevBtn.disabled = _strokeIndex <= 0;
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = false;
}

// Spacebar to trigger "Show Strokes" — persistent listener, inert when button absent
document.addEventListener('keydown', (e) => {
  if (e.key !== ' ') return;
  const btn = document.getElementById('show-strokes-btn');
  if (!btn) return;
  e.preventDefault();
  btn.click();
});
