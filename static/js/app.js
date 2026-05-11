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
  selectedChapters: [],
  chapterImages: [],
  questionTypes: {},
  questionPaper: null,
  paperId: null,
  answerSheetFile: null,
  currentUser: null,
};

/* ===== INIT ===== */
document.addEventListener('DOMContentLoaded', async () => {
  // Auth gate — check login state first, then decide what to show
  let user = null;
  try {
    const res = await fetch('/api/user');
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

  document.getElementById('board').addEventListener('change', onClassChange);
  document.getElementById('class_num').addEventListener('change', onClassChange);
  document.getElementById('subject').addEventListener('change', onSubjectChange);

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
  const btn = document.getElementById('login-submit-btn');
  const errEl = document.getElementById('login-error');
  btn.disabled = true;
  btn.textContent = 'Signing in...';
  errEl.style.display = 'none';
  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.getElementById('login-email').value.trim(),
        password: document.getElementById('login-password').value,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error;
      errEl.style.display = 'block';
    } else {
      window.location.reload();
    }
  } catch (e) {
    errEl.textContent = 'Network error. Please try again.';
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
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: document.getElementById('reg-name').value.trim(),
        email: document.getElementById('reg-email').value.trim(),
        password,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error;
      errEl.style.display = 'block';
    } else {
      window.location.reload();
    }
  } catch (e) {
    errEl.textContent = 'Network error. Please try again.';
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
    const res = await fetch('/api/user');
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
async function onClassChange() {
  const classNum = document.getElementById('class_num').value;
  const board    = document.getElementById('board').value;
  const subjSel  = document.getElementById('subject');

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

    subjSel.innerHTML = '<option value="">Select Subject...</option>';
    data.subjects.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      subjSel.appendChild(opt);
    });
    subjSel.disabled = false;
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
  window.scrollTo({ top: 0, behavior: 'smooth' });
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

  document.getElementById('marks-target').textContent = state.totalMarks;
  updateMarksTotal();

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

/* ===== CHAPTERS ===== */
async function loadChapters() {
  const container = document.getElementById('chapters-container');
  container.innerHTML = '<div class="loading-chapters">Loading chapters...</div>';

  try {
    const res = await fetch('/api/chapters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ class_num: state.classNum, subject: state.subject, board: state.board })
    });
    const data = await res.json();

    container.innerHTML = '';
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
    await loadCustomChapters();
  } catch (e) {
    container.innerHTML = '<div class="loading-chapters">Error loading chapters. Please try again.</div>';
  }
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
  document.getElementById('chapter-count').textContent =
    `${state.selectedChapters.length} chapter${state.selectedChapters.length !== 1 ? 's' : ''} selected`;
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
  const grid = document.getElementById('qt-grid');
  grid.innerHTML = `<div class="loading-chapters">Loading question types for ${escapeHtml(subject)}...</div>`;

  try {
    const res = await fetch(`/api/question-types?subject=${encodeURIComponent(subject)}`);
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
            <input type="number" id="${key}-marks" value="${defaultMarks}" min="1" max="20"
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
    const count = parseInt(document.getElementById(`${key}-count`)?.value || '0');
    const marks = parseInt(document.getElementById(`${key}-marks`)?.value || '0');
    const subtotal = count * marks;
    total += subtotal;
    const el = document.getElementById(`${key}-total`);
    if (el) el.textContent = subtotal;
  });

  document.getElementById('marks-counter').textContent = total;
  const target = state.totalMarks;
  const statusEl = document.getElementById('marks-status');

  if (total === target) {
    statusEl.textContent = '✓ Matches target';
    statusEl.className = 'marks-ok';
  } else if (total > target) {
    statusEl.textContent = `▲ ${total - target} over target`;
    statusEl.className = 'marks-over';
  } else {
    statusEl.textContent = `▼ ${target - total} under target`;
    statusEl.className = 'marks-under';
  }
}

function collectQuestionTypes() {
  const result = {};
  document.querySelectorAll('.qt-card[data-key]').forEach(card => {
    const key = card.dataset.key;
    const enabled = document.getElementById(`enable-${key}`)?.checked;
    if (!enabled) return;
    const count = parseInt(document.getElementById(`${key}-count`)?.value || '0');
    const marks = parseInt(document.getElementById(`${key}-marks`)?.value || '0');
    if (count > 0) result[key] = { count, marks };
  });
  return result;
}

/* ===== FORMAT FORMULA (superscript / subscript) ===== */
function formatFormula(rawText) {
  // 1. HTML-escape
  const e = String(rawText)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  // 2. Apply sup/sub
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
    formData.append('chapters', JSON.stringify(state.selectedChapters));
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

  let html = `
    <div class="qp-header">
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
          <span class="qp-meta-value">${info.date || '___________'}</span>
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
  (paper.sections || []).forEach(section => {
    html += `
      <div class="qp-section">
        <div class="qp-section-header">
          <span class="qp-section-title">${escapeHtml(section.section_name || '')}</span>
          <span class="qp-section-inst">${escapeHtml(section.instructions || '')}</span>
        </div>
    `;

    (section.questions || []).forEach((q) => {
      const type = section.type;
      html += `<div class="qp-question"><div class="qp-question-row">`;
      html += `<span class="qp-q-num">${globalQNum}.</span>`;

      let qBody = `<div class="qp-q-text">`;

      if (type === 'mcq' || type === 'assertion_reason') {
        qBody += formatFormula(q.text || '');
        if (q.options && q.options.length > 0) {
          qBody += `<div class="qp-options">`;
          q.options.forEach(opt => { qBody += `<div class="qp-option">${formatFormula(opt)}</div>`; });
          qBody += `</div>`;
        }
      } else if (type === 'fill_blank') {
        const text = formatFormula(q.text || '').replace(/_+/g, '<span class="qp-blank">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>');
        qBody += text;
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
      } else if (type === 'true_false') {
        qBody += formatFormula(q.text || '') + ' &nbsp; <strong>[True / False]</strong>';
      } else if (type === 'map_work') {
        qBody += formatFormula(q.text || '') + '<div class="qp-map-hint">[Refer to outline map provided]</div>';
      } else if (type === 'reading_passage' || type === 'reading_poem') {
        qBody += formatFormula(q.text || '');
        if (q.passage) {
          qBody += `<div class="qp-passage">${escapeHtml(q.passage)}</div>`;
        }
        if (q.sub_questions && q.sub_questions.length > 0) {
          qBody += '<ol class="qp-subq">';
          q.sub_questions.forEach(sq => { qBody += `<li>${formatFormula(sq)}</li>`; });
          qBody += '</ol>';
        }
      } else {
        qBody += formatFormula(q.text || '');
      }

      qBody += `</div>`;
      html += qBody;
      html += `<span class="qp-q-marks">[${q.marks || 1} mark${(q.marks || 1) > 1 ? 's' : ''}]</span>`;
      html += `</div></div>`;
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
