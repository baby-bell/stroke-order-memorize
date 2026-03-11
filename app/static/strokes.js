let _strokeTotal = 0;
let _strokeIndex = 0;

function initStrokes(total) {
  _strokeTotal = total;
  _strokeIndex = 0;
  // Enable rating buttons now that strokes are loaded
  document.querySelectorAll('.rating-btn').forEach(btn => {
    btn.disabled = false;
  });
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = _strokeTotal === 0;
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
}
