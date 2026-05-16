/* ===== STATE ===== */
const state = {
  currentStep: 1,
  board: '',
  classNum: '',
  subject: '',
  examType: '',
  totalMarks: 80,
  duration: '3 Hours',
  difficulty: 'mixed',
  teacherName: '',
  schoolName: '',
  schoolLogoDataUrl: '',
  examDate: '',
  syllabusVersion: 'new',
  selectedChapters: [],
  selectedGrammarTopics: [],
  chapterImages: [],
  questionTypes: {},
  questionPaper: null,
  paperId: null,
  answerSheetFile: null,
  currentUser: null,
};

/* ===== NETWORK RETRY UTILITY ===== */
/**
 * Wraps fetch() with automatic retry on network failures (e.g. cold-start after
 * deployment). Only retries on connection errors — HTTP error responses (4xx, 5xx)
 * are returned immediately without retrying.
 *
 * @param {string}   url
 * @param {object}   options    — standard fetch options
 * @param {number}   maxRetries — total attempts (default 3)
 * @param {number}   delay      — ms between attempts, linear (default 1500)
 * @param {function} onRetry    — optional callback(attemptNumber) called before each retry
 */
async function _fetchWithRetry(url, options = {}, maxRetries = 3, delay = 1500, onRetry = null) {
  let lastErr;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await fetch(url, options);  // success or HTTP error → return as-is
    } catch (err) {
      lastErr = err;                     // only TypeError (network failure) reaches here
      if (attempt < maxRetries - 1) {
        if (onRetry) onRetry(attempt + 1, maxRetries);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }
  throw lastErr;
}

/* ===== INIT ===== */
document.addEventListener('DOMContentLoaded', async () => {
  // Auth gate — check login state first, then decide what to show
  // Use retry so a cold-start after deployment doesn't strand the user.
  let user = null;
  try {
    const res = await _fetchWithRetry('/api/user', {}, 3, 1500);
    user = await res.json();
  } catch (e) {
    user = { logged_in: false };
  }

  if (!user.logged_in) {
    // Show landing page, hide app
    document.getElementById('landing-page').style.display = 'block';
    document.getElementById('app-content').style.display = 'none';
    document.getElementById('site-header').style.display = 'block';
    // Keep login button visible, hide app-specific header items
    document.getElementById('history-btn').style.display = 'none';
    document.getElementById('usage-badge').style.display = 'none';
    document.getElementById('upgrade-btn').style.display = 'none';

    // Show Google OAuth section in modal if available
    if (user.oauth_available) {
      const sec = document.getElementById('auth-google-section');
      if (sec) sec.style.display = 'block';
    }
    return; // stop app init
  }

  // Logged in — show app, hide landing
  document.getElementById('landing-page').style.display = 'none';
  document.getElementById('app-content').style.display = 'block';
  document.getElementById('history-btn').style.display = 'inline-flex';

  state.currentUser = user;

  // Update auth area header
  updateAuthHeader(user);
  // Update usage badge
  updateUsageBadge(user);

  // Init app
  loadBoards();
  updateMarksTotal();
  loadUserProfile();   // pre-fill teacher name, school name, and logo from saved profile

  document.getElementById('board').addEventListener('change', onBoardChange);
  document.getElementById('class_num').addEventListener('change', onClassChange);
  document.getElementById('subject').addEventListener('change', onSubjectChange);

  // Hide "saved" badge once user manually edits the field
  document.getElementById('teacher_name').addEventListener('input', () => {
    const b = document.getElementById('teacher-saved-badge');
    if (b) b.style.display = 'none';
  });
  document.getElementById('school_name').addEventListener('input', () => {
    const b = document.getElementById('school-name-saved-badge');
    if (b) b.style.display = 'none';
  });

  // Close profile menu when clicking outside
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('profile-menu');
    const chip = document.getElementById('profile-chip');
    if (menu && chip && !menu.contains(e.target) && !chip.contains(e.target)) {
      menu.style.display = 'none';
    }
  });
});

/* ===== AUTH MODAL ===== */
function openAuthModal(tab = 'login') {
  document.getElementById('auth-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
  switchAuthTab(tab);
  // Clear previous errors
  document.getElementById('login-error').style.display = 'none';
  document.getElementById('register-error').style.display = 'none';
}

function closeAuthModal() {
  document.getElementById('auth-modal').style.display = 'none';
  document.body.style.overflow = '';
}

function handleAuthModalOverlayClick(event) {
  if (event.target === document.getElementById('auth-modal')) {
    closeAuthModal();
  }
}

function switchAuthTab(tab) {
  document.getElementById('login-form').style.display = tab === 'login' ? 'block' : 'none';
  document.getElementById('register-form').style.display = tab === 'register' ? 'block' : 'none';
  document.getElementById('tab-login').classList.toggle('active', tab === 'login');
  document.getElementById('tab-register').classList.toggle('active', tab === 'register');
}

async function handleLogin(event) {
  event.preventDefault();
  const btn   = document.getElementById('login-submit-btn');
  const errEl = document.getElementById('login-error');
  btn.disabled = true;
  btn.textContent = 'Signing in...';
  errEl.style.display = 'none';
  try {
    const res = await _fetchWithRetry(
      '/auth/login',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email:    document.getElementById('login-email').value.trim(),
          password: document.getElementById('login-password').value,
        }),
      },
      3, 1500,
      (attempt, total) => { btn.textContent = `Connecting… (${attempt}/${total})`; }
    );
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error;
      errEl.style.display = 'block';
    } else {
      btn.textContent = 'Signing in…';
      window.location.reload();
    }
  } catch (e) {
    errEl.textContent = 'Unable to reach the server. Please check your connection and try again.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sign In';
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const password = document.getElementById('reg-password').value;
  const confirm = document.getElementById('reg-confirm').value;
  const errEl = document.getElementById('register-error');
  if (password !== confirm) {
    errEl.textContent = 'Passwords do not match.';
    errEl.style.display = 'block';
    return;
  }
  const btn = document.getElementById('reg-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Creating account...';
  errEl.style.display = 'none';
  try {
    const res = await _fetchWithRetry(
      '/auth/register',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name:     document.getElementById('reg-name').value.trim(),
          email:    document.getElementById('reg-email').value.trim(),
          password,
        }),
      },
      3, 1500,
      (attempt, total) => { btn.textContent = `Connecting… (${attempt}/${total})`; }
    );
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error;
      errEl.style.display = 'block';
    } else {
      window.location.reload();
    }
  } catch (e) {
    errEl.textContent = 'Unable to reach the server. Please check your connection and try again.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Free Account';
  }
}

/* ===== AUTH HEADER ===== */
function updateAuthHeader(data) {
  const loginBtn = document.getElementById('login-btn');
  const profileChip = document.getElementById('profile-chip');

  if (data.logged_in) {
    loginBtn.style.display = 'none';
    profileChip.style.display = 'flex';
    document.getElementById('profile-name').textContent = data.name || data.email;
    document.getElementById('profile-email').textContent = data.email || '';
    if (data.picture) {
      document.getElementById('profile-pic').src = data.picture;
    } else {
      document.getElementById('profile-pic').style.display = 'none';
    }
  } else {
    loginBtn.style.display = 'flex';
    profileChip.style.display = 'none';
  }
}

/* ===== USAGE BADGE ===== */
function updateUsageBadge(user) {
  const badge = document.getElementById('usage-badge');
  const upgradeBtn = document.getElementById('upgrade-btn');
  if (!badge) return;

  const plan = user.plan || 'free';
  const usage = user.usage || { papers: 0, evals: 0 };
  const planInfo = user.plan_info || { papers_per_month: 3, evals_per_month: 5 };

  if (plan === 'free') {
    const paperLimit = planInfo.papers_per_month || 3;
    const papersUsed = usage.papers || 0;
    const pct = paperLimit > 0 ? (papersUsed / paperLimit) * 100 : 0;

    let colorClass = 'badge-green';
    if (pct >= 100) colorClass = 'badge-red';
    else if (pct >= 80) colorClass = 'badge-orange';

    badge.textContent = `${papersUsed}/${paperLimit} papers`;
    badge.className = `usage-badge ${colorClass}`;
    badge.style.display = 'inline-flex';

    if (upgradeBtn) upgradeBtn.style.display = 'inline-flex';
  } else {
    const planLabel = plan.charAt(0).toUpperCase() + plan.slice(1);
    badge.textContent = `${planLabel} ✓`;
    badge.className = 'usage-badge badge-pro';
    badge.style.display = 'inline-flex';
    if (upgradeBtn) upgradeBtn.style.display = 'none';
  }
}

/* ===== AUTH / LOGIN STATE (kept for compatibility) ===== */
async function checkLoginState() {
  try {
    const res  = await _fetchWithRetry('/api/user', {}, 3, 1500);
    const data = await res.json();
    updateAuthHeader(data);
    if (data.logged_in) updateUsageBadge(data);
  } catch (e) {
    // Auth optional — fail silently
  }
}

function toggleProfileMenu() {
  const menu = document.getElementById('profile-menu');
  menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
}

/* ===== API KEY SETTINGS ===== */
function openApiKeySettings() {
  const modal = document.getElementById('api-key-modal');
  if (!modal) return;
  // Reset state
  document.getElementById('api-key-input').value = '';
  document.getElementById('api-key-msg').style.display = 'none';
  // Show whether a key is already saved (we know this from loadUserProfile)
  const hasKey = window._profileHasApiKey || false;
  const cur = document.getElementById('api-key-current');
  if (cur) cur.style.display = hasKey ? 'block' : 'none';
  modal.style.display = 'flex';
}

function closeApiKeySettings() {
  const modal = document.getElementById('api-key-modal');
  if (modal) modal.style.display = 'none';
}

async function saveApiKeySettings() {
  const input = document.getElementById('api-key-input');
  const btn   = document.getElementById('api-key-save-btn');
  const msg   = document.getElementById('api-key-msg');
  const key   = (input.value || '').trim();
  if (!key) { showToast('Please enter an API key first.', 'error'); return; }

  btn.disabled = true; btn.textContent = '⏳ Testing…';
  msg.style.display = 'none';
  try {
    const res  = await fetch('/api/settings/api-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    if (data.warning) {
      msg.textContent = '⚠ ' + data.warning;
      msg.style.color = 'var(--warning, #b45309)';
      msg.style.display = 'block';
    } else {
      window._profileHasApiKey = true;
      showToast('API key saved and verified!', 'success');
      closeApiKeySettings();
    }
  } catch (e) {
    msg.textContent = '✗ ' + (e.message || 'Failed to save');
    msg.style.color = 'var(--error, #dc2626)';
    msg.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Save & Test';
  }
}

async function clearApiKeySettings() {
  if (!confirm('Remove your saved API key? The shared server key will be used instead.')) return;
  try {
    await fetch('/api/settings/api-key', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: '' }),
    });
    window._profileHasApiKey = false;
    showToast('API key removed.', 'success');
    closeApiKeySettings();
  } catch (e) {
    showToast('Failed to remove key: ' + e.message, 'error');
  }
}

/* ===== UPGRADE MODAL ===== */
function openUpgradeModal(tab) {
  document.getElementById('upgrade-modal').style.display = 'flex';
  document.body.style.overflow = 'hidden';
  switchUpgradeTab(tab || 'pricing');
}

function closeUpgradeModal() {
  document.getElementById('upgrade-modal').style.display = 'none';
  document.body.style.overflow = '';
}

function handleUpgradeModalOverlayClick(event) {
  if (event.target === document.getElementById('upgrade-modal')) closeUpgradeModal();
}

