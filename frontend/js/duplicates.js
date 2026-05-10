requireAuth();

let duplicatePayload = { groups: [], summary: {} };
let selectedPhotoIds = new Set();
let photoIndex = new Map();
let activeLightboxPhotoId = null;


function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}


function photoTitle(photo) {
  return photo.display_name || photo.scene || photo.original_filename || photo.filename || `Photo ${photo.id}`;
}


function photoTimestamp(photo) {
  return photo.captured_at || photo.uploaded_at;
}


function photoMeta(photo) {
  const parts = [];
  if (photo.folder_label) {
    parts.push(photo.folder_label);
  }
  if (photo.scene && photo.scene !== photo.folder_label) {
    parts.push(photo.scene);
  }
  if (photoTimestamp(photo)) {
    parts.push(new Date(photoTimestamp(photo)).toLocaleString());
  }
  return parts.join(' - ');
}


function groupTitle(group) {
  if (group.type === 'similar') {
    return `${group.count} similar photos found`;
  }
  return `${group.count} exact copies found`;
}


function groupDescription(group) {
  if (group.type === 'similar') {
    return `These photos look nearly identical. Review them, then remove ${group.reclaimable_count} extra photo${group.reclaimable_count === 1 ? '' : 's'} if they are true duplicates.`;
  }
  return `Keep one copy and remove ${group.reclaimable_count} extra photo${group.reclaimable_count === 1 ? '' : 's'} from this group.`;
}


function groupBadge(group) {
  return group.type === 'similar' ? 'Similar Duplicate' : 'Exact Duplicate';
}


function updateSummary() {
  const summary = duplicatePayload.summary || {};
  document.getElementById('summary-groups').textContent = summary.group_count || 0;
  document.getElementById('summary-photos').textContent = summary.duplicate_photo_count || 0;
  document.getElementById('summary-reclaim').textContent = summary.reclaimable_count || 0;
  document.getElementById('summary-unhashed').textContent = summary.unhashed_count || 0;
}


function updateSelectionMeta() {
  const count = selectedPhotoIds.size;
  document.getElementById('selection-meta').textContent = count === 0
    ? 'No duplicate photos selected'
    : `${count} duplicate photo${count === 1 ? '' : 's'} selected`;
}


function rebuildPhotoIndex() {
  photoIndex = new Map();
  (duplicatePayload.groups || []).forEach((group) => {
    group.photos.forEach((photo) => photoIndex.set(photo.id, photo));
  });
}


function syncSelection() {
  const validIds = new Set(photoIndex.keys());
  selectedPhotoIds = new Set(Array.from(selectedPhotoIds).filter((photoId) => validIds.has(photoId)));
  updateSelectionMeta();
}


async function loadDuplicates() {
  const root = document.getElementById('duplicates-groups');
  root.innerHTML = `
    <div class="empty-state">
      <h3>Loading duplicates...</h3>
      <p>Checking your library for exact and similar duplicate photos.</p>
    </div>
  `;

  try {
    duplicatePayload = await Duplicates.get();
    rebuildPhotoIndex();
    syncSelection();
    updateSummary();
    await renderGroups();
  } catch (error) {
    const message = /Failed to fetch/i.test(error.message || '')
      ? 'Could not reach the Flask backend. If you just added Duplicates, restart Flask and reload this page.'
      : (error.message || 'The server returned an unexpected error.');
    root.innerHTML = `
      <div class="empty-state">
        <h3>Could not load duplicates</h3>
        <p>${escapeHtml(message)}</p>
      </div>
    `;
  }
}


async function renderGroups() {
  const root = document.getElementById('duplicates-groups');
  const groups = duplicatePayload.groups || [];
  const summary = duplicatePayload.summary || {};

  if (!groups.length) {
    const needsScan = (summary.unhashed_count || 0) > 0;
    root.innerHTML = `
      <div class="empty-state">
        <h3>${needsScan ? 'Scan your library first' : 'No duplicates found'}</h3>
        <p>${needsScan
          ? `${summary.unhashed_count} photo${summary.unhashed_count === 1 ? '' : 's'} still need duplicate hashes. Run a scan to check them.`
          : 'Your non-trashed library does not currently contain any duplicate groups.'}</p>
        <div class="empty-actions">
          <button class="btn btn-secondary" onclick="scanLibrary()">Scan Library</button>
          <a class="btn btn-primary" href="gallery.html">Back to Gallery</a>
        </div>
      </div>
    `;
    return;
  }

  root.innerHTML = groups.map((group) => `
    <section class="duplicate-group">
        <div class="group-header">
        <div>
          <div class="group-title">${groupTitle(group)}</div>
          <div class="group-meta">${groupDescription(group)}</div>
        </div>
        <div class="group-badges">
          <span class="badge-pill badge-match">${groupBadge(group)}</span>
          <span class="badge-pill badge-score">${group.confidence_score}% Match</span>
        </div>
      </div>
      <div class="group-grid">
        ${group.photos.map((photo) => `
          <article class="duplicate-card ${selectedPhotoIds.has(photo.id) ? 'selected' : ''}" data-photo-id="${photo.id}">
            <div class="duplicate-preview" onclick="openLightbox(${photo.id})">
              <input
                class="duplicate-checkbox"
                type="checkbox"
                ${selectedPhotoIds.has(photo.id) ? 'checked' : ''}
                onclick="event.stopPropagation()"
                onchange="toggleSelection(${photo.id}, this.checked)"
              />
              <img data-photo-id="${photo.id}" alt="${escapeHtml(photoTitle(photo))}" loading="lazy"/>
            </div>
            <div class="duplicate-card-body">
              <div class="duplicate-title">${escapeHtml(photoTitle(photo))}</div>
              <div class="duplicate-meta">${escapeHtml(photoMeta(photo))}</div>
              ${group.kept_photo_id === photo.id ? '<div class="recommended-keep">Suggested Keep</div>' : ''}
              <div class="duplicate-card-actions">
                <button class="btn btn-secondary btn-sm" onclick="keepPhoto(${photo.id})">Keep This</button>
                <button class="btn btn-danger btn-sm" onclick="trashPhotos([${photo.id}])">Trash</button>
              </div>
            </div>
          </article>
        `).join('')}
      </div>
    </section>
  `).join('');

  await hydrateProtectedImages(root);
}


function toggleSelection(photoId, checked) {
  if (checked) {
    selectedPhotoIds.add(photoId);
  } else {
    selectedPhotoIds.delete(photoId);
  }
  const card = document.querySelector(`.duplicate-card[data-photo-id="${photoId}"]`);
  if (card) {
    card.classList.toggle('selected', checked);
  }
  updateSelectionMeta();
}


async function scanLibrary() {
  const button = document.getElementById('scan-btn');
  const previous = button.textContent;
  button.innerHTML = '<span class="spinner"></span>';
  try {
    duplicatePayload = await Duplicates.scan();
    rebuildPhotoIndex();
    syncSelection();
    updateSummary();
    await renderGroups();
    showToast('Duplicate scan completed', 'success');
  } catch (error) {
    showToast(error.message || 'Duplicate scan failed', 'error');
  } finally {
    button.textContent = previous;
  }
}


async function trashPhotos(photoIds) {
  if (!photoIds.length) {
    showToast('Select duplicate photos first', 'error');
    return;
  }

  try {
    duplicatePayload = await Duplicates.trash(photoIds);
    rebuildPhotoIndex();
    syncSelection();
    updateSummary();
    await renderGroups();
    showToast('Moved selected duplicates to trash', 'success');
  } catch (error) {
    showToast(error.message || 'Could not trash duplicate photos', 'error');
  }
}


async function trashSelected() {
  await trashPhotos(Array.from(selectedPhotoIds));
}


async function keepPhoto(photoId) {
  try {
    duplicatePayload = await Duplicates.keep(photoId);
    rebuildPhotoIndex();
    syncSelection();
    updateSummary();
    await renderGroups();
    showToast('Kept the selected copy and moved the extras to trash', 'success');
  } catch (error) {
    showToast(error.message || 'Could not keep this duplicate photo', 'error');
  }
}


async function openLightbox(photoId) {
  const photo = photoIndex.get(photoId);
  if (!photo) {
    showToast('Photo not found', 'error');
    return;
  }

  activeLightboxPhotoId = photoId;
  const image = document.getElementById('duplicates-lightbox-img');
  image.removeAttribute('src');
  image.alt = photoTitle(photo);
  try {
    image.src = await getProtectedPhotoUrl(photo.id);
  } catch (error) {
    showToast('Photo preview unavailable', 'error');
    return;
  }

  document.getElementById('duplicates-lightbox-title').textContent = photoTitle(photo);
  document.getElementById('duplicates-lightbox-meta').textContent = photoMeta(photo);
  document.getElementById('duplicates-lightbox').classList.add('open');
}


function closeLightbox(event) {
  if (!event || event.target.id === 'duplicates-lightbox' || event.target.classList.contains('lightbox-close')) {
    activeLightboxPhotoId = null;
    document.getElementById('duplicates-lightbox').classList.remove('open');
  }
}


document.getElementById('scan-btn').addEventListener('click', () => {
  void scanLibrary();
});

document.getElementById('trash-selected-btn').addEventListener('click', () => {
  void trashSelected();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && activeLightboxPhotoId) {
    closeLightbox({ target: { id: 'duplicates-lightbox' } });
  }
});


updateSelectionMeta();
void loadDuplicates();
