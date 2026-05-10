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
  answerSheetFile: null
};

/* ===== INIT ===== */
document.addEventListener('DOMContentLoaded', () => {
  loadBoards();
  checkLoginState();
  updateMarksTotal();

  document.getElementById('class_num').addEventListener('change', onClassChange);
  document.getElementById('subject').addEventListener('change', onSubjectChange);

  // Close profile menu when clicking outside
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('profile-menu');
    const chip = document.getElementById('profile-chip');
    if (menu && !menu.contains(e.target) && !chip.contains(e.target)) {
      menu.style.display = 'none';
    }
  });
});

/* ===== AUTH / LOGIN STATE ===== */
async function checkLoginState() {
  try {
    const res = await fetch('/api/user');
    const data = await res.json();
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
  } catch (e) {
    // Auth optional — fail silently
  }
}

function toggleProfileMenu() {
  const menu = document.getElementById('profile-menu');
  menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
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
  const subjSel = document.getElementById('subject');

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
      body: JSON.stringify({ class_num: classNum })
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
      body: JSON.stringify({ class_num: state.classNum, subject: state.subject })
    });
    const data = await res.json();

    container.innerHTML = '';
    if (!data.chapters || data.chapters.length === 0) {
      container.innerHTML = '<div class="loading-chapters">No chapters found for this subject/class.</div>';
      return;
    }

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
  } catch (e) {
    container.innerHTML = '<div class="loading-chapters">Error loading chapters. Please try again.</div>';
  }
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

    if (!res.ok || data.error) {
      showToast(data.error || 'Failed to generate paper.', 'error');
      return;
    }

    state.questionPaper = data.paper;
    state.paperId = data.paper_id || null;
    renderQuestionPaper(data.paper);
    gotoStep(4);
    showToast('Question paper generated successfully!', 'success');
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
        qBody += escapeHtml(q.text || '');
        if (q.options && q.options.length > 0) {
          qBody += `<div class="qp-options">`;
          q.options.forEach(opt => { qBody += `<div class="qp-option">${escapeHtml(opt)}</div>`; });
          qBody += `</div>`;
        }
      } else if (type === 'fill_blank') {
        const text = (q.text || '').replace(/_+/g, '<span class="qp-blank">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>');
        qBody += text;
      } else if (type === 'match') {
        qBody += escapeHtml(q.text || '');
        if (q.column_a && q.column_b) {
          qBody += `<div class="qp-match-table">`;
          const len = Math.max(q.column_a.length, q.column_b.length);
          for (let i = 0; i < len; i++) {
            qBody += `<div class="qp-match-row">
              <span class="qp-match-col-a">${i + 1}. ${escapeHtml(q.column_a[i] || '')}</span>
              <span>${String.fromCharCode(97 + i)}) ${escapeHtml(q.column_b[i] || '')}</span>
            </div>`;
          }
          qBody += `</div>`;
        }
      } else if (type === 'true_false') {
        qBody += escapeHtml(q.text || '') + ' &nbsp; <strong>[True / False]</strong>';
      } else if (type === 'map_work') {
        qBody += escapeHtml(q.text || '') + '<div class="qp-map-hint">[Refer to outline map provided]</div>';
      } else if (type === 'reading_passage' || type === 'reading_poem') {
        qBody += escapeHtml(q.text || '');
        if (q.passage) {
          qBody += `<div class="qp-passage">${escapeHtml(q.passage)}</div>`;
        }
        if (q.sub_questions && q.sub_questions.length > 0) {
          qBody += '<ol class="qp-subq">';
          q.sub_questions.forEach(sq => { qBody += `<li>${escapeHtml(sq)}</li>`; });
          qBody += '</ol>';
        }
      } else {
        qBody += escapeHtml(q.text || '');
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

    if (!res.ok || data.error) {
      showToast(data.error || 'Evaluation failed.', 'error');
      return;
    }

    renderEvaluationReport(data.report);
    showToast('Evaluation complete!', 'success');
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
function openHistoryPanel() {
  document.getElementById('history-panel').classList.add('open');
  document.getElementById('history-overlay').classList.add('open');
  loadHistory();
}

function closeHistoryPanel() {
  document.getElementById('history-panel').classList.remove('open');
  document.getElementById('history-overlay').classList.remove('open');
}

async function loadHistory() {
  const body = document.getElementById('history-panel-body');
  body.innerHTML = '<div class="loading-chapters">Loading history...</div>';

  try {
    const res = await fetch('/api/history');
    const data = await res.json();

    if (!data.papers || data.papers.length === 0) {
      body.innerHTML = `
        <div class="history-empty">
          <div style="font-size:2.5rem;margin-bottom:0.5rem;">&#128196;</div>
          <p>No question papers yet.</p>
          <p style="font-size:0.8rem;color:var(--text-muted);">Generate your first paper to see it here.</p>
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
    const data = await res.json();
    const p = data.paper;
    const evals = data.evaluations || [];

    const date = new Date(p.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

    let html = `
      <button class="btn btn-outline btn-sm" onclick="loadHistory()" style="margin-bottom:1rem;">&#8592; Back to History</button>
      <div class="history-detail-header">
        <div class="history-subject" style="font-size:1.1rem;">${escapeHtml(p.subject)}</div>
        <div class="history-item-meta" style="margin-top:0.35rem;">
          Class ${escapeHtml(String(p.class_num))} &bull; ${escapeHtml(p.board)}<br>
          ${escapeHtml(p.exam_type)} &bull; ${p.total_marks} marks &bull; ${date}
        </div>
        ${p.teacher_name ? `<div class="history-teacher" style="margin-top:0.25rem;">Teacher: ${escapeHtml(p.teacher_name)}</div>` : ''}
      </div>
    `;

    html += `<button class="btn btn-primary btn-sm" onclick="restorePaper(${JSON.stringify(p.paper_json).replace(/"/g, '&quot;')}, ${p.id})" style="margin-bottom:1rem;width:100%;">
      &#128196; Load This Paper
    </button>`;

    if (evals.length > 0) {
      html += `<div class="history-evals-title">Evaluations (${evals.length})</div>`;
      evals.forEach(ev => {
        const evDate = new Date(ev.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
        html += `
          <div class="history-eval-item">
            <div class="history-eval-student">${escapeHtml(ev.student_name || 'Unknown')}</div>
            <div class="history-item-meta">Roll: ${escapeHtml(ev.roll_no || 'N/A')} &bull; ${evDate}</div>
            <div class="history-eval-score">${ev.total_obtained}/${ev.total_marks} &mdash; ${ev.percentage}% &mdash; Grade ${ev.grade}</div>
          </div>
        `;
      });
    } else {
      html += `<div class="history-empty"><p>No evaluations for this paper yet.</p></div>`;
    }

    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<div class="loading-chapters">Error loading paper details.</div>';
  }
}

function restorePaper(paperJsonStr, paperId) {
  try {
    const paper = typeof paperJsonStr === 'string' ? JSON.parse(paperJsonStr) : paperJsonStr;
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
    gotoStep(4);
    showToast('Paper loaded from history!', 'success');
  } catch (e) {
    showToast('Failed to load paper from history.', 'error');
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