function switchUpgradeTab(tab) {
  ['pricing', 'contact', 'callback'].forEach(t => {
    document.getElementById(`utab-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`upanel-${t}`).style.display = t === tab ? 'block' : 'none';
  });
}

async function submitContactForm(event, type) {
  event.preventDefault();
  const isContact = type === 'contact';
  const errEl = document.getElementById(isContact ? 'contact-form-error' : 'callback-form-error');
  const succEl = document.getElementById(isContact ? 'contact-form-success' : 'callback-form-success');
  const btn = document.getElementById(isContact ? 'contact-submit-btn' : 'callback-submit-btn');
  errEl.style.display = 'none';
  succEl.style.display = 'none';

  const payload = { request_type: type };
  if (isContact) {
    payload.name        = document.getElementById('cf-name').value.trim();
    payload.school_name = document.getElementById('cf-school').value.trim();
    payload.email       = document.getElementById('cf-email').value.trim();
    payload.mobile      = document.getElementById('cf-mobile').value.trim();
    payload.message     = document.getElementById('cf-message').value.trim();
  } else {
    payload.name    = document.getElementById('cb-name').value.trim();
    payload.email   = document.getElementById('cb-email').value.trim();
    payload.mobile  = document.getElementById('cb-mobile').value.trim();
    payload.message = '';
  }

  btn.disabled = true;
  btn.textContent = 'Sending...';
  try {
    const res = await fetch('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error;
      errEl.style.display = 'block';
    } else {
      const msg = type === 'callback'
        ? '✓ Callback request received! Our support team will contact you within 48 hours during business hours (Mon–Sat, 9 AM–6 PM IST).'
        : '✓ Message sent! We’ll get back to you soon.';
      succEl.textContent = msg;
      succEl.style.display = 'block';
      document.getElementById(isContact ? 'contact-form' : 'callback-form').reset();
    }
  } catch (e) {
    errEl.textContent = 'Network error. Please try again.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = isContact ? '✉ Send Message' : '☎ Request Callback';
  }
}

/* ===== BOARDS ===== */
async function loadBoards() {
  try {
    const res = await fetch('/api/boards');
    const data = await res.json();
    const sel = document.getElementById('board');
    data.boards.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b;
      opt.textContent = b;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.error('Failed to load boards:', e);
  }
}

/* ===== CLASS / SUBJECT ===== */
function onBoardChange() {
  state.board = document.getElementById('board').value;
  onClassChange();
  // Refresh question types if a subject is already picked
  const sub = document.getElementById('subject').value;
  if (sub) loadQuestionTypes(sub);
}

async function onClassChange() {
  const classNum = document.getElementById('class_num').value;
  state.classNum = classNum;
  const board    = state.board || document.getElementById('board').value || '';
  const subjSel  = document.getElementById('subject');
  console.log('[ExamCraft] onClassChange board=' + board + ' class=' + classNum);

  subjSel.innerHTML = '<option value="">Loading...</option>';
  subjSel.disabled = true;

  if (!classNum) {
    subjSel.innerHTML = '<option value="">Select Class first...</option>';
    return;
  }

  try {
    const res = await fetch('/api/subjects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ class_num: classNum, board })
    });
    const data = await res.json();
    console.log('[ExamCraft] subjects received:', data.subjects);

    subjSel.innerHTML = '<option value="">Select Subject...</option>';
    data.subjects.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      subjSel.appendChild(opt);
    });
    subjSel.disabled = false;

    // If a subject was already selected, refresh question types for the new class
    const currentSub = subjSel.value;
    if (currentSub) loadQuestionTypes(currentSub);
  } catch (e) {
    subjSel.innerHTML = '<option value="">Error loading subjects</option>';
    subjSel.disabled = false;
  }
}

async function onSubjectChange() {
  state.selectedChapters = [];
  updateChapterCount();
  const subject = document.getElementById('subject').value;
  if (subject) {
    await loadQuestionTypes(subject);
  }
}

/* ===== STEP NAVIGATION ===== */
function gotoStep(step) {
  if (step > state.currentStep && step !== state.currentStep + 1) return;

  document.querySelectorAll('.step-section').forEach(s => s.classList.remove('active'));
  document.getElementById(`section-${step}`).classList.add('active');

  document.querySelectorAll('.step').forEach((s, i) => {
    s.classList.remove('active', 'completed');
    if (i + 1 < step) s.classList.add('completed');
    else if (i + 1 === step) s.classList.add('active');
  });

  document.querySelectorAll('.step-line').forEach((l, i) => {
    l.classList.toggle('completed', i < step - 1);
  });

  state.currentStep = step;

  // When returning to step 3 (e.g. "← Regenerate"), restore the user's
  // last question-type configuration so the counts/marks are preserved.
  if (step === 3) _restoreQuestionTypeInputs();

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/**
 * Re-apply state.questionTypes back onto the rendered QT cards.
 * Called whenever we navigate (back) to step 3 after a paper has been generated.
 * If state.questionTypes is empty (first visit) this is a no-op.
 */
function _restoreQuestionTypeInputs() {
  const qt = state.questionTypes;
  if (!qt || Object.keys(qt).length === 0) return;

  document.querySelectorAll('.qt-card[data-key]').forEach(card => {
    const key      = card.dataset.key;
    const enableEl = document.getElementById(`enable-${key}`);
    const inputsDiv= document.getElementById(`inputs-${key}`);
    if (!enableEl) return;

    const saved = qt[key];  // present only if that type was enabled last time
    if (saved) {
      // Re-enable the card
      enableEl.checked = true;
      card.classList.add('active');
      if (inputsDiv) {
        inputsDiv.classList.remove('disabled');
        inputsDiv.querySelectorAll('input').forEach(inp => inp.disabled = false);
      }
      // Restore count & marks
      const countEl = document.getElementById(`${key}-count`);
      const marksEl = document.getElementById(`${key}-marks`);
      if (countEl) countEl.value = saved.count;
      if (marksEl) marksEl.value = saved.marks;
    } else {
      // This type was not enabled last time — keep it unchecked
      enableEl.checked = false;
      card.classList.remove('active');
      if (inputsDiv) {
        inputsDiv.classList.add('disabled');
        inputsDiv.querySelectorAll('input').forEach(inp => inp.disabled = true);
      }
    }
  });

  updateMarksTotal();
}

/* ===== USER PROFILE (teacher name, school name, logo persistence) ===== */
// localStorage keys for offline / fallback storage
const _LS_TEACHER = 'ec_teacher_name';
const _LS_SCHOOL  = 'ec_school_name';
const _LS_LOGO    = 'ec_school_logo';
// Max logo size to store in localStorage (~400 KB data-URL ≈ 300 KB image)
const _LS_LOGO_MAX = 400 * 1024;

function _lsGet(key) { try { return localStorage.getItem(key) || ''; } catch { return ''; } }
function _lsSet(key, val) { try { if (val) localStorage.setItem(key, val); } catch {} }
function _lsDel(key) { try { localStorage.removeItem(key); } catch {} }

/** Apply profile data (teacher name, school name, logo) to the form fields and state. */
function _applyProfile(teacher, school, logo) {
  if (teacher) {
    state.teacherName = teacher;
    const inp = document.getElementById('teacher_name');
    if (inp && !inp.value.trim()) {
      inp.value = teacher;
      const badge = document.getElementById('teacher-saved-badge');
      if (badge) badge.style.display = 'inline-flex';
    }
  }
  if (school) {
    state.schoolName = school;
    const inp = document.getElementById('school_name');
    if (inp && !inp.value.trim()) {
      inp.value = school;
      const badge = document.getElementById('school-name-saved-badge');
      if (badge) badge.style.display = 'inline-flex';
    }
  }
  if (logo && !state.schoolLogoDataUrl) {
    state.schoolLogoDataUrl = logo;
    const img = document.getElementById('logo-preview-img');
    if (img) img.src = logo;
    const previewWrap = document.getElementById('logo-preview-wrap');
    if (previewWrap) previewWrap.style.display = 'block';
    const placeholder = document.getElementById('logo-upload-placeholder');
    if (placeholder) placeholder.style.display = 'none';
    const removeBtn = document.getElementById('logo-remove-btn');
    if (removeBtn) removeBtn.style.display = 'inline-flex';
    const savedNote = document.getElementById('logo-saved-note');
    if (savedNote) savedNote.style.display = 'block';
  }
}

async function loadUserProfile() {
  // 1. Load from localStorage immediately (instant, no network wait)
  const lsTeacher = _lsGet(_LS_TEACHER);
  const lsSchool  = _lsGet(_LS_SCHOOL);
  const lsLogo    = _lsGet(_LS_LOGO);
  if (lsTeacher || lsSchool || lsLogo) {
    _applyProfile(lsTeacher, lsSchool, lsLogo);
  }

  // 2. Then load from server (may override with fresher data)
  try {
    const res = await fetch('/api/user-profile');
    if (!res.ok) return;   // not authenticated — localStorage values are good enough
    const p = await res.json();
    const serverTeacher = p.teacher_name || '';
    const serverSchool  = p.school_name  || '';
    const serverLogo    = p.school_logo  || '';
    window._profileHasApiKey = !!p.has_api_key;

    // Server data wins; update localStorage cache so it stays fresh
    if (serverTeacher) _lsSet(_LS_TEACHER, serverTeacher);
    if (serverSchool)  _lsSet(_LS_SCHOOL,  serverSchool);
    if (serverLogo)    { if (serverLogo.length <= _LS_LOGO_MAX) _lsSet(_LS_LOGO, serverLogo); }

    // Apply server values (override the localStorage values if different)
    if (serverTeacher || serverSchool || serverLogo) {
      // Reset state so _applyProfile can overwrite with server data
      if (serverLogo) state.schoolLogoDataUrl = '';
      _applyProfile(serverTeacher, serverSchool, serverLogo);
    }
  } catch (e) {
    // Network failure — localStorage values already applied above
  }
}

async function saveUserProfile(teacherName, schoolName, schoolLogoDataUrl) {
  // Always persist non-empty values to localStorage immediately
  if (teacherName)       _lsSet(_LS_TEACHER, teacherName);
  if (schoolName)        _lsSet(_LS_SCHOOL,  schoolName);
  if (schoolLogoDataUrl && schoolLogoDataUrl.length <= _LS_LOGO_MAX)
    _lsSet(_LS_LOGO, schoolLogoDataUrl);

  // Build server payload — only send non-empty values to avoid overwriting
  // a previously-saved logo/name when the current state hasn't loaded it yet.
  const payload = {};
  if (teacherName)       payload.teacher_name = teacherName;
  if (schoolName)        payload.school_name  = schoolName;
  // Only send logo if we actually have one in state (prevents race-condition wipe)
  if (schoolLogoDataUrl) payload.school_logo  = schoolLogoDataUrl;

  if (Object.keys(payload).length === 0) return;  // nothing to save

  try {
    await fetch('/api/user-profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    // Silently ignore — localStorage already saved above
  }
}

/** Call this when the user explicitly removes the school logo. */
function clearSavedLogo() {
  _lsDel(_LS_LOGO);
  try {
    fetch('/api/user-profile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ school_logo: '' }),
    });
  } catch {}
}

/* ===== SCHOOL LOGO ===== */
function handleLogoUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    state.schoolLogoDataUrl = e.target.result;
    const img = document.getElementById('logo-preview-img');
    img.src = e.target.result;
    document.getElementById('logo-preview-wrap').style.display = 'block';
    document.getElementById('logo-upload-placeholder').style.display = 'none';
    document.getElementById('logo-remove-btn').style.display = 'inline-flex';
    // Hide "using saved logo" note — user uploaded a fresh one
    const savedNote = document.getElementById('logo-saved-note');
    if (savedNote) savedNote.style.display = 'none';
  };
  reader.readAsDataURL(file);
}

function removeLogo() {
  state.schoolLogoDataUrl = '';
  document.getElementById('school_logo').value = '';
  document.getElementById('logo-preview-img').src = '';
  document.getElementById('logo-preview-wrap').style.display = 'none';
  document.getElementById('logo-upload-placeholder').style.display = 'flex';
  document.getElementById('logo-remove-btn').style.display = 'none';
  const savedNote = document.getElementById('logo-saved-note');
  if (savedNote) savedNote.style.display = 'none';
  // Explicitly clear the saved logo from localStorage and server
  clearSavedLogo();
}

function goToStep2() {
  const board = document.getElementById('board').value;
  const classNum = document.getElementById('class_num').value;
  const subject = document.getElementById('subject').value;
  const totalMarks = document.getElementById('total_marks').value;

  if (!board) { showToast('Please select a board.', 'error'); return; }
  if (!classNum) { showToast('Please select a class.', 'error'); return; }
  if (!subject) { showToast('Please select a subject.', 'error'); return; }
  if (!totalMarks || totalMarks < 10) { showToast('Total marks must be at least 10.', 'error'); return; }

  state.board = board;
  state.classNum = classNum;
  state.subject = subject;
  state.totalMarks = parseInt(totalMarks);
  state.examType = document.getElementById('exam_type').value;
  state.duration = document.getElementById('duration').value;
  state.difficulty = document.getElementById('difficulty').value;
  state.teacherName = document.getElementById('teacher_name').value.trim();
  state.schoolName = document.getElementById('school_name').value.trim();
  state.examDate = (document.getElementById('exam_date').value || '').trim();

  document.getElementById('marks-target').textContent = state.totalMarks;
  updateMarksTotal();

  // Persist teacher name, school name, and logo to server (best-effort, non-blocking)
  saveUserProfile(state.teacherName, state.schoolName, state.schoolLogoDataUrl);

  // Reset syllabus version whenever subject/class changes
  state.syllabusVersion = 'new';
  const toggleWrap = document.getElementById('syllabus-toggle-wrap');
  if (toggleWrap) {
    toggleWrap.querySelectorAll('.syllabus-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.version === 'new');
    });
  }

  loadChapters();
  gotoStep(2);
}

function goToStep3() {
  if (state.selectedChapters.length === 0) {
    showToast('Please select at least one chapter.', 'error');
    return;
  }
  // Update subject hint
  const hint = document.getElementById('qt-subject-hint');
  if (hint) hint.textContent = `Question types for ${state.subject} — Class ${state.classNum}`;
  gotoStep(3);
}

/* ===== SYLLABUS VERSION TOGGLE ===== */
function switchSyllabusVersion(version) {
  state.syllabusVersion = version;
  state.selectedChapters = [];
  document.querySelectorAll('.syllabus-toggle-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.version === version);
  });
  loadChapters();
}

/* ===== CHAPTERS ===== */
async function loadChapters() {
  const container = document.getElementById('chapters-container');
  container.innerHTML = '<div class="loading-chapters">Loading chapters...</div>';

  try {
    const board = state.board || document.getElementById('board').value || '';
    const res = await fetch('/api/chapters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        class_num: state.classNum,
        subject: state.subject,
        board,
        syllabus_version: state.syllabusVersion || 'new'
      })
    });
    const data = await res.json();

    // Show/hide syllabus version toggle based on whether legacy exists
    const toggleWrap = document.getElementById('syllabus-toggle-wrap');
    if (toggleWrap) {
      if (data.has_legacy) {
        toggleWrap.style.display = 'flex';
        // Update active state
        toggleWrap.querySelectorAll('.syllabus-toggle-btn').forEach(btn => {
          btn.classList.toggle('active', btn.dataset.version === (state.syllabusVersion || 'new'));
        });
      } else {
        toggleWrap.style.display = 'none';
        state.syllabusVersion = 'new';
      }
    }

    container.innerHTML = '';
    // Reset grammar topics each time chapters are (re)loaded for a new subject/class
    state.selectedGrammarTopics = [];
    if (!data.chapters || data.chapters.length === 0) {
      container.innerHTML = '<div class="loading-chapters">No chapters found for this subject/class.</div>';
    } else {
      data.chapters.forEach((ch, idx) => {
        const item = document.createElement('div');
        item.className = 'chapter-item';
        item.dataset.chapter = ch;
        item.innerHTML = `
          <input type="checkbox" id="ch-${idx}" onchange="toggleChapter('${escapeAttr(ch)}', this.checked)" />
          <span>${escapeHtml(ch)}</span>
        `;
        item.addEventListener('click', (e) => {
          if (e.target.tagName !== 'INPUT') {
            const cb = item.querySelector('input');
            cb.checked = !cb.checked;
            toggleChapter(ch, cb.checked);
          }
        });
        container.appendChild(item);
      });
    }
    renderGrammarTopics(data.grammar_topics || []);
    await loadCustomChapters();
  } catch (e) {
    container.innerHTML = '<div class="loading-chapters">Error loading chapters. Please try again.</div>';
    renderGrammarTopics([]);
  }
}

/* ── Grammar Topics (English / Hindi) ── */
function renderGrammarTopics(topics) {
  const wrap = document.getElementById('grammar-topics-section');
  if (!wrap) return;
  if (!topics || topics.length === 0) {
    wrap.style.display = 'none';
    state.selectedGrammarTopics = [];
    updateChapterCount();
    return;
  }
  wrap.style.display = 'block';
  const container = document.getElementById('grammar-topics-container');
  container.innerHTML = '';
  // Re-apply any previously selected topics
  topics.forEach((topic, idx) => {
    const alreadySelected = state.selectedGrammarTopics.includes(topic);
    const item = document.createElement('div');
    item.className = 'chapter-item grammar-topic-item' + (alreadySelected ? ' selected' : '');
    item.dataset.grammarTopic = topic;
    item.innerHTML = `
      <input type="checkbox" id="gt-${idx}" ${alreadySelected ? 'checked' : ''}
             onchange="toggleGrammarTopic('${escapeAttr(topic)}', this.checked)" />
      <span>${escapeHtml(topic)}</span>
    `;
    item.addEventListener('click', (e) => {
      if (e.target.tagName !== 'INPUT') {
        const cb = item.querySelector('input');
        cb.checked = !cb.checked;
        toggleGrammarTopic(topic, cb.checked);
      }
    });
    container.appendChild(item);
  });
  updateChapterCount();
}

function toggleGrammarTopic(topic, checked) {
  if (checked) {
    if (!state.selectedGrammarTopics.includes(topic)) state.selectedGrammarTopics.push(topic);
  } else {
    state.selectedGrammarTopics = state.selectedGrammarTopics.filter(t => t !== topic);
  }
  document.querySelectorAll('.grammar-topic-item').forEach(item => {
    if (item.dataset.grammarTopic === topic) item.classList.toggle('selected', checked);
  });
  updateChapterCount();
}

function selectAllGrammarTopics() {
  document.querySelectorAll('.grammar-topic-item').forEach(item => {
    const cb = item.querySelector('input');
    if (cb) {
      cb.checked = true;
      item.classList.add('selected');
      const t = item.dataset.grammarTopic;
      if (!state.selectedGrammarTopics.includes(t)) state.selectedGrammarTopics.push(t);
    }
  });
  updateChapterCount();
}

function deselectAllGrammarTopics() {
  document.querySelectorAll('.grammar-topic-item').forEach(item => {
    const cb = item.querySelector('input');
    if (cb) { cb.checked = false; item.classList.remove('selected'); }
  });
  state.selectedGrammarTopics = [];
  updateChapterCount();
}

/* ── Custom chapter localStorage helpers (fallback for unauthenticated users) ── */
function _customKey() {
  return `${state.subject}__${state.classNum}`;
}
function _getLocalCustomChapters() {
  try {
    const all = JSON.parse(localStorage.getItem('examcraft_custom_chapters') || '{}');
    return all[_customKey()] || [];
  } catch { return []; }
}
function _setLocalCustomChapters(chapters) {
  try {
    const all = JSON.parse(localStorage.getItem('examcraft_custom_chapters') || '{}');
    all[_customKey()] = chapters;
    localStorage.setItem('examcraft_custom_chapters', JSON.stringify(all));
  } catch {}
}

async function loadCustomChapters() {
  let chapters = [];
  try {
    const res = await fetch(`/api/custom-chapters?subject=${encodeURIComponent(state.subject)}&class_num=${encodeURIComponent(state.classNum)}`);
    if (res.status === 401) {
      chapters = _getLocalCustomChapters();
    } else {
      const data = await res.json();
      chapters = data.chapters || [];
    }
  } catch {
    chapters = _getLocalCustomChapters();
  }
  renderCustomChapters(chapters);
}

function renderCustomChapters(chapters) {
  const section = document.getElementById('custom-chapters-section');
  const container = document.getElementById('custom-chapters-container');
  if (!section || !container) return;

  if (chapters.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = 'block';
  container.innerHTML = '';
  chapters.forEach((item, idx) => {
    const div = document.createElement('div');
    div.className = 'chapter-item';
    div.dataset.chapter = item.chapter;
    div.dataset.customId = String(item.id);
    const isSelected = state.selectedChapters.includes(item.chapter);
    if (isSelected) div.classList.add('selected');
    div.innerHTML = `
      <input type="checkbox" id="cch-${idx}" ${isSelected ? 'checked' : ''} onchange="toggleChapter('${escapeAttr(item.chapter)}', this.checked)" />
      <span>${escapeHtml(item.chapter)}</span>
      <button class="chapter-delete-btn" title="Remove custom chapter" onclick="removeCustomChapter('${escapeAttr(String(item.id))}', event)">&#10005;</button>
    `;
    div.addEventListener('click', (e) => {
      if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') {
        const cb = div.querySelector('input');
        cb.checked = !cb.checked;
        toggleChapter(item.chapter, cb.checked);
      }
    });
    container.appendChild(div);
  });
}

async function addCustomChapter() {
  const input = document.getElementById('custom-chapter-input');
  const chapter = input.value.trim();
  if (!chapter) { showToast('Please enter a chapter name.', 'error'); return; }

  try {
    const res = await fetch('/api/custom-chapters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: state.subject, class_num: state.classNum, chapter })
    });
    if (res.status === 401) {
      const chapters = _getLocalCustomChapters();
      const id = Date.now().toString();
      chapters.push({ id, chapter });
      _setLocalCustomChapters(chapters);
      renderCustomChapters(chapters);
    } else {
      await loadCustomChapters();
    }
  } catch {
    const chapters = _getLocalCustomChapters();
    chapters.push({ id: Date.now().toString(), chapter });
    _setLocalCustomChapters(chapters);
    renderCustomChapters(chapters);
  }

  input.value = '';
  showToast('Custom chapter added!', 'success');
}

async function removeCustomChapter(id, event) {
  event.stopPropagation();
  const el = document.querySelector(`[data-custom-id="${CSS.escape(id)}"]`);
  const chapterName = el ? el.dataset.chapter : null;

  try {
    const res = await fetch(`/api/custom-chapters/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res.status === 401) {
      const chapters = _getLocalCustomChapters().filter(c => String(c.id) !== id);
      _setLocalCustomChapters(chapters);
      renderCustomChapters(chapters);
    } else {
      await loadCustomChapters();
    }
  } catch {
    const chapters = _getLocalCustomChapters().filter(c => String(c.id) !== id);
    _setLocalCustomChapters(chapters);
    renderCustomChapters(chapters);
  }

  if (chapterName) {
    state.selectedChapters = state.selectedChapters.filter(c => c !== chapterName);
    updateChapterCount();
  }
  showToast('Custom chapter removed.', 'success');
}

function toggleChapter(chapter, checked) {
  if (checked) {
    if (!state.selectedChapters.includes(chapter)) state.selectedChapters.push(chapter);
  } else {
    state.selectedChapters = state.selectedChapters.filter(c => c !== chapter);
  }
  document.querySelectorAll('.chapter-item').forEach(item => {
    if (item.dataset.chapter === chapter) item.classList.toggle('selected', checked);
  });
  updateChapterCount();
}

function selectAllChapters() {
  document.querySelectorAll('.chapter-item').forEach(item => {
    const cb = item.querySelector('input');
    if (cb) {
      cb.checked = true;
      item.classList.add('selected');
      const ch = item.dataset.chapter;
      if (!state.selectedChapters.includes(ch)) state.selectedChapters.push(ch);
    }
  });
  updateChapterCount();
}

function deselectAllChapters() {
  document.querySelectorAll('.chapter-item').forEach(item => {
    const cb = item.querySelector('input');
    if (cb) { cb.checked = false; item.classList.remove('selected'); }
  });
  state.selectedChapters = [];
  updateChapterCount();
}

function updateChapterCount() {
  const cCount = state.selectedChapters.length;
  const gCount = state.selectedGrammarTopics.length;
  let label = `${cCount} chapter${cCount !== 1 ? 's' : ''} selected`;
  if (gCount > 0) label += `, ${gCount} grammar topic${gCount !== 1 ? 's' : ''}`;
  document.getElementById('chapter-count').textContent = label;
}

/* ===== CHAPTER IMAGE UPLOAD ===== */
function handleChapterImageUpload(event) {
  const files = Array.from(event.target.files);
  const container = document.getElementById('chapter-image-previews');

  files.forEach(file => {
    if (!file.type.startsWith('image/')) return;
    state.chapterImages.push(file);
    const reader = new FileReader();
    reader.onload = (e) => {
      const item = document.createElement('div');
      item.className = 'image-preview-item';
      const idx = state.chapterImages.length - 1;
      item.innerHTML = `
        <img src="${e.target.result}" alt="Chapter page" />
        <button class="image-preview-remove" onclick="removeChapterImage(${idx})">&#10005;</button>
      `;
      container.appendChild(item);
    };
    reader.readAsDataURL(file);
  });
}

function removeChapterImage(idx) {
  state.chapterImages.splice(idx, 1);
  const container = document.getElementById('chapter-image-previews');
  container.innerHTML = '';
  state.chapterImages.forEach((file, i) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const item = document.createElement('div');
      item.className = 'image-preview-item';
      item.innerHTML = `
        <img src="${e.target.result}" alt="Chapter page" />
        <button class="image-preview-remove" onclick="removeChapterImage(${i})">&#10005;</button>
      `;
      container.appendChild(item);
    };
    reader.readAsDataURL(file);
  });
}

