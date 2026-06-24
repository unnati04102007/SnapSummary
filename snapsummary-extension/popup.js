// popup.js - SnapSummary Extension Logic

const API = 'http://localhost:5000';

// ── State ─────────────────────────────────────────────
let selectedLang  = 'en';
let selectedMode  = 'brief';
let currentUrl    = '';
let currentTitle   = '';
let currentResult  = null;
let userGroqKey    = '';

// Load userGroqKey on popup load
chrome.storage.local.get(['userGroqKey'], (res) => {
  if (res.userGroqKey) {
    userGroqKey = res.userGroqKey;
    const input = document.getElementById('groq-key-input');
    if (input) input.value = userGroqKey;
  }
});

// ── DOM refs ──────────────────────────────────────────
const screens = {
  main:     document.getElementById('screen-main'),
  loading:  document.getElementById('screen-loading'),
  result:   document.getElementById('screen-result'),
  history:  document.getElementById('screen-history'),
  settings: document.getElementById('screen-settings'),
};

function showScreen(name) {
  Object.keys(screens).forEach(key => {
    if (screens[key]) {
      screens[key].classList.remove('active');
    }
  });
  if (screens[name]) {
    screens[name].classList.add('active');
  }
}

// ── Toast ─────────────────────────────────────────────
function showToast(msg, duration = 2000) {
  const t = document.getElementById('toast');
  if (t) {
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), duration);
  }
}

// ── Detect YouTube URL ────────────────────────────────
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs[0];
  const url = tab?.url || '';
  const title = tab?.title || '';

  const urlBar  = document.getElementById('url-bar');
  const urlText = document.getElementById('url-text');

  if (url.includes('youtube.com/watch') || url.includes('youtu.be/') || url.includes('youtube.com/shorts/')) {
    currentUrl   = url;
    currentTitle = title.replace(' - YouTube', '').trim();
    if (urlText) urlText.textContent = currentTitle;
    if (urlBar) urlBar.classList.remove('no-yt');
  } else {
    if (urlText) urlText.textContent = 'Open a YouTube video first';
    if (urlBar) urlBar.classList.add('no-yt');
    
    const summarizeBtn = document.getElementById('btn-summarize');
    const audioBtn = document.getElementById('btn-audio-overview');
    const videoBtn = document.getElementById('btn-video-overview');
    
    if (summarizeBtn) summarizeBtn.disabled = true;
    if (audioBtn) audioBtn.disabled = true;
    if (videoBtn) videoBtn.disabled = true;
  }
});

// ── Language toggle ───────────────────────────────────
document.querySelectorAll('[data-lang]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-lang]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedLang = btn.dataset.lang;
  });
});

// Mode toggle
document.querySelectorAll('[data-mode]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedMode = btn.dataset.mode;
  });
});

// ── Loading steps helper ──────────────────────────────
function setStep(active) {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`step-${i}`);
    if (el) {
      el.classList.remove('active', 'done');
      if (i < active)  el.classList.add('done');
      if (i === active) el.classList.add('active');
    }
  }
}

// ── Show Result ───────────────────────────────────────
function showResult(data, lang, mode) {
  currentResult = data;

  const resultTitleEl = document.getElementById('result-title');
  const langTagEl = document.getElementById('result-lang-tag');
  const modeTagEl = document.getElementById('result-mode-tag');

  if (resultTitleEl) resultTitleEl.textContent = data.title || currentTitle;
  if (langTagEl) langTagEl.textContent = lang === 'en' ? 'English' : lang === 'hi' ? 'Hindi' : 'Hinglish';
  if (modeTagEl) modeTagEl.textContent = mode === 'brief' ? 'Brief' : 'Detailed';

  // Paragraph
  const paraEl = document.getElementById('result-paragraph');
  if (paraEl) paraEl.textContent = data.paragraph || '';

  // Key points
  const pointsEl = document.getElementById('result-points');
  if (pointsEl) {
    pointsEl.innerHTML = '';
    (data.points || []).forEach(pt => {
      const card = document.createElement('div');
      card.className = 'point-card';
      card.textContent = pt;
      pointsEl.appendChild(card);
    });
  }

  // Takeaway
  const takeawayEl = document.getElementById('result-takeaway');
  if (takeawayEl) takeawayEl.textContent = data.takeaway || '';

  // Audio player reset
  const container = document.getElementById('audio-player-container');
  const player    = document.getElementById('audio-player');
  if (container) container.style.display = 'none';
  if (player)    player.src = '';

  saveHistory({
    title:  data.title || currentTitle,
    url:    currentUrl,
    lang:   lang,
    mode:   mode,
    result: data,
    time:   Date.now(),
  });

  showScreen('result');
}

