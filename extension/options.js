// Kageboard options page script — server URL + credentials config

const DEFAULT_SERVER = 'http://127.0.0.1:5000';
const serverInput = document.getElementById('server-url');
const usernameInput = document.getElementById('auth-username');
const passwordInput = document.getElementById('auth-password');
const saveBtn = document.getElementById('save-btn');
const testBtn = document.getElementById('test-btn');
const status = document.getElementById('status');

// Load current settings
async function loadSettings() {
  try {
    const data = await chrome.runtime.sendMessage({ action: 'get-credentials' });
    serverInput.value = (await chrome.storage.sync.get(['server_url'])).server_url || DEFAULT_SERVER;
    usernameInput.value = data.username || '';
    passwordInput.value = data.password || '';
  } catch (_) {
    serverInput.value = DEFAULT_SERVER;
  }
}

// Save
saveBtn.addEventListener('click', async () => {
  const url = serverInput.value.trim() || DEFAULT_SERVER;
  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  try {
    new URL(url);
  } catch (_) {
    showStatus('error', 'Invalid server URL');
    return;
  }

  // Server URL is not sensitive — sync is fine. Credentials use storage.local.
  await chrome.storage.sync.set({ server_url: url });

  try {
    await chrome.runtime.sendMessage({
      action: 'save-credentials',
      username: username || 'kageboard',
      password,
    });
  } catch (e) {
    showStatus('error', 'Failed to save credentials');
    return;
  }

  showStatus('success', 'Saved!');
});

// Test connection
testBtn.addEventListener('click', async () => {
  showStatus('info', 'Testing…');

  // Save first
  const url = serverInput.value.trim() || DEFAULT_SERVER;
  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  await chrome.storage.sync.set({ server_url: url });
  await chrome.runtime.sendMessage({
    action: 'save-credentials',
    username: username || 'kageboard',
    password,
  });

  try {
    const result = await chrome.runtime.sendMessage({ action: 'check-auth' });
    if (result.authenticated) {
      showStatus('success', 'Connected and authenticated ✓');
    } else {
      showStatus('error', 'Connected but authentication failed. Check username and password.');
    }
  } catch (e) {
    showStatus('error', 'Could not reach Kageboard. Is it running?');
  }
});

function showStatus(kind, msg) {
  status.className = `status show ${kind}`;
  status.textContent = msg;
  if (kind === 'success') {
    setTimeout(() => { status.className = 'status'; }, 4000);
  }
}

loadSettings();