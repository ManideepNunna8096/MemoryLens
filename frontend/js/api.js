const API_BASE = (() => {
  if (window.MEMORYLENS_API_BASE) {
    return window.MEMORYLENS_API_BASE.replace(/\/$/, '');
  }

  if (window.location.protocol === 'file:' || !window.location.hostname) {
    return 'http://localhost:5000';
  }

  return `${window.location.protocol}//${window.location.hostname}:5000`;
})();

const PHOTO_URL_CACHE = new Map();
const JOB_POLL_INTERVAL_MS = 1000;

function getToken() {
  return localStorage.getItem('ml_token');
}

function getRefreshToken() {
  return localStorage.getItem('ml_refresh_token');
}

function setToken(token) {
  if (token) {
    localStorage.setItem('ml_token', token);
  }
}

function setAuthTokens(accessToken, refreshToken) {
  if (accessToken) {
    localStorage.setItem('ml_token', accessToken);
  }
  if (refreshToken) {
    localStorage.setItem('ml_refresh_token', refreshToken);
  }
}

function hasSession() {
  return Boolean(getToken() || getRefreshToken());
}

function revokePhotoCache() {
  PHOTO_URL_CACHE.forEach((url) => URL.revokeObjectURL(url));
  PHOTO_URL_CACHE.clear();
}

function getLoginPath() {
  return window.location.pathname.includes('/pages/') ? '../index.html' : 'index.html';
}

function clearToken() {
  revokePhotoCache();
  localStorage.removeItem('ml_token');
  localStorage.removeItem('ml_refresh_token');
  localStorage.removeItem('ml_user');
  window.location.href = getLoginPath();
}

function requireAuth() {
  if (!hasSession()) {
    window.location.href = getLoginPath();
  }
}

function authHeaders(token = getToken()) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function parseJwt(token) {
  if (!token) {
    return null;
  }

  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(window.atob(base64));
  } catch (error) {
    return null;
  }
}

function isTokenExpiringSoon(token, skewSeconds = 30) {
  const payload = parseJwt(token);
  if (!payload || !payload.exp) {
    return true;
  }
  return payload.exp <= Math.floor(Date.now() / 1000) + skewSeconds;
}

async function parseJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    return { error: text };
  }
}

function parseDownloadFilename(disposition, fallbackName = 'memorylens-export.zip') {
  if (!disposition) {
    return fallbackName;
  }

  const utfMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utfMatch && utfMatch[1]) {
    return decodeURIComponent(utfMatch[1]);
  }

  const basicMatch = disposition.match(/filename="?([^"]+)"?/i);
  if (basicMatch && basicMatch[1]) {
    return basicMatch[1];
  }

  return fallbackName;
}

async function downloadResponse(response, fallbackName = 'memorylens-export.zip') {
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(data.error || 'Download failed');
  }

  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = blobUrl;
  anchor.download = parseDownloadFilename(response.headers.get('Content-Disposition'), fallbackName);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

async function refreshAccessToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error('Your session has expired. Please sign in again.');
  }

  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: authHeaders(refreshToken),
  });
  const data = await parseJson(response);

  if (!response.ok || !data.access_token) {
    clearToken();
    throw new Error(data.error || 'Your session has expired. Please sign in again.');
  }

  setAuthTokens(data.access_token, data.refresh_token);
  return data.access_token;
}

async function ensureAccessToken() {
  const token = getToken();
  if (token && !isTokenExpiringSoon(token)) {
    return token;
  }

  if (!getRefreshToken()) {
    return token;
  }

  return refreshAccessToken();
}

async function apiFetch(path, options = {}, allowRefresh = true) {
  const headers = { ...(options.headers || {}) };
  const token = await ensureAccessToken();
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401 && allowRefresh && getRefreshToken()) {
    const newToken = await refreshAccessToken();
    const retryHeaders = { ...(options.headers || {}), Authorization: `Bearer ${newToken}` };
    return fetch(`${API_BASE}${path}`, {
      ...options,
      headers: retryHeaders,
    });
  }

  return response;
}

