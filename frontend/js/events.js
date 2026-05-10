requireAuth();

let eventsCache = [];
const selectedEventIds = new Set();

let activeModalEventId = null;
let activeModalEventLabel = '';
let activeModalPhotos = [];
const splitSelection = new Set();
let draggedPhotoIds = [];


function updateEventSelectionMeta() {
  const count = selectedEventIds.size;
  document.getElementById('selection-meta').textContent = `${count} event${count === 1 ? '' : 's'} selected`;
}


function updateSplitMeta() {
  const count = splitSelection.size;
  document.getElementById('split-meta').textContent = `${count} photo${count === 1 ? '' : 's'} selected for split`;
}


function clearSelectedEvents() {
  selectedEventIds.clear();
  updateEventSelectionMeta();
  document.querySelectorAll('.event-card').forEach((card) => card.classList.remove('event-selected'));
  document.querySelectorAll('.event-select').forEach((input) => {
    input.checked = false;
  });
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


async function shareEventLink(eventId, label) {
  const response = await Events.share(eventId);
  const url = buildShareViewerUrl('events', response.token);
  await copyShareLink(url, label || response.label || 'Shared album');
  showToast('Album share link ready', 'success');
}


async function exportEventById(eventId) {
  await Events.export(eventId);
  showToast('Album export started', 'success');
}


async function loadEvents() {
  try {
    eventsCache = await Events.getAll();
    await renderEvents(eventsCache);
  } catch (error) {
    document.getElementById('events-grid').innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <h3>No events yet</h3>
        <p>Upload photos and click "Organize New Photos"</p>
      </div>`;
  }
}


async function renderEvents(events) {
  const grid = document.getElementById('events-grid');
  if (!events.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      <h3>No events yet</h3>
      <p>Upload some photos then click "Organize New Photos" above</p>
    </div>`;
    clearSelectedEvents();
    return;
  }

  grid.innerHTML = '';
  events.forEach((event) => {
    const card = document.createElement('div');
    card.className = 'event-card';
    if (selectedEventIds.has(event.id)) {
      card.classList.add('event-selected');
    }
    card.onclick = () => openEvent(event.id, event.label);

    const previews = event.preview_photos || [];
    let thumbHtml = '';
    for (let index = 0; index < 3; index += 1) {
      if (previews[index]) {
        thumbHtml += `<img data-photo-id="${previews[index].id}" alt="${previews[index].scene || 'preview'}" loading="lazy"/>`;
      } else {
        thumbHtml += '<div class="event-thumb-placeholder">+</div>';
      }
    }

    card.innerHTML = `
      <label class="event-select-wrap" onclick="event.stopPropagation()">
        <input class="event-select" type="checkbox" ${selectedEventIds.has(event.id) ? 'checked' : ''} onchange="toggleEventSelection(${event.id}, this)"/>
      </label>
      <div class="event-thumb-grid">${thumbHtml}</div>
      <div class="event-info">
        <div class="event-name">${event.label}</div>
        <div class="event-meta">
          <span>${event.photo_count} photos</span>
        </div>
        <div class="event-actions" onclick="event.stopPropagation()">
          <button class="action-btn" onclick='renameEvent(${event.id}, ${JSON.stringify(event.label)})'>Rename</button>
          <button class="action-btn" onclick='shareEvent(${event.id}, ${JSON.stringify(event.label)})'>Share</button>
          <button class="action-btn" onclick="exportEvent(${event.id})">Export</button>
          <button class="action-btn action-danger" onclick="deleteEvent(event, ${event.id})">Delete</button>
        </div>
      </div>`;

    grid.appendChild(card);
  });

  updateEventSelectionMeta();
  await hydrateProtectedImages(grid);
}


function toggleEventSelection(eventId, input) {
  if (input.checked) {
    selectedEventIds.add(eventId);
  } else {
    selectedEventIds.delete(eventId);
  }

  const card = input.closest('.event-card');
  if (card) {
    card.classList.toggle('event-selected', input.checked);
  }
  updateEventSelectionMeta();
}


async function organizePhotos() {
  const buttonLabel = document.getElementById('org-btn-text');
  buttonLabel.innerHTML = '<span class="spinner"></span> Organizing...';

  try {
    const response = await Events.organize();
    const job = await Jobs.waitForCompletion(response.job.id, (update) => {
      const done = update.completed_items || 0;
      const total = update.total_items || 0;
      buttonLabel.innerHTML = `<span class="spinner"></span> Organizing ${done}/${total || '?'}`;
    });

    if (job.status === 'failed') {
      throw new Error(job.error_message || 'Organization failed');
    }

    const count = job.result?.events_created || 0;
    const matched = job.result?.matched_existing_count || 0;
    const merged = job.result?.merged_duplicate_albums || 0;
    const leftovers = job.result?.unassigned_count || 0;
    showToast(`Matched ${matched}, merged ${merged}, created ${count}, leftovers ${leftovers}`, 'success');
    await loadEvents();
  } catch (error) {
    showToast(error.message || 'Organization failed. Check the backend.', 'error');
  }

  buttonLabel.textContent = 'Organize New Photos';
}


async function renameEvent(eventId, currentLabel) {
  const nextLabel = prompt('Rename event', currentLabel || '');
  if (nextLabel === null) {
    return;
  }
  const trimmed = nextLabel.trim();
  if (!trimmed) {
    showToast('Event name cannot be empty', 'error');
    return;
  }

  try {
    await Events.rename(eventId, trimmed);
    showToast('Event renamed', 'success');
    await loadEvents();
  } catch (error) {
    showToast(error.message || 'Rename failed', 'error');
  }
}


async function mergeSelectedEvents() {
  if (selectedEventIds.size < 2) {
    showToast('Select at least 2 events to merge', 'error');
    return;
  }

  const eventIds = [...selectedEventIds];
  const mergeLabel = document.getElementById('merge-label').value.trim();

  try {
    const merged = await Events.merge(eventIds, mergeLabel || null);
    showToast(`Merged into "${merged.label}"`, 'success');
    clearSelectedEvents();
    document.getElementById('merge-label').value = '';
    await loadEvents();
  } catch (error) {
    showToast(error.message || 'Merge failed', 'error');
  }
}


function renderMoveTargets() {
  const select = document.getElementById('move-target-select');
  const targets = eventsCache.filter((event) => event.id !== activeModalEventId);
  select.innerHTML = ['<option value="">Move selected into...</option>']
    .concat(targets.map((event) => `<option value="${event.id}">${event.label}</option>`))
    .join('');

  const dropTargets = document.getElementById('drop-targets');
  dropTargets.innerHTML = '';
  targets.forEach((event) => {
    const item = document.createElement('div');
    item.className = 'drop-target';
    item.dataset.eventId = String(event.id);
    item.innerHTML = `<strong>${event.label}</strong><span>${event.photo_count} photos</span>`;
    item.ondragover = allowAlbumDrop;
    item.ondragleave = clearAlbumDrop;
    item.ondrop = (dropEvent) => dropOnAlbum(dropEvent, event.id);
    dropTargets.appendChild(item);
  });
}


async function openEvent(id, label) {
  activeModalEventId = id;
  activeModalEventLabel = label;
  splitSelection.clear();
  draggedPhotoIds = [];
  updateSplitMeta();

  document.getElementById('split-label').value = `${label} Split`;
  document.getElementById('modal-title').textContent = label;
  document.getElementById('modal-subtitle').textContent = 'Drag a photo into another album or split out a new one.';
  document.getElementById('modal-grid').innerHTML = '<div class="spinner" style="margin:24px auto"></div>';
  document.getElementById('event-modal').classList.add('open');
  renderMoveTargets();

  try {
    activeModalPhotos = await Events.getPhotos(id);
    const grid = document.getElementById('modal-grid');
    grid.innerHTML = '';

    activeModalPhotos.forEach((photo) => {
      const item = document.createElement('div');
      item.className = 'modal-photo';
      item.draggable = true;
      item.dataset.photoId = String(photo.id);
      item.ondragstart = (dragEvent) => startPhotoDrag(dragEvent, photo.id);
      item.ondragend = (dragEvent) => endPhotoDrag(dragEvent);
      item.innerHTML = `
        <img data-photo-id="${photo.id}" alt="${photo.scene}" loading="lazy"/>
        <div class="modal-photo-meta">
          <span>${photo.scene || 'Unlabeled'}</span>
          <div class="modal-photo-actions">
            <label onclick="event.stopPropagation()">
              <input type="checkbox" onchange="toggleSplitSelection(${photo.id}, this)"/>
              Select
            </label>
            <button type="button" class="modal-photo-btn modal-photo-btn-danger" onclick="deletePhotoFromAlbum(event, ${photo.id})">Remove</button>
          </div>
        </div>
      `;
      grid.appendChild(item);
    });

    document.getElementById('modal-subtitle').textContent = `${activeModalPhotos.length} photo${activeModalPhotos.length === 1 ? '' : 's'} in this album.`;
    renderMoveTargets();
    await hydrateProtectedImages(grid);
  } catch (error) {
    showToast(error.message || 'Could not load event photos', 'error');
  }
}


function toggleSplitSelection(photoId, input) {
  if (input.checked) {
    splitSelection.add(photoId);
  } else {
    splitSelection.delete(photoId);
  }
  updateSplitMeta();
}


function currentDragSelection(photoId) {
  if (splitSelection.size > 0 && splitSelection.has(photoId)) {
    return [...splitSelection];
  }
  return [photoId];
}


function startPhotoDrag(event, photoId) {
  draggedPhotoIds = currentDragSelection(photoId);
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', JSON.stringify(draggedPhotoIds));
  event.currentTarget.classList.add('dragging');
}


function endPhotoDrag(event) {
  draggedPhotoIds = [];
  document.querySelectorAll('.drop-target').forEach((target) => target.classList.remove('active'));
  event.currentTarget.classList.remove('dragging');
}


function allowAlbumDrop(event) {
  event.preventDefault();
  event.currentTarget.classList.add('active');
}


function clearAlbumDrop(event) {
  event.currentTarget.classList.remove('active');
}


async function movePhotosToEvent(photoIds, targetEventId) {
  if (!photoIds.length) {
    showToast('Select or drag at least 1 photo', 'error');
    return;
  }

  try {
    await Events.movePhotos(photoIds, targetEventId);
    showToast(`Moved ${photoIds.length} photo${photoIds.length === 1 ? '' : 's'}`, 'success');
    await loadEvents();

    const currentEvent = eventsCache.find((event) => event.id === activeModalEventId);
    if (currentEvent) {
      await openEvent(currentEvent.id, currentEvent.label);
    } else {
      closeModal();
    }
  } catch (error) {
    showToast(error.message || 'Move failed', 'error');
  }
}


async function dropOnAlbum(event, targetEventId) {
  event.preventDefault();
  event.currentTarget.classList.remove('active');

  let photoIds = draggedPhotoIds.slice();
  if (!photoIds.length) {
    try {
      photoIds = JSON.parse(event.dataTransfer.getData('text/plain') || '[]');
    } catch (error) {
      photoIds = [];
    }
  }

  await movePhotosToEvent(photoIds, targetEventId);
}


async function moveSelectedPhotos() {
  if (!splitSelection.size) {
    showToast('Select photos first, then choose a destination album', 'error');
    return;
  }

  const targetEventId = Number(document.getElementById('move-target-select').value || 0);
  if (!targetEventId) {
    showToast('Choose a destination album', 'error');
    return;
  }

  await movePhotosToEvent([...splitSelection], targetEventId);
}


async function splitSelectedPhotos() {
  if (!activeModalEventId) {
    showToast('Open an event first', 'error');
    return;
  }
  if (splitSelection.size === 0) {
    showToast('Select photos to split', 'error');
    return;
  }

  const newLabel = document.getElementById('split-label').value.trim();
  try {
    await Events.split(activeModalEventId, [...splitSelection], newLabel || null);
    showToast('Split completed', 'success');
    await loadEvents();
    const currentEvent = eventsCache.find((event) => event.id === activeModalEventId);
    if (currentEvent) {
      await openEvent(currentEvent.id, currentEvent.label);
    } else {
      closeModal();
    }
  } catch (error) {
    showToast(error.message || 'Split failed', 'error');
  }
}


async function exportActiveEvent() {
  if (!activeModalEventId) {
    return;
  }
  await exportEventById(activeModalEventId);
}


async function shareActiveEvent() {
  if (!activeModalEventId) {
    return;
  }
  await shareEventLink(activeModalEventId, activeModalEventLabel);
}


async function exportEvent(eventId) {
  await exportEventById(eventId);
}


async function shareEvent(eventId, label) {
  await shareEventLink(eventId, label);
}


function closeModal() {
  document.getElementById('event-modal').classList.remove('open');
  activeModalEventId = null;
  activeModalEventLabel = '';
  activeModalPhotos = [];
  splitSelection.clear();
  draggedPhotoIds = [];
  updateSplitMeta();
}


document.getElementById('event-modal').addEventListener('click', (event) => {
  if (event.target.id === 'event-modal') {
    closeModal();
  }
});


async function deleteEvent(event, id) {
  event.stopPropagation();
  if (!confirm('Delete this event album?')) {
    return;
  }

  try {
    await Events.delete(id);
    selectedEventIds.delete(id);
    showToast('Event deleted', 'success');
    await loadEvents();
    if (activeModalEventId === id) {
      closeModal();
    }
  } catch (error) {
    showToast(error.message || 'Delete failed', 'error');
  }
}


async function deletePhotoFromAlbum(event, photoId) {
  event.stopPropagation();
  if (!confirm('Remove this photo from the album? It will stay in the gallery.')) {
    return;
  }

  try {
    await Events.removePhotos(activeModalEventId, [photoId]);
    splitSelection.delete(photoId);
    draggedPhotoIds = draggedPhotoIds.filter((id) => id !== photoId);
    showToast('Photo removed from album', 'success');
    await loadEvents();

    const currentEvent = eventsCache.find((item) => item.id === activeModalEventId);
    if (currentEvent) {
      await openEvent(currentEvent.id, currentEvent.label);
    } else {
      closeModal();
    }
  } catch (error) {
    showToast(error.message || 'Delete failed', 'error');
  }
}


loadEvents();
