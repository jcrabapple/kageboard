// Kageboard options page script

const DEFAULT_SERVER = 'http://127.0.0.1:5000';
const serverInput = document.getElementById('server-url');
const saveBtn = document.getElementById('save-btn');
const status = document.getElementById('status');

// Load current settings
chrome.storage.sync.get(['server_url'], (data) => {
  serverInput.value = data.server_url || DEFAULT_SERVER;
});

// Save
saveBtn.addEventListener('click', () => {
  const url = serverInput.value.trim() || DEFAULT_SERVER;

  // Basic validation
  try {
    new URL(url);
  } catch (_) {
    showStatus('error', 'Invalid URL');
    return;
  }

  chrome.storage.sync.set({ server_url: url }, () => {
    if (chrome.runtime.lastError) {
      showStatus('error', chrome.runtime.lastError.message);
      return;
    }
    showStatus('success', 'Saved!');

    // Test connection
    fetch(`${url}/api/jobs`)
      .then(r => r.json())
      .then(() => showStatus('success', 'Saved — connected to Kageboard ✓'))
      .catch(() => showStatus('success', 'Saved — but could not reach Kageboard. Is it running?'));
  });
});

function showStatus(kind, msg) {
  status.className = `status show ${kind}`;
  status.textContent = msg;
  setTimeout(() => { status.className = 'status'; }, 4000);
}