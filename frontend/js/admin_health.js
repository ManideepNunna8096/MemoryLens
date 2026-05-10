const HEALTH_STATUS_LABELS = {
  ok: 'Healthy',
  degraded: 'Degraded',
  error: 'Unavailable',
};

function healthBadgeClass(status) {
  if (status === 'ok') {
    return 'is-good';
  }
  if (status === 'degraded') {
    return 'is-warn';
  }
  return 'is-bad';
}

function modelBadgeClass(model) {
  return model.ready ? 'is-good' : 'is-bad';
}

function formatCount(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function renderModelItem(title, model) {
  const subtitleParts = [];
  if (model.ready) {
    subtitleParts.push('ready for use');
  } else {
    subtitleParts.push('missing prerequisites');
  }

  if (model.files) {
    const missing = Object.entries(model.files)
      .filter(([, present]) => !present)
      .map(([key]) => key.replace(/_/g, ' '));
    if (missing.length) {
      subtitleParts.push(`missing: ${missing.join(', ')}`);
    }
  }

  return `
    <div class="health-model">
      <div>
        <div class="health-model-title">${title}</div>
        <div class="health-model-subtitle">${subtitleParts.join(' | ')}</div>
      </div>
      <span class="health-pill ${modelBadgeClass(model)}">${model.ready ? 'Ready' : 'Missing'}</span>
    </div>
  `;
}

function renderHealth(payload) {
  const status = payload.status || 'error';
  const database = payload.database || {};
  const counts = database.counts || {};
  const vector = payload.vector || {};
  const models = payload.models || {};
  const summary = payload.summary || {};
  const backup = payload.backup || {};

  document.getElementById('health-status').textContent = HEALTH_STATUS_LABELS[status] || status;
  document.getElementById('health-status').className = `health-pill ${healthBadgeClass(status)}`;
  document.getElementById('health-last-updated').textContent = payload.timestamp ? `Updated ${new Date(payload.timestamp).toLocaleString()}` : 'Updated just now';
  document.getElementById('health-summary').textContent = status === 'ok'
    ? 'Everything essential is online.'
    : 'One or more subsystems need attention.';

  document.getElementById('db-dialect').textContent = database.dialect || 'unknown';
  document.getElementById('db-counts').innerHTML = `
    <div class="metric"><strong>${formatCount(counts.users)}</strong><span>All accounts</span></div>
    <div class="metric"><strong>${formatCount(database.visible_photo_count ?? counts.photos)}</strong><span>Active photos</span></div>
    <div class="metric"><strong>${formatCount(counts.events)}</strong><span>Events</span></div>
    <div class="metric"><strong>${formatCount(database.ready_photo_count ?? counts.photos)}</strong><span>Ready photos</span></div>
  `;

  document.getElementById('vector-copy').textContent = vector.pgvector_enabled
    ? 'pgvector is active and ready for similarity search.'
    : vector.reason || 'pgvector is not ready yet.';
  document.getElementById('vector-pill').textContent = vector.pgvector_enabled ? 'Enabled' : 'Pending';
  document.getElementById('vector-pill').className = `health-pill ${vector.pgvector_enabled ? 'is-good' : 'is-warn'}`;

  document.getElementById('status-strip').innerHTML = `
    <div class="status-chip ${vector.pgvector_enabled ? 'is-good' : 'is-warn'}">Vector: ${summary.vector || 'pending'}</div>
    <div class="status-chip ${models.scene_classifier?.ready ? 'is-good' : 'is-warn'}">Scene: ${summary.scene_classifier || 'pending'}</div>
    <div class="status-chip ${models.clip?.ready ? 'is-good' : 'is-warn'}">CLIP: ${summary.clip || 'pending'}</div>
    <div class="status-chip ${models.event_grouping?.ready ? 'is-good' : 'is-warn'}">Events: ${summary.events || 'pending'}</div>
  `;

  document.getElementById('models-list').innerHTML = `
    ${renderModelItem('Scene classifier', models.scene_classifier || {})}
    ${renderModelItem('CLIP embeddings', models.clip || {})}
    ${renderModelItem('Event grouping', models.event_grouping || {})}
  `;
  document.getElementById('health-note').textContent = 'Counts include imported legacy rows and demo/smoke data that remain in PostgreSQL.';

  document.getElementById('backup-pill').textContent = backup.available ? 'Available' : 'Missing';
  document.getElementById('backup-pill').className = `health-pill ${backup.available ? 'is-good' : 'is-warn'}`;
  document.getElementById('backup-summary').textContent = backup.available
    ? `Latest backup: ${backup.latest?.name || 'available'}`
    : 'No backup yet';
  document.getElementById('backup-modified').textContent = backup.latest?.modified_at
    ? `Last backup: ${new Date(backup.latest.modified_at).toLocaleString()}`
    : 'Last backup time not available';
}

async function refreshHealth() {
  const button = document.getElementById('refresh-health');
  const status = document.getElementById('health-status');

  button.disabled = true;
  status.textContent = 'Checking...';
  status.className = 'health-pill';

  try {
    const response = await fetch(`${API_BASE}/admin/health`, { cache: 'no-store' });
    const payload = await response.json();
    renderHealth(payload);
  } catch (error) {
    renderHealth({
      status: 'error',
      timestamp: new Date().toISOString(),
      error: error.message || 'Health check failed',
      database: {},
      vector: {},
      models: {},
      backup: {},
    });
  } finally {
    button.disabled = false;
  }
}

async function createBackup() {
  const button = document.getElementById('run-backup');
  const status = document.getElementById('backup-action-status');

  button.disabled = true;
  status.textContent = 'Creating backup...';

  try {
    const response = await apiFetch('/admin/backup', { method: 'POST' });
    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (parseError) {
        payload = { error: text };
      }
    }
    if (!response.ok) {
      throw new Error(payload.error || 'Backup failed');
    }
    status.textContent = 'Backup created successfully.';
    await refreshHealth();
  } catch (error) {
    status.textContent = error.message || 'Backup could not be started';
  } finally {
    button.disabled = false;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('refresh-health').addEventListener('click', refreshHealth);
  const inlineRefresh = document.getElementById('refresh-health-inline');
  if (inlineRefresh) {
    inlineRefresh.addEventListener('click', refreshHealth);
  }
  document.getElementById('run-backup').addEventListener('click', createBackup);
  refreshHealth();
  window.addEventListener('focus', refreshHealth);
  setInterval(refreshHealth, 30000);
});
