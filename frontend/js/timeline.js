requireAuth();

let currentGroup = 'year';
let timelinePeriods = [];
let expandedPeriods = new Set();
let expandedPreviewPeriods = new Set();
let photoIndex = new Map();
let activeLightboxPhotoId = null;
let drillPath = [];


function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}


function groupLabel(group) {
  if (group === 'year') {
    return 'year';
  }
  if (group === 'month') {
    return 'month';
  }
  return 'day';
}


function groupCollectionLabel(group, count) {
  const noun = groupLabel(group);
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}


function nextGroup(group) {
  if (group === 'year') {
    return 'month';
  }
  if (group === 'month') {
    return 'day';
  }
  return null;
}


function activeRange() {
  if (!drillPath.length) {
    return null;
  }
  const parent = drillPath[drillPath.length - 1];
  return { start: parent.start, end: parent.end };
}


function photoTimestamp(photo) {
  return photo.captured_at || photo.uploaded_at;
}


function photoTitle(photo) {
  return photo.display_name || photo.scene || photo.original_filename || photo.filename || `Photo ${photo.id}`;
}


function photoMeta(photo) {
  const pieces = [];
  if (photo.scene) {
    pieces.push(photo.scene);
  }
  if (photo.folder_label && photo.folder_label !== photo.scene) {
    pieces.push(photo.folder_label);
  }
  const timestamp = photoTimestamp(photo);
  if (timestamp) {
    pieces.push(new Date(timestamp).toLocaleString());
  }
  return pieces.join(' - ');
}


function updateToggleState() {
  document.querySelectorAll('.timeline-chip').forEach((button) => {
    button.classList.toggle('active', button.dataset.group === currentGroup);
  });
}


function updateSummary() {
  const photoCount = timelinePeriods.reduce((sum, period) => sum + period.count, 0);
  let summary = `${photoCount} photo${photoCount === 1 ? '' : 's'} across ${groupCollectionLabel(currentGroup, timelinePeriods.length)}`;
  if (drillPath.length) {
    summary += ` in ${drillPath.map((item) => item.label).join(' / ')}`;
  }
  document.getElementById('timeline-summary').textContent = summary;
}


function renderDrilldown() {
  const panel = document.getElementById('timeline-drilldown');
  const copy = document.getElementById('timeline-drilldown-copy');
  const backButton = document.getElementById('timeline-drilldown-back');

  if (!drillPath.length) {
    panel.classList.remove('active');
    copy.textContent = '';
    return;
  }

  const pathLabel = drillPath.map((item) => item.label).join(' / ');
  const previousLevel = drillPath[drillPath.length - 1];
  copy.innerHTML = `Browsing <strong>${escapeHtml(groupCollectionLabel(currentGroup, timelinePeriods.length))}</strong> inside <strong>${escapeHtml(pathLabel)}</strong>.`;
  backButton.textContent = `Back to ${groupLabel(previousLevel.group)} view`;
  panel.classList.add('active');
}


function buildPhotoIndex() {
  photoIndex = new Map();
  timelinePeriods.forEach((period) => {
    period.photos.forEach((photo) => {
      photoIndex.set(photo.id, photo);
    });
  });
}


function initializeExpandedPeriods() {
  expandedPeriods = currentGroup === 'day'
    ? new Set(timelinePeriods.slice(0, 6).map((period) => period.key))
    : new Set();
  expandedPreviewPeriods = new Set();
}


function previewMarkup(period) {
  const previewLimit = currentGroup === 'year' ? 24 : 18;
  const isExpanded = expandedPreviewPeriods.has(period.key);
  const previews = isExpanded ? period.photos : period.photos.slice(0, previewLimit);
  const hiddenCount = Math.max(period.photos.length - previews.length, 0);
  const previewClass = currentGroup === 'year' ? 'period-preview period-preview-year' : 'period-preview period-preview-month';
  return `
    <div class="${previewClass}">
      <div class="period-preview-grid">
        ${previews.map((photo) => `
          <div class="period-preview-card">
            <img data-photo-id="${photo.id}" alt="${escapeHtml(photoTitle(photo))}" loading="lazy"/>
          </div>
        `).join('')}
      </div>
      ${period.photos.length > previewLimit ? `
        <button type="button" class="period-preview-more" data-preview-key="${escapeHtml(period.key)}">
          ${isExpanded ? 'Show less' : 'Show more'}
          <span>${isExpanded ? 'Collapse this view' : `+${hiddenCount} photos`}</span>
        </button>
      ` : ''}
      <div class="period-preview-note">
        ${currentGroup === 'year'
          ? 'Open this year to browse its months.'
          : 'Open this month to browse its days.'}
      </div>
    </div>
  `;
}