// Enable secondary buttons on main screen after popup loads (in case they were disabled)
const mainAudioBtn = document.getElementById('btn-audio-overview');
const mainVideoBtn = document.getElementById('btn-video-overview');
if (mainAudioBtn) mainAudioBtn.disabled = false;
if (mainVideoBtn) mainVideoBtn.disabled = false;

// ── API call: Summarize ───────────────────────────────
document.getElementById('btn-summarize').addEventListener('click', async () => {
  if (!currentUrl) return;

  showScreen('loading');
  document.getElementById('loading-title').textContent = 'Generating summary...';
  document.getElementById('loading-sub').textContent   = 'Downloading and transcribing...';
  setStep(1);

  try {
    setStep(1);
    await delay(500);
    setStep(2);

    const res = await fetch(`${API}/summarize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url:  currentUrl,
        lang: selectedLang,
        mode: selectedMode,
        groq_key: userGroqKey,
      })
    });

    setStep(3);
    const data = await res.json();

    if (!res.ok) throw new Error(data.error || 'Server error');

    setStep(4);
    await delay(400);

    showResult(data, selectedLang, selectedMode);

  } catch (err) {
    showScreen('main');
    showToast(`Error: ${err.message}`, 3000);
  }
});

// ── Audio Overview button (main screen) ──
document.getElementById('btn-audio-overview').addEventListener('click', async () => {
  if (!currentUrl) return;

  showScreen('loading');
  document.getElementById('loading-title').textContent = 'Creating audio overview...';
  document.getElementById('loading-sub').textContent   = 'Generating script and voice...';
  setStep(1);

  try {
    setStep(2);
    const res = await fetch(`${API}/audio-overview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        url: currentUrl, 
        lang: selectedLang, 
        mode: selectedMode, 
        groq_key: userGroqKey 
      })
    });

    setStep(3);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');
    setStep(4);
    await delay(300);

    // Audio player settings
    const container = document.getElementById('audio-player-container');
    const player    = document.getElementById('audio-player');
    if (container) container.style.display = 'block';
    if (player) {
      player.src = `${API}/stream?file=${encodeURIComponent(data.audio_file)}`;
      player.load();
      player.play().catch(e => console.log('Autoplay blocked:', e));
    }

    // Auto-download MP3 overview
    downloadFile(`${API}/download?file=${data.audio_file}`, `audio_overview_${Date.now()}.mp3`);
    
    if (currentResult) {
      showResult(currentResult, selectedLang, selectedMode);
    } else {
      showScreen('main');
    }
    showToast('Audio ready & downloading! 🎧');

  } catch (err) {
    showScreen('main');
    showToast(`Error: ${err.message}`, 3000);
  }
});