/* ===== DYNAMIC QUESTION TYPES ===== */
const QT_ICONS = {
  mcq: '&#9711;', fill_blank: '&#9135;', match: '&#8596;', true_false: '&#10003;',
  short_answer: '&#128221;', long_answer: '&#128210;', diagram: '&#128444;',
  reading_passage: '&#128196;', reading_poem: '&#127928;', grammar: '&#9998;',
  writing: '&#9997;', literature_short: '&#128218;', literature_long: '&#128215;',
  map_work: '&#127757;', source_based: '&#128203;', numerical: '&#8730;',
  assertion_reason: '&#9888;', chemical_eq: '&#9874;', practical: '&#128203;',
  program: '&#128187;', output: '&#9654;', error: '&#9888;',
  _default: '&#10067;'
};

async function loadQuestionTypes(subject) {
  const board    = state.board    || document.getElementById('board').value    || '';
  const classNum = state.classNum || document.getElementById('class_num').value || '';
  const grid = document.getElementById('qt-grid');
  grid.innerHTML = `<div class="loading-chapters">Loading question types for ${escapeHtml(subject)}…</div>`;

  try {
    const params = new URLSearchParams({ subject, board, class_num: classNum });
    const res  = await fetch(`/api/question-types?${params}`);
    const data = await res.json();
    renderQuestionTypeCards(data.types || data.question_types || []);
  } catch (e) {
    grid.innerHTML = '<div class="loading-chapters">Error loading question types. Please try again.</div>';
  }
}