async function downloadWithAuth(path, options = {}, fallbackName = 'memorylens-export.zip') {
  const response = await apiFetch(path, options);
  return downloadResponse(response, fallbackName);
}

async function downloadPublic(path, fallbackName = 'memorylens-export.zip') {
  const response = await fetch(`${API_BASE}${path}`);
  return downloadResponse(response, fallbackName);
}

function buildShareViewerUrl(kind, token) {
  const search = `kind=${encodeURIComponent(kind)}&token=${encodeURIComponent(token)}`;
  if (window.location.protocol === 'file:') {
    return `share.html?${search}`;
  }

  const url = new URL(window.location.href);
  if (url.pathname.includes('/pages/')) {
    url.pathname = url.pathname.replace(/\/[^/]*$/, '/share.html');
  } else {
    url.pathname = '/pages/share.html';
  }
  url.search = search;
  return url.toString();
}

async function getJsonOrThrow(path, options = {}) {
  const response = await apiFetch(path, options);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(data.error || 'Request failed');
  }
  return data;
}

async function getProtectedPhotoUrl(photoId) {
  if (PHOTO_URL_CACHE.has(photoId)) {
    return PHOTO_URL_CACHE.get(photoId);
  }

  const response = await apiFetch(`/photos/${photoId}/file`);
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(data.error || 'Could not load photo');
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  PHOTO_URL_CACHE.set(photoId, objectUrl);
  return objectUrl;
}

async function hydrateProtectedImages(root = document) {
  const images = [...root.querySelectorAll('img[data-photo-id]')];
  await Promise.all(images.map(async (image) => {
    if (image.dataset.loaded === 'true') {
      return;
    }

    try {
      image.src = await getProtectedPhotoUrl(Number(image.dataset.photoId));
      image.dataset.loaded = 'true';
    } catch (error) {
      image.alt = image.alt || 'Photo unavailable';
      image.dataset.loaded = 'error';
    }
  }));
}

const Auth = {
  async register(name, email, password) {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password }),
    });
    return parseJson(response);
  },

  async login(email, password) {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return parseJson(response);
  },
};

const Photos = {
  async upload(files, onProgress) {
    await ensureAccessToken();

    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}/photos/upload`);
      xhr.setRequestHeader('Authorization', `Bearer ${getToken()}`);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };

      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status >= 400) {
            reject(new Error(data.error || 'Upload failed'));
            return;
          }
          resolve(data);
        } catch (error) {
          reject(new Error('Upload failed'));
        }
      };

      xhr.onerror = () => reject(new Error('Upload failed'));
      xhr.send(formData);
    });
  },

  async getAll(filters = {}) {
    const options = typeof filters === 'string' ? { scene: filters } : (filters || {});
    const params = new URLSearchParams();
    if (options.scene) {
      params.set('scene', options.scene);
    }
    if (options.status) {
      params.set('status', options.status);
    }
    if (options.collection) {
      params.set('collection', options.collection);
    }
    if (options.sort) {
      params.set('sort', options.sort);
    }
    if (options.page) {
      params.set('page', String(options.page));
    }
    if (options.page_size) {
      params.set('page_size', String(options.page_size));
    }
    const query = params.toString() ? `?${params.toString()}` : '';
    return getJsonOrThrow(`/photos/all${query}`);
  },

  async getScenes(filters = {}) {
    const options = filters || {};
    const params = new URLSearchParams();
    if (options.collection) {
      params.set('collection', options.collection);
    }
    const query = params.toString() ? `?${params.toString()}` : '';
    return getJsonOrThrow(`/photos/scenes${query}`);
  },

  async delete(photoId) {
    return getJsonOrThrow(`/photos/${photoId}`, { method: 'DELETE' });
  },

  async rename(photoId, name) {
    const requestOptions = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    };

    let response = await apiFetch(`/photos/${photoId}/rename`, requestOptions);
    let data = await parseJson(response);
    if (response.ok) {
      return data;
    }

    if (response.status === 404 || response.status === 405) {
      response = await apiFetch(`/photos/${photoId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      data = await parseJson(response);
      if (response.ok) {
        return data;
      }
    }

    throw new Error(data.error || 'Request failed');
  },

  async bulkAction(action, photoIds, extra = {}) {
    return getJsonOrThrow('/photos/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, photo_ids: photoIds, ...extra }),
    });
  },

  async retry(photoIds) {
    return getJsonOrThrow('/photos/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds }),
    });
  },

  async export(photoIds, label = 'gallery-selection') {
    return downloadWithAuth(
      '/photos/export',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photo_ids: photoIds, label }),
      },
      'gallery-selection.zip',
    );
  },

  async share(photoIds, options = {}) {
    return getJsonOrThrow('/photos/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds, ...options }),
    });
  },
};

function folderLabelFromPhoto(photo) {
  return photo.folder_label || photo.custom_folder || photo.scene || 'Uncategorized';
}


function buildFolderPayloads(photos) {
  const counts = new Map();
  photos
    .filter((photo) => photo.processing_status === 'ready')
    .forEach((photo) => {
      const name = folderLabelFromPhoto(photo);
      if (!counts.has(name)) {
        counts.set(name, {
          name,
          count: 0,
          custom_count: 0,
          ai_count: 0,
        });
      }

      const entry = counts.get(name);
      entry.count += 1;
      if (photo.custom_folder) {
        entry.custom_count += 1;
      } else {
        entry.ai_count += 1;
      }
    });

  return [...counts.values()]
    .map((entry) => ({
      ...entry,
      kind: entry.custom_count && entry.ai_count ? 'mixed' : entry.custom_count ? 'custom' : 'ai',
      deletable: entry.custom_count > 0 && entry.ai_count === 0,
    }))
    .sort((a, b) => (b.count - a.count) || a.name.localeCompare(b.name));
}


async function loadAllPhotosForFolderOps() {
  const photos = await Photos.getAll({ collection: 'all', sort: 'scene' });
  return Array.isArray(photos) ? photos : (photos.items || []);
}


async function fallbackFolderPhotos(folderName) {
  const photos = await loadAllPhotosForFolderOps();
  return photos.filter((photo) => folderLabelFromPhoto(photo) === folderName);
}