async function renderTimeline() {
  const root = document.getElementById('timeline-list');
  if (!timelinePeriods.length) {
    root.innerHTML = `
      <div class="empty-state">
        <h3>No photos in the timeline yet</h3>
        <p>Upload photos first, then browse them here by year, month, or day.</p>
      </div>
    `;
    return;
  }

  root.innerHTML = timelinePeriods.map((period) => {
    const isDayView = currentGroup === 'day';
    const isOpen = expandedPeriods.has(period.key);
    const actionLabel = isDayView
      ? (isOpen ? 'Hide Photos' : 'Open Photos')
      : (currentGroup === 'year' ? 'View Months' : 'View Days');

    return `
      <section class="timeline-period ${isDayView && isOpen ? 'open' : ''}" data-key="${escapeHtml(period.key)}">
        <button type="button" class="period-header" data-key="${escapeHtml(period.key)}">
          <div>
            <div class="period-label">${escapeHtml(period.label)}</div>
            <div class="period-meta">${period.count} photo${period.count === 1 ? '' : 's'}</div>
          </div>
          <span class="period-toggle">${actionLabel}</span>
        </button>
        ${isDayView ? `
          <div class="period-grid">
            ${period.photos.map((photo) => `
              <article class="timeline-card" data-photo-id="${photo.id}">
                <img data-photo-id="${photo.id}" alt="${escapeHtml(photoTitle(photo))}" loading="lazy"/>
                <div class="timeline-card-body">
                  <div class="timeline-card-title">${escapeHtml(photoTitle(photo))}</div>
                  <div class="timeline-card-meta">${escapeHtml(photoMeta(photo))}</div>
                  ${photo.event_label ? `<div class="timeline-card-badge">${escapeHtml(photo.event_label)}</div>` : ''}
                </div>
              </article>
            `).join('')}
          </div>
        ` : previewMarkup(period)}
      </section>
    `;
  }).join('');

  root.querySelectorAll('.period-header').forEach((button) => {
    button.addEventListener('click', () => onPeriodSelected(button.dataset.key));
  });

  root.querySelectorAll('.period-preview-more').forEach((button) => {
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      togglePreviewExpansion(button.dataset.previewKey);
    });
  });

  if (currentGroup === 'day') {
    root.querySelectorAll('.timeline-card').forEach((card) => {
      card.addEventListener('click', () => openLightbox(Number(card.dataset.photoId)));
    });
  }

  await hydrateProtectedImages(root);
}


function togglePeriod(key) {
  if (expandedPeriods.has(key)) {
    expandedPeriods.delete(key);
  } else {
    expandedPeriods.add(key);
  }
  void renderTimeline();
}


function togglePreviewExpansion(key) {
  if (!key) {
    return;
  }
  if (expandedPreviewPeriods.has(key)) {
    expandedPreviewPeriods.delete(key);
  } else {
    expandedPreviewPeriods.add(key);
  }
  void renderTimeline();
}


function drillIntoPeriod(key) {
  const period = timelinePeriods.find((item) => item.key === key);
  const targetGroup = nextGroup(currentGroup);
  if (!period || !targetGroup) {
    return;
  }

  drillPath.push({
    key: period.key,
    label: period.label,
    start: period.start,
    end: period.end,
    group: currentGroup,
  });
  currentGroup = targetGroup;
  void loadTimeline();
}


function onPeriodSelected(key) {
  if (currentGroup === 'day') {
    togglePeriod(key);
    return;
  }
  drillIntoPeriod(key);
}


function stepBack() {
  if (!drillPath.length) {
    return;
  }
  const previous = drillPath.pop();
  currentGroup = previous.group;
  void loadTimeline();
}


async function loadTimeline() {
  const root = document.getElementById('timeline-list');
  root.innerHTML = `
    <div class="empty-state">
      <h3>Loading timeline...</h3>
      <p>Grouping your photos by ${escapeHtml(groupLabel(currentGroup))}.</p>
    </div>
  `;

  try {
    const range = activeRange();
    const response = await Timeline.get(
      currentGroup,
      range ? { start: range.start, end: range.end } : {},
    );
    timelinePeriods = response.periods || [];
    initializeExpandedPeriods();
    buildPhotoIndex();
    updateToggleState();
    renderDrilldown();
    updateSummary();
    await renderTimeline();
  } catch (error) {
    root.innerHTML = `
      <div class="empty-state">
        <h3>Could not load the timeline</h3>
        <p>${escapeHtml(error.message || 'The server returned an unexpected error.')}</p>
      </div>
    `;
    document.getElementById('timeline-summary').textContent = 'Timeline unavailable';
    renderDrilldown();
  }
}


function setGroup(group) {
  if (!group || group === currentGroup) {
    if (!drillPath.length) {
      return;
    }
  }
  currentGroup = group;
  drillPath = [];
  void loadTimeline();
}


async function openLightbox(photoId) {
  const photo = photoIndex.get(photoId);
  if (!photo) {
    showToast('Photo not found', 'error');
    return;
  }

  activeLightboxPhotoId = photoId;
  const image = document.getElementById('timeline-lightbox-img');
  image.removeAttribute('src');
  image.alt = photoTitle(photo);
  try {
    image.src = await getProtectedPhotoUrl(photo.id);
  } catch (error) {
    showToast('Photo preview unavailable', 'error');
    return;
  }

  document.getElementById('timeline-lightbox-title').textContent = photoTitle(photo);
  document.getElementById('timeline-lightbox-meta').textContent = photoMeta(photo);
  document.getElementById('timeline-lightbox').classList.add('open');
}


function closeLightbox(event) {
  if (!event || event.target.id === 'timeline-lightbox' || event.target.classList.contains('lightbox-close')) {
    activeLightboxPhotoId = null;
    document.getElementById('timeline-lightbox').classList.remove('open');
  }
}


document.querySelectorAll('.timeline-chip').forEach((button) => {
  button.addEventListener('click', () => setGroup(button.dataset.group));
});


document.getElementById('timeline-drilldown-back').addEventListener('click', stepBack);


document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && activeLightboxPhotoId) {
    closeLightbox({ target: { id: 'timeline-lightbox' } });
  }
});


updateToggleState();
renderDrilldown();
void loadTimeline();