function renderQuestionTypeCards(types) {
  const grid = document.getElementById('qt-grid');
  grid.innerHTML = '';

  if (!types || types.length === 0) {
    grid.innerHTML = '<div class="loading-chapters">No question types available.</div>';
    return;
  }

  types.forEach((t, idx) => {
    const key = t.key;
    const defaultEnabled = idx < 3;
    const icon = QT_ICONS[key] || QT_ICONS['_default'];
    const defaultCount = t.default_count || 5;
    const defaultMarks = t.default_marks || 1;
    const defaultTotal = defaultEnabled ? defaultCount * defaultMarks : 0;

    const card = document.createElement('div');
    card.className = 'qt-card' + (defaultEnabled ? ' active' : '');
    card.id = `qt-${key}`;
    card.dataset.key = key;
    card.innerHTML = `
      <div class="qt-header">
        <div class="qt-toggle">
          <input type="checkbox" id="enable-${key}" ${defaultEnabled ? 'checked' : ''}
                 onchange="toggleQType('${key}')" />
          <label for="enable-${key}">
            <span class="qt-icon">${icon}</span>
            <strong>${escapeHtml(t.label)}</strong>
          </label>
        </div>
        ${t.badge ? `<span class="qt-badge">${escapeHtml(t.badge)}</span>` : ''}
      </div>
      ${t.description ? `<div class="qt-desc">${escapeHtml(t.description)}</div>` : ''}
      <div class="qt-inputs${defaultEnabled ? '' : ' disabled'}" id="inputs-${key}">
        <div class="qt-row">
          <div class="qt-field">
            <label>No. of Questions</label>
            <input type="number" id="${key}-count" value="${defaultCount}" min="1" max="50"
                   onchange="updateMarksTotal()" ${defaultEnabled ? '' : 'disabled'} />
          </div>
          <div class="qt-field">
            <label>Marks Each</label>
            <input type="number" id="${key}-marks" value="${defaultMarks}" min="0.5" max="20" step="0.5"
                   onchange="updateMarksTotal()" ${defaultEnabled ? '' : 'disabled'} />
          </div>
          <div class="qt-total">= <span id="${key}-total">${defaultTotal}</span> marks</div>
        </div>
      </div>
    `;
    grid.appendChild(card);
  });

  updateMarksTotal();
}

/* ===== QUESTION TYPE TOGGLES ===== */
function toggleQType(key) {
  const enabled = document.getElementById(`enable-${key}`).checked;
  const inputsDiv = document.getElementById(`inputs-${key}`);
  const card = document.getElementById(`qt-${key}`);

  inputsDiv.classList.toggle('disabled', !enabled);
  card.classList.toggle('active', enabled);
  inputsDiv.querySelectorAll('input').forEach(inp => inp.disabled = !enabled);
  updateMarksTotal();
}

/* ===== MARKS TOTAL (dynamic — works with any set of qt cards) ===== */
function _fmtNum(n) {
  // Display a number cleanly: integer → "5", float → "1.5"
  return n % 1 === 0 ? String(n) : n.toFixed(1);
}

/** Convert 1→i, 2→ii, 3→iii … (lowercase Roman numerals for sub-questions) */
function _toRoman(n) {
  if (n < 1) return String(n);
  const vals = [1, 4, 5, 9, 10, 40, 50, 90, 100];
  const syms = ['i','iv','v','ix','x','xl','l','xc','c'];
  let r = '';
  for (let i = vals.length - 1; i >= 0; i--) {
    while (n >= vals[i]) { r += syms[i]; n -= vals[i]; }
  }
  return r;
}

function updateMarksTotal() {
  let total = 0;

  document.querySelectorAll('.qt-card[data-key]').forEach(card => {
    const key = card.dataset.key;
    const enableEl = document.getElementById(`enable-${key}`);
    if (!enableEl?.checked) {
      const el = document.getElementById(`${key}-total`);
      if (el) el.textContent = '0';
      return;
    }
    const count    = parseInt(document.getElementById(`${key}-count`)?.value  || '0');
    const marks    = parseFloat(document.getElementById(`${key}-marks`)?.value || '0');
    const subtotal = count * marks;
    total += subtotal;
    const el = document.getElementById(`${key}-total`);
    if (el) el.textContent = _fmtNum(subtotal);
  });

  // Round to avoid floating-point noise (e.g. 0.1+0.2 = 0.30000000000000004)
  total = Math.round(total * 100) / 100;

  document.getElementById('marks-counter').textContent = _fmtNum(total);
  const target    = state.totalMarks;
  const statusEl  = document.getElementById('marks-status');
  const diff      = Math.round((total - target) * 100) / 100;

  if (Math.abs(diff) < 0.001) {
    statusEl.textContent = '✓ Matches target';
    statusEl.className   = 'marks-ok';
  } else if (diff > 0) {
    statusEl.textContent = `▲ ${_fmtNum(diff)} over target`;
    statusEl.className   = 'marks-over';
  } else {
    statusEl.textContent = `▼ ${_fmtNum(-diff)} under target`;
    statusEl.className   = 'marks-under';
  }
}

function collectQuestionTypes() {
  const result = {};
  document.querySelectorAll('.qt-card[data-key]').forEach(card => {
    const key     = card.dataset.key;
    const enabled = document.getElementById(`enable-${key}`)?.checked;
    if (!enabled) return;
    const count = parseInt(document.getElementById(`${key}-count`)?.value  || '0');
    const marks = parseFloat(document.getElementById(`${key}-marks`)?.value || '0');
    if (count > 0) result[key] = { count, marks };
  });
  return result;
}

/* ===== GREEK & MATH SYMBOL NORMALISATION ===== */
// Maps LaTeX backslash commands → Unicode character
const _LATEX_SYMBOLS = {
  // Greek lowercase
  '\\alpha':'α','\\beta':'β','\\gamma':'γ','\\delta':'δ',
  '\\epsilon':'ε','\\varepsilon':'ε','\\zeta':'ζ','\\eta':'η',
  '\\theta':'θ','\\vartheta':'ϑ','\\iota':'ι','\\kappa':'κ',
  '\\lambda':'λ','\\mu':'μ','\\nu':'ν','\\xi':'ξ',
  '\\pi':'π','\\varpi':'ϖ','\\rho':'ρ','\\varrho':'ϱ',
  '\\sigma':'σ','\\varsigma':'ς','\\tau':'τ','\\upsilon':'υ',
  '\\phi':'φ','\\varphi':'φ','\\chi':'χ','\\psi':'ψ','\\omega':'ω',
  // Greek uppercase
  '\\Alpha':'Α','\\Beta':'Β','\\Gamma':'Γ','\\Delta':'Δ',
  '\\Epsilon':'Ε','\\Zeta':'Ζ','\\Eta':'Η','\\Theta':'Θ',
  '\\Iota':'Ι','\\Kappa':'Κ','\\Lambda':'Λ','\\Mu':'Μ',
  '\\Nu':'Ν','\\Xi':'Ξ','\\Pi':'Π','\\Rho':'Ρ',
  '\\Sigma':'Σ','\\Tau':'Τ','\\Upsilon':'Υ','\\Phi':'Φ',
  '\\Chi':'Χ','\\Psi':'Ψ','\\Omega':'Ω',
  // Maths operators / relations
  '\\times':'×','\\div':'÷','\\pm':'±','\\mp':'∓','\\cdot':'·',
  '\\leq':'≤','\\le':'≤','\\geq':'≥','\\ge':'≥',
  '\\neq':'≠','\\ne':'≠','\\approx':'≈','\\equiv':'≡',
  '\\propto':'∝','\\sim':'∼','\\simeq':'≃',
  '\\infty':'∞','\\partial':'∂','\\nabla':'∇',
  '\\sum':'∑','\\prod':'∏','\\int':'∫',
  '\\in':'∈','\\notin':'∉',
  '\\subset':'⊂','\\supset':'⊃','\\subseteq':'⊆','\\supseteq':'⊇',
  '\\cup':'∪','\\cap':'∩','\\emptyset':'∅',
  '\\rightarrow':'→','\\to':'→','\\leftarrow':'←',
  '\\leftrightarrow':'↔','\\Rightarrow':'⇒','\\Leftarrow':'⇐',
  '\\Leftrightarrow':'⟺','\\uparrow':'↑','\\downarrow':'↓',
  '\\angle':'∠','\\perp':'⊥','\\parallel':'∥',
  '\\triangle':'△','\\square':'□','\\therefore':'∴','\\because':'∵',
  '\\circ':'°','\\degree':'°',
  '\\ldots':'…','\\cdots':'⋯','\\vdots':'⋮','\\ddots':'⋱',
  '\\forall':'∀','\\exists':'∃','\\nexists':'∄',
  '\\oplus':'⊕','\\otimes':'⊗','\\odot':'⊙',
  '\\langle':'⟨','\\rangle':'⟩',
};
// Sort keys longest-first so longer commands win over short prefixes
const _LATEX_KEYS = Object.keys(_LATEX_SYMBOLS).sort((a, b) => b.length - a.length);

