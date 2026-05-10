function getShareParams() {
  const params = new URLSearchParams(window.location.search);
  return {
    kind: params.get('kind'),
    token: params.get('token'),
  };
}


function renderShareHero(payload, kind, token) {
  const hero = document.getElementById('share-hero');
  const photoCount = payload.photos?.length || 0;
  const expiresAt = payload.expires_at ? new Date(payload.expires_at).toLocaleString() : 'Unknown';
  const title = payload.label || payload.event?.label || 'Shared Photos';
  const isEventShare = kind === 'event' || kind === 'events';
  const downloadKind = isEventShare ? 'events' : 'photos';

  hero.innerHTML = `
    <h1>${title}</h1>
    <p>${isEventShare ? 'A shared event album from MemoryLens.' : 'A shared photo collection from MemoryLens.'}</p>
    <div class="share-meta">
      <span>${photoCount} photo${photoCount === 1 ? '' : 's'}</span>
      <span>Available until ${expiresAt}</span>
    </div>
    <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn btn-primary" onclick="downloadShared('${downloadKind}', '${token}')">Download Album</button>
      <a class="btn btn-ghost" href="gallery.html">Open MemoryLens</a>
    </div>
  `;
}


function renderShareGrid(payload, kind, token) {
  const grid = document.getElementById('share-grid');
  const photoKind = (kind === 'event' || kind === 'events') ? 'events' : 'photos';
  const photos = payload.photos || [];
  if (!photos.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><h3>No photos available</h3><p>This share is empty or has expired.</p></div>`;
    return;
  }

  grid.innerHTML = '';
  photos.forEach((photo) => {
    const card = document.createElement('article');
    card.className = 'share-card';
    const imageUrl = Shared.imageUrl(photoKind, token, photo.id);
    card.innerHTML = `
      <img src="${imageUrl}" alt="${photo.scene || 'shared photo'}" loading="lazy"/>
      <div class="share-card-body">
        <div class="share-card-title">${photo.original_filename || photo.filename}</div>
        <div class="share-card-meta">${photo.scene || 'Unlabeled'} - ${new Date(photo.captured_at || photo.uploaded_at).toLocaleDateString()}</div>
      </div>
    `;
    grid.appendChild(card);
  });
}


async function downloadShared(kind, token) {
  try {
    await Shared.download(kind, token, 'memorylens-share.zip');
  } catch (error) {
    showToast(error.message || 'Download failed', 'error');
  }
}


async function initSharedView() {
  const { kind, token } = getShareParams();
  if (!kind || !token) {
    document.getElementById('share-hero').innerHTML = `
      <h1>Share link unavailable</h1>
      <p>This page needs a valid MemoryLens share token.</p>
    `;
    return;
  }

  try {
    const payload = await Shared.get(kind, token);
    renderShareHero(payload, kind, token);
    renderShareGrid(payload, kind, token);
  } catch (error) {
    document.getElementById('share-hero').innerHTML = `
      <h1>Share link unavailable</h1>
      <p>${error.message || 'This share link is no longer available.'}</p>
    `;
  }
}


initSharedView();
