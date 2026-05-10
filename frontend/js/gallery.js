requireAuth();

const PAGE_SIZE = 24;
const PROCESSING_STATUSES = new Set(['queued', 'in_progress']);
const COLLECTION_LABELS = {
  active: 'Library',
  favorites: 'Favorites',
  trash: 'Trash',
};

let allPhotos = [];
let currentPhotos = [];
let foldersCache = [];
let eventsCache = [];
let currentScene = null;
let currentCollection = 'active';
let currentSort = 'newest';
let refreshTimer = null;
let isLoading = false;
let visibleCount = PAGE_SIZE;
let sentinelObserver = null;
let openFolderMenu = null;
let activeLightboxPhotoId = null;
let activeDetailPhotoId = null;
let folderSearchQuery = '';
const selectedPhotoIds = new Set();


function photoFolderName(photo) {
  return photo.folder_label || photo.custom_folder || photo.scene || 'Uncategorized';
}


function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}


function photoNameSource(photo) {
  return photo.display_name || photo.scene || photo.original_filename || photo.filename || `Photo ${photo.id}`;
}


function photoDisplayTitle(photo) {
  return photoNameSource(photo);
}


function photoMetaText(photo) {
  const dateLabel = new Date(photoDateLabel(photo)).toLocaleDateString();
  const folderLabel = photoFolderName(photo);
  const sceneLabel = photo.scene || 'Unlabeled';
  const parts = [];
  if (folderLabel && folderLabel !== sceneLabel) {
    parts.push(folderLabel);
  }
  parts.push(sceneLabel);
  parts.push(dateLabel);
  return parts.join(' - ');
}


function photoEventLabel(photo) {
  if (!photo?.event_id) {
    return 'Not in an album';
  }
  return eventsCache.find((event) => event.id === photo.event_id)?.label || `Album #${photo.event_id}`;
}


function formatPhotoDate(value) {
  if (!value) {
    return 'Not available';
  }
  return new Date(value).toLocaleString();
}


function getPhotoById(photoId) {
  return currentPhotos.find((item) => item.id === photoId) || allPhotos.find((item) => item.id === photoId) || null;
}


function filteredPhotos() {
  const photos = currentScene
    ? currentPhotos.filter((photo) => photoFolderName(photo) === currentScene)
    : currentPhotos.slice();
  return photos;
}


function visiblePhotos() {
  return filteredPhotos().slice(0, visibleCount);
}


function processingPhotos() {
  return allPhotos.filter((photo) => PROCESSING_STATUSES.has(photo.processing_status) && !photo.is_trashed);
}


function failedPhotos() {
  return allPhotos.filter((photo) => photo.processing_status === 'failed' && !photo.is_trashed);
}


function favoritePhotos() {
  return allPhotos.filter((photo) => photo.is_favorite && !photo.is_trashed);
}


function photoDateLabel(photo) {
  return photo.captured_at || photo.uploaded_at;
}


function selectionCount() {
  return selectedPhotoIds.size;
}


function updateStats() {
  document.getElementById('stat-total').textContent = allPhotos.length;
  document.getElementById('stat-ready').textContent = foldersCache.length;
  document.getElementById('stat-favorites').textContent = favoritePhotos().length;
  document.getElementById('stat-processing').textContent = processingPhotos().length;
  document.getElementById('all-count').textContent = currentPhotos.length;
}


function updateCollectionTabs() {
  document.querySelectorAll('.collection-chip').forEach((button) => {
    button.classList.toggle('active', button.dataset.collection === currentCollection);
  });
}


function updateSelectionMeta() {
  const count = selectionCount();
  document.getElementById('selection-meta').textContent = count === 0
    ? 'No photos selected'
    : `${count} photo${count === 1 ? '' : 's'} selected`;
  document.getElementById('bulk-bar').classList.toggle('active', count > 0);
}


function updateProcessingBanner() {
  const banner = document.getElementById('processing-banner');
  const title = document.getElementById('processing-title');
  const copy = document.getElementById('processing-copy');
  const processingCount = processingPhotos().length;
  const failedCount = failedPhotos().length;

  if (processingCount === 0 && failedCount === 0) {
    banner.style.display = 'none';
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
    return;
  }

  banner.style.display = 'block';
  if (processingCount > 0) {
    title.textContent = `${processingCount} photo${processingCount === 1 ? '' : 's'} still processing`;
    copy.textContent = failedCount > 0
      ? `${failedCount} failed photo${failedCount === 1 ? '' : 's'} can be retried from the gallery cards or bulk actions.`
      : 'The gallery will refresh automatically while background processing finishes.';
  } else {
    title.textContent = `${failedCount} photo${failedCount === 1 ? '' : 's'} need attention`;
    copy.textContent = 'Retry failed items from the gallery cards or select them in bulk.';
  }

  if (processingCount > 0 && !refreshTimer) {
    refreshTimer = setInterval(() => {
      refreshGalleryData(true);
    }, 5000);
  }
}


function renderSceneFilters() {
  if (currentScene && !foldersCache.some((entry) => entry.name === currentScene)) {
    currentScene = null;
  }
  if (openFolderMenu && !foldersCache.some((entry) => entry.name === openFolderMenu)) {
    openFolderMenu = null;
  }

  const allItem = document.getElementById('scene-all');
  allItem.classList.toggle('active', currentScene === null);
  allItem.querySelector('.scene-label').textContent = `All ${COLLECTION_LABELS[currentCollection]}`;

  const sceneList = document.getElementById('scene-list');
  const query = folderSearchQuery.trim().toLowerCase();
  const visibleFolders = query
    ? foldersCache.filter((folder) => folder.name.toLowerCase().includes(query))
    : foldersCache;

  sceneList.innerHTML = '';
  if (!visibleFolders.length) {
    sceneList.innerHTML = `
      <div class="empty-state" style="padding:18px 8px;text-align:left">
        <h3 style="font-size:16px;margin-bottom:6px">No matching folders</h3>
        <p style="font-size:13px">Try a different folder name or clear the search.</p>
      </div>`;
    return;
  }

  visibleFolders.forEach((folder) => {
    const row = document.createElement('div');
    row.className = 'folder-row';
    row.innerHTML = `
      <button type="button" class="scene-item folder-main ${currentScene === folder.name ? 'active' : ''}">
        <span class="scene-name">${escapeHtml(folder.name)}</span>
        <span class="scene-count">${folder.count}</span>
      </button>
      <div class="folder-actions">
        <button type="button" class="folder-menu-toggle ${openFolderMenu === folder.name ? 'active' : ''}" aria-label="Folder actions">...</button>
        <div class="folder-menu ${openFolderMenu === folder.name ? 'open' : ''}">
          <button type="button" class="folder-rename">Rename folder</button>
          <button type="button" class="danger folder-delete">Delete folder</button>
        </div>
      </div>
    `;

    const mainButton = row.querySelector('.folder-main');
    const menuToggle = row.querySelector('.folder-menu-toggle');
    const menu = row.querySelector('.folder-menu');
    const renameButton = row.querySelector('.folder-rename');
    const deleteButton = row.querySelector('.folder-delete');

    mainButton.onclick = () => {
      currentScene = folder.name;
      openFolderMenu = null;
      visibleCount = PAGE_SIZE;
      renderSceneFilters();
      void renderPhotos();
    };
    menuToggle.addEventListener('click', (event) => toggleFolderMenu(event, folder.name));
    menu.addEventListener('click', (event) => event.stopPropagation());
    renameButton.addEventListener('click', (event) => void renameFolder(event, folder.name));
    if (deleteButton) {
      deleteButton.addEventListener('click', (event) => void deleteFolder(event, folder));
    }

    sceneList.appendChild(row);
  });
}


function renderEventSelect() {
  const select = document.getElementById('move-event-select');
  const options = ['<option value="">Move selected to album...</option>']
    .concat(eventsCache.map((event) => `<option value="${event.id}">${event.label}</option>`));
  select.innerHTML = options.join('');
}


function renderFolderSelect() {
  const select = document.getElementById('move-folder-select');
  if (!select) {
    return;
  }

  const previousValue = select.value;
  select.innerHTML = '';

  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Move selected to folder...';
  select.appendChild(placeholder);

  const createOption = document.createElement('option');
  createOption.value = '__new__';
  createOption.textContent = 'Create new folder...';
  select.appendChild(createOption);

  const resetOption = document.createElement('option');
  resetOption.value = '__ai__';
  resetOption.textContent = 'Use AI scene folders';
  select.appendChild(resetOption);

  foldersCache.forEach((folder) => {
    const option = document.createElement('option');
    option.value = folder.name;
    option.textContent = `${folder.name} (${folder.count})`;
    select.appendChild(option);
  });

  if ([...select.options].some((option) => option.value === previousValue)) {
    select.value = previousValue;
  }
}


function syncSelection() {
  const allowedIds = new Set(currentPhotos.map((photo) => photo.id));
  [...selectedPhotoIds].forEach((photoId) => {
    if (!allowedIds.has(photoId)) {
      selectedPhotoIds.delete(photoId);
    }
  });
  updateSelectionMeta();
}


async function refreshGalleryData(isBackgroundRefresh = false) {
  if (isLoading) {
    return;
  }
  isLoading = true;

  try {
    const [collectionData, allData, folders, events] = await Promise.all([
      Photos.getAll({ collection: currentCollection, sort: currentSort }),
      Photos.getAll({ collection: 'all', sort: 'newest' }),
      Folders.getAll({ collection: currentCollection }),
      Events.getAll(),
    ]);

    currentPhotos = Array.isArray(collectionData) ? collectionData : collectionData.items;
    allPhotos = Array.isArray(allData) ? allData : allData.items;
    foldersCache = folders;
    eventsCache = events;

    syncSelection();
    updateCollectionTabs();
    updateStats();
    renderSceneFilters();
    renderEventSelect();
    renderFolderSelect();
    updateProcessingBanner();
    await renderPhotos();

  } catch (error) {
    if (!isBackgroundRefresh) {
      document.getElementById('gallery-grid').innerHTML = `
        <div class="empty-state" style="grid-column:1/-1">
          <h3>Could not load the gallery</h3>
          <p>${error.message || 'The server returned an unexpected error.'}</p>
          <a class="btn btn-primary" href="upload.html">Go to Upload</a>
        </div>`;
    }
  } finally {
    isLoading = false;
  }
}


function statusBadge(photo) {
  if (photo.processing_status === 'failed') {
    return { label: 'Failed', className: 'badge-failed' };
  }
  if (photo.processing_status === 'ready') {
    return { label: photo.scene || 'Ready', className: 'badge-ready' };
  }
  return { label: 'Processing', className: 'badge-processing' };
}


function stateFlag(photo) {
  if (photo.is_trashed) {
    return '<span class="mini-flag">Trash</span>';
  }
  if (photo.is_favorite) {
    return '<span class="mini-flag">Favorite</span>';
  }
  return '';
}


function actionButtons(photo) {
  const buttons = [];
  if (photo.processing_status === 'failed') {
    buttons.push(`<button class="mini-action danger" onclick="retryPhoto(event, ${photo.id})">Retry</button>`);
  } else {
    buttons.push(`<button class="mini-action" onclick="downloadSinglePhoto(event, ${photo.id})">Download</button>`);
  }
  buttons.push(`<button class="mini-action" onclick="openDetailsFromCard(event, ${photo.id})">Details</button>`);
  buttons.push(`<button class="mini-action" onclick="shareSinglePhoto(event, ${photo.id})">Share</button>`);
  buttons.push(`<button class="mini-action" onclick="renamePhoto(event, ${photo.id})">Rename</button>`);

  if (photo.is_trashed) {
    buttons.push(`<button class="mini-action" onclick="restorePhoto(event, ${photo.id})">Restore</button>`);
    buttons.push(`<button class="mini-action danger" onclick="deletePhoto(event, ${photo.id})">Delete</button>`);
    return buttons.join('');
  }

  buttons.push(
    `<button class="mini-action" onclick="toggleFavorite(event, ${photo.id}, ${photo.is_favorite ? 'true' : 'false'})">${photo.is_favorite ? 'Unfavorite' : 'Favorite'}</button>`,
  );
  buttons.push(`<button class="mini-action danger" onclick="trashPhoto(event, ${photo.id})">Trash</button>`);
  buttons.push(`<button class="mini-action danger" onclick="deletePhoto(event, ${photo.id})">Delete</button>`);
  return buttons.join('');
}


async function renderPhotos() {
  const grid = document.getElementById('gallery-grid');
  const status = document.getElementById('gallery-status');
  const photos = filteredPhotos();

  if (!photos.length) {
    const messages = {
      active: ['No photos in your library', 'Upload photos or restore items from trash.'],
      favorites: ['No favorites yet', 'Mark your best photos so they stay easy to revisit.'],
      trash: ['Trash is empty', 'Moved-to-trash photos will appear here until you restore or delete them permanently.'],
    };
    const [title, description] = messages[currentCollection] || messages.active;
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      <h3>${title}</h3>
      <p>${description}</p>
      <a class="btn btn-primary" href="upload.html">Upload Photos</a>
    </div>`;
    status.textContent = '';
    disconnectObserver();
    return;
  }

  grid.innerHTML = '';
  visiblePhotos().forEach((photo) => {
    const card = document.createElement('article');
    card.className = `photo-card ${selectedPhotoIds.has(photo.id) ? 'selected' : ''}`;
    card.onclick = () => openLightbox(photo);

    const badge = statusBadge(photo);
    card.innerHTML = `
      <label class="card-checkbox" onclick="event.stopPropagation()">
        <input type="checkbox" ${selectedPhotoIds.has(photo.id) ? 'checked' : ''} onchange="togglePhotoSelection(${photo.id}, this.checked)"/>
      </label>
      <div class="photo-img-wrap">
        <img data-photo-id="${photo.id}" alt="${photo.scene || 'photo'}" loading="lazy"/>
        <div class="photo-topline">
          <span class="badge ${badge.className}">${badge.label}</span>
          ${stateFlag(photo)}
        </div>
        <div class="photo-overlay">${actionButtons(photo)}</div>
      </div>
      <div class="photo-info">
        <div class="photo-title-row">
          <div class="photo-scene">${photoDisplayTitle(photo)}</div>
        </div>
        <div class="photo-meta">${photoMetaText(photo)}</div>
      </div>`;

    grid.appendChild(card);
  });

  await hydrateProtectedImages(grid);
  status.textContent = `${Math.min(visibleCount, photos.length)} of ${photos.length} photos shown`;
  observeSentinel(photos.length > visibleCount);
}


function observeSentinel(hasMore) {
  disconnectObserver();
  const sentinel = document.getElementById('gallery-sentinel');
  if (!hasMore) {
    sentinel.style.display = 'none';
    return;
  }

  sentinel.style.display = 'block';
  sentinelObserver = new IntersectionObserver((entries) => {
    if (!entries[0]?.isIntersecting) {
      return;
    }
    visibleCount += PAGE_SIZE;
    void renderPhotos();
  }, { rootMargin: '240px' });
  sentinelObserver.observe(sentinel);
}


function disconnectObserver() {
  if (sentinelObserver) {
    sentinelObserver.disconnect();
    sentinelObserver = null;
  }
}


function openLightbox(photo) {
  activeLightboxPhotoId = photo.id;
  const image = document.getElementById('lightbox-img');
  image.removeAttribute('src');
  image.dataset.photoId = String(photo.id);
  delete image.dataset.loaded;
  document.getElementById('lightbox-scene').textContent = photo.scene || 'Unlabeled';
  document.getElementById('lightbox-date').textContent = new Date(photoDateLabel(photo)).toLocaleDateString();
  document.getElementById('lightbox').classList.add('open');
  void hydrateProtectedImages(document.getElementById('lightbox'));
}


function closeLightbox(event) {
  if (!event || event.target.id === 'lightbox' || event.target.classList.contains('lightbox-close')) {
    activeLightboxPhotoId = null;
    document.getElementById('lightbox').classList.remove('open');
  }
}


async function openDetailsPanel(photoId) {
  const photo = getPhotoById(photoId);
  if (!photo) {
    showToast('Photo not found', 'error');
    return;
  }

  const statusText = photo.processing_status === 'ready'
    ? 'Ready photo'
    : photo.processing_status === 'failed'
      ? 'Failed photo'
      : 'Processing photo';

  activeDetailPhotoId = photo.id;
  document.getElementById('details-title').textContent = photoDisplayTitle(photo);
  document.getElementById('details-subtitle').textContent = `${photo.processing_status === 'ready' ? 'Ready photo' : 'Processing photo'} • ID ${photo.id}`;
  document.getElementById('details-custom-name').textContent = photo.display_name || 'Not set';
  document.getElementById('details-subtitle').textContent = `${statusText} - ID ${photo.id}`;
  document.getElementById('details-folder').textContent = photoFolderName(photo);
  document.getElementById('details-scene').textContent = photo.scene || 'Unlabeled';
  document.getElementById('details-event').textContent = photoEventLabel(photo);
  document.getElementById('details-upload-date').textContent = formatPhotoDate(photo.uploaded_at);
  document.getElementById('details-original-name').textContent = photo.original_filename || photo.filename || 'Unknown';

  const detailsImage = document.getElementById('details-image');
  detailsImage.removeAttribute('src');
  detailsImage.alt = photoDisplayTitle(photo);
  try {
    detailsImage.src = await getProtectedPhotoUrl(photo.id);
  } catch (error) {
    detailsImage.alt = 'Photo preview unavailable';
  }

  document.getElementById('details-panel').classList.add('open');
  document.getElementById('details-panel').setAttribute('aria-hidden', 'false');
  document.getElementById('details-backdrop').classList.add('open');
}


function closeDetailsPanel() {
  activeDetailPhotoId = null;
  document.getElementById('details-panel').classList.remove('open');
  document.getElementById('details-panel').setAttribute('aria-hidden', 'true');
  document.getElementById('details-backdrop').classList.remove('open');
}


function openDetailsFromCard(event, photoId) {
  event.stopPropagation();
  void openDetailsPanel(photoId);
}


function openDetailsFromLightbox(event) {
  event.stopPropagation();
  if (!activeLightboxPhotoId) {
    showToast('Open a photo first', 'error');
    return;
  }
  const photoId = activeLightboxPhotoId;
  closeLightbox();
  void openDetailsPanel(photoId);
}


function togglePhotoSelection(photoId, checked) {
  if (checked) {
    selectedPhotoIds.add(photoId);
  } else {
    selectedPhotoIds.delete(photoId);
  }
  updateSelectionMeta();
  void renderPhotos();
}


function toggleSelectVisible() {
  const ids = visiblePhotos().map((photo) => photo.id);
  const shouldSelect = ids.some((id) => !selectedPhotoIds.has(id));
  ids.forEach((id) => {
    if (shouldSelect) {
      selectedPhotoIds.add(id);
    } else {
      selectedPhotoIds.delete(id);
    }
  });
  updateSelectionMeta();
  void renderPhotos();
}


function clearSelection() {
  selectedPhotoIds.clear();
  updateSelectionMeta();
  void renderPhotos();
}


async function copyShareLink(url, title) {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return true;
    } catch (error) {
      if (error && error.name === 'AbortError') {
        return false;
      }
    }
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(url);
    return true;
  }

  window.prompt('Copy this share link', url);
  return true;
}


async function sharePhotos(photoIds, label = 'Shared Photos') {
  const response = await Photos.share(photoIds, { label });
  const url = buildShareViewerUrl('photos', response.token);
  await copyShareLink(url, response.label || label);
  showToast('Share link ready', 'success');
}


async function runBulkAction(action, ids, extra = {}, successMessage = 'Updated') {
  if (!ids.length) {
    showToast('Select at least 1 photo', 'error');
    return;
  }
  await Photos.bulkAction(action, ids, extra);
  clearSelection();
  showToast(successMessage, 'success');
  await refreshGalleryData(false);
}


async function setPhotosFolder(ids, folderName, successMessage) {
  if (!ids.length) {
    showToast('Select at least 1 photo', 'error');
    return;
  }

  await Folders.movePhotos(ids, folderName);
  clearSelection();
  showToast(successMessage, 'success');
  await refreshGalleryData(false);
}


async function retryPhotos(ids) {
  const response = await Photos.retry(ids);
  showToast(`Retry started for ${ids.length} photo${ids.length === 1 ? '' : 's'}`, 'success');
  if (response.job?.id) {
    await refreshGalleryData(false);
  }
}


async function downloadPhotos(ids, label = 'gallery-selection') {
  if (!ids.length) {
    showToast('Select at least 1 photo', 'error');
    return;
  }
  await Photos.export(ids, label);
}


async function shareSelectedPhotos() {
  const ids = [...selectedPhotoIds];
  if (!ids.length) {
    showToast('Select photos to share', 'error');
    return;
  }
  await sharePhotos(ids, `${ids.length} shared photos`);
}


async function downloadSelectedPhotos() {
  const ids = [...selectedPhotoIds];
  await downloadPhotos(ids, `${COLLECTION_LABELS[currentCollection]}-selection`);
}


async function moveSelectedToEvent() {
  const ids = [...selectedPhotoIds];
  const targetEventId = document.getElementById('move-event-select').value;
  if (!ids.length) {
    showToast('Select photos to move', 'error');
    return;
  }
  if (!targetEventId) {
    showToast('Choose an album first', 'error');
    return;
  }

  await runBulkAction('move_to_event', ids, { event_id: targetEventId }, 'Moved photos to album');
  document.getElementById('move-event-select').value = '';
}


async function moveSelectedToFolder() {
  const ids = [...selectedPhotoIds];
  if (!ids.length) {
    showToast('Select photos to move', 'error');
    return;
  }

  const select = document.getElementById('move-folder-select');
  const selectedValue = select?.value || '';
  if (!selectedValue) {
    showToast('Choose a folder first', 'error');
    return;
  }

  let targetFolder = '';
  if (selectedValue === '__new__') {
    const folderName = prompt('Create a new folder for the selected photos', '');
    if (folderName === null) {
      return;
    }
    targetFolder = folderName.trim();
    if (!targetFolder) {
      showToast('Folder name cannot be empty', 'error');
      return;
    }
  } else if (selectedValue === '__ai__') {
    targetFolder = '';
  } else {
    targetFolder = selectedValue;
  }

  const trimmed = targetFolder.trim();
  const successMessage = trimmed
    ? `Moved photos to "${trimmed}"`
    : 'Moved photos back to AI folders';
  await setPhotosFolder(ids, trimmed, successMessage);
  if (select) {
    select.value = '';
  }
}


async function createFolderFromSelection() {
  const ids = [...selectedPhotoIds];
  if (!ids.length) {
    showToast('Select photos first, then create the new folder', 'error');
    return;
  }

  const folderName = prompt('Create a new folder for the selected photos', '');
  if (folderName === null) {
    return;
  }

  const trimmed = folderName.trim();
  if (!trimmed) {
    showToast('Folder name cannot be empty', 'error');
    return;
  }

  await setPhotosFolder(ids, trimmed, `Created "${trimmed}" and moved selected photos`);
}


async function favoriteSelectedPhotos() {
  await runBulkAction('favorite', [...selectedPhotoIds], {}, 'Added to favorites');
}


async function trashSelectedPhotos() {
  if (!selectionCount() || !confirm('Move the selected photos to trash?')) {
    return;
  }
  await runBulkAction('trash', [...selectedPhotoIds], {}, 'Moved photos to trash');
}


async function restoreSelectedPhotos() {
  await runBulkAction('restore', [...selectedPhotoIds], {}, 'Restored selected photos');
}


async function deleteSelectedPhotos() {
  if (!selectionCount() || !confirm('Delete the selected photos permanently?')) {
    return;
  }
  await runBulkAction('delete', [...selectedPhotoIds], {}, 'Deleted selected photos');
}


async function retrySelectedPhotos() {
  const ids = [...selectedPhotoIds];
  if (!ids.length) {
    showToast('Select failed photos to retry', 'error');
    return;
  }
  await retryPhotos(ids);
}


async function toggleFavorite(event, photoId, isFavorite) {
  event.stopPropagation();
  await runBulkAction(isFavorite ? 'unfavorite' : 'favorite', [photoId], {}, isFavorite ? 'Removed from favorites' : 'Added to favorites');
}


async function trashPhoto(event, photoId) {
  event.stopPropagation();
  if (!confirm('Move this photo to trash?')) {
    return;
  }
  await runBulkAction('trash', [photoId], {}, 'Moved photo to trash');
}


async function restorePhoto(event, photoId) {
  event.stopPropagation();
  await runBulkAction('restore', [photoId], {}, 'Photo restored');
}


async function deletePhoto(event, photoId) {
  event.stopPropagation();
  if (!confirm('Delete this photo permanently?')) {
    return;
  }
  await Photos.delete(photoId);
  showToast('Photo deleted', 'success');
  await refreshGalleryData(false);
}


async function retryPhoto(event, photoId) {
  event.stopPropagation();
  await retryPhotos([photoId]);
}


async function downloadSinglePhoto(event, photoId) {
  event.stopPropagation();
  await downloadPhotos([photoId], `photo-${photoId}`);
}


async function shareSinglePhoto(event, photoId) {
  event.stopPropagation();
  await sharePhotos([photoId], `Photo ${photoId}`);
}


async function renamePhoto(event, photoId) {
  event.stopPropagation();
  const photo = currentPhotos.find((item) => item.id === photoId) || allPhotos.find((item) => item.id === photoId);
  if (!photo) {
    showToast('Photo not found', 'error');
    return;
  }

  const currentTitle = photo.display_name || photo.scene || photoDisplayTitle(photo);
  const nextTitle = prompt('Rename photo', currentTitle);
  if (nextTitle === null) {
    return;
  }

  const trimmed = nextTitle.trim();
  if (!trimmed) {
    showToast('Photo name cannot be empty', 'error');
    return;
  }

  try {
    await Photos.rename(photoId, trimmed);
    showToast('Photo renamed', 'success');
    await refreshGalleryData(false);
  } catch (error) {
    showToast(error.message || 'Rename failed', 'error');
  }
}


async function renameActiveDetailPhoto() {
  if (!activeDetailPhotoId) {
    return;
  }
  await renamePhoto({ stopPropagation() {} }, activeDetailPhotoId);
  const updatedPhoto = getPhotoById(activeDetailPhotoId);
  if (updatedPhoto) {
    await openDetailsPanel(updatedPhoto.id);
  }
}


async function shareActiveDetailPhoto() {
  if (!activeDetailPhotoId) {
    return;
  }
  await shareSinglePhoto({ stopPropagation() {} }, activeDetailPhotoId);
}


async function downloadActiveDetailPhoto() {
  if (!activeDetailPhotoId) {
    return;
  }
  await downloadSinglePhoto({ stopPropagation() {} }, activeDetailPhotoId);
}


function toggleFolderMenu(event, folderName) {
  event.stopPropagation();
  openFolderMenu = openFolderMenu === folderName ? null : folderName;
  renderSceneFilters();
}


async function renameFolder(event, sourceFolder) {
  event.stopPropagation();
  openFolderMenu = null;
  renderSceneFilters();

  const nextFolder = prompt(`Rename folder "${sourceFolder}"`, sourceFolder);
  if (nextFolder === null) {
    return;
  }

  const trimmed = nextFolder.trim();
  if (!trimmed) {
    showToast('Folder name cannot be empty', 'error');
    return;
  }

  try {
    await Folders.rename(sourceFolder, trimmed);
    if (currentScene === sourceFolder) {
      currentScene = trimmed;
    }
    showToast(`Renamed folder to "${trimmed}"`, 'success');
    await refreshGalleryData(false);
  } catch (error) {
    showToast(error.message || 'Folder rename failed', 'error');
  }
}


async function deleteFolder(event, folder) {
  event.stopPropagation();
  openFolderMenu = null;
  renderSceneFilters();

  const folderName = folder.name;
  if (folder.kind === 'ai') {
    showToast('AI scene folders cannot be deleted directly. Rename the folder first if you want to turn it into a custom folder.', 'info');
    return;
  }

  if (!confirm(`Delete folder "${folderName}"? Photos will go back to their AI scene folders.`)) {
    return;
  }

  try {
    await Folders.delete(folderName);
    if (currentScene === folderName) {
      currentScene = null;
    }
    showToast(`Deleted folder "${folderName}"`, 'success');
    await refreshGalleryData(false);
  } catch (error) {
    showToast(error.message || 'Folder delete failed', 'error');
  }
}


function setCollection(collection) {
  if (currentCollection === collection) {
    return;
  }
  currentCollection = collection;
  currentScene = null;
  openFolderMenu = null;
  visibleCount = PAGE_SIZE;
  clearSelection();
  void refreshGalleryData(false);
}


function setSort(value) {
  currentSort = value;
  visibleCount = PAGE_SIZE;
  void refreshGalleryData(false);
}


function filterScene(scene = null) {
  currentScene = scene;
  openFolderMenu = null;
  visibleCount = PAGE_SIZE;
  renderSceneFilters();
  void renderPhotos();
}


window.addEventListener('beforeunload', () => {
  disconnectObserver();
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }
});


document.addEventListener('click', () => {
  if (!openFolderMenu) {
    return;
  }
  openFolderMenu = null;
  renderSceneFilters();
});


document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeLightbox({ target: { id: 'lightbox' } });
    closeDetailsPanel();
    if (openFolderMenu) {
      openFolderMenu = null;
      renderSceneFilters();
    }
  }
});


document.getElementById('sort-select').addEventListener('change', (event) => {
  setSort(event.target.value);
});


document.querySelectorAll('.collection-chip').forEach((button) => {
  button.addEventListener('click', () => setCollection(button.dataset.collection));
});


document.getElementById('details-rename-btn').addEventListener('click', () => {
  void renameActiveDetailPhoto();
});
document.getElementById('details-share-btn').addEventListener('click', () => {
  void shareActiveDetailPhoto();
});
document.getElementById('details-download-btn').addEventListener('click', () => {
  void downloadActiveDetailPhoto();
});

const folderSearchInput = document.getElementById('folder-search-input');
if (folderSearchInput) {
  folderSearchInput.addEventListener('input', (event) => {
    folderSearchQuery = event.target.value || '';
    openFolderMenu = null;
    renderSceneFilters();
  });
}


updateSelectionMeta();
refreshGalleryData(false);