// Maps HTML entity names → Unicode character
const _HTML_ENTITIES = {
  '&alpha;':'α','&beta;':'β','&gamma;':'γ','&delta;':'δ','&epsilon;':'ε',
  '&zeta;':'ζ','&eta;':'η','&theta;':'θ','&iota;':'ι','&kappa;':'κ',
  '&lambda;':'λ','&mu;':'μ','&nu;':'ν','&xi;':'ξ','&pi;':'π',
  '&rho;':'ρ','&sigma;':'σ','&tau;':'τ','&upsilon;':'υ','&phi;':'φ',
  '&chi;':'χ','&psi;':'ψ','&omega;':'ω',
  '&Alpha;':'Α','&Beta;':'Β','&Gamma;':'Γ','&Delta;':'Δ','&Epsilon;':'Ε',
  '&Zeta;':'Ζ','&Eta;':'Η','&Theta;':'Θ','&Iota;':'Ι','&Kappa;':'Κ',
  '&Lambda;':'Λ','&Mu;':'Μ','&Nu;':'Ν','&Xi;':'Ξ','&Pi;':'Π',
  '&Rho;':'Ρ','&Sigma;':'Σ','&Tau;':'Τ','&Upsilon;':'Υ','&Phi;':'Φ',
  '&Chi;':'Χ','&Psi;':'Ψ','&Omega;':'Ω',
  '&times;':'×','&divide;':'÷','&plusmn;':'±','&middot;':'·',
  '&le;':'≤','&ge;':'≥','&ne;':'≠','&asymp;':'≈','&equiv;':'≡',
  '&infin;':'∞','&part;':'∂','&sum;':'∑','&prod;':'∏','&int;':'∫',
  '&rArr;':'⇒','&lArr;':'⇐','&hArr;':'⟺',
  '&rarr;':'→','&larr;':'←','&harr;':'↔',
  '&ang;':'∠','&perp;':'⊥','&there4;':'∴',
  '&deg;':'°','&hellip;':'…','&sdot;':'·',
};

/**
 * Normalise a raw text string by converting:
 *   • HTML entity names (&alpha; &theta; &times; …) → Unicode
 *   • LaTeX commands (\alpha \beta \times \sqrt{x} \frac{a}{b} …) → Unicode/plain
 * Unicode Greek characters already in the string are left untouched.
 */
function _normalizeSymbols(text) {
  let s = String(text);

  // 1. HTML entity names → Unicode (before any escaping touches the & chars)
  for (const [ent, uni] of Object.entries(_HTML_ENTITIES)) {
    // plain string replace (split-join is fastest for repeated fixed strings)
    s = s.split(ent).join(uni);
  }

  // 2. Special LaTeX constructs with braced arguments
  s = s.replace(/\\sqrt\{([^}]+)\}/g, '√($1)');                  // \sqrt{x} → √(x)
  s = s.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '($1)/($2)');   // \frac{a}{b} → (a)/(b)
  s = s.replace(/\\(?:overline|hat|vec|bar|tilde|dot|ddot)\{([^}]+)\}/g, '$1'); // strip deco
  s = s.replace(/\\text\{([^}]+)\}/g, '$1');                      // \text{...} → plain
  s = s.replace(/\\mathrm\{([^}]+)\}/g, '$1');                    // \mathrm{...} → plain

  // 3. LaTeX symbol commands (longest-first to avoid partial matches)
  for (const cmd of _LATEX_KEYS) {
    // Escape the backslash; require command not followed by another letter
    const pat = new RegExp(cmd.replace(/\\/g, '\\\\') + '(?![a-zA-Z])', 'g');
    s = s.replace(pat, _LATEX_SYMBOLS[cmd]);
  }

  return s;
}

/* ===== FORMAT FORMULA (Greek symbols / superscript / subscript) ===== */
function formatFormula(rawText) {
  // 1. Normalise Greek/math symbols (LaTeX & HTML entities → Unicode)
  const normalized = _normalizeSymbols(rawText);
  // 2. HTML-escape (Unicode Greek chars are multi-byte and are NOT touched by this)
  const e = normalized
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  // 3. Apply superscript / subscript notation
  return e
    .replace(/\^\{([^}]{1,30})\}/g, '<sup>$1</sup>')
    .replace(/_\{([^}]{1,30})\}/g,  '<sub>$1</sub>')
    .replace(/\^(\d+)/g,            '<sup>$1</sup>')
    .replace(/\^([a-zA-Z])\b/g,     '<sup>$1</sup>')
    .replace(/_(\d+)/g,             '<sub>$1</sub>');
}

/* ===== GENERATE PAPER ===== */
async function generatePaper() {
  const qt = collectQuestionTypes();
  if (Object.keys(qt).length === 0) {
    showToast('Please enable at least one question type.', 'error');
    return;
  }

  state.questionTypes = qt;
  showLoading('Generating Question Paper...', 'Gemini AI is crafting NCERT-aligned questions for your exam');

  try {
    const formData = new FormData();
    formData.append('board', state.board);
    formData.append('class_num', state.classNum);
    formData.append('subject', state.subject);
    formData.append('exam_type', state.examType);
    formData.append('total_marks', state.totalMarks);
    formData.append('duration', state.duration);
    formData.append('difficulty', state.difficulty);
    formData.append('teacher_name', state.teacherName);
    formData.append('school_name', state.schoolName);
    formData.append('exam_date', state.examDate || '');
    const _allChapters = [...state.selectedChapters, ...state.selectedGrammarTopics];
    formData.append('chapters', JSON.stringify(_allChapters));
    formData.append('question_types', JSON.stringify(qt));

    state.chapterImages.forEach(file => formData.append('chapter_images', file));

    const res = await fetch('/api/generate-paper', { method: 'POST', body: formData });
    const data = await res.json();

    if (res.status === 401 || data.error === 'auth_required') {
      showToast('Please sign in to continue.', 'error');
      return;
    }
    if (res.status === 403 || data.error === 'limit_reached') {
      showToast(`Paper limit reached (${data.limit || 3}/month on Free plan). Upgrade to generate more!`, 'error');
      openUpgradeModal();
      return;
    }
    if (!res.ok || data.error) {
      showToast(data.error || 'Failed to generate paper.', 'error');
      return;
    }

    state.questionPaper = data.paper;
    state.paperId = data.paper_id || null;
    renderQuestionPaper(data.paper);
    gotoStep(4);
    showToast('Question paper generated successfully!', 'success');

    // Refresh usage badge
    try {
      const ur = await fetch('/api/user');
      const ud = await ur.json();
      if (ud.logged_in) updateUsageBadge(ud);
    } catch (e) { /* ignore */ }
  } catch (e) {
    showToast('Network error. Please check your connection.', 'error');
  } finally {
    hideLoading();
  }
}

