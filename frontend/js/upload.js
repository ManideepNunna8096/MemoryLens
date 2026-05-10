requireAuth();

let selectedFiles = [];


function fileSelectionKey(file) {
  return [file.name, file.size, file.lastModified].join('::');
}

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const previewGrid = document.getElementById('preview-grid');
const uploadActions = document.getElementById('upload-actions');
const fileCount = document.getElementById('file-count');

dropZone.addEventListener('dragover', (event) => {
  event.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

dropZone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropZone.classList.remove('drag-over');
  addFiles([...event.dataTransfer.files]);
});

fileInput.addEventListener('change', () => addFiles([...fileInput.files]));

function addFiles(files) {
  files = files.filter((file) => file.type.startsWith('image/'));
  if (!files.length) {
    showToast('Please select image files only', 'error');
    return;
  }

  files.forEach((file) => {
    const fileKey = fileSelectionKey(file);
    if (selectedFiles.find((selected) => fileSelectionKey(selected) === fileKey)) {
      return;
    }

    selectedFiles.push(file);

    const reader = new FileReader();
    reader.onload = (event) => addPreviewCard(file, fileKey, event.target.result);
    reader.readAsDataURL(file);
  });

  updateActions();
}

function addPreviewCard(file, key, src) {
  const item = document.createElement('div');
  item.className = 'preview-item';
  item.dataset.key = key;
  item.innerHTML = `
    <img src="${src}" alt="${file.name}"/>
    <button class="preview-remove" type="button">X</button>
    <div class="preview-name">${file.name}</div>
  `;
  item.querySelector('.preview-remove').addEventListener('click', () => removeFile(key));
  previewGrid.appendChild(item);
}

function removeFile(key) {
  selectedFiles = selectedFiles.filter((file) => fileSelectionKey(file) !== key);
  previewGrid.querySelector(`.preview-item[data-key="${CSS.escape(key)}"]`)?.remove();
  updateActions();
}

function clearFiles() {
  selectedFiles = [];
  previewGrid.innerHTML = '';
  fileInput.value = '';
  updateActions();
  document.getElementById('results-wrap').innerHTML = '';
  document.getElementById('progress-wrap').style.display = 'none';
}

function updateActions() {
  uploadActions.style.display = selectedFiles.length ? 'flex' : 'none';
  fileCount.textContent = `${selectedFiles.length} photo${selectedFiles.length !== 1 ? 's' : ''} selected`;
}

async function startUpload() {
  if (!selectedFiles.length) {
    return;
  }

  const buttonLabel = document.getElementById('upload-btn-text');
  buttonLabel.innerHTML = '<span class="spinner"></span> Classifying...';

  const progressWrap = document.getElementById('progress-wrap');
  const progressBar = document.getElementById('progress-bar');
  const progressLabel = document.getElementById('progress-label');

  progressWrap.style.display = 'block';
  progressBar.style.width = '0%';

  try {
    const response = await Photos.upload(selectedFiles, (pct) => {
      progressBar.style.width = `${pct}%`;
      progressLabel.textContent = `Uploading... ${pct}%`;
    });

    const rejected = response.rejected || [];
    const initialJob = response.job;
    progressLabel.textContent = 'AI is classifying your photos...';

    const job = await Jobs.waitForCompletion(initialJob.id, (update) => {
      progressBar.style.width = `${update.progress || 0}%`;
      const done = update.completed_items || 0;
      const total = update.total_items || 0;
      progressLabel.textContent = `AI is classifying your photos... ${done}/${total}`;
    });

    progressBar.style.width = '100%';
    const result = job.result || { photos: [], errors: [] };
    const results = [...(result.photos || []), ...(result.errors || []), ...rejected];
    await renderResults(results);

    const successCount = result.success_count || 0;
    const failureCount = (result.failure_count || 0) + rejected.length;
    if (failureCount) {
      showToast(`${successCount} uploaded, ${failureCount} failed`, 'info');
    } else {
      showToast(`${successCount} photos classified successfully!`, 'success');
    }
    selectedFiles = [];
    previewGrid.innerHTML = '';
    fileInput.value = '';
    updateActions();
  } catch (error) {
    showToast(error.message || 'Upload failed. Is Flask running?', 'error');
  }

  buttonLabel.textContent = 'Classify & Upload';
  progressWrap.style.display = 'none';
}

async function renderResults(results) {
  const wrap = document.getElementById('results-wrap');
  wrap.innerHTML = `<h3 style="font-family:var(--font-head);font-size:18px;margin-bottom:16px">
    Classification Results</h3>`;

  results.forEach((result) => {
    const item = document.createElement('div');
    item.className = 'result-item';
    if (result.error) {
      item.innerHTML = `
        <div class="result-info">
          <div class="result-name">${result.filename}</div>
          <div class="result-scene" style="color:var(--danger)">Error: ${result.error}</div>
        </div>
      `;
      wrap.appendChild(item);
      return;
    }

    item.innerHTML = `
      <img class="result-img" data-photo-id="${result.id}" alt="${result.scene}"/>
      <div class="result-info">
        <div class="result-name">${result.original_filename || result.filename}</div>
        <div class="result-scene">Scene detected: ${result.scene}</div>
      </div>
      <span class="badge badge-purple">${result.scene}</span>
    `;
    wrap.appendChild(item);
  });

  await hydrateProtectedImages(wrap);
}