const Folders = {
  async getAll(filters = {}) {
    const options = filters || {};
    const params = new URLSearchParams();
    if (options.collection) {
      params.set('collection', options.collection);
    }
    const query = params.toString() ? `?${params.toString()}` : '';

    const response = await apiFetch(`/folders/all${query}`);
    const data = await parseJson(response);
    if (response.ok) {
      return data;
    }

    if (response.status === 404 || response.status === 405) {
      const photos = await Photos.getAll({ collection: options.collection || 'active', sort: 'scene' });
      const items = Array.isArray(photos) ? photos : (photos.items || []);
      return buildFolderPayloads(items);
    }

    throw new Error(data.error || 'Request failed');
  },

  async movePhotos(photoIds, targetFolder) {
    const response = await apiFetch('/folders/move-photos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds, target_folder: targetFolder }),
    });
    const data = await parseJson(response);
    if (response.ok) {
      return data;
    }

    if (response.status === 404 || response.status === 405) {
      return Photos.bulkAction('set_folder', photoIds, { folder_name: targetFolder });
    }

    throw new Error(data.error || 'Request failed');
  },

  async rename(sourceFolder, targetFolder) {
    const response = await apiFetch('/folders/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_folder: sourceFolder, target_folder: targetFolder }),
    });
    const data = await parseJson(response);
    if (response.ok) {
      return data;
    }

    if (response.status === 404 || response.status === 405) {
      const photos = await fallbackFolderPhotos(sourceFolder);
      const photoIds = photos.map((photo) => photo.id);
      if (!photoIds.length) {
        throw new Error('Folder not found');
      }
      return Photos.bulkAction('set_folder', photoIds, { folder_name: targetFolder });
    }

    throw new Error(data.error || 'Request failed');
  },

  async merge(sourceFolders, targetFolder) {
    const response = await apiFetch('/folders/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_folders: sourceFolders, target_folder: targetFolder }),
    });
    const data = await parseJson(response);
    if (response.ok) {
      return data;
    }

    if (response.status === 404 || response.status === 405) {
      const photos = await loadAllPhotosForFolderOps();
      const sourceSet = new Set(sourceFolders);
      const photoIds = photos
        .filter((photo) => sourceSet.has(folderLabelFromPhoto(photo)))
        .map((photo) => photo.id);
      if (!photoIds.length) {
        throw new Error('No photos were found in the selected folders');
      }
      return Photos.bulkAction('set_folder', photoIds, { folder_name: targetFolder });
    }

    throw new Error(data.error || 'Request failed');
  },

  async delete(folderName) {
    const response = await apiFetch('/folders/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_name: folderName }),
    });
    const data = await parseJson(response);
    if (response.ok) {
      return data;
    }

    if (response.status === 404 || response.status === 405) {
      const photos = await fallbackFolderPhotos(folderName);
      const photoIds = photos.map((photo) => photo.id);
      if (!photoIds.length) {
        return { deleted_count: 0, message: 'Folder already gone' };
      }
      return Photos.bulkAction('set_folder', photoIds, { folder_name: '' });
    }

    throw new Error(data.error || 'Request failed');
  },
};

const Jobs = {
  async get(jobId) {
    return getJsonOrThrow(`/jobs/${jobId}`);
  },

  async waitForCompletion(jobId, onUpdate = null, timeoutMs = 180000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const job = await Jobs.get(jobId);
      if (onUpdate) {
        onUpdate(job);
      }

      if (['completed', 'completed_with_errors', 'failed'].includes(job.status)) {
        return job;
      }

      await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    }

    throw new Error('Timed out while waiting for background processing');
  },
};

const Search = {
  async query(text) {
    return getJsonOrThrow(`/search?q=${encodeURIComponent(text)}`);
  },
};

const Timeline = {
  async get(group = 'day', filters = {}) {
    const params = new URLSearchParams();
    params.set('group', group);
    if (filters.collection) {
      params.set('collection', filters.collection);
    }
    if (filters.start) {
      params.set('start', filters.start);
    }
    if (filters.end) {
      params.set('end', filters.end);
    }
    const query = params.toString() ? `?${params.toString()}` : '';
    return getJsonOrThrow(`/timeline${query}`);
  },
};

const Duplicates = {
  async get() {
    try {
      return await getJsonOrThrow('/duplicates');
    } catch (error) {
      if (/not found on the server/i.test(error.message || '')) {
        throw new Error('The Duplicates backend is not loaded yet. Restart Flask once to enable this section.');
      }
      throw error;
    }
  },

  async scan(options = {}) {
    try {
      return await getJsonOrThrow('/duplicates/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options),
      });
    } catch (error) {
      if (/not found on the server/i.test(error.message || '')) {
        throw new Error('The Duplicates backend is not loaded yet. Restart Flask once to enable this section.');
      }
      throw error;
    }
  },

  async trash(photoIds) {
    try {
      return await getJsonOrThrow('/duplicates/trash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photo_ids: photoIds }),
      });
    } catch (error) {
      if (/not found on the server/i.test(error.message || '')) {
        throw new Error('The Duplicates backend is not loaded yet. Restart Flask once to enable this section.');
      }
      throw error;
    }
  },

  async keep(photoId) {
    try {
      return await getJsonOrThrow('/duplicates/keep', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photo_id: photoId }),
      });
    } catch (error) {
      if (/not found on the server/i.test(error.message || '')) {
        throw new Error('The Duplicates backend is not loaded yet. Restart Flask once to enable this section.');
      }
      throw error;
    }
  },
};

const Events = {
  async organize() {
    return getJsonOrThrow('/events/organize', { method: 'POST' });
  },

  async getAll() {
    return getJsonOrThrow('/events/all');
  },

  async getPhotos(eventId) {
    return getJsonOrThrow(`/events/${eventId}/photos`);
  },

  async delete(eventId) {
    return getJsonOrThrow(`/events/${eventId}`, { method: 'DELETE' });
  },

  async rename(eventId, label) {
    return getJsonOrThrow(`/events/${eventId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
    });
  },

  async merge(eventIds, label) {
    return getJsonOrThrow('/events/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_ids: eventIds, label }),
    });
  },

  async split(eventId, photoIds, newLabel) {
    return getJsonOrThrow(`/events/${eventId}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds, new_label: newLabel }),
    });
  },

  async movePhotos(photoIds, targetEventId) {
    return getJsonOrThrow('/events/move-photos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds, target_event_id: targetEventId }),
    });
  },

  async removePhotos(eventId, photoIds) {
    return getJsonOrThrow(`/events/${eventId}/remove-photos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds }),
    });
  },

  async export(eventId) {
    return downloadWithAuth(`/events/${eventId}/export`, { method: 'GET' }, `event-${eventId}.zip`);
  },

  async share(eventId, options = {}) {
    return getJsonOrThrow(`/events/${eventId}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options),
    });
  },
};

const Shared = {
  async get(kind, token) {
    const response = await fetch(`${API_BASE}/share/${kind}/${token}`);
    const data = await parseJson(response);
    if (!response.ok) {
      throw new Error(data.error || 'Share link is unavailable');
    }
    return data;
  },

  imageUrl(kind, token, photoId) {
    return `${API_BASE}/share/${kind}/${encodeURIComponent(token)}/file/${photoId}`;
  },

  async download(kind, token, fallbackName = 'memorylens-share.zip') {
    return downloadPublic(`/share/${kind}/${encodeURIComponent(token)}/download`, fallbackName);
  },
};

function showToast(message, type = 'info') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const icons = { success: 'OK', error: 'X', info: 'i' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function renderPhotoCard(photo, onDelete = null) {
  const card = document.createElement('div');
  card.className = 'photo-card';
  card.dataset.id = photo.id;
  const sceneLabel = photo.processing_status === 'ready'
    ? photo.scene
    : photo.processing_status === 'failed'
      ? 'Failed'
      : 'Processing';
  card.innerHTML = `
    <div class="photo-img-wrap">
      <img data-photo-id="${photo.id}" alt="${photo.scene}" loading="lazy"/>
      <div class="photo-overlay">
        <span class="badge badge-purple">${sceneLabel}</span>
        ${onDelete ? `<button class="btn btn-sm btn-ghost delete-btn" onclick="handleDelete(${photo.id})">X</button>` : ''}
      </div>
    </div>
    <div class="photo-info">
      <p class="photo-scene">${sceneLabel}</p>
      <p class="photo-date">${new Date(photo.uploaded_at).toLocaleDateString()}</p>
    </div>
  `;
  return card;
}

function fmt(value) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value;
}

function setActiveNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-link').forEach((link) => {
    link.classList.toggle('active', link.getAttribute('href') && path.includes(link.getAttribute('href')));
  });
}

function loadNavUser() {
  const user = JSON.parse(localStorage.getItem('ml_user') || '{}');
  const nameEl = document.getElementById('nav-username');
  const avatarEl = document.getElementById('nav-avatar');
  if (nameEl && user.name) {
    nameEl.textContent = user.name;
  }
  if (avatarEl && user.name) {
    avatarEl.textContent = user.name[0].toUpperCase();
  }
}

window.addEventListener('beforeunload', revokePhotoCache);

document.addEventListener('DOMContentLoaded', () => {
  setActiveNav();
  loadNavUser();
});