/* ===== RENDER QUESTION PAPER ===== */
function renderQuestionPaper(paper) {
  const container = document.getElementById('question-paper-display');
  const info = paper.paper_info || {};

  let html = `<div class="qp-header">`;

  // School branding: logo + name side-by-side when both present, else centered
  const _hasLogo = !!state.schoolLogoDataUrl;
  const _hasName = !!state.schoolName;
  if (_hasLogo || _hasName) {
    if (_hasLogo && _hasName) {
      html += `<div class="qp-branding-row">`;
      html += `<div class="qp-branding-logo"><img src="${state.schoolLogoDataUrl}" alt="School Logo" class="qp-school-logo" /></div>`;
      html += `<div class="qp-branding-text"><div class="qp-school-name">${escapeHtml(state.schoolName)}</div></div>`;
      html += `</div>`;
    } else if (_hasLogo) {
      html += `<div class="qp-branding-center"><img src="${state.schoolLogoDataUrl}" alt="School Logo" class="qp-school-logo" /></div>`;
    } else {
      html += `<div class="qp-school-name">${escapeHtml(state.schoolName)}</div>`;
    }
  }

  html += `
      <div class="qp-school">${escapeHtml(info.board || state.board)} &mdash; NCERT Curriculum</div>
      <div class="qp-title">${escapeHtml(info.subject || state.subject)}</div>
      <div class="qp-exam-type">${escapeHtml(info.exam_type || state.examType)}</div>
  `;
  if (state.teacherName) {
    html += `<div class="qp-teacher">Teacher: ${escapeHtml(state.teacherName)}</div>`;
  }
  html += `
      <div class="qp-meta">
        <div class="qp-meta-item">
          <span class="qp-meta-label">Class</span>
          <span class="qp-meta-value">${escapeHtml(String(info.class || state.classNum))}</span>
        </div>
        <div class="qp-meta-item">
          <span class="qp-meta-label">Total Marks</span>
          <span class="qp-meta-value">${escapeHtml(String(info.total_marks || state.totalMarks))}</span>
        </div>
        <div class="qp-meta-item">
          <span class="qp-meta-label">Duration</span>
          <span class="qp-meta-value">${escapeHtml(info.duration || state.duration)}</span>
        </div>
        <div class="qp-meta-item">
          <span class="qp-meta-label">Date</span>
          <span class="qp-meta-value">${info.date || state.examDate || '___________'}</span>
        </div>
      </div>
    </div>
  `;

  if (paper.instructions && paper.instructions.length > 0) {
    html += `
      <div class="qp-instructions">
        <h4>General Instructions</h4>
        <ol>${paper.instructions.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ol>
      </div>
    `;
  }

  let globalQNum = 1;
  (paper.sections || []).forEach((section, secIdx) => {
    html += `
      <div class="qp-section">
        <div class="qp-section-header">
          <span class="qp-section-title">${escapeHtml(section.section_name || '')}</span>
          <span class="qp-section-inst">${escapeHtml(section.instructions || '')}</span>
        </div>
    `;

    (section.questions || []).forEach((q, qIdx) => {
      const type       = section.type;
      const _isPassage = (type === 'reading_passage' || type === 'reading_poem');

      // Open question wrapper — NOTE: qp-question-row is closed separately
      // so passage sub-question rows can be inserted as siblings inside qp-question.
      html += `<div class="qp-question">`;
      html += `<div class="qp-question-row">`;
      html += `<span class="qp-q-num">${globalQNum}.</span>`;

      let qBody = `<div class="qp-q-text" id="qtext-${secIdx}-${qIdx}">`;

      // Pre-build image HTML — injected INSIDE qp-q-text so it sits in the
      // text column (flex:1), not as a separate flex sibling in qp-question-row.
      const _hasQImg = !!q.image_data_url;
      const _imgW    = (q.image_size || 60) + '%';
      const _imgHtml = _hasQImg
        ? `<div class="qp-q-image-wrap"><img src="${q.image_data_url}" class="qp-q-image" style="width:${_imgW};max-width:${_imgW}" alt="Question diagram" /></div>`
        : '';

      if (type === 'mcq' || type === 'assertion_reason') {
        qBody += formatFormula(q.text || '');
        // Image goes BETWEEN question text and options
        qBody += _imgHtml;
        if (q.options && q.options.length > 0) {
          qBody += `<div class="qp-options">`;
          q.options.forEach(opt => { qBody += `<div class="qp-option">${formatFormula(opt)}</div>`; });
          qBody += `</div>`;
        }
      } else if (type === 'fill_blank') {
        const text = formatFormula(q.text || '').replace(/_+/g, '<span class="qp-blank">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>');
        qBody += text;
        qBody += _imgHtml;
      } else if (type === 'match') {
        qBody += formatFormula(q.text || '');
        if (q.column_a && q.column_b) {
          qBody += `<div class="qp-match-table">`;
          const len = Math.max(q.column_a.length, q.column_b.length);
          for (let i = 0; i < len; i++) {
            qBody += `<div class="qp-match-row">
              <span class="qp-match-col-a">${i + 1}. ${formatFormula(q.column_a[i] || '')}</span>
              <span>${String.fromCharCode(97 + i)}) ${formatFormula(q.column_b[i] || '')}</span>
            </div>`;
          }
          qBody += `</div>`;
        }
        qBody += _imgHtml;
      } else if (type === 'true_false') {
        qBody += formatFormula(q.text || '') + ' &nbsp; <strong>[True / False]</strong>';
        qBody += _imgHtml;
      } else if (type === 'map_work') {
        qBody += formatFormula(q.text || '') + '<div class="qp-map-hint">[Refer to outline map provided]</div>';
        qBody += _imgHtml;
      } else if (_isPassage) {
        // Passage text + passage box only — sub-questions rendered as sibling rows below
        qBody += formatFormula(q.text || '');
        if (q.passage) {
          qBody += `<div class="qp-passage">${formatFormula(q.passage)}</div>`;
        }
        if (q.sub_questions && q.sub_questions.length > 0) {
          qBody += `<div class="qp-subq-label">Answer the following questions:</div>`;
        }
        qBody += _imgHtml;
      } else if (type === 'geometry_diagram') {
        qBody += formatFormula(q.text || '');
        if (q.figure_description) {
          qBody += `<div class="qp-figure-box">
            <div class="qp-figure-label">&#9998; Construction Space</div>
            <div class="qp-figure-desc">${escapeHtml(q.figure_description)}</div>
          </div>`;
        }
        qBody += _imgHtml;
      } else {
        qBody += formatFormula(q.text || '');
        qBody += _imgHtml;
      }

      qBody += `</div>`;  // close qp-q-text — image is already inside, no extra block needed

      html += qBody;

      // Marks label + edit button (right side of main row)
      const _qm    = q.marks != null ? q.marks : 1;
      const _qmStr = _fmtNum(_qm);
      if (_isPassage) {
        html += `<span class="qp-q-marks">[Total: ${_qmStr} marks]</span>`;
      } else {
        html += `<span class="qp-q-marks">[${_qmStr} mark${_qm === 1 ? '' : 's'}]</span>`;
      }
      html += `<button class="q-edit-btn" onclick="editQuestion(${secIdx},${qIdx})" title="Edit question">&#9998;</button>`;
      html += `</div>`;  // close qp-question-row

      // ── Sub-question rows (outside qp-question-row so marks column aligns) ──
      if (_isPassage && q.sub_questions && q.sub_questions.length > 0) {
        q.sub_questions.forEach((sq, sqIdx) => {
          const sqText  = (typeof sq === 'object' && sq !== null) ? (sq.text || '') : String(sq);
          const sqMarks = (typeof sq === 'object' && sq !== null && sq.marks != null)
                          ? sq.marks : null;
          const marksHtml = sqMarks != null
            ? `<span class="qp-q-marks">[${_fmtNum(sqMarks)} mark${sqMarks === 1 ? '' : 's'}]</span>`
            : '';
          html += `<div class="qp-subq-row">`;
          html += `<span class="qp-subq-num">(${_toRoman(sqIdx + 1)})</span>`;
          html += `<div class="qp-subq-text">${formatFormula(sqText)}</div>`;
          html += marksHtml;
          html += `<span class="qp-subq-spacer"></span>`;  // mirrors edit-btn space
          html += `</div>`;
        });
      }

      html += `</div>`;  // close qp-question
      globalQNum++;
    });

    html += `</div>`;
  });

  if (paper.answer_key && paper.answer_key.length > 0) {
    html += `
      <div class="qp-answer-key">
        <h3>&#9989; Answer Key</h3>
        <div class="answer-key-grid">
          ${paper.answer_key.map(a =>
            `<div class="answer-key-item"><strong>${escapeHtml(a.q_id || '')}:</strong> ${escapeHtml(String(a.answer || ''))}</div>`
          ).join('')}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;
}

/* ===== ANSWER SHEET UPLOAD ===== */
function handleAnswerSheetUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  state.answerSheetFile = file;
  document.getElementById('upload-filename').textContent = `✓ ${file.name} (${formatFileSize(file.size)})`;
  document.getElementById('answer-upload-zone').style.borderColor = 'var(--success)';
  document.getElementById('answer-upload-zone').style.background = 'var(--success-bg)';
  showToast(`File ready: ${file.name}`, 'success');
}

/* ===== EVALUATE ===== */
async function evaluateAnswerSheet() {
  const studentName = document.getElementById('student_name').value.trim() || 'Student';
  const rollNo = document.getElementById('roll_no').value.trim() || 'N/A';

  if (!state.answerSheetFile) {
    showToast('Please upload an answer sheet first.', 'error');
    return;
  }
  if (!state.questionPaper) {
    showToast('No question paper found. Please generate a paper first.', 'error');
    return;
  }

  showLoading('Evaluating Answer Sheet...', 'Gemini AI is reading and marking the answer sheet');

  try {
    const formData = new FormData();
    formData.append('answer_sheet', state.answerSheetFile);
    formData.append('student_name', studentName);
    formData.append('roll_no', rollNo);
    formData.append('question_paper', JSON.stringify(state.questionPaper));
    if (state.paperId) formData.append('paper_id', state.paperId);

    const res = await fetch('/api/evaluate', { method: 'POST', body: formData });
    const data = await res.json();

    if (res.status === 401 || data.error === 'auth_required') {
      showToast('Please sign in to continue.', 'error');
      return;
    }
    if (res.status === 403 || data.error === 'limit_reached') {
      showToast(`Evaluation limit reached (${data.limit || 5}/month on Free plan). Upgrade to evaluate more!`, 'error');
      openUpgradeModal();
      return;
    }
    if (!res.ok || data.error) {
      showToast(data.error || 'Evaluation failed.', 'error');
      return;
    }

    renderEvaluationReport(data.report);
    showToast('Evaluation complete!', 'success');

    // Refresh usage badge
    try {
      const ur = await fetch('/api/user');
      const ud = await ur.json();
      if (ud.logged_in) updateUsageBadge(ud);
    } catch (e) { /* ignore */ }
  } catch (e) {
    showToast('Network error during evaluation.', 'error');
  } finally {
    hideLoading();
  }
}

/* ===== RENDER REPORT ===== */
function renderEvaluationReport(report) {
  document.getElementById('eval-form-card').style.display = 'none';
  const reportDiv = document.getElementById('evaluation-report');
  reportDiv.style.display = 'block';

  const paperInfo = state.questionPaper?.paper_info || {};
  document.getElementById('report-meta').innerHTML = `
    <div><strong>Student:</strong> ${escapeHtml(report.student_name || 'N/A')}</div>
    <div><strong>Roll No:</strong> ${escapeHtml(report.roll_no || 'N/A')}</div>
    <div><strong>Subject:</strong> ${escapeHtml(paperInfo.subject || state.subject)}</div>
    <div><strong>Class:</strong> ${escapeHtml(String(paperInfo.class || state.classNum))}</div>
    <div><strong>Exam:</strong> ${escapeHtml(paperInfo.exam_type || state.examType)}</div>
    <div><strong>Board:</strong> ${escapeHtml(paperInfo.board || state.board)}</div>
  `;

  const obtained = report.total_obtained || 0;
  const total = report.total_marks || state.totalMarks;
  const pct = report.percentage || ((obtained / total) * 100).toFixed(1);

  document.getElementById('score-obtained').textContent = obtained;
  document.getElementById('score-total').textContent = `out of ${total}`;
  document.getElementById('score-percentage').textContent = `${pct}%`;
  document.getElementById('score-grade').textContent = `Grade: ${report.grade || '-'}`;

  const secContainer = document.getElementById('section-wise-table');
  if (report.section_wise_marks && report.section_wise_marks.length > 0) {
    let html = `<div class="section-marks-bar">`;
    report.section_wise_marks.forEach(s => {
      const pctSec = s.maximum > 0 ? Math.round((s.obtained / s.maximum) * 100) : 0;
      html += `
        <div class="section-marks-item">
          <div>
            <div class="section-marks-name">Section ${escapeHtml(s.section || '')} &mdash; ${escapeHtml(s.section_name || '')}</div>
            <div style="font-size:0.75rem;color:var(--text-muted);">${pctSec}% scored</div>
          </div>
          <div class="section-marks-score">${s.obtained}/${s.maximum}</div>
        </div>
      `;
    });
    html += `</div>`;
    secContainer.innerHTML = html;
  } else {
    secContainer.innerHTML = '<p style="color:var(--text-muted);padding:1rem 0;">No section-wise data available.</p>';
  }

  const qContainer = document.getElementById('question-wise-table');
  if (report.evaluations && report.evaluations.length > 0) {
    let html = `
      <table class="report-table">
        <thead>
          <tr>
            <th>Q. No</th><th>Sec</th>
            <th style="min-width:200px;">Question</th>
            <th style="min-width:150px;">Student's Answer</th>
            <th style="min-width:150px;">Correct Answer</th>
            <th>Marks</th><th>Status</th>
            <th style="min-width:180px;">Feedback</th>
          </tr>
        </thead><tbody>
    `;
    report.evaluations.forEach((ev, idx) => {
      const isCorrect = ev.is_correct;
      const isPartial = !isCorrect && ev.marks_obtained > 0;
      let statusHtml, marksClass;
      if (isCorrect) { statusHtml = `<span class="status-correct">&#10003; Correct</span>`; marksClass = 'full'; }
      else if (isPartial) { statusHtml = `<span class="status-partial">&#8759; Partial</span>`; marksClass = 'partial'; }
      else { statusHtml = `<span class="status-wrong">&#10007; Wrong</span>`; marksClass = 'zero'; }

      html += `
        <tr>
          <td><strong>${escapeHtml(ev.q_id || String(idx + 1))}</strong></td>
          <td>${escapeHtml(ev.section || '')}</td>
          <td style="font-size:0.82rem;">${escapeHtml(ev.question_text || '')}</td>
          <td style="font-size:0.82rem;">${escapeHtml(ev.student_answer || 'Not attempted')}</td>
          <td style="font-size:0.82rem;color:var(--success);font-weight:500;">${escapeHtml(String(ev.correct_answer || ''))}</td>
          <td>
            <span class="marks-pill ${marksClass}">${ev.marks_obtained}</span>
            <span style="color:var(--text-muted);font-size:0.8rem;">/${ev.max_marks}</span>
          </td>
          <td>${statusHtml}</td>
          <td style="font-size:0.8rem;color:var(--text-muted);">${escapeHtml(ev.feedback || '')}</td>
        </tr>
      `;
    });
    html += `
        <tr style="background:var(--gradient-soft);">
          <td colspan="5" style="text-align:right;font-weight:700;color:var(--text-primary);">Total</td>
          <td><strong style="color:var(--primary);font-size:1rem;">${obtained}/${total}</strong></td>
          <td colspan="2" style="font-weight:700;color:var(--secondary);">${pct}% &mdash; Grade ${report.grade || '-'}</td>
        </tr>
      </tbody></table>`;
    qContainer.innerHTML = html;
  } else {
    qContainer.innerHTML = '<p style="color:var(--text-muted);padding:1rem 0;">No question-wise data available.</p>';
  }

  document.getElementById('examiner-remarks').textContent = report.remarks || 'No remarks provided.';
  reportDiv.scrollIntoView({ behavior: 'smooth' });
}

function resetEvaluation() {
  document.getElementById('eval-form-card').style.display = 'block';
  document.getElementById('evaluation-report').style.display = 'none';
  document.getElementById('student_name').value = '';
  document.getElementById('roll_no').value = '';
  document.getElementById('answer_sheet').value = '';
  document.getElementById('upload-filename').textContent = '';
  document.getElementById('answer-upload-zone').style.borderColor = '';
  document.getElementById('answer-upload-zone').style.background = '';
  state.answerSheetFile = null;
}

/* ===== HISTORY PANEL ===== */
let _historyCurrentView = 'active';
const _historyDetailCache = {};

function openHistoryPanel() {
  document.getElementById('history-panel').classList.add('open');
  document.getElementById('history-overlay').classList.add('open');
  loadHistory(_historyCurrentView);
}