// ── Video Overview button (main screen) ──
document.getElementById('btn-video-overview').addEventListener('click', async () => {
  if (!currentUrl) return;

  showScreen('loading');
  document.getElementById('loading-title').textContent = 'Creating video overview...';
  document.getElementById('loading-sub').textContent   = 'Building slides and voiceover...';

  setStep(1);
  const stepInterval = setInterval(() => {
    const cur = parseInt(document.querySelector('.step-item.active')?.id?.split('-')[1] || '1');
    if (cur < 3) setStep(cur + 1);
  }, 8000);

  try {
    const res = await fetch(`${API}/video-overview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        url: currentUrl, 
        lang: selectedLang, 
        mode: selectedMode, 
        groq_key: userGroqKey 
      })
    });

    clearInterval(stepInterval);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');
    setStep(4);
    await delay(300);

    // Open video in a new tab
    const videoUrl = `${API}/stream?file=${encodeURIComponent(data.video_file)}`;
    chrome.tabs.create({ url: videoUrl });

    // Auto-download MP4 video
    downloadFile(`${API}/download?file=${data.video_file}`, `video_overview_${Date.now()}.mp4`);

    showScreen('main');
    showToast('Video ready & opening! 🎬');

  } catch (err) {
    clearInterval(stepInterval);
    showScreen('main');
    showToast(`Error: ${err.message}`, 3000);
  }
});

// ── Result screen Audio button ──
document.getElementById('btn-dl-audio').addEventListener('click', async () => {
  if (!currentUrl) return;

  const btn = document.getElementById('btn-dl-audio');
  btn.disabled = true;
  btn.textContent = '...';

  try {
    const res = await fetch(`${API}/audio-overview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        url: currentUrl, 
        lang: selectedLang, 
        mode: selectedMode, 
        groq_key: userGroqKey 
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');

    // Show/Play audio
    const container = document.getElementById('audio-player-container');
    const player    = document.getElementById('audio-player');
    if (container) container.style.display = 'block';
    if (player) {
      player.src = `${API}/stream?file=${encodeURIComponent(data.audio_file)}`;
      player.load();
      player.play().catch(e => console.log('Autoplay blocked:', e));
    }
    showToast('Audio ready! 🎧');

  } catch(e) {
    showToast('Failed: ' + e.message);
  }

  btn.disabled = false;
  btn.innerHTML = `<svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 18v-6a9 9 0 0118 0v6"/><path d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3z"/></svg>Audio`;
});

// ── Result screen Video button ──
document.getElementById('btn-dl-video').addEventListener('click', async () => {
  if (!currentUrl) return;

  const btn = document.getElementById('btn-dl-video');
  btn.disabled = true;
  btn.textContent = 'Building...';

  try {
    const res = await fetch(`${API}/video-overview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        url: currentUrl, 
        lang: selectedLang, 
        mode: selectedMode, 
        groq_key: userGroqKey 
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');

    // New tab video stream
    const videoUrl = `${API}/stream?file=${encodeURIComponent(data.video_file)}`;
    chrome.tabs.create({ url: videoUrl });
    showToast('Video opening! 🎬');

  } catch(e) {
    showToast('Failed: ' + e.message);
  }

  btn.disabled = false;
  btn.innerHTML = `<svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>Video`;
});

// Save result text summary
document.getElementById('btn-dl-txt').addEventListener('click', () => {
  if (!currentResult) return;
  const content = `${currentResult.title || currentTitle}\n\nKEY POINTS:\n${(currentResult.points||[]).map(p=>`• ${p}`).join('\n')}\n\nTAKEAWAY:\n${currentResult.takeaway||''}`;
  const blob = new Blob([content], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = 'summary.txt';
  a.click();
  showToast('Saved!');
});

// Copy summary to clipboard
document.getElementById('btn-copy').addEventListener('click', () => {
  if (!currentResult) return;
  const text = `${currentResult.title || ''}\n\n${(currentResult.points||[]).map(p=>`• ${p}`).join('\n')}\n\n${currentResult.takeaway||''}`;
  navigator.clipboard.writeText(text).then(() => showToast('Copied!'));
});

// ── Navigation ────────────────────────────────────────
document.getElementById('btn-back-result').addEventListener('click',  () => showScreen('main'));
document.getElementById('btn-back-history').addEventListener('click', () => showScreen('main'));
document.getElementById('btn-history').addEventListener('click', () => {
  const s = document.getElementById('history-search');
  if (s) s.value = '';
  loadHistory();
  showScreen('history');
});
document.getElementById('btn-settings').addEventListener('click', () => {
  const status = document.getElementById('key-status');
  if (status) status.textContent = '';
  showScreen('settings');
});
document.getElementById('btn-back-settings').addEventListener('click', () => showScreen('main'));

// Save API key
document.getElementById('btn-save-key').addEventListener('click', () => {
  const input = document.getElementById('groq-key-input');
  const status = document.getElementById('key-status');
  const key = input ? input.value.trim() : '';
  
  if (key && !key.startsWith('gsk_')) {
    if (status) {
      status.style.color = '#EF4444';
      status.textContent = 'Error: Invalid key format. Must start with "gsk_".';
    }
    return;
  }
  
  chrome.storage.local.set({ userGroqKey: key }, () => {
    userGroqKey = key;
    if (status) {
      status.style.color = '#00D4FF';
      status.textContent = key ? 'Key saved successfully!' : 'Key cleared. Using default key.';
    }
    setTimeout(() => {
      if (status) status.textContent = '';
      showScreen('main');
    }, 800);
  });
});

// ── History Search ────────────────────────────────────
const searchInput = document.getElementById('history-search');
if (searchInput) {
  searchInput.addEventListener('input', (e) => loadHistory(e.target.value));
}

// ── History ───────────────────────────────────────────
function saveHistory(item) {
  chrome.storage.local.get(['history'], (res) => {
    const history = res.history || [];
    // Avoid duplicates in history based on URL + lang + mode
    const duplicateIdx = history.findIndex(h => h.url === item.url && h.lang === item.lang && h.mode === item.mode);
    if (duplicateIdx !== -1) {
      history.splice(duplicateIdx, 1);
    }
    history.unshift(item);
    chrome.storage.local.set({ history: history.slice(0, 50) });
  });
}

function loadHistory(filter = '') {
  const list = document.getElementById('history-list');
  if (list) list.innerHTML = '<div class="history-empty">Loading...</div>';

  chrome.storage.local.get(['history'], (res) => {
    let history = res.history || [];

    if (filter.trim()) {
      const q = filter.trim().toLowerCase();
      history = history.filter(item =>
        (item.title || '').toLowerCase().includes(q) ||
        (item.result?.paragraph || '').toLowerCase().includes(q) ||
        (item.result?.takeaway  || '').toLowerCase().includes(q)
      );
    }

    const countEl = document.getElementById('history-count');
    if (countEl) {
      countEl.textContent = `${history.length} item${history.length !== 1 ? 's' : ''}`;
    }

    if (!history.length) {
      if (list) {
        list.innerHTML = filter
          ? '<div class="history-empty">No results found</div>'
          : '<div class="history-empty">No history yet. Summarize a video first!</div>';
      }
      return;
    }

    if (list) {
      list.innerHTML = '';
      history.forEach((item, idx) => {
        const div = document.createElement('div');
        div.className = 'history-item';
        const timeStr = formatTime(item.time);
        const langStr = item.lang === 'en' ? 'English' :
                        item.lang === 'hi' ? 'Hindi' : 'Hinglish';
        const modeStr = item.mode === 'brief' ? 'Brief' : 'Detailed';
        const preview = item.result?.takeaway ||
                        item.result?.paragraph?.slice(0, 80) || '';

        div.innerHTML = `
          <div class="history-info">
            <div class="history-name">${item.title || 'Untitled'}</div>
            <div class="history-meta">${langStr} · ${modeStr} · ${timeStr}</div>
            ${preview ? `<div style="font-size:10px;color:rgba(255,255,255,0.4);margin-top:3px;
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
              max-width:220px;">${preview}</div>` : ''}
          </div>
          <button class="del-btn" data-idx="${idx}" title="Delete">
            <svg fill="none" viewBox="0 0 24 24" width="13" height="13">
              <path stroke="currentColor" stroke-width="2.5" d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>
            </svg>
          </button>`;

        div.addEventListener('click', (e) => {
          if (e.target.closest('.del-btn')) return;
          currentResult = item.result;
          currentUrl    = item.url;
          currentTitle  = item.title;
          selectedLang  = item.lang;
          selectedMode  = item.mode;
          showResult(item.result, item.lang, item.mode);
        });
        list.appendChild(div);
      });

      list.querySelectorAll('.del-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          chrome.storage.local.get(['history'], (res2) => {
            const full = res2.history || [];
            const clicked = history[parseInt(btn.dataset.idx)];
            const realIdx = full.findIndex(h => h.time === clicked.time);
            if (realIdx !== -1) {
              full.splice(realIdx, 1);
              chrome.storage.local.set({ history: full }, () => {
                showToast('Deleted!');
                loadHistory(document.getElementById('history-search')?.value || '');
              });
            }
          });
        });
      });
    }
  });
}

// ── Clear all history ─────────────────────────────────
document.getElementById('btn-clear-all').addEventListener('click', () => {
  if (confirm('Clear all history?')) {
    chrome.storage.local.set({ history: [] }, () => loadHistory());
  }
});

// ── Helpers ───────────────────────────────────────────
function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

function formatTime(ts) {
  const diff = Date.now() - ts;
  if (diff < 60000)  return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff/60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff/3600000)}h ago`;
  return `${Math.floor(diff/86400000)}d ago`;
}

function downloadFile(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
}