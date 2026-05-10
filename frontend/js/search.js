requireAuth();

function quickSearch(element) {
  document.getElementById('search-input').value = element.textContent;
  doSearch();
}

async function doSearch() {
  const query = document.getElementById('search-input').value.trim();
  if (!query) {
    showToast('Enter a search term', 'error');
    return;
  }

  document.getElementById('results-section').style.display = 'none';
  document.getElementById('empty-msg').style.display = 'none';

  const button = document.querySelector('.search-bar-wrap .btn');
  button.innerHTML = '<span class="spinner"></span>';

  try {
    const results = await Search.query(query);
    button.textContent = 'Search';

    if (!results.length) {
      document.getElementById('empty-msg').style.display = 'block';
      return;
    }

    document.getElementById('results-title').textContent = `Results for "${query}"`;
    document.getElementById('results-count').textContent = `${results.length} photo${results.length !== 1 ? 's' : ''} found`;
    document.getElementById('results-section').style.display = 'block';

    const grid = document.getElementById('results-grid');
    grid.innerHTML = '';

    results.forEach((photo) => {
      const pct = photo.relevance || Math.round((photo.score || 0) * 100);
      const card = document.createElement('div');
      card.className = 'photo-card';
      card.innerHTML = `
        <img data-photo-id="${photo.id}" alt="${photo.scene}" loading="lazy"/>
        <div class="photo-card-info">
          <div class="photo-card-scene">${photo.scene}</div>
          <div class="photo-card-score">Relevance: ${pct}%</div>
          <div class="score-bar"><div class="score-fill" style="width:${pct}%"></div></div>
        </div>`;
      grid.appendChild(card);
    });

    await hydrateProtectedImages(grid);
  } catch (error) {
    showToast(error.message || 'Search failed. Check the backend.', 'error');
    button.textContent = 'Search';
  }
}

document.getElementById('search-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    doSearch();
  }
});