function closeHistoryPanel() {
  document.getElementById('history-panel').classList.remove('open');
  document.getElementById('history-overlay').classList.remove('open');
}

function switchHistoryTab(view) {
  loadHistory(view);
}

async function loadHistory(view) {
  if (view) _historyCurrentView = view;
  const activeTab = document.getElementById('hvtab-active');
  const archivedTab = document.getElementById('hvtab-archived');
  if (activeTab) activeTab.classList.toggle('active', _historyCurrentView === 'active');
  if (archivedTab) archivedTab.classList.toggle('active', _historyCurrentView === 'archived');

  const body = document.getElementById('history-panel-body');
  body.innerHTML = '<div class="loading-chapters">Loading history...</div>';

  try {
    const res = await fetch(`/api/history?view=${_historyCurrentView}`);
    if (res.status === 401) {
      body.innerHTML = '<div class="history-empty"><p>Sign in to view history.</p></div>';
      return;
    }
    const data = await res.json();

    if (!data.papers || data.papers.length === 0) {
      const emptyMsg = _historyCurrentView === 'archived'
        ? 'No archived papers.'
        : 'No question papers yet.<br><small>Generate your first paper to see it here.</small>';
      body.innerHTML = `
        <div class="history-empty">
          <div style="font-size:2.5rem;margin-bottom:0.5rem;">&#128196;</div>
          <p>${emptyMsg}</p>
        </div>`;
      return;
    }

    body.innerHTML = '';
    data.papers.forEach(p => {
      const item = document.createElement('div');
      item.className = 'history-item';
      const date = new Date(p.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
      item.innerHTML = `
        <div class="history-item-top">
          <span class="history-subject">${escapeHtml(p.subject)}</span>
          <span class="history-date">${date}</span>
        </div>
        <div class="history-item-meta">
          Class ${escapeHtml(String(p.class_num))} &bull; ${escapeHtml(p.board)} &bull; ${escapeHtml(p.exam_type)}
        </div>
        <div class="history-item-meta">
          ${p.total_marks} marks &bull; ${p.evaluation_count || 0} evaluation${p.evaluation_count !== 1 ? 's' : ''}
        </div>
        ${p.teacher_name ? `<div class="history-teacher">Teacher: ${escapeHtml(p.teacher_name)}</div>` : ''}
        ${p.archived ? '<div class="history-archived-badge">&#128230; Archived</div>' : ''}
      `;
      item.addEventListener('click', () => loadHistoryDetail(p.id));
      body.appendChild(item);
    });
  } catch (e) {
    body.innerHTML = '<div class="loading-chapters">Error loading history.</div>';
  }
}

async function loadHistoryDetail(paperId) {
  const body = document.getElementById('history-panel-body');
  body.innerHTML = '<div class="loading-chapters">Loading paper details...</div>';

  try {
    const res = await fetch(`/api/history/${paperId}`);
    if (res.status === 401) {
      body.innerHTML = '<div class="history-empty"><p>Sign in to view history.</p></div>';
      return;
    }
    // API returns metadata at top level: {id, board, class_num, subject, exam_type,
    // teacher_name, total_marks, created_at, paper: <questions>, evaluations: [...]}
    const data = await res.json();
    _historyDetailCache[paperId] = data;

    const evals = data.evaluations || [];
    const date = new Date(data.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

    let html = `
      <button class="btn btn-outline btn-sm" onclick="loadHistory()" style="margin-bottom:1rem;">&#8592; Back to History</button>
      <div class="history-detail-header">
        <div class="history-subject" style="font-size:1.1rem;">${escapeHtml(data.subject || '')}</div>
        <div class="history-item-meta" style="margin-top:0.35rem;">
          Class ${escapeHtml(String(data.class_num || ''))} &bull; ${escapeHtml(data.board || '')}<br>
          ${escapeHtml(data.exam_type || '')} &bull; ${data.total_marks} marks &bull; ${date}
        </div>
        ${data.teacher_name ? `<div class="history-teacher" style="margin-top:0.25rem;">Teacher: ${escapeHtml(data.teacher_name)}</div>` : ''}
      </div>
    `;

    html += `<div style="display:flex;gap:0.5rem;margin-bottom:1rem;flex-wrap:wrap;">`;
    html += `<button class="btn btn-primary btn-sm" onclick="loadPaperFromCache(${paperId})" style="flex:1;">&#128196; Load This Paper</button>`;
    if (!data.archived) {
      html += `<button class="btn btn-outline btn-sm" onclick="archivePaper(${paperId})" title="Archive" style="padding:0.4rem 0.75rem;">&#128230; Archive</button>`;
    } else {
      html += `<button class="btn btn-outline btn-sm" onclick="unarchivePaper(${paperId})" style="padding:0.4rem 0.75rem;">&#8635; Unarchive</button>`;
    }
    html += `</div>`;

    if (evals.length > 0) {
      html += `<div class="history-evals-title">Evaluations (${evals.length})</div>`;
      evals.forEach((ev, idx) => {
        const evDate = new Date(ev.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
        const hasReport = !!ev.report;
        html += `
          <div class="history-eval-item">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:0.5rem;">
              <div>
                <div class="history-eval-student">${escapeHtml(ev.student_name || 'Unknown')}</div>
                <div class="history-item-meta">Roll: ${escapeHtml(ev.roll_no || 'N/A')} &bull; ${evDate}</div>
                <div class="history-eval-score">${ev.total_obtained}/${ev.total_marks} &mdash; ${ev.percentage}% &mdash; Grade ${ev.grade}</div>
              </div>
              ${hasReport ? `<button class="btn btn-outline btn-sm" onclick="viewHistoryEval(${paperId}, ${idx})" style="white-space:nowrap;flex-shrink:0;">&#128203; View Report</button>` : ''}
            </div>
          </div>
        `;
      });
    } else {
      html += `<div class="history-empty" style="padding:1rem 0;"><p>No evaluations for this paper yet.</p></div>`;
    }

    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<div class="loading-chapters">Error loading paper details.</div>';
  }
}

function loadPaperFromCache(paperId) {
  const data = _historyDetailCache[paperId];
  if (!data || !data.paper) { showToast('Paper data not available.', 'error'); return; }
  restorePaper(data.paper, paperId);
}

function viewHistoryEval(paperId, evalIdx) {
  const data = _historyDetailCache[paperId];
  if (!data || !data.paper) { showToast('Paper data not available.', 'error'); return; }
  const ev = (data.evaluations || [])[evalIdx];
  if (!ev || !ev.report) { showToast('Evaluation report not available.', 'error'); return; }
  // Load the paper into state first so report metadata renders correctly
  const paper = typeof data.paper === 'string' ? JSON.parse(data.paper) : data.paper;
  state.questionPaper = paper;
  state.paperId = paperId;
  const info = paper.paper_info || {};
  state.board = info.board || state.board;
  state.classNum = String(info.class || state.classNum);
  state.subject = info.subject || state.subject;
  state.examType = info.exam_type || state.examType;
  state.totalMarks = info.total_marks || state.totalMarks;
  const report = typeof ev.report === 'string' ? JSON.parse(ev.report) : ev.report;
  closeHistoryPanel();
  state.currentStep = 4; // bypass sequential guard so gotoStep(5) works from any step
  gotoStep(5);
  renderEvaluationReport(report);
  showToast('Evaluation report loaded!', 'success');
}

async function archivePaper(paperId) {
  try {
    const res = await fetch(`/api/history/${paperId}/archive`, { method: 'POST' });
    if (res.ok) { showToast('Paper archived.', 'success'); loadHistory('active'); }
    else { showToast('Failed to archive paper.', 'error'); }
  } catch (e) { showToast('Error archiving paper.', 'error'); }
}

async function unarchivePaper(paperId) {
  try {
    const res = await fetch(`/api/history/${paperId}/unarchive`, { method: 'POST' });
    if (res.ok) { showToast('Paper unarchived.', 'success'); loadHistory('archived'); }
    else { showToast('Failed to unarchive paper.', 'error'); }
  } catch (e) { showToast('Error unarchiving paper.', 'error'); }
}

function restorePaper(paperData, paperId) {
  try {
    const paper = typeof paperData === 'string' ? JSON.parse(paperData) : paperData;
    state.questionPaper = paper;
    state.paperId = paperId;
    const info = paper.paper_info || {};
    state.board = info.board || state.board;
    state.classNum = String(info.class || state.classNum);
    state.subject = info.subject || state.subject;
    state.examType = info.exam_type || state.examType;
    state.totalMarks = info.total_marks || state.totalMarks;

    renderQuestionPaper(paper);
    closeHistoryPanel();
    state.currentStep = 3; // bypass sequential guard so gotoStep(4) works from any step
    gotoStep(4);
    showToast('Paper loaded from history!', 'success');
  } catch (e) {
    showToast('Failed to load paper from history.', 'error');
  }
}

/* ===== INLINE QUESTION EDITING ===== */

/** Strip "A) ", "(B) ", "C. " etc. prefix from an option string. */
function _stripOptionPrefix(opt) {
  return String(opt).replace(/^[\(\[]?[A-Da-d][\)\]\.]\s*/i, '').trim();
}

function editQuestion(secIdx, qIdx) {
  const section     = state.questionPaper.sections[secIdx];
  const q           = section.questions[qIdx];
  const sectionType = section.type || '';
  const isMCQ       = (sectionType === 'mcq' || sectionType === 'assertion_reason');

  const textEl = document.getElementById(`qtext-${secIdx}-${qIdx}`);
  if (!textEl) return;

  const currentText = q.text || '';
  const hasImg      = !!q.image_data_url;
  const curSize     = q.image_size || 60;

  // Answer-key entry for this question
  const qId       = q.q_id || '';
  const akEntry   = (state.questionPaper.answer_key || []).find(a => a.q_id === qId);
  const curAnswer = akEntry ? (akEntry.answer || '') : '';

  // ── MCQ options + correct answer block ──────────────────────────────────
  let mcqBlock = '';
  if (isMCQ) {
    const labels  = ['A', 'B', 'C', 'D'];
    const opts    = q.options || [];
    const optRows = labels.map((lbl, i) => {
      const val = _stripOptionPrefix(opts[i] || '');
      return `<div class="q-option-edit-row">
        <span class="q-option-edit-label">(${lbl})</span>
        <input type="text" class="q-option-edit-input"
               id="qopt-${secIdx}-${qIdx}-${i}"
               value="${escapeAttr(val)}" placeholder="Option ${lbl}…" />
      </div>`;
    }).join('');

    // Correct-answer radio row — current answer letter pre-selected
    const curLetter = curAnswer.trim().toUpperCase().charAt(0);
    const radios = labels.map(lbl => `
      <label class="q-correct-radio">
        <input type="radio" name="qcorrect-${secIdx}-${qIdx}" value="${lbl}"
               ${curLetter === lbl ? 'checked' : ''} />
        <span>(${lbl})</span>
      </label>`).join('');

    mcqBlock = `
      <div class="q-options-edit-section">
        <div class="q-options-edit-header">
          <span>&#9997; Answer Options</span>
        </div>
        ${optRows}
        <div class="q-correct-answer-row">
          <span class="q-correct-answer-label">&#9989; Correct Answer:</span>
          ${radios}
        </div>
      </div>`;
  }

  // ── Answer-key textarea (non-MCQ only) ──────────────────────────────────
  const answerBlock = !isMCQ ? `
    <div class="q-answer-edit-row">
      <label class="q-answer-edit-label">&#9989; Answer Key Entry
        <span class="q-img-optional">(update if question changed)</span>
      </label>
      <textarea class="q-answer-edit-textarea" id="qanswer-${secIdx}-${qIdx}"
                rows="3" placeholder="Enter correct answer…"
      >${curAnswer.replace(/</g, '&lt;')}</textarea>
    </div>` : '';

  textEl.innerHTML = `
    <div class="q-edit-header-row">
      <span class="q-edit-header-label">&#9997; Edit Question</span>
      <button class="btn btn-sm q-regen-btn" id="qregen-${secIdx}-${qIdx}"
              onclick="regenerateQuestion(${secIdx},${qIdx})">&#128260; Regenerate</button>
    </div>
    <textarea class="q-edit-textarea" id="qedit-${secIdx}-${qIdx}"
              rows="4">${currentText.replace(/</g, '&lt;')}</textarea>
    ${mcqBlock}
    <div class="q-img-upload-row">
      <label class="q-img-upload-label">
        <span>&#128247; Add/replace diagram image
          <span class="q-img-optional">(optional)</span>
        </span>
        <input type="file" accept="image/*" class="q-img-file-input"
               id="qimg-${secIdx}-${qIdx}"
               onchange="previewQuestionImage(${secIdx},${qIdx},this)" />
      </label>
      ${hasImg
        ? `<button class="btn btn-sm q-img-clear-btn"
                   onclick="clearQuestionImage(${secIdx},${qIdx})">&#10005; Remove image</button>`
        : ''}
    </div>
    ${hasImg
      ? `<div class="q-img-preview-wrap">
           <img src="${q.image_data_url}" class="q-img-preview" id="qimgprev-${secIdx}-${qIdx}" />
         </div>`
      : `<div class="q-img-preview-wrap" id="qimgprev-wrap-${secIdx}-${qIdx}" style="display:none">
           <img class="q-img-preview" id="qimgprev-${secIdx}-${qIdx}" />
         </div>`}
    <div class="q-img-size-row" id="qimgsize-wrap-${secIdx}-${qIdx}"
         ${hasImg ? '' : 'style="display:none"'}>
      <span class="q-img-size-label">Image size:
        <strong id="qimgsize-val-${secIdx}-${qIdx}">${curSize}%</strong>
      </span>
      <input type="range" min="20" max="100" step="5" value="${curSize}"
             class="q-img-size-slider" id="qimgslider-${secIdx}-${qIdx}"
             oninput="document.getElementById('qimgsize-val-${secIdx}-${qIdx}').textContent=this.value+'%'" />
      <span style="font-size:0.75rem;color:var(--text-secondary)">
        Small&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Large
      </span>
    </div>
    ${answerBlock}
    <div class="q-edit-btns">
      <button class="btn btn-primary btn-sm"
              onclick="saveQuestion(${secIdx},${qIdx})">&#10003; Save</button>
      <button class="btn btn-outline btn-sm"
              onclick="cancelEditQuestion()">Cancel</button>
    </div>
  `;
  document.getElementById(`qedit-${secIdx}-${qIdx}`).focus();
}

function previewQuestionImage(secIdx, qIdx, input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    // Store temporarily in the question object (will be committed on Save)
    state.questionPaper.sections[secIdx].questions[qIdx]._pendingImage = dataUrl;
    // Show preview image
    const prevImg = document.getElementById(`qimgprev-${secIdx}-${qIdx}`);
    if (prevImg) prevImg.src = dataUrl;
    const prevWrap = document.getElementById(`qimgprev-wrap-${secIdx}-${qIdx}`);
    if (prevWrap) prevWrap.style.display = 'block';
    // Reveal size slider (hidden until an image exists)
    const sizeWrap = document.getElementById(`qimgsize-wrap-${secIdx}-${qIdx}`);
    if (sizeWrap) sizeWrap.style.display = 'flex';
  };
  reader.readAsDataURL(file);
}

function clearQuestionImage(secIdx, qIdx) {
  state.questionPaper.sections[secIdx].questions[qIdx].image_data_url = '';
  state.questionPaper.sections[secIdx].questions[qIdx]._pendingImage  = '';
  renderQuestionPaper(state.questionPaper);
  // Re-open edit mode so user can continue editing
  editQuestion(secIdx, qIdx);
}

function saveQuestion(secIdx, qIdx) {
  const ta = document.getElementById(`qedit-${secIdx}-${qIdx}`);
  if (!ta) return;

  const section     = state.questionPaper.sections[secIdx];
  const q           = section.questions[qIdx];
  const sectionType = section.type || '';
  const isMCQ       = (sectionType === 'mcq' || sectionType === 'assertion_reason');

  q.text = ta.value.trim();

  // Commit any pending image
  if (q._pendingImage !== undefined) {
    q.image_data_url = q._pendingImage || '';
    delete q._pendingImage;
  }
  // Persist image size from slider
  if (q.image_data_url) {
    const slider = document.getElementById(`qimgslider-${secIdx}-${qIdx}`);
    if (slider) q.image_size = parseInt(slider.value, 10) || 60;
  }

  if (isMCQ) {
    // Save updated options
    const labels = ['A', 'B', 'C', 'D'];
    q.options = labels.map((lbl, i) => {
      const input = document.getElementById(`qopt-${secIdx}-${qIdx}-${i}`);
      const val   = input ? input.value.trim() : '';
      return val ? `${lbl}) ${val}` : (q.options && q.options[i] ? q.options[i] : `${lbl}) —`);
    });
    // Save correct answer from radio selection
    const radio = document.querySelector(`input[name="qcorrect-${secIdx}-${qIdx}"]:checked`);
    if (radio && state.questionPaper.answer_key) {
      const qId     = q.q_id || '';
      const akEntry = state.questionPaper.answer_key.find(a => a.q_id === qId);
      if (akEntry) akEntry.answer = radio.value;
    }
  } else {
    // Non-MCQ: free-text answer key update
    const answerTa = document.getElementById(`qanswer-${secIdx}-${qIdx}`);
    if (answerTa) {
      const newAnswer = answerTa.value.trim();
      if (newAnswer && state.questionPaper.answer_key) {
        const qId = q.q_id || '';
        let akEntry = state.questionPaper.answer_key.find(a => a.q_id === qId);
        if (akEntry) {
          akEntry.answer = newAnswer;
        } else if (qId) {
          // Create a new answer key entry if one didn't exist
          state.questionPaper.answer_key.push({ q_id: qId, answer: newAnswer });
        }
      }
    }
  }

  renderQuestionPaper(state.questionPaper);
  showToast('Question updated!', 'success');
}


function cancelEditQuestion() {
  // Clean up any pending image that wasn't saved
  (state.questionPaper?.sections || []).forEach(sec =>
    (sec.questions || []).forEach(q => { delete q._pendingImage; })
  );
  renderQuestionPaper(state.questionPaper);
}

/* ===== REGENERATE SINGLE QUESTION ===== */
async function regenerateQuestion(secIdx, qIdx) {
  const paper = state.questionPaper;
  if (!paper) return;

  const section     = paper.sections[secIdx];
  const q           = section.questions[qIdx];
  const sectionType = section.type || 'short_answer';
  const isMCQ       = (sectionType === 'mcq' || sectionType === 'assertion_reason');

  const btn = document.getElementById(`qregen-${secIdx}-${qIdx}`);
  if (btn) {
    btn.disabled    = true;
    btn.textContent = '⏳ Generating…';
  }

  // Collect context from the paper
  const info        = paper.paper_info || {};
  const subject     = info.subject || '';
  const class_num   = info.class  || '';
  const board       = info.board  || 'CBSE';
  const marks       = q.marks || 1;
  const currentText = q.text || '';

  // Chapter list (stored on paper_info.chapters as a comma-separated string)
  const chapStr  = info.chapters || '';
  const chapters = chapStr ? chapStr.split(',').map(s => s.trim()).filter(Boolean) : [];

  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 45000);   // 45-second timeout

    const resp = await fetch('/api/regenerate-question', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ section_type: sectionType, subject, class_num, board,
                                marks, chapters, current_text: currentText }),
      signal:  ctrl.signal,
    });
    clearTimeout(timeout);

    const data = await resp.json();

    if (!resp.ok || data.error) {
      showToast(data.error || 'Regeneration failed — please try again.', 'error');
      return;
    }

    const nq = data.question;   // { text, options?, correct_answer?, answer?, explanation? }

    // ── Fill the question textarea ──────────────────────────────────────────
    const ta = document.getElementById(`qedit-${secIdx}-${qIdx}`);
    if (ta && nq.text) ta.value = nq.text;

    if (isMCQ && Array.isArray(nq.options)) {
      // ── Fill MCQ option inputs ────────────────────────────────────────────
      const labels = ['A', 'B', 'C', 'D'];
      nq.options.forEach((opt, i) => {
        const inp = document.getElementById(`qopt-${secIdx}-${qIdx}-${i}`);
        if (inp) inp.value = String(opt).replace(/^[\(\[]?[A-Da-d][\)\]\.]\s*/i, '').trim();
      });

      // ── Pre-select correct-answer radio ────────────────────────────────────
      const correctLetter = (nq.correct_answer || '').trim().toUpperCase().charAt(0);
      if (correctLetter) {
        const radio = document.querySelector(
          `input[name="qcorrect-${secIdx}-${qIdx}"][value="${correctLetter}"]`
        );
        if (radio) radio.checked = true;
      }
    } else if (!isMCQ) {
      // ── Fill answer textarea ──────────────────────────────────────────────
      const ans = nq.answer || nq.explanation || '';
      const ansTA = document.getElementById(`qanswer-${secIdx}-${qIdx}`);
      if (ansTA && ans) ansTA.value = ans;
    }

    showToast('Question regenerated — review and save when ready.', 'success');

  } catch (err) {
    if (err.name === 'AbortError') {
      showToast('Regeneration timed out — please try again.', 'error');
    } else {
      showToast('Regeneration failed: ' + err.message, 'error');
    }
  } finally {
    if (btn) {
      btn.disabled    = false;
      btn.textContent = '🔄 Regenerate';
    }
  }
}

/* ===== PRINT & DOWNLOAD ===== */
function printPaper() {
  document.body.classList.remove('print-report');
  window.print();
}

function printReport() {
  document.body.classList.add('print-report');
  window.print();
  // Clean up class after print dialog closes
  window.addEventListener('afterprint', () => {
    document.body.classList.remove('print-report');
  }, { once: true });
}

async function downloadWord() {
  if (!state.questionPaper) {
    showToast('No question paper to download.', 'error');
    return;
  }

  showLoading('Generating Word Document...', 'Building your question paper in .docx format');

  try {
    const formData = new FormData();
    formData.append('paper_json', JSON.stringify(state.questionPaper));
    formData.append('school_name', state.schoolName || '');
    if (state.schoolLogoDataUrl) {
      formData.append('school_logo', state.schoolLogoDataUrl);
    }

    const res = await fetch('/api/download-word', { method: 'POST', body: formData });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || 'Failed to generate Word file.', 'error');
      return;
    }

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `QuestionPaper_${state.subject.replace(/\s+/g, '_')}_Class${state.classNum}.docx`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('Word document downloaded!', 'success');
  } catch (e) {
    showToast('Network error generating Word file.', 'error');
  } finally {
    hideLoading();
  }
}

/* ===== LOADING ===== */
function showLoading(title = 'Processing...', sub = '') {
  document.getElementById('loading-title').textContent = title;
  document.getElementById('loading-sub').textContent = sub;
  document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
  document.getElementById('loading-overlay').style.display = 'none';
}

/* ===== TOAST ===== */
let toastTimeout;
function showToast(message, type = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast ${type} show`;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('show'), 3500);
}

/* ===== UTILITIES ===== */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(text)));
  return div.innerHTML;
}

function escapeAttr(text) {
  return String(text).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/* ===== DRAG AND DROP for answer sheet ===== */
const answerZone = document.getElementById ? document.getElementById('answer-upload-zone') : null;
if (answerZone) {
  answerZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    answerZone.classList.add('dragover');
  });
  answerZone.addEventListener('dragleave', () => answerZone.classList.remove('dragover'));
  answerZone.addEventListener('drop', (e) => {
    e.preventDefault();
    answerZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) {
      state.answerSheetFile = file;
      document.getElementById('upload-filename').textContent = `✓ ${file.name} (${formatFileSize(file.size)})`;
      answerZone.style.borderColor = 'var(--success)';
      answerZone.style.background = 'var(--success-bg)';
      showToast(`File ready: ${file.name}`, 'success');
    }
  });
}
