import os
import json
import io
import uuid
import tempfile
import re
import time
from datetime import datetime, timezone, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from google import genai
from google.genai import types as genai_types
from PIL import Image
from werkzeug.utils import secure_filename

# ── Flask-SQLAlchemy ──────────────────────────────────────────────────────────
from flask_sqlalchemy import SQLAlchemy

# ── Flask-Login ───────────────────────────────────────────────────────────────
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user, current_user, login_required,
)

# ── Authlib (Google OAuth) — imported conditionally so app works without it ──
try:
    from authlib.integrations.flask_client import OAuth
    _AUTHLIB_AVAILABLE = True
except ImportError:
    _AUTHLIB_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# APP INITIALISATION
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'examcraft_india_secret_key_2024')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Cache-busting: changes on every server restart (every Render deploy)
_STATIC_VERSION = str(int(time.time()))

@app.context_processor
def inject_static_version():
    return {'static_v': _STATIC_VERSION}

# Database — prefer PostgreSQL (DATABASE_URL env var on Render), fall back to SQLite
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_db_url = os.environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(BASE_DIR, 'examcraft.db')}"
# Render provides "postgres://" but SQLAlchemy 1.4+ requires "postgresql://"
if _db_url.startswith('postgres://'):
    _db_url = 'postgresql://' + _db_url[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Login manager
login_manager = LoginManager(app)
login_manager.login_view = None  # API app — no redirect

UPLOAD_FOLDER = tempfile.mkdtemp()
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt'}

# Google OAuth credentials
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
_OAUTH_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and _AUTHLIB_AVAILABLE)

# Set up Authlib OAuth object only when credentials are present
if _OAUTH_CONFIGURED:
    oauth = OAuth(app)
    google_oauth = oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )
else:
    oauth = None
    google_oauth = None

CONTACT_EMAIL = 'arun.kmr06@gmail.com'

# ═══════════════════════════════════════════════════════════════════════════════
# SYMBOL NORMALISATION — converts LaTeX backslash commands and HTML entity names
# for Greek letters / maths operators to their Unicode equivalents so they render
# correctly in both the on-screen paper and the Word-doc download.
# ═══════════════════════════════════════════════════════════════════════════════

_LATEX_TO_UNICODE = {
    # ── Greek lowercase ───────────────────────────────────────────────────────
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\varepsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η',
    r'\theta': 'θ', r'\vartheta': 'ϑ', r'\iota': 'ι', r'\kappa': 'κ',
    r'\lambda': 'λ', r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ',
    r'\pi': 'π', r'\varpi': 'ϖ', r'\rho': 'ρ', r'\varrho': 'ϱ',
    r'\sigma': 'σ', r'\varsigma': 'ς', r'\tau': 'τ', r'\upsilon': 'υ',
    r'\phi': 'φ', r'\varphi': 'φ', r'\chi': 'χ', r'\psi': 'ψ', r'\omega': 'ω',
    # ── Greek uppercase ───────────────────────────────────────────────────────
    r'\Alpha': 'Α', r'\Beta': 'Β', r'\Gamma': 'Γ', r'\Delta': 'Δ',
    r'\Epsilon': 'Ε', r'\Zeta': 'Ζ', r'\Eta': 'Η', r'\Theta': 'Θ',
    r'\Iota': 'Ι', r'\Kappa': 'Κ', r'\Lambda': 'Λ', r'\Mu': 'Μ',
    r'\Nu': 'Ν', r'\Xi': 'Ξ', r'\Pi': 'Π', r'\Rho': 'Ρ',
    r'\Sigma': 'Σ', r'\Tau': 'Τ', r'\Upsilon': 'Υ', r'\Phi': 'Φ',
    r'\Chi': 'Χ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
    # ── Maths operators / relations ───────────────────────────────────────────
    r'\times': '×', r'\div': '÷', r'\pm': '±', r'\mp': '∓', r'\cdot': '·',
    r'\leq': '≤', r'\le': '≤', r'\geq': '≥', r'\ge': '≥',
    r'\neq': '≠', r'\ne': '≠', r'\approx': '≈', r'\equiv': '≡',
    r'\propto': '∝', r'\sim': '∼', r'\simeq': '≃',
    r'\infty': '∞', r'\partial': '∂', r'\nabla': '∇',
    r'\sum': '∑', r'\prod': '∏', r'\int': '∫',
    r'\in': '∈', r'\notin': '∉',
    r'\subset': '⊂', r'\supset': '⊃', r'\subseteq': '⊆', r'\supseteq': '⊇',
    r'\cup': '∪', r'\cap': '∩', r'\emptyset': '∅',
    r'\rightarrow': '→', r'\to': '→', r'\leftarrow': '←',
    r'\leftrightarrow': '↔', r'\Rightarrow': '⇒', r'\Leftarrow': '⇐',
    r'\Leftrightarrow': '⟺', r'\uparrow': '↑', r'\downarrow': '↓',
    r'\angle': '∠', r'\perp': '⊥', r'\parallel': '∥',
    r'\triangle': '△', r'\square': '□', r'\therefore': '∴', r'\because': '∵',
    r'\circ': '°', r'\degree': '°',
    r'\ldots': '…', r'\cdots': '⋯', r'\vdots': '⋮', r'\ddots': '⋱',
    r'\forall': '∀', r'\exists': '∃', r'\nexists': '∄',
    r'\oplus': '⊕', r'\otimes': '⊗', r'\odot': '⊙',
    r'\langle': '⟨', r'\rangle': '⟩',
}

# Sort keys longest-first so longer commands match before shorter prefixes
_LATEX_KEYS_SORTED = sorted(_LATEX_TO_UNICODE.keys(), key=len, reverse=True)

_HTML_ENTITY_TO_UNICODE = {
    '&alpha;': 'α', '&beta;': 'β', '&gamma;': 'γ', '&delta;': 'δ',
    '&epsilon;': 'ε', '&zeta;': 'ζ', '&eta;': 'η', '&theta;': 'θ',
    '&iota;': 'ι', '&kappa;': 'κ', '&lambda;': 'λ', '&mu;': 'μ',
    '&nu;': 'ν', '&xi;': 'ξ', '&pi;': 'π', '&rho;': 'ρ',
    '&sigma;': 'σ', '&tau;': 'τ', '&upsilon;': 'υ', '&phi;': 'φ',
    '&chi;': 'χ', '&psi;': 'ψ', '&omega;': 'ω',
    '&Alpha;': 'Α', '&Beta;': 'Β', '&Gamma;': 'Γ', '&Delta;': 'Δ',
    '&Epsilon;': 'Ε', '&Zeta;': 'Ζ', '&Eta;': 'Η', '&Theta;': 'Θ',
    '&Iota;': 'Ι', '&Kappa;': 'Κ', '&Lambda;': 'Λ', '&Mu;': 'Μ',
    '&Nu;': 'Ν', '&Xi;': 'Ξ', '&Pi;': 'Π', '&Rho;': 'Ρ',
    '&Sigma;': 'Σ', '&Tau;': 'Τ', '&Upsilon;': 'Υ', '&Phi;': 'Φ',
    '&Chi;': 'Χ', '&Psi;': 'Ψ', '&Omega;': 'Ω',
    '&times;': '×', '&divide;': '÷', '&plusmn;': '±', '&middot;': '·',
    '&le;': '≤', '&ge;': '≥', '&ne;': '≠', '&asymp;': '≈',
    '&equiv;': '≡', '&infin;': '∞', '&part;': '∂',
    '&sum;': '∑', '&prod;': '∏', '&int;': '∫',
    '&rArr;': '⇒', '&lArr;': '⇐', '&hArr;': '⟺',
    '&rarr;': '→', '&larr;': '←', '&harr;': '↔',
    '&ang;': '∠', '&perp;': '⊥', '&there4;': '∴',
    '&deg;': '°', '&hellip;': '…', '&sdot;': '·',
}


def _normalize_symbols(text: str) -> str:
    """Convert LaTeX-style symbol commands and HTML entity names to Unicode.

    Examples
    --------
    _normalize_symbols(r'\\alpha + \\beta') → 'α + β'
    _normalize_symbols('&theta; = 30°')    → 'θ = 30°'
    _normalize_symbols(r'\\sqrt{x}')       → '√(x)'
    _normalize_symbols(r'\\frac{a}{b}')    → '(a)/(b)'
    """
    import re as _re
    s = str(text)

    # 1. HTML entities first (before escaping could touch the ampersands)
    for entity, uni in _HTML_ENTITY_TO_UNICODE.items():
        s = s.replace(entity, uni)

    # 2. Special LaTeX constructs with braced arguments
    s = _re.sub(r'\\sqrt\{([^}]+)\}', r'√(\1)', s)        # \sqrt{x} → √(x)
    s = _re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1)/(\2)', s)  # \frac{a}{b}
    s = _re.sub(r'\\(?:overline|hat|vec|bar|tilde|dot|ddot)\{([^}]+)\}',
                r'\1', s)                                    # decorations → plain

    # 3. LaTeX symbol commands (longest-match first, must not be followed by a letter)
    for cmd in _LATEX_KEYS_SORTED:
        uni = _LATEX_TO_UNICODE[cmd]
        # Escape the backslash for the regex; ensure not followed by another letter
        pattern = re.escape(cmd) + r'(?![a-zA-Z])'
        s = _re.sub(pattern, uni, s)

    return s


def _email_body(name, email, mobile, school_name, message, request_type):
    return (
        f"ExamCraft India - New {request_type.title()} Request\n\n"
        f"Name:    {name}\n"
        f"Email:   {email}\n"
        f"Mobile:  {mobile or 'Not provided'}\n"
        f"School:  {school_name or 'Not provided'}\n"
        f"Type:    {request_type.title()}\n\n"
        f"Message:\n{message or 'No message provided'}\n\n"
        f"---\nReceived at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )


def _send_via_resend(subject, body):
    """Send via Resend HTTP API — works on all hosts, never blocked by firewall."""
    import requests as http
    api_key = os.environ.get('RESEND_API_KEY', '').strip()
    try:
        resp = http.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}',
                     'Content-Type': 'application/json'},
            json={'from': 'ExamCraft India <onboarding@resend.dev>',
                  'to': [CONTACT_EMAIL],
                  'subject': subject,
                  'text': body},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            print(f'[EMAIL] Sent via Resend to {CONTACT_EMAIL}')
            return True, None
        err = f'Resend API returned {resp.status_code}: {resp.text}'
        print(f'[EMAIL ERROR] {err}')
        return False, err
    except Exception as e:
        err = f'Resend request failed: {e}'
        print(f'[EMAIL ERROR] {err}')
        return False, err


def _smtp_message(subject, smtp_user, reply_to, body):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = smtp_user
    msg['To']      = CONTACT_EMAIL
    msg['Reply-To'] = reply_to
    msg.attach(MIMEText(body, 'plain'))
    return msg.as_string()


def _send_via_smtp(subject, reply_to, body):
    """Try Gmail SSL (port 465) first, then STARTTLS (port 587) as fallback."""
    smtp_user = os.environ.get('SMTP_USER', '').strip()
    smtp_pass = os.environ.get('SMTP_PASS', '').replace(' ', '').strip()
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    raw = _smtp_message(subject, smtp_user, reply_to, body)

    # ── Attempt 1: SSL on port 465 (most reliable on cloud hosts) ────────────
    try:
        print(f'[EMAIL] Trying SMTP SSL port 465 → {smtp_host}')
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=15) as srv:
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, CONTACT_EMAIL, raw)
        print(f'[EMAIL] Sent via SSL to {CONTACT_EMAIL}')
        return True, None
    except smtplib.SMTPAuthenticationError:
        err = ('Gmail authentication failed. '
               'Make sure SMTP_USER is your full Gmail address and '
               'SMTP_PASS is a Gmail App Password (not your normal password). '
               'Also confirm 2-Step Verification is ON at myaccount.google.com.')
        print(f'[EMAIL ERROR] {err}')
        return False, err          # Auth errors won't be fixed by retrying
    except Exception as e:
        print(f'[EMAIL] SSL port 465 failed ({e}) — trying STARTTLS port 587')

    # ── Attempt 2: STARTTLS on port 587 ──────────────────────────────────────
    try:
        print(f'[EMAIL] Trying SMTP STARTTLS port 587 → {smtp_host}')
        with smtplib.SMTP(smtp_host, 587, timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, CONTACT_EMAIL, raw)
        print(f'[EMAIL] Sent via STARTTLS to {CONTACT_EMAIL}')
        return True, None
    except smtplib.SMTPAuthenticationError:
        err = ('Gmail authentication failed. '
               'SMTP_PASS must be a Gmail App Password, not your regular password.')
        print(f'[EMAIL ERROR] {err}')
        return False, err
    except Exception as e:
        err = f'Both SMTP methods failed. Last error: {e}'
        print(f'[EMAIL ERROR] {err}')
        return False, err


def send_contact_email(name, email, mobile, school_name, message, request_type):
    subject = (f'ExamCraft India - '
               f'{"Callback Request" if request_type == "callback" else "Contact Request"}'
               f' from {name}')
    body = _email_body(name, email, mobile, school_name, message, request_type)

    # Resend HTTP API takes priority (most reliable on any host)
    if os.environ.get('RESEND_API_KEY', '').strip():
        return _send_via_resend(subject, body)

    # Fall back to Gmail SMTP (tries port 465 SSL, then 587 STARTTLS)
    if os.environ.get('SMTP_USER', '').strip():
        return _send_via_smtp(subject, email, body)

    print('[EMAIL] No email service configured — set RESEND_API_KEY or SMTP_USER/SMTP_PASS')
    return False, 'No email service configured'


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    google_id     = db.Column(db.String(128), unique=True, nullable=True)   # optional
    email         = db.Column(db.String(256), unique=True, nullable=False)
    name          = db.Column(db.String(256))
    picture       = db.Column(db.String(512))
    password_hash = db.Column(db.String(256))
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    papers      = db.relationship('QuestionPaper', backref='user', lazy=True)
    evaluations = db.relationship('Evaluation', backref='user', lazy=True)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class QuestionPaper(db.Model):
    __tablename__ = 'question_papers'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    session_id  = db.Column(db.String(64), nullable=False)
    board       = db.Column(db.String(128))
    class_num   = db.Column(db.String(8))
    subject     = db.Column(db.String(128))
    exam_type   = db.Column(db.String(64))
    teacher_name= db.Column(db.String(256))
    total_marks = db.Column(db.Integer)
    paper_json  = db.Column(db.Text)
    archived    = db.Column(db.Boolean, default=False, server_default='0', nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    evaluations = db.relationship('Evaluation', backref='paper', lazy=True)


class Evaluation(db.Model):
    __tablename__ = 'evaluations'
    id             = db.Column(db.Integer, primary_key=True)
    paper_id       = db.Column(db.Integer, db.ForeignKey('question_papers.id'), nullable=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    session_id     = db.Column(db.String(64), nullable=False)
    student_name   = db.Column(db.String(256))
    roll_no        = db.Column(db.String(64))
    report_json    = db.Column(db.Text)
    total_obtained = db.Column(db.Float)
    total_marks    = db.Column(db.Float)
    percentage     = db.Column(db.Float)
    grade          = db.Column(db.String(8))
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class UserSubscription(db.Model):
    __tablename__ = 'user_subscriptions'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    plan            = db.Column(db.String(20), default='free')   # free / pro / school
    status          = db.Column(db.String(20), default='active') # active / cancelled
    stripe_sub_id   = db.Column(db.String(200))
    razorpay_sub_id = db.Column(db.String(200))
    period_end      = db.Column(db.DateTime)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class CustomChapter(db.Model):
    __tablename__ = 'custom_chapters'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject    = db.Column(db.String(100), nullable=False)
    class_num  = db.Column(db.String(10), nullable=False)
    chapter    = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ContactRequest(db.Model):
    __tablename__ = 'contact_requests'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(256), nullable=False)
    school_name  = db.Column(db.String(256))
    email        = db.Column(db.String(256), nullable=False)
    mobile       = db.Column(db.String(20))
    message      = db.Column(db.Text)
    request_type = db.Column(db.String(20), default='contact')
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class UserProfile(db.Model):
    """Stores per-user preferences: teacher name, school info, and logo.
    One row per user — upserted via /api/user-profile endpoints."""
    __tablename__ = 'user_profiles'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    teacher_name = db.Column(db.String(256))
    school_name  = db.Column(db.String(256))
    school_logo  = db.Column(db.Text)   # base64 data-URL (may be large)
    updated_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ═══════════════════════════════════════════════════════════════════════════════
# PLANS & SUBSCRIPTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

# Admin accounts — unlimited access, no restrictions
ADMIN_EMAILS = {'rajmft@gmail.com', 'arun.kmr06@gmail.com'}

PLANS = {
    'free':   {'name': 'Free',   'price_monthly': 0,    'papers_per_month': 10, 'evals_per_month': 15, 'features': ['10 papers / month', '15 evaluations / month', 'All boards & subjects', 'PDF & Word download']},
    'pro':    {'name': 'Pro',    'price_monthly': 299,  'papers_per_month': -1, 'evals_per_month': -1, 'features': ['Unlimited papers', 'Unlimited evaluations', 'Word download', 'Priority support', 'Everything in Free']},
    'school': {'name': 'School', 'price_monthly': 2999, 'papers_per_month': -1, 'evals_per_month': -1, 'features': ['Everything in Pro', 'Up to 10 teacher accounts', 'School branding', 'Dedicated support']},
    'admin':  {'name': 'Admin',  'price_monthly': 0,    'papers_per_month': -1, 'evals_per_month': -1, 'features': ['Unlimited everything']},
}


def get_user_plan(user_id):
    user = db.session.get(User, user_id)
    if user and user.email in ADMIN_EMAILS:
        return 'admin', PLANS['admin']
    sub = UserSubscription.query.filter_by(user_id=user_id).first()
    plan_key = sub.plan if sub else 'free'
    return plan_key, PLANS.get(plan_key, PLANS['free'])


def get_user_usage(user_id):
    from sqlalchemy import extract
    now = datetime.now(timezone.utc)
    papers = QuestionPaper.query.filter(
        QuestionPaper.user_id == user_id,
        extract('year',  QuestionPaper.created_at) == now.year,
        extract('month', QuestionPaper.created_at) == now.month,
    ).count()
    evals = Evaluation.query.filter(
        Evaluation.user_id == user_id,
        extract('year',  Evaluation.created_at) == now.year,
        extract('month', Evaluation.created_at) == now.month,
    ).count()
    return {'papers': papers, 'evals': evals}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def get_session_id():
    """Return (and lazily create) a stable anonymous session UUID."""
    if 'sid' not in session:
        session['sid'] = str(uuid.uuid4())
    return session['sid']


def get_gemini_client():
    api_key = os.environ.get('GOOGLE_API_KEY', '')
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


# Models tried in order — 2.5 Flash first, fall back to 2.0 Flash if unavailable
_GEMINI_MODELS = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash']


def gemini_generate(client, contents, config, max_retries=3):
    """
    Call generate_content with retry + exponential backoff for transient errors
    (503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED, 500 INTERNAL).
    Falls back to gemini-2.0-flash if 2.5-flash is persistently unavailable.
    """
    _RETRYABLE = ('503', '429', '500', 'UNAVAILABLE', 'RESOURCE_EXHAUSTED', 'INTERNAL')

    for model in _GEMINI_MODELS:
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents, config=config)
                if attempt > 0 or model != _GEMINI_MODELS[0]:
                    print(f'[GEMINI] Success with {model} on attempt {attempt + 1}')
                return resp
            except Exception as e:
                last_err = e
                err_str = str(e)
                if not any(code in err_str for code in _RETRYABLE):
                    raise          # non-transient — don't retry
                if attempt < max_retries:
                    wait = 2 ** (attempt + 1)   # 2 s, 4 s, 8 s
                    print(f'[GEMINI] {model} attempt {attempt + 1} failed ({err_str[:100]}), '
                          f'retrying in {wait}s…')
                    time.sleep(wait)
                else:
                    print(f'[GEMINI] {model} exhausted {max_retries} retries — '
                          f'{"trying fallback model" if model == _GEMINI_MODELS[0] else "giving up"}')
        # If we get here all retries for this model failed — try next model

    raise last_err   # all models exhausted


# Valid characters that may follow a backslash inside a JSON string
_VALID_JSON_ESC = frozenset('"\\/ bfnrtu')


def _fix_json_strings(text):
    """Walk the raw text character-by-character and fix problems inside JSON
    string values:
      1. Bare control characters (newline, tab, CR) → proper escape sequences.
      2. Invalid escape sequences (e.g. \\p, \\m, \\s from LaTeX-style notation)
         → double the backslash so they become valid literal backslashes.
    This covers both the original 'unescaped control char' error and the newer
    'Invalid \\escape' error produced by Gemini's math/science output."""
    result = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_string:
            if c == '\\' and i + 1 < len(text):
                nxt = text[i + 1]
                if nxt in _VALID_JSON_ESC:
                    # Valid escape sequence — copy both chars verbatim
                    result.append(c)
                    i += 1
                    result.append(text[i])
                else:
                    # Invalid escape (e.g. \p, \m, \s, \f used as LaTeX) —
                    # escape the backslash so the char after it is kept as-is
                    result.append('\\\\')
                    # Do NOT advance i; the loop will handle nxt on the next pass
            elif c == '"':
                in_string = False
                result.append(c)
            elif c == '\n':
                result.append('\\n')
            elif c == '\r':
                result.append('\\r')
            elif c == '\t':
                result.append('\\t')
            elif ord(c) < 0x20:
                pass  # drop other control chars
            else:
                result.append(c)
        else:
            if c == '"':
                in_string = True
            result.append(c)
        i += 1
    return ''.join(result)


def extract_json(text):
    """Robustly extract and parse JSON from an AI model response.

    Attempts five progressive strategies:
    1. Direct parse (response was already valid JSON).
    2. Strip markdown fences, then parse.
    3. Extract outermost { … } block, then parse.
    4. Apply common structural fixes (trailing commas, NaN/Infinity/undefined),
       then parse.
    5. Fix unescaped control characters inside string values, then parse.
    Raises JSONDecodeError only when all five strategies fail.
    """
    # Pre-processing: replace NaN/Infinity/undefined before any parse attempt.
    # Python's json.loads silently accepts NaN (producing float('nan')) which
    # would later cause json.dumps to emit invalid JSON.
    raw = re.sub(r'\b(NaN|-?Infinity|undefined)\b', 'null', text.strip())

    # ── Stage 1: direct parse ──────────────────────────────────────────────────
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # ── Stage 2: strip markdown fences ────────────────────────────────────────
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw, flags=re.MULTILINE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # ── Stage 3: extract outermost { … } block ────────────────────────────────
    start = cleaned.find('{')
    end   = cleaned.rfind('}')
    if start == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", cleaned, 0)
    extracted = cleaned[start:end + 1]
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        pass

    # ── Stage 4: fix trailing commas ──────────────────────────────────────────
    fixed = re.sub(r',\s*([}\]])', r'\1', extracted)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # ── Stage 5: fix unescaped control chars in strings ───────────────────────
    fully_fixed = _fix_json_strings(fixed)
    return json.loads(fully_fixed)   # let this raise if still broken


def _enforce_paper_specs(paper, question_types):
    """Post-process AI output to enforce exact question counts, exact marks per
    question, and well-formed passage sub-questions.

    For every section whose type matches a teacher-configured question type:
      • Sets q['marks'] to the exact teacher-specified value on every question.
      • Trims the question list to the requested count if AI over-generated.
      • For reading_passage / reading_poem: ensures sub_questions are objects
        with 'text' and 'marks' fields and that their marks are distributed so
        they sum to the section total.
    """
    if not paper or not isinstance(paper.get('sections'), list):
        return paper

    # Build lookup:  type_key → {count, marks}
    qt_spec: dict = {}
    for key, cfg in (question_types or {}).items():
        c = int(cfg.get('count', 0))
        m = float(cfg.get('marks', 1))
        if c > 0:
            qt_spec[key] = {'count': c, 'marks': m}

    for section in paper['sections']:
        sec_type = section.get('type', '')
        spec = qt_spec.get(sec_type)
        if not spec:
            continue

        target_count = spec['count']
        target_marks = spec['marks']
        questions    = section.get('questions', [])

        # ── Fix section instructions (AI often writes wrong marks there) ──────
        mf = int(target_marks) if target_marks == int(target_marks) else target_marks
        mw = f"{mf} mark{'s' if target_marks != 1 else ''}"
        _INST_MAP = {
            'mcq':              f"Choose the correct option. Each question carries {mw}.",
            'assertion_reason': f"Select the correct assertion-reason combination. Each carries {mw}.",
            'true_false':       f"State whether the following are True or False. Each carries {mw}.",
            'fill_blank':       f"Fill in the blanks with appropriate words. Each carries {mw}.",
            'match':            f"Match Column A with Column B. Each question carries {mw}.",
            'short_answer':     f"Answer the following questions briefly. Each carries {mw}.",
            'long_answer':      f"Answer the following questions in detail. Each carries {mw}.",
            'reading_passage':  "Read the following passage carefully and answer the questions that follow.",
            'reading_poem':     "Read the following poem carefully and answer the questions that follow.",
            'grammar':          f"Attempt the following grammar exercises. Each carries {mw}.",
            'writing':          f"Attempt the following writing task. It carries {mw}.",
            'literature_short': f"Answer the following questions briefly. Each carries {mw}.",
            'literature_long':  f"Answer the following questions in detail. Each carries {mw}.",
            'diagram':          f"Draw neat, labelled diagrams as required. Each carries {mw}.",
            'geometry_diagram': f"Construct the geometric figure(s) as described. Show all steps and label clearly. Each carries {mw}.",
            'numerical':        f"Solve the following numerical problems. Each carries {mw}.",
            'source_based':     f"Study the source carefully and answer the questions. Each carries {mw}.",
            'map_work':         f"On the outline map provided, locate and label as directed. Each carries {mw}.",
            'chemical_eq':      f"Balance or write the required chemical equations. Each carries {mw}.",
            'practical':        f"Answer the following practical-based questions. Each carries {mw}.",
            'program':          f"Write programs as required. Each carries {mw}.",
            'output':           f"Write the output for the following code. Each carries {mw}.",
            'error':            f"Find and correct the errors in the following. Each carries {mw}.",
        }
        section['instructions'] = _INST_MAP.get(
            sec_type, f"Attempt all questions. Each carries {mw}."
        )

        for q in questions:
            # ── Enforce marks ──────────────────────────────────────────────────
            q['marks'] = target_marks

            # ── Passage sub-questions ──────────────────────────────────────────
            if sec_type in ('reading_passage', 'reading_poem'):
                subs = q.get('sub_questions') or []
                if subs:
                    # Normalise to list of {'text': ..., 'marks': ...} dicts
                    normalised = []
                    for s in subs:
                        if isinstance(s, dict):
                            normalised.append({
                                'text':  s.get('text', str(s)),
                                'marks': float(s.get('marks', 1)),
                            })
                        else:
                            normalised.append({'text': str(s), 'marks': 0.0})

                    # Distribute target_marks across sub-questions
                    n = len(normalised)
                    # If they already have explicit per-sub marks, keep relative weights
                    raw_total = sum(s['marks'] for s in normalised)
                    if raw_total > 0:
                        for s in normalised:
                            s['marks'] = round(s['marks'] / raw_total * target_marks * 2) / 2
                            s['marks'] = max(0.5, s['marks'])
                    else:
                        # All zero / plain strings — distribute evenly
                        per_sub = round(target_marks / n * 2) / 2
                        per_sub = max(0.5, per_sub)
                        for s in normalised:
                            s['marks'] = per_sub

                    q['sub_questions'] = normalised

        # ── Trim excess questions ──────────────────────────────────────────────
        if len(questions) > target_count:
            section['questions'] = questions[:target_count]

    return paper


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(file_path):
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ''
            for page in reader.pages:
                text += page.extract_text() + '\n'
        return text.strip()
    except Exception as e:
        return f"[Could not extract PDF text: {str(e)}]"


def extract_text_from_docx(file_path):
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        return '\n'.join(paragraphs)
    except Exception as e:
        return f"[Could not extract DOCX text: {str(e)}]"


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC DATA — BOARDS
# ═══════════════════════════════════════════════════════════════════════════════

BOARDS = [
    "CBSE",
    "ICSE/ISC (CISCE)",
    "Andhra Pradesh (BSEAP)",
    "Arunachal Pradesh (DBSE)",
    "Assam Secondary (SEBA)",
    "Assam Higher Secondary (AHSEC)",
    "Bihar (BSEB)",
    "Chhattisgarh (CGBSE)",
    "Goa (GBSHSE)",
    "Gujarat (GSEB)",
    "Haryana (HBSE)",
    "Himachal Pradesh (HPBOSE)",
    "Jammu & Kashmir (JKBOSE)",
    "Jharkhand (JAC)",
    "Karnataka (KSEAB)",
    "Kerala (SCERT Kerala)",
    "Madhya Pradesh (MPBSE)",
    "Maharashtra (MSBSHSE)",
    "Manipur Secondary (BSEM)",
    "Manipur Higher Secondary (COHSEM)",
    "Meghalaya (MBOSE)",
    "Mizoram (MBSE)",
    "Nagaland (NBSE)",
    "Odisha Secondary (BSE Odisha)",
    "Odisha Higher Secondary (CHSE Odisha)",
    "Punjab (PSEB)",
    "Rajasthan (RBSE)",
    "Sikkim (BSSE)",
    "Tamil Nadu (Samacheer Kalvi)",
    "Telangana (BSE Telangana)",
    "Tripura (TBSE)",
    "Uttar Pradesh (UPMSP)",
    "Uttarakhand (UBSE)",
    "West Bengal Secondary (WBBSE)",
    "West Bengal Higher Secondary (WBCHSE)",
    "Puducherry",
    "Other",
]


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC DATA — BOARD → REGIONAL LANGUAGE MAPPING
# ═══════════════════════════════════════════════════════════════════════════════
# Regional language(s) are inserted in the subjects list just before "Hindi"
# for the corresponding board, reflecting each state government's language
# policy (Three-Language Formula and state medium mandates).

BOARD_REGIONAL_LANGUAGES = {
    # ── South India ───────────────────────────────────────────────────────────
    "Andhra Pradesh (BSEAP)":              ["Telugu"],
    "Telangana (BSE Telangana)":           ["Telugu"],
    "Karnataka (KSEAB)":                   ["Kannada"],
    "Kerala (SCERT Kerala)":               ["Malayalam"],
    "Tamil Nadu (Samacheer Kalvi)":        ["Tamil"],
    "Puducherry":                           ["Tamil"],
    # ── West India ────────────────────────────────────────────────────────────
    "Maharashtra (MSBSHSE)":               ["Marathi"],
    "Goa (GBSHSE)":                        ["Konkani", "Marathi"],
    "Gujarat (GSEB)":                      ["Gujarati"],
    # ── East India ────────────────────────────────────────────────────────────
    "West Bengal Secondary (WBBSE)":       ["Bengali"],
    "West Bengal Higher Secondary (WBCHSE)": ["Bengali"],
    "Tripura (TBSE)":                      ["Bengali"],
    "Odisha Secondary (BSE Odisha)":       ["Odia"],
    "Odisha Higher Secondary (CHSE Odisha)": ["Odia"],
    "Assam Secondary (SEBA)":             ["Assamese"],
    "Assam Higher Secondary (AHSEC)":     ["Assamese"],
    # ── North & North-West India ──────────────────────────────────────────────
    "Punjab (PSEB)":                       ["Punjabi"],
    "Jammu & Kashmir (JKBOSE)":            ["Urdu"],
    # ── North-East India ──────────────────────────────────────────────────────
    "Manipur Secondary (BSEM)":            ["Manipuri (Meitei)"],
    "Manipur Higher Secondary (COHSEM)":   ["Manipuri (Meitei)"],
    "Mizoram (MBSE)":                      ["Mizo"],
    "Meghalaya (MBOSE)":                   ["Khasi"],
    "Nagaland (NBSE)":                     ["Nagamese"],
    "Sikkim (BSSE)":                       ["Nepali"],
    # ── Boards where Hindi IS the state language (no override needed) ─────────
    # Bihar (BSEB), UP (UPMSP), MP (MPBSE), Rajasthan (RBSE), Haryana (HBSE),
    # Himachal Pradesh (HPBOSE), Jharkhand (JAC), Chhattisgarh (CGBSE),
    # Uttarakhand (UBSE) → Hindi already in SUBJECTS_BY_CLASS, no change needed
}


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC DATA — NCERT CHAPTERS
# ═══════════════════════════════════════════════════════════════════════════════

NCERT_CHAPTERS = {
    "Mathematics": {
        "1": ["Shapes and Spaces", "Numbers from One to Nine", "Addition", "Subtraction",
               "Numbers from Ten to Twenty", "Time", "Measurement", "Numbers from Twenty-one to Fifty",
               "Data Handling", "Patterns", "Numbers", "Money", "How Many"],
        "2": ["What is Long, What is Round?", "Counting in Groups", "How Much Can You Carry?",
               "Counting in Tens", "Patterns", "Footprints", "Jugs and Mugs", "Tens and Ones",
               "My Funday", "Add our Points", "Lines and Lines", "Give and Take",
               "The Longest Step", "Birds Come, Birds Go", "How Many Ponytails?"],
        "3": ["Where to Look From", "Fun with Numbers", "Give and Take", "Long and Short",
               "Shapes and Designs", "Fun with Give and Take", "Time Goes On", "Who is Heavier?",
               "How Many Times?", "Play with Patterns", "Jugs and Mugs", "Can We Share?",
               "Smart Charts!", "Rupees and Paise"],
        "4": ["Building with Bricks", "Long and Short", "A Trip to Bhopal", "Tick-Tick-Tick",
               "The Way The World Looks", "The Junk Seller", "Jugs and Mugs", "Carts and Wheels",
               "Halves and Quarters", "Play with Patterns", "Tables and Shares",
               "How Heavy? How Light?", "Fields and Fences", "Smart Charts"],
        "5": ["The Fish Tale", "Shapes and Angles", "How Many Squares?", "Parts and Wholes",
               "Does it Look the Same?", "Be My Multiple, I'll be Your Factor",
               "Can You See the Pattern?", "Mapping Your Way", "Boxes and Sketches",
               "Tenths and Hundredths", "Area and its Boundary", "Smart Charts",
               "Ways to Multiply and Divide", "How Big? How Heavy?"],
        "6": ["Patterns in Mathematics", "Lines and Angles", "Number Play",
               "Data Handling and Presentation", "Prime Time", "Perimeter and Area",
               "Fractions", "Playing with Constructions", "Symmetry",
               "The Other Side of Zero"],
        # Class 7 uses new NCERT 'Ganita Prakash' Part I + Part II (2025-26 onwards)
        "7": [
            # Part I
            "Large Numbers Around Us", "Arithmetic Expressions",
            "A Peek Beyond the Point", "Expressions Using Letter-Numbers",
            "Parallel and Intersecting Lines", "Number Play",
            "A Tale of Three Intersecting Lines",
            # Part II
            "Geometric Twins", "Integers — Multiplication and Division",
            "Finding Common Ground", "Decimals — Multiplication and Division",
            "Connecting the Dots", "Constructions and Tilings", "Finding the Unknown",
        ],
        # Class 8 uses new NCERT 'Ganita Prakash' Part I + Part II (2025-26 onwards)
        "8": [
            # Part I
            "A Square and A Cube", "Power Play", "A Story of Numbers",
            "Quadrilaterals", "Number Play", "We Distribute, Yet Things Multiply",
            "Proportional Reasoning",
            # Part II
            "Fractions in Disguise", "The Baudhayana-Pythagoras Theorem",
            "Proportional Reasoning-2", "Exploring Some Geometrical Themes",
            "Tales by Dots and Lines", "Algebra Play", "Area",
        ],
        "9": ["Number Systems", "Polynomials", "Coordinate Geometry",
               "Linear Equations in Two Variables",
               "Lines and Angles", "Triangles", "Quadrilaterals",
               "Areas of Parallelograms and Triangles", "Circles",
               "Heron's Formula", "Surface Areas and Volumes", "Statistics", "Probability"],
        "10": ["Real Numbers", "Polynomials", "Pair of Linear Equations in Two Variables",
                "Quadratic Equations", "Arithmetic Progressions", "Triangles",
                "Coordinate Geometry", "Introduction to Trigonometry",
                "Some Applications of Trigonometry", "Circles",
                "Areas Related to Circles", "Surface Areas and Volumes", "Statistics", "Probability"],
        "11": ["Sets", "Relations and Functions", "Trigonometric Functions",
                "Principle of Mathematical Induction",
                "Complex Numbers and Quadratic Equations", "Linear Inequalities",
                "Permutations and Combinations", "Binomial Theorem", "Sequences and Series",
                "Straight Lines", "Conic Sections",
                "Introduction to Three Dimensional Geometry",
                "Limits and Derivatives", "Statistics", "Probability"],
        "12": ["Relations and Functions", "Inverse Trigonometric Functions", "Matrices",
                "Determinants", "Continuity and Differentiability",
                "Application of Derivatives", "Integrals", "Application of Integrals",
                "Differential Equations", "Vector Algebra", "Three Dimensional Geometry",
                "Linear Programming", "Probability"],
    },
    "Science": {
        # Class 6 Science uses the new NCERT 'Curiosity – Part 1' textbook (2024-25 onwards)
        "6": ["The Wonderful World of Science", "Diversity in the Living World",
               "Mindful Eating: A Path to a Healthy Body", "Exploring Magnets",
               "Measurement of Length and Motion", "Materials Around Us",
               "Temperature and its Measurement", "A Journey through States of Water",
               "Methods of Separation in Everyday Life",
               "Living Organisms and their Surroundings", "Nature's Treasure"],
        # Class 7 Science uses new NCERT 'Curiosity – Part 1' textbook (2025-26 onwards)
        "7": ["The Ever-Evolving World of Science", "Exploring Substances: Acidic, Basic and Neutral",
               "Electricity: Circuits and their Components", "The World of Metals and Non-metals",
               "Changes Around Us: Physical and Chemical", "Adolescence: A Stage of Growth and Change",
               "Heat Transfer in Nature", "Measurement of Time and Motion",
               "Life Processes in Animals", "Life Processes in Plants",
               "Light: Shadows and Reflections", "Earth, Moon, and the Sun"],
        # Class 8 Science uses new NCERT 'Curiosity – Part 1' textbook (2025-26 onwards)
        "8": ["Exploring the Investigative World of Science",
               "The Invisible Living World: Beyond Our Naked Eye", "Health: The Ultimate Treasure",
               "Electricity: Magnetic and Heating Effects", "Exploring Forces",
               "Pressure, Winds, Storms, and Cyclones", "Particulate Nature of Matter",
               "Nature of Matter: Elements, Compounds, and Mixtures",
               "The Amazing World of Solutes, Solvents, and Solutions",
               "Light: Mirrors and Lenses", "Keeping Time with the Skies",
               "How Nature Works in Harmony",
               "Our Home: Earth, a Unique Life Sustaining Planet"],
        "9": ["Matter in Our Surroundings", "Is Matter Around Us Pure?",
               "Atoms and Molecules", "Structure of the Atom",
               "The Fundamental Unit of Life", "Tissues",
               "Diversity in Living Organisms", "Motion", "Force and Laws of Motion",
               "Gravitation", "Work and Energy", "Sound", "Why Do We Fall Ill?"],
        "10": ["Chemical Reactions and Equations", "Acids, Bases and Salts",
                "Metals and Non-metals", "Carbon and its Compounds",
                "Periodic Classification of Elements", "Life Processes",
                "Control and Coordination", "How do Organisms Reproduce?",
                "Heredity and Evolution", "Light – Reflection and Refraction",
                "Human Eye and Colourful World", "Electricity",
                "Magnetic Effects of Electric Current", "Sources of Energy",
                "Our Environment"],
    },
    "Physics": {
        "11": ["Physical World", "Units and Measurement", "Motion in a Straight Line",
                "Motion in a Plane", "Laws of Motion", "Work, Energy and Power",
                "System of Particles and Rotational Motion", "Gravitation",
                "Mechanical Properties of Solids", "Mechanical Properties of Fluids",
                "Thermal Properties of Matter", "Thermodynamics", "Kinetic Theory",
                "Oscillations", "Waves"],
        "12": ["Electric Charges and Fields", "Electrostatic Potential and Capacitance",
                "Current Electricity", "Moving Charges and Magnetism",
                "Magnetism and Matter", "Electromagnetic Induction", "Alternating Current",
                "Electromagnetic Waves", "Ray Optics and Optical Instruments",
                "Wave Optics", "Dual Nature of Radiation and Matter", "Atoms", "Nuclei",
                "Semiconductor Electronics"],
    },
    "Chemistry": {
        "11": ["Some Basic Concepts of Chemistry", "Structure of Atom",
                "Classification of Elements and Periodicity in Properties",
                "Chemical Bonding and Molecular Structure", "States of Matter",
                "Thermodynamics", "Equilibrium", "Redox Reactions", "Hydrogen",
                "The s-Block Elements", "The p-Block Elements",
                "Organic Chemistry – Some Basic Principles and Techniques",
                "Hydrocarbons"],
        "12": ["The Solid State", "Solutions", "Electrochemistry", "Chemical Kinetics",
                "General Principles and Processes of Isolation of Elements",
                "The p-Block Elements", "The d- and f-Block Elements",
                "Coordination Compounds", "Haloalkanes and Haloarenes",
                "Alcohols, Phenols and Ethers",
                "Aldehydes, Ketones and Carboxylic Acids", "Amines", "Biomolecules"],
    },
    "Biology": {
        "11": ["The Living World", "Biological Classification", "Plant Kingdom",
                "Animal Kingdom", "Morphology of Flowering Plants",
                "Anatomy of Flowering Plants", "Structural Organisation in Animals",
                "Cell: The Unit of Life", "Biomolecules", "Cell Cycle and Cell Division",
                "Transport in Plants", "Mineral Nutrition",
                "Photosynthesis in Higher Plants", "Respiration in Plants",
                "Plant Growth and Development", "Digestion and Absorption",
                "Breathing and Exchange of Gases", "Body Fluids and Circulation",
                "Excretory Products and their Elimination", "Locomotion and Movement",
                "Neural Control and Coordination",
                "Chemical Coordination and Integration"],
        "12": ["Reproduction in Organisms", "Sexual Reproduction in Flowering Plants",
                "Human Reproduction", "Reproductive Health",
                "Principles of Inheritance and Variation",
                "Molecular Basis of Inheritance", "Evolution",
                "Human Health and Disease",
                "Strategies for Enhancement in Food Production",
                "Microbes in Human Welfare",
                "Biotechnology: Principles and Processes",
                "Biotechnology and its Applications", "Organisms and Populations",
                "Ecosystem", "Biodiversity and Conservation"],
    },
    "Social Science": {
        # Class 6 Social Science uses the new integrated NCERT textbook
        # 'Exploring Society: India and Beyond – Part 1' (2024-25 onwards)
        "6": ["Locating Places on the Earth", "The Beginnings of Indian Civilisation",
               "India: Physical Setting", "The Vedic Period", "Governing Ancient India",
               "India: Climate, Vegetation and Wildlife", "From Villages to Cities",
               "Religious Reforms and New Religions", "Maps and Globe",
               "India: Natural Resources", "Landforms and their Evolution",
               "Empires and Republics (600 BCE – 200 CE)", "Unity in Diversity",
               "The Spread of Indian Culture", "Our Cultural Heritage",
               "Local Government"],
        # Class 7 Social Science uses new integrated NCERT 'Exploring Society – Part 1 & 2' (2025-26 onwards)
        "7": ["Geographical Diversity of India", "Understanding the Weather", "Climates of India",
               "New Beginnings: Cities and States", "The Rise of Empires", "The Age of Reorganisation",
               "The Gupta Era: An Age of Tireless Creativity", "How the Land Becomes Sacred",
               "From the Rulers to the Ruled: Types of Governments",
               "The Constitution of India — An Introduction", "From Barter to Money",
               "Understanding Markets", "The Story of Indian Farming", "India and Her Neighbours",
               "Empires and Kingdoms: 6th to 10th Centuries", "Turning Tides: 11th and 12th Centuries",
               "India, a Home to Many", "The State, the Government, and You",
               "Infrastructure: Engine of India's Development", "Banks and the Magic of Finance"],
        # Class 8 Social Science uses new NCERT 'Exploring Society – Part 1' only (Part 2 recalled by Supreme Court)
        "8": ["Natural Resources and Their Use", "Reshaping India's Political Map",
               "The Rise of the Marathas", "The Colonial Era in India",
               "Universal Franchise and India's Electoral System",
               "The Parliamentary System: Legislature and Executive",
               "Factors of Production"],
        "9": {
            "History": ["The French Revolution",
                        "Socialism in Europe and the Russian Revolution",
                        "Nazism and the Rise of Hitler",
                        "Forest Society and Colonialism",
                        "Pastoralists in the Modern World"],
            "Geography": ["India – Size and Location", "Physical Features of India", "Drainage",
                          "Climate", "Natural Vegetation and Wildlife", "Population"],
            "Civics": ["What is Democracy? Why Democracy?", "Constitutional Design",
                       "Electoral Politics", "Working of Institutions", "Democratic Rights"],
            "Economics": ["The Story of Village Palampur", "People as Resource",
                          "Poverty as a Challenge", "Food Security in India"],
        },
        "10": {
            "History": ["The Rise of Nationalism in Europe", "Nationalism in India",
                        "The Making of a Global World", "The Age of Industrialisation",
                        "Print Culture and the Modern World"],
            "Geography": ["Resources and Development", "Forest and Wildlife Resources",
                          "Water Resources", "Agriculture", "Minerals and Energy Resources",
                          "Manufacturing Industries", "Lifelines of National Economy"],
            "Civics": ["Power Sharing", "Federalism", "Gender, Religion and Caste",
                       "Political Parties", "Outcomes of Democracy", "Challenges to Democracy"],
            "Economics": ["Development", "Sectors of the Indian Economy", "Money and Credit",
                          "Globalisation and the Indian Economy", "Consumer Rights"],
        },
    },
    "English": {
        "6": ["Who Did Patrick's Homework?", "How the Dog Found Himself a New Master!",
               "Taros's Reward", "An Indian – American Woman in Space: Kalpana Chawla",
               "A Different Kind of School", "Who I Am", "Fair Play", "A Game of Chance",
               "Desert Animals", "The Banyan Tree"],
        "7": ["Three Questions", "A Gift of Chappals", "Gopal and the Hilsa Fish",
               "The Ashes That Made Trees Bloom", "Quality", "Expert Detectives",
               "The Invention of Vita-Wonk", "Fire: Friend and Foe",
               "A Bicycle in Good Repair", "The Story of Cricket"],
        "8": ["The Best Christmas Present in the World", "The Tsunami",
               "Glimpses of the Past", "Bepin Choudhury's Lapse of Memory",
               "The Summit Within", "This is Jody's Fawn", "A Visit to Cambridge",
               "A Short Monsoon Diary", "The Great Stone Face–I", "The Great Stone Face–II"],
        "9": ["The Fun They Had", "The Sound of Music", "The Little Girl",
               "A Truly Beautiful Mind", "The Snake and the Mirror", "My Childhood",
               "Packing", "Reach for the Top", "The Bond of Love", "Kathmandu",
               "If I Were You"],
        "10": ["A Letter to God", "Nelson Mandela: Long Walk to Freedom",
                "Two Stories about Flying", "From the Diary of Anne Frank",
                "The Hundred Dresses–I", "The Hundred Dresses–II", "Glimpses of India",
                "Mijbil the Otter", "Madam Rides the Bus", "The Sermon at Benares",
                "The Proposal"],
        "11": ["The Portrait of a Lady", "We're Not Afraid to Die...",
                "Discovering Tut: the Saga Continues", "Landscape of the Soul",
                "The Ailing Planet: the Green Movement's Role", "The Browning Version",
                "The Adventure", "Silk Road"],
        "12": ["The Last Lesson", "Lost Spring", "Deep Water", "The Rattrap", "Indigo",
                "Poets and Pancakes", "The Interview", "Going Places"],
    },
    "Hindi": {
        # ── Primary (Rimjhim series) ──────────────────────────────────────────
        "1": ["झूला", "आम की कहानी", "आम की टोकरी", "पत्ते ही पत्ते",
               "पकौड़ी", "छुक-छुक गाड़ी", "रसोईघर",
               "चूहो! म्याऊँ सो रही है", "बंदर और गिलहरी",
               "पगड़ी", "पतंग", "गेंद-बल्ला",
               "एक बुढ़िया", "मैं भी", "चकई के चकदुम",
               "चार चने", "भगदड़", "हाथी चल्लम चल्लम"],
        "2": ["ऊँट चला", "भालू ने खेली फुटबॉल", "म्याऊँ म्याऊँ!!",
               "अधिक बलवान कौन?", "दोस्त की मदद", "बहुत हुआ",
               "मेरी किताब", "तितली और कली", "बुलबुल",
               "मेरा दोस्त", "जब मुझे साँप ने काटा",
               "सबसे अच्छा पेड़", "मोर"],
        "3": ["कक्कू", "शेखीबाज़ मक्खी", "चाँद वाली अम्मा",
               "मन करता है", "बहादुर बित्तो", "हमसे सब कहते",
               "टिप टिप बूँद पड़ी", "बंदर बाँट",
               "अक्ल बड़ी या भैंस", "मीरा बहन और बाघ",
               "जब मुझे साँप ने काटा", "कब आओगे"],
        "4": ["मन के भोले-भाले बादल", "जैसा सवाल वैसा जवाब",
               "किरमिच की गेंद", "पापा जब बच्चे थे",
               "दोस्त की पोशाक", "नाव बनाओ नाव बनाओ",
               "दान का हिसाब", "कौन", "स्वतन्त्रता की ओर",
               "थप्प रोटी थप्प दाल", "पढ़क्कू की सूझ",
               "सुनीता की पहिया कुर्सी", "हुदहुद", "मुफ़्त ही मुफ़्त"],
        "5": ["राख की रस्सी", "फसलों के त्योहार", "खिलौनेवाला",
               "नन्हा फनकार", "जहाँ चाह वहाँ राह",
               "चिट्ठी का सफ़र", "डाकिए की कहानी कँवरसिंह की ज़ुबानी",
               "वे दिन भी क्या दिन थे", "एक माँ की बेबसी",
               "एक दिन की बादशाहत", "चावल की रोटियाँ",
               "गुरु और चेला", "स्वामी की दादी"],
        # ── Middle school (Vasant Part 1-3) ──────────────────────────────────
        "6": ["वह चिड़िया जो", "बचपन", "नादान दोस्त", "चाँद से थोड़ी सी गप्पें",
               "अक्षरों का महत्त्व", "पार नज़र के", "साथी हाथ बढ़ाना", "ऐसे–ऐसे",
               "टिकट–अलबम", "झाँसी की रानी", "जो देखकर भी नहीं देखते",
               "संसार पुस्तक है", "मैं सबसे छोटी होऊँ", "लोकगीत", "नौकर",
               "वन के मार्ग में", "साँस–साँस में बाँस"],
        "7": ["हम पंछी उन्मुक्त गगन के", "दादी माँ", "हिमालय की बेटियाँ",
               "कठपुतली", "मितव्ययता", "रक्त और हमारा शरीर",
               "पापा खो गए", "शाम — एक किसान", "चिड़िया की बच्ची",
               "अपूर्व अनुभव", "रहीम के दोहे", "कंचा",
               "एक तिनका", "खानपान की बदलती तस्वीर", "नीलकंठ",
               "भोर और बरखा", "वीर कुँवर सिंह",
               "संघर्ष के कारण मैं तुनुकमिजाज हो गया",
               "आश्रम का अनुमानित व्यय", "विप्लव-गायन"],
        "8": ["ध्वनि", "लाख की चूड़ियाँ", "बस की यात्रा",
               "दीवानों की हस्ती", "चिट्ठियों की अनूठी दुनिया",
               "भगवान के डाकिए", "क्या निराश हुआ जाए",
               "यह सबसे कठिन समय नहीं", "कबीर की साखियाँ",
               "कामचोर", "जब सिनेमा ने बोलना सीखा",
               "सुदामा चरित", "जहाँ पहिया है", "अकबरी लोटा",
               "सूरदास के पद", "पानी की कहानी",
               "बाज और साँप", "टोपी"],
        # ── Secondary & Senior Secondary ─────────────────────────────────────
        "9": ["दो बैलों की कथा", "ल्हासा की ओर", "उपभोक्तावाद की संस्कृति",
               "साँवले सपनों की याद",
               "नाना साहब की पुत्री देवी मैना को भस्म कर दिया गया",
               "प्रेमचंद के फटे जूते", "मेरे बचपन के दिन",
               "एक कुत्ता और एक मैना"],
        "10": ["सूरदास के पद", "राम-लक्ष्मण-परशुराम संवाद", "सवैया और कवित्त",
                "आत्मकथ्य", "उत्साह और अट नहीं रही",
                "यह दंतुरहित मुस्कान और फसल", "छाया मत छूना", "कन्यादान",
                "संगतकार", "नेताजी का चश्मा", "बालगोबिन भगत", "लखनवी अंदाज़",
                "मानवीय करुणा की दिव्य चमक", "एक कहानी यह भी",
                "स्त्री शिक्षा के विरोधी कुतर्कों का खंडन",
                "नौबतखाने में इबादत", "संस्कृति"],
        "11": ["हम तौ एक एक करि जाना", "संतों देखत जग बौराना", "वे आँखें",
                "घर की याद", "चंपा काले काले अच्छर नहीं चीन्हती",
                "गालिब के पत्र", "ओ सदानीरा", "आत्मा का ताप"],
        "12": ["आत्म-परिचय, एक गीत", "पतंग",
                "कविता के बहाने, बात सीधी थी पर",
                "कैमरे में बंद अपाहिज", "सहर्ष स्वीकारा है", "उषा", "बादल राग",
                "कवितावली (उत्तर काण्ड से), लक्ष्मण-मूर्च्छा और राम का विलाप",
                "रुबाइयाँ, गज़ल", "छोटा मेरा खेत, बगुलों के पंख"],
    },
    "Sanskrit": {
        "6": ["सुभाषितानि", "दशमः त्वम् असि", "बालिका पाठशाला", "विद्यालयः",
               "वृक्षाः", "समुद्रतटः", "बकस्य प्रतिकारः", "सूक्तिस्तबकः",
               "क्रीडास्पर्धा", "कृषिकाः कर्मवीराः", "पुष्पोत्सवः",
               "विमानयानं रचयाम"],
        # Ruchira Part 2
        "7": ["सुभाषितानि", "दुर्बुद्धिः विनश्यति", "स्वावलम्बनम्",
               "हास्यबालकविसम्मेलनम्", "पण्डिता रमाबाई", "सदाचारः",
               "संकल्पः सिद्धिदायकः", "त्रिकोणक्षेत्रम्",
               "अहमपि विद्यालयं गमिष्यामि", "विश्वबन्धुत्वम्",
               "रामोऽभिषेचनम्"],
        # Ruchira Part 3
        "8": ["सुभाषितानि", "बिलस्य वाणी न कदापि मे श्रुता",
               "डिजीभारतम्", "सदैव पुरतो निधेहि चरणम्",
               "कण्टकेनैव कण्टकम्", "गृहं शून्यं सुतां विना",
               "भारतजनताऽहम्", "संसारसागरस्य नायकाः",
               "सप्तभगिन्यः", "नीतिनवनीतम्",
               "सावित्री बाई फुले", "कः रक्षति कः रक्षितः"],
        "9": ["भारतीवसन्तगीतिः", "स्वर्णकाकः", "गोदोहनम्", "कल्पतरूः",
               "सूक्तिमौक्तिकम्", "भ्रान्तो बालः", "प्रत्यभिज्ञानम्",
               "लौहतुला", "सिकतासेतुः", "जटायोः शौर्यम्"],
        "10": ["शुचिपर्यावरणम्", "बुद्धिर्बलवती सदा", "शिशुलालनम्",
                "जननी तुल्यवत्सला", "सुभाषितानि", "सौहार्दं प्रकृतेः शोभा",
                "विचित्रः साक्षी", "सूक्तयः", "भारतीयसंस्काराः", "नीतिनवनीतम्"],
    },

    # ── Regional Language Chapters (State Board Syllabi) ──────────────────────
    # Chapter titles are in the respective language scripts where applicable.

    "Marathi": {  # Maharashtra Balbharati / Kumarbharati / Yuvakbharati
        "1":  ["माझे घर", "माझी शाळा", "माझी आई", "फुले", "रंग",
                "पाऊस", "प्राणी", "झाडे", "सण", "खेळ", "चंद्र", "सूर्य"],
        "2":  ["मित्र", "पाखरांचे घर", "शेतकरी", "बाजार",
                "पत्र", "गाणे", "निसर्ग", "नदी", "गोष्ट", "माझा देश"],
        "3":  ["एक होती मुलगी", "शूर शिवाजी", "आमची गाय",
                "फुलांची राणी", "गुरुजी", "माझे गाव", "सकाळ",
                "माझ्या बागेत", "पाणी", "हवा", "पृथ्वी"],
        "4":  ["छत्रपती शिवाजी महाराज", "माझ्या स्वप्नातला भारत",
                "हत्ती आणि मुंगी", "झाड आणि वारा",
                "पक्षांचे जग", "समुद्र", "आकाश",
                "चांगले काम", "सण-उत्सव", "माझी भाषा मराठी"],
        "5":  ["भारत माझा देश", "संत तुकाराम", "झाशीची राणी",
                "पाणी वाचवा", "माझे स्वप्न", "श्रावण महिना",
                "डॉ. बाबासाहेब आंबेडकर", "स्वातंत्र्यदिन",
                "निसर्गाची किमया", "मला आवडते"],
        "6":  ["माझ्या मना", "आनंदाचे डोही", "गाय",
                "भगवान गौतम बुद्ध", "पाणी", "हिरवाई",
                "माझी बाई", "खेळ", "परोपकार",
                "शहाणे व्हा", "तरुण भारत", "एक होता राजा"],
        "7":  ["सूर्योदय", "शेतकऱ्याचे मन", "प्रतिज्ञा",
                "माझ्या देशाची माती", "आईची माया",
                "जंगलाचा राजा", "नदीचे गाणे",
                "स्वप्न", "जगात सुंदर ते", "बोधकथा",
                "आपली भाषा", "माझे आजोबा"],
        "8":  ["मेंढपाळाचे गाणे", "गडद निळे जलद भरुनी",
                "रात्री पाऊस पडतो", "पृथ्वीचे प्रेमगीत",
                "जगणे", "माझ्या शाळेची आठवण",
                "आईची भाकर", "गावाकडे", "विज्ञान",
                "क्षितिजाशी", "सुखाच्या जाणिवेने", "नवा देश"],
        "9":  ["छत्रपती शिवाजी महाराज", "माझ्या मना बन दगड",
                "भिक्षुगाथा", "थेंब थेंब सागर झाला",
                "खोद आणि शोध", "दोन दिवस",
                "वाघाची शिकार", "स्वाभिमान",
                "नदी पाहिली नव्हती", "चाफा",
                "आम्ही बाई", "माझे पेशवे"],
        "10": ["वाट पाहताना", "माझ्या शब्दांनो",
                "आकाशाशी जडले नाते", "उतराई",
                "एकटा जीव", "लहानपण देगा देवा",
                "झाले बहु, होणार बहु", "गोडी जीवनाची",
                "मी आहे तुमची मुलगी", "प्रिय नेताजी",
                "क्षितिज", "सत्याग्रह", "उपक्रम"],
        "11": ["यौवनाचे गाणे", "कुणाच्या बापाचे काय जाते",
                "इतिहासाची साक्ष", "मुक्त होण्यासाठी",
                "श्रावणात घन निळा बरसला",
                "एकटी", "पुन्हा एकदा", "अभिमानी",
                "नदीकाठी", "वाऱ्याने हलते रान",
                "मला काय त्याचे", "प्रवास", "कशासाठी"],
        "12": ["वसंतसेना", "घर माझे", "एक आटपाट नगर",
                "युगांत", "माझे घर", "सुखाचे दोन घोट",
                "रात्र आणखी", "तेव्हा सारे जग",
                "मित्रा", "राहिले दूर घर माझे",
                "वाहते पाणी", "एकला चलो रे"],
    },

    "Tamil": {  # Tamil Nadu Samacheer Kalvi
        "1":  ["என் குடும்பம்", "பள்ளி", "விலங்குகள்", "பறவைகள்",
                "நிறங்கள்", "எண்கள்", "பருவங்கள்", "விழாக்கள்", "நாடு"],
        "2":  ["என் ஊர்", "உழவன்", "மழை", "காடு",
                "நட்பு", "வீடு", "தமிழ்", "கடல்", "மரங்கள்"],
        "3":  ["வீரம்", "திருவள்ளுவர்", "அன்னை",
                "இயற்கை", "விளையாட்டு", "சுகாதாரம்",
                "நல்வழி", "ஊக்கம்", "தாய்மொழி"],
        "4":  ["பாரதியார்", "கம்பன்", "ஔவையார்",
                "அறிவியல்", "காணி நிலம்", "என் தமிழ்",
                "நம் நாடு", "வரலாறு", "சுற்றுச்சூழல்"],
        "5":  ["புரட்சிக்கவி", "மணிவாசகர்", "திருக்குறள்",
                "செந்தமிழ்", "வீரத்தமிழ்", "நல்வழி",
                "இந்தியா", "விடுதலை", "நதிகள்", "மலைகள்"],
        "6":  ["காடு", "மழை", "மதிப்பெண்", "திருவள்ளுவர்",
                "பாரதிதாசன்", "ஔவையார்", "வீர மாமனிதர்",
                "அறிவின் ஊற்று", "இயற்கை அழகு",
                "திருக்குறள்", "மொழியின் வலிமை", "கண்ணதாசன்"],
        "7":  ["வாழ்க்கை வழிகாட்டி", "ஜி. யு. போப்",
                "செல்வாக்கு", "விண்ணை தோட்டம்",
                "வாழ்வியல் நூல்கள்", "நம் மொழி",
                "பூமியின் கதை", "இலக்கியம்",
                "சங்க இலக்கியம்", "கபிலர்", "நக்கீரர்"],
        "8":  ["அணி இலக்கணம்", "யாப்பிலக்கணம்",
                "தொல்காப்பியம்", "சிலப்பதிகாரம்",
                "மணிமேகலை", "கம்பராமாயணம்",
                "திருவாசகம்", "நாலடியார்",
                "புறப்பொருள்", "அகப்பொருள்",
                "நிழல் வீடு", "வாழும் தமிழ்"],
        "9":  ["தமிழ் இலக்கிய வரலாறு", "குறுந்தொகை",
                "அகநானூறு", "புறநானூறு",
                "திருக்குறள் — அறத்துப்பால்",
                "திருக்குறள் — பொருட்பால்",
                "கம்பன் காட்டும் இராமன்", "இளங்கோவடிகள்",
                "பாரதியார் கவிதைகள்", "ஆசுகவிஞர்கள்",
                "இக்கால இலக்கியம்"],
        "10": ["திருக்குறள் — காமத்துப்பால்",
                "சிறுகதை", "கவிதை", "நாவல்",
                "உரைநடை", "வாழ்க்கை வரலாறு",
                "பெரியார் சிந்தனைகள்", "அம்பேத்கர்",
                "விஞ்ஞானம்", "சுற்றுச்சூழல்",
                "தமிழ் — உலக மொழி"],
        "11": ["சங்க இலக்கியம் — அகம்", "சங்க இலக்கியம் — புறம்",
                "காப்பிய இலக்கியம்", "பக்தி இலக்கியம்",
                "நீதி இலக்கியம்", "உரைநடை இலக்கியம்",
                "புதுக்கவிதை", "சிறுகதை — உலகம்",
                "தமிழ் இலக்கண அடிப்படைகள்",
                "மொழியியல்", "தமிழக வரலாறு"],
        "12": ["இலக்கிய விமர்சனம்", "கவிதை — சீர்திருத்தம்",
                "நாடகம்", "தமிழ் தத்துவம்",
                "திருவள்ளுவர் — தத்துவம்",
                "பாரதியார் — தேசியம்",
                "மகாகவி கவிதை", "உலகத்தமிழ்",
                "தமிழ் — செம்மொழி", "இலக்கண முடிவுகள்"],
    },

    "Telugu": {  # Andhra Pradesh / Telangana State Board
        "1":  ["నా కుటుంబం", "నా పాఠశాల", "జంతువులు", "పక్షులు",
                "రంగులు", "సంఖ్యలు", "ఋతువులు", "పండుగలు"],
        "2":  ["నా ఊరు", "రైతు", "వర్షం", "అడవి",
                "స్నేహం", "ఇల్లు", "తెలుగు", "సముద్రం"],
        "3":  ["వీరత్వం", "నన్నయ", "అమ్మ",
                "ప్రకృతి", "ఆట", "ఆరోగ్యం",
                "జ్ఞానం", "మాతృభాష"],
        "4":  ["ఉమ్మడి కుటుంబం", "కృష్ణదేవరాయ",
                "శ్రీనాథుడు", "పోతన",
                "మన తెలుగు", "వరలక్ష్మి",
                "ఆంధ్రప్రదేశ్", "భారతదేశం"],
        "5":  ["తెలంగాణ", "శ్రీకాళహస్తి",
                "భద్రాచలం", "రాయలసీమ",
                "తెలుగు సాహిత్యం", "వీరనారి",
                "సమాజసేవ", "పర్యావరణం"],
        "6":  ["పద్య సాహిత్యం", "గద్య సాహిత్యం",
                "పోతన భాగవతం", "నన్నయ మహాభారతం",
                "తిక్కన", "ఎర్రన", "శ్రీనాథ కావ్యాలు",
                "అష్టదిగ్గజాలు", "కృష్ణదేవరాయ",
                "మన జిల్లా", "తెలుగు వ్యాకరణం"],
        "7":  ["రామాయణం", "మహాభారతం",
                "భాగవతం", "కావ్య లక్షణాలు",
                "ఛందస్సు", "అలంకారాలు",
                "ప్రాచీన సాహిత్యం", "మధ్యకాల కవులు",
                "ఆధునిక కవిత్వం", "నాటకం"],
        "8":  ["ఆంధ్ర మహాభారతం", "ఆంధ్ర రామాయణం",
                "శతక సాహిత్యం", "వేమన శతకం",
                "సుమతీ శతకం", "నీతి సాహిత్యం",
                "జానపద సాహిత్యం", "ఆధునిక వచనం",
                "స్వాతంత్ర్య సాహిత్యం", "సాహిత్య విమర్శ"],
        "9":  ["నన్నయ పద్యాలు", "తిక్కన పద్యాలు",
                "పోతన పద్యాలు", "శ్రీనాథ పద్యాలు",
                "ఆధునిక కవిత్వం", "కథా సాహిత్యం",
                "నాటక సాహిత్యం", "వ్యాస సాహిత్యం",
                "తెలుగు వ్యాకరణం", "సంధులు — సమాసాలు"],
        "10": ["సహృదయత", "పాండవ ఉద్యోగ విజయాలు",
                "రామాయణ విశేషాలు", "మన సంస్కృతి",
                "ఆధునిక తెలుగు కవులు", "కథానికలు",
                "మహిళా సాధికారత", "విజ్ఞాన వికాసం",
                "తెలుగు ఉపాధ్యాయులు", "భాషా వికాసం"],
        "11": ["ప్రాచీన కావ్యాలు", "మధ్యకాల సాహిత్యం",
                "ఆధునిక సాహిత్యం", "నవల",
                "కథ", "నాటకం", "వ్యాసం",
                "తెలుగు భాషా చరిత్ర",
                "పాశ్చాత్య సాహిత్య ప్రభావం",
                "విమర్శ సాహిత్యం"],
        "12": ["సాహిత్య సిద్ధాంతాలు", "రసాభాస",
                "నవ్య కవిత్వం", "దళిత సాహిత్యం",
                "స్త్రీ సాహిత్యం", "అనువాద సాహిత్యం",
                "తెలుగు భాష — భవిష్యత్తు",
                "భాషా ప్రణాళిక", "అధ్యయన నైపుణ్యాలు"],
    },

    "Kannada": {  # Karnataka State Board
        "1":  ["ನನ್ನ ಮನೆ", "ನನ್ನ ಶಾಲೆ", "ಪ್ರಾಣಿಗಳು", "ಹಕ್ಕಿಗಳು",
                "ಬಣ್ಣಗಳು", "ಸಂಖ್ಯೆಗಳು", "ಋತುಗಳು", "ಹಬ್ಬಗಳು"],
        "2":  ["ನನ್ನ ಊರು", "ರೈತ", "ಮಳೆ", "ಕಾಡು",
                "ಸ್ನೇಹ", "ಮನೆ", "ಕನ್ನಡ", "ಸಮುದ್ರ"],
        "3":  ["ವೀರ ಕನ್ನಡಿಗ", "ಕಿತ್ತೂರು ರಾಣಿ",
                "ಅಮ್ಮ", "ಪ್ರಕೃತಿ", "ಆರೋಗ್ಯ", "ಜ್ಞಾನ"],
        "4":  ["ಬಸವಣ್ಣ", "ಅಕ್ಕಮಹಾದೇವಿ",
                "ಕನಕದಾಸ", "ಪುರಂದರದಾಸ",
                "ಕರ್ನಾಟಕ ಐತಿಹ್ಯ", "ನಮ್ಮ ಕನ್ನಡ"],
        "5":  ["ರಾಷ್ಟ್ರಕವಿ ಕುವೆಂಪು", "ಡಾ. ರಾಜ್‌ಕುಮಾರ್",
                "ವಿಜಯನಗರ ಸಾಮ್ರಾಜ್ಯ", "ಟಿಪ್ಪು ಸುಲ್ತಾನ್",
                "ಕನ್ನಡ ನಾಡು", "ಪರಿಸರ ಸಂರಕ್ಷಣೆ"],
        "6":  ["ಪಂಪ ಭಾರತ", "ರನ್ನ ಕಾವ್ಯ",
                "ನಾಗಚಂದ್ರ", "ಹರಿಹರ",
                "ರಾಘವಾಂಕ", "ಕುಮಾರವ್ಯಾಸ",
                "ಷಡ್ಪದಿ ಕಾವ್ಯ", "ವಚನ ಸಾಹಿತ್ಯ",
                "ದಾಸ ಕೀರ್ತನೆ", "ಆಧುನಿಕ ಕಾವ್ಯ",
                "ಕನ್ನಡ ವ್ಯಾಕರಣ"],
        "7":  ["ಆದಿಕವಿ ಪಂಪ", "ಕಬ್ಬಿಗ ರನ್ನ",
                "ಜನ್ನ ಕಾವ್ಯ", "ರಾಘವಾಂಕ",
                "ಹರಿಹರ ರಗಳೆ", "ಕುಮಾರವ್ಯಾಸ ಭಾರತ",
                "ಬಸವೇಶ್ವರ ವಚನಗಳು",
                "ಕನಕದಾಸ ಕೀರ್ತನೆ",
                "ಆಧುನಿಕ ಕಥೆ", "ಪ್ರಬಂಧ"],
        "8":  ["ಗದ್ಯ ಸಾಹಿತ್ಯ", "ಪದ್ಯ ಸಾಹಿತ್ಯ",
                "ಏಕಾಂಕ ನಾಟಕ", "ಜೀವನ ಚರಿತ್ರೆ",
                "ಪ್ರವಾಸ ಕಥನ", "ಸ್ವಾತಂತ್ರ್ಯ ಸಾಹಿತ್ಯ",
                "ರಾಷ್ಟ್ರಕವಿ ಕುವೆಂಪು", "ಡಾ. ಯು. ಆರ್. ಅನಂತಮೂರ್ತಿ",
                "ಬೇಂದ್ರೆ ಕಾವ್ಯ", "ಕೆ. ಎಸ್. ನರಸಿಂಹಸ್ವಾಮಿ"],
        "9":  ["ರಾಮಾಯಣ ದರ್ಶನಂ", "ಮಲೆಗಳಲ್ಲಿ ಮದುಮಗಳು",
                "ಕಾನೂರು ಹೆಗ್ಗಡತಿ", "ಸಮ್ಮಕ್ಕ ಕಥೆ",
                "ಬಾಗಿಲು ತೆರೆದು", "ಅಲೆಮಾರಿ",
                "ದ್ಯಾವನೂರು", "ಮೂಕಜ್ಜಿಯ ಕನಸುಗಳು",
                "ಕನ್ನಡ ವ್ಯಾಕರಣ", "ಪ್ರಬಂಧ ಲೇಖನ"],
        "10": ["ಮಾನವ ಜಾತಿ ತಾನೊಂದೆ ವಲಂ",
                "ಬೆಳಗಾಗಿ ಎದ್ದು", "ಉಯ್ಯಾಲೆ",
                "ಭಾರತ ಭಾರತಿ", "ಶಿಶು ಗೀತೆ",
                "ನಮ್ಮ ಕನ್ನಡ", "ಗ್ರಾಮ ಜೀವನ",
                "ರಾಷ್ಟ್ರ ಪ್ರೇಮ", "ಪ್ರಕೃತಿ ಚಿತ್ರ",
                "ಸಾಹಿತ್ಯ ಪ್ರಕಾರಗಳು"],
        "11": ["ಪ್ರಾಚೀನ ಕಾವ್ಯ", "ಮಧ್ಯಕಾಲ ಸಾಹಿತ್ಯ",
                "ಆಧುನಿಕ ಸಾಹಿತ್ಯ", "ನಾಟಕ",
                "ಕಾದಂಬರಿ", "ಕಥೆ",
                "ಕನ್ನಡ ಭಾಷೆಯ ಇತಿಹಾಸ",
                "ಪಾಶ್ಚಾತ್ಯ ಪ್ರಭಾವ", "ವಿಮರ್ಶೆ"],
        "12": ["ಸಾಹಿತ್ಯ ಸಿದ್ಧಾಂತ", "ಕನ್ನಡ ನವ್ಯ ಕಾವ್ಯ",
                "ದಲಿತ ಸಾಹಿತ್ಯ", "ಬಂಡಾಯ ಸಾಹಿತ್ಯ",
                "ನಾಡೋಜ ಕಾದಂಬರಿ", "ಭಾಷಾ ವಿಜ್ಞಾನ",
                "ಅನುವಾದ ಸಿದ್ಧಾಂತ", "ಕನ್ನಡ ಭಾಷಾ ನೀತಿ"],
    },

    "Malayalam": {  # Kerala SCERT
        "1":  ["എന്റെ കുടുംബം", "എന്റെ വിദ്യാലയം", "മൃഗങ്ങൾ",
                "പക്ഷികൾ", "നിറങ്ങൾ", "ആഘോഷങ്ങൾ", "പ്രകൃതി"],
        "2":  ["എന്റെ നാട്", "കർഷകൻ", "മഴ", "കാട്",
                "സ്നേഹം", "വീട്", "മലയാളം", "കടൽ"],
        "3":  ["ഭാരതം", "കേരളം", "അമ്മ",
                "പ്രകൃതി", "കളി", "ആരോഗ്യം",
                "ജ്ഞാനം", "മാതൃഭാഷ"],
        "4":  ["ശ്രീനാരായണഗുരു", "ടിപ്പു സുൽത്താൻ",
                "കേരള വരലാർ", "നമ്മൾ",
                "ആധുനിക കേരളം", "ജ്ഞാനം"],
        "5":  ["ചെറുശ്ശേരി", "ഏഴുത്തച്ഛൻ",
                "കുഞ്ചൻ നമ്പ്യാർ", "ആശാൻ",
                "ഉള്ളൂർ", "വള്ളത്തോൾ",
                "ജി. ശങ്കരക്കുറുപ്പ്", "കേരളം"],
        "6":  ["ഗദ്യം", "പദ്യം", "ഏഴുത്തച്ഛൻ",
                "ചെറുശ്ശേരി", "കൃഷ്ണഗാഥ",
                "കിളിപ്പാട്ട്", "ആട്ടപ്രകാരം",
                "ആശാൻ കവിത", "വള്ളത്തോൾ",
                "ഉള്ളൂർ", "ആധുനിക ഗദ്യം"],
        "7":  ["ഭൂതകണ്ണാടി", "ആദ്യക്കത്ത്",
                "ഒരിടത്ത്", "ജ്ഞാനക്കൊതി",
                "ഒരു ദേശത്തിന്റെ കഥ",
                "ഖസാക്കിന്റെ ഇതിഹാസം",
                "ചെമ്മീൻ", "ഭ്രമരം",
                "ഉത്തരകോസലം", "ലോകവേദം"],
        "8":  ["ഗദ്യ സാഹിത്യ ചരിത്രം",
                "പദ്യ സാഹിത്യ ചരിത്രം",
                "നോവൽ", "ചെറുകഥ",
                "നാടകം", "ലേഖനം",
                "ആത്മകഥ", "യാത്രാ വിവരണം",
                "ബാലസാഹിത്യം", "ആധുനിക കവിത"],
        "9":  ["ഒരു ദേശത്തിന്റെ കഥ", "കായൽ",
                "ഭ്രമരം", "ഉത്തരകോസലം",
                "ഒരു സംഭ്രമം", "ഭൂമിക്ക് ഒരു ചരമഗീതം",
                "ആരണ്യകം", "ഭക്തിഗാനം",
                "ആധുനിക നോവൽ", "ഗദ്യശൈലി"],
        "10": ["കേരളീയ സംസ്കൃതി",
                "ആധുനിക മലയാള കവിത",
                "ആഖ്യാനം", "ആത്മകഥ",
                "ലേഖനം", "പ്രബന്ധം",
                "ഭാഷാ ശാസ്ത്രം", "വ്യാകരണം",
                "അലങ്കാരം", "ഛന്ദസ്"],
        "11": ["ആദ്യകാല ഗദ്യം", "ഭക്തി സാഹിത്യം",
                "മണിപ്രവാളം", "ഗ്രന്ഥഭാഷ",
                "ആധുനിക ഗദ്യം", "ചെറുകഥ",
                "നോവൽ", "ഭാഷാ ചരിത്രം",
                "ഭാഷാ ശാസ്ത്രം"],
        "12": ["കവിത — ആധുനികം", "നോവൽ — ആഖ്യാന",
                "നാടകം — ആധുനികം", "ചരിത്ര ദർശനം",
                "ദലിത് സാഹിത്യം", "സ്ത്രീ സാഹിത്യം",
                "അനുവാദ ചരിത്രം", "ഭാഷാ നയം"],
    },

    "Bengali": {  # West Bengal Board / Tripura Board
        "1":  ["আমার পরিবার", "আমার স্কুল", "পশুপাখি",
                "রঙ", "সংখ্যা", "ঋতু", "উৎসব", "প্রকৃতি"],
        "2":  ["আমার গ্রাম", "কৃষক", "বৃষ্টি", "বন",
                "বন্ধুত্ব", "বাড়ি", "বাংলা", "সমুদ্র"],
        "3":  ["বীরত্ব", "রবীন্দ্রনাথ",
                "মা", "প্রকৃতি", "খেলাধুলা",
                "স্বাস্থ্য", "জ্ঞান", "মাতৃভাষা"],
        "4":  ["নজরুল ইসলাম", "বিদ্যাসাগর",
                "মাইকেল মধুসূদন", "বঙ্কিমচন্দ্র",
                "বাংলার ইতিহাস", "আমাদের বাংলা"],
        "5":  ["রামকৃষ্ণ পরমহংস", "স্বামী বিবেকানন্দ",
                "সুভাষচন্দ্র বসু", "জগদীশ বসু",
                "পশ্চিমবঙ্গ", "পরিবেশ রক্ষা"],
        "6":  ["রবীন্দ্রনাথের কবিতা",
                "নজরুলের কবিতা", "জীবনানন্দ দাশ",
                "মাইকেল মধুসূদন", "বঙ্কিমচন্দ্রের গদ্য",
                "রবীন্দ্রনাথের ছোটগল্প",
                "শরৎচন্দ্রের গদ্য", "বিভূতিভূষণ",
                "মানিক বন্দ্যোপাধ্যায়",
                "বাংলা ব্যাকরণ"],
        "7":  ["গীতাঞ্জলি", "সোনার তরী",
                "মেঘনাদবধ কাব্য", "আনন্দমঠ",
                "পথের পাঁচালী", "দেবদাস",
                "পল্লীসমাজ", "চাঁদের পাহাড়",
                "প্রবন্ধ সাহিত্য", "নাটক সাহিত্য"],
        "8":  ["বাংলা সাহিত্যের ইতিহাস",
                "মঙ্গলকাব্য", "বৈষ্ণব পদাবলী",
                "চর্যাপদ", "রামায়ণ",
                "মহাভারত", "আধুনিক গদ্য",
                "আধুনিক কবিতা", "নাটক", "উপন্যাস"],
        "9":  ["আমি কি ডরাই সখি", "বাঁশি",
                "নোঙর", "আদাব",
                "পথের দাবী", "ইছামতী",
                "বিষবৃক্ষ", "আরণ্যক",
                "বাংলা ব্যাকরণ", "রচনা"],
        "10": ["উদয়ের পথে", "প্রতিদান",
                "পল্লিজননী", "আমার সোনার বাংলা",
                "ক্যামেলিয়া", "দিবারাত্রির কাব্য",
                "পান্থজনের সখা", "মৃত্যুক্ষুধা",
                "বাংলা ভাষা ও সাহিত্য",
                "নির্বাচিত গদ্য"],
        "11": ["প্রাচীন ও মধ্যযুগীয় সাহিত্য",
                "আধুনিক সাহিত্য", "ছোটগল্প",
                "উপন্যাস", "নাটক", "প্রবন্ধ",
                "বাংলা ভাষার ইতিহাস",
                "ভাষাবিজ্ঞান"],
        "12": ["কবিতা — আধুনিকতা",
                "উত্তরআধুনিক সাহিত্য",
                "নারী সাহিত্য", "দলিত সাহিত্য",
                "বাংলা চলচ্চিত্র ও সাহিত্য",
                "তুলনামূলক সাহিত্য",
                "বাংলা ভাষা নীতি"],
    },

    "Gujarati": {  # Gujarat Secondary and Higher Secondary Education Board (GSEB)
        "1":  ["મારું ઘર", "મારી શાળા", "પ્રાણીઓ",
                "પક્ષીઓ", "રંગો", "ઋતુઓ", "તહેવારો"],
        "2":  ["મારું ગામ", "ખેડૂત", "વરસાદ",
                "જંગલ", "મિત્રતા", "ઘર", "ગુજરાત"],
        "3":  ["ભક્તિ", "નરસિંહ મહેતા", "મા",
                "પ્રકૃતિ", "રમત-ગમત", "આરોગ્ય"],
        "4":  ["ગઢ", "ગાંધીજી", "સરદાર પટેલ",
                "ઝવેરચંદ મેઘાણી", "ગુજરાત ઇતિહાસ"],
        "5":  ["ગઢ ગ્રહ ગામ", "ઉત્સવ",
                "ગુજરાતી સાહિત્ય", "ઉદ્ઘોષ",
                "ગ્રામ્ય જીવન", "પ્રકૃતિ"],
        "6":  ["ગઝલ", "ભજન", "નવલિકા",
                "નિબંધ", "ઝવેરચંદ મેઘાણી",
                "ઉમાશંકર જોશી", "સુન્દરમ્",
                "ન્હાનાભાઈ ભટ્ટ",
                "ગુજરાતી ભાષાનો ઇતિહાસ",
                "ગુજરાતી વ્યાકરણ"],
        "7":  ["ભ. ક. ઠાકોર", "ઉમાશંકર",
                "રઘુવીર ચૌધરી", "ગઝલ",
                "ટૂંકી વાર્તા", "નવલકથા",
                "ઓળખ", "ઝ.મે. ઝૂઝ"],
        "8":  ["જૂની ગુજરાતી", "ભક્તિ-જ્ઞાન સાહિત્ય",
                "ઐતિહાસિક ગઝલ", "ઇ. સ. ૧૯મી સ.",
                "ઇ. સ. ૨૦મી સ.", "ગુજરાતી નાટક",
                "ગ. ના. ઠ.", "ધૂ. ભ. ઠ."],
        "9":  ["આ ઘડી રળિયામણી", "ત્રિભેટો",
                "ગામડું", "ઓળખ",
                "ભ. ક. ઠ.ની ગઝલ", "ઉ. જ. ની કવિતા",
                "નવલિકા", "ગ. ના. ઠ. :",
                "ગુજરાતી ભાષા", "ગ. ન. ૧"],
        "10": ["ગ. ન. ૨", "ઓ. આ. ઝ.",
                "ભ. ત. ઘ.", "ન. ભ. ઠ.",
                "ઝ. મ. ઝ.", "ઉ. ટ. ઠ.",
                "ઝ. ભ. ઝ.", "ગ. ઠ. ઝ.",
                "ઉ. ત. ઝ.", "ભ. ઠ. ઝ."],
        "11": ["પ્રાચીન ગુજરાતી સાહિત્ય",
                "ભક્તિ-ઉપાસના સાહિત્ય",
                "આધુનિક ગઝલ", "ટૂંકી વાર્તા",
                "નવલ-ગઝ.", "ગ. ભ. ઇ.",
                "ભ. ઠ. ઉ.", "ઝ. ત. ઈ."],
        "12": ["ઉ. ત. ૧", "ઉ. ત. ૨",
                "ઝ. ભ. ૧", "ઝ. ભ. ૨",
                "ગ. ત. ૧", "ગ. ભ. ૨",
                "ઝ. ઠ. ઝ.", "ઝ. ત. ૩"],
    },

    "Punjabi": {  # Punjab School Education Board (PSEB)
        "1":  ["ਮੇਰਾ ਪਰਿਵਾਰ", "ਮੇਰਾ ਸਕੂਲ", "ਪਸ਼ੂ ਅਤੇ ਪੰਛੀ",
                "ਰੰਗ", "ਗਿਣਤੀ", "ਰੁੱਤਾਂ", "ਤਿਉਹਾਰ"],
        "2":  ["ਮੇਰਾ ਪਿੰਡ", "ਕਿਸਾਨ", "ਮੀਂਹ",
                "ਜੰਗਲ", "ਦੋਸਤੀ", "ਘਰ", "ਪੰਜਾਬ"],
        "3":  ["ਵੀਰਤਾ", "ਗੁਰੂ ਨਾਨਕ ਦੇਵ ਜੀ",
                "ਮਾਂ", "ਕੁਦਰਤ", "ਖੇਡਾਂ"],
        "4":  ["ਭਗਤ ਸਿੰਘ", "ਲਾਲਾ ਲਾਜਪਤ ਰਾਏ",
                "ਮਹਾਰਾਜਾ ਰਣਜੀਤ ਸਿੰਘ",
                "ਪੰਜਾਬ ਦਾ ਇਤਿਹਾਸ", "ਸਾਡਾ ਪੰਜਾਬ"],
        "5":  ["ਗੁਰੂ ਗੋਬਿੰਦ ਸਿੰਘ ਜੀ", "ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ",
                "ਧਰਮ ਅਤੇ ਸੇਵਾ", "ਸ਼ਹੀਦ",
                "ਪੰਜਾਬੀ ਸੱਭਿਆਚਾਰ"],
        "6":  ["ਗੁਰਬਾਣੀ", "ਵਾਰਾਂ",
                "ਸੂਫ਼ੀ ਕਲਾਮ", "ਕਿੱਸੇ",
                "ਕਹਾਣੀ", "ਨਿਬੰਧ",
                "ਪੰਜਾਬੀ ਲੋਕ ਗੀਤ", "ਅਲੱਲ੍ਹ ਯਾਰ",
                "ਭਾਈ ਵੀਰ ਸਿੰਘ", "ਪੰਜਾਬੀ ਵਿਆਕਰਣ"],
        "7":  ["ਕਿੱਸਾ ਕਾਵਿ", "ਗੁਰੁਮਤਿ ਕਾਵਿ",
                "ਵਾਰ ਕਾਵਿ", "ਸੂਫ਼ੀ ਕਾਵਿ",
                "ਅਧੁਨਿਕ ਕਵਿਤਾ", "ਕਹਾਣੀ",
                "ਨਾਵਲ", "ਨਾਟਕ", "ਨਿਬੰਧ"],
        "8":  ["ਕਿੱਸਾ ਹੀਰ ਰਾਂਝਾ", "ਮਿਰਜ਼ਾ ਸਾਹਿਬਾਂ",
                "ਸੱਸੀ ਪੁੰਨੂ", "ਸੋਹਣੀ ਮਹੀਂਵਾਲ",
                "ਗੁਰਬਾਣੀ ਵਿਆਖਿਆ", "ਭਾਈ ਵੀਰ ਸਿੰਘ",
                "ਧਨੀ ਰਾਮ ਚਾਤ੍ਰਿਕ", "ਅਧੁਨਿਕ ਗਦ"],
        "9":  ["ਪੰਜਾਬੀ ਕਵਿਤਾ", "ਪੰਜਾਬੀ ਕਹਾਣੀ",
                "ਪੰਜਾਬੀ ਨਾਵਲ", "ਪੰਜਾਬੀ ਨਾਟਕ",
                "ਪੰਜਾਬੀ ਨਿਬੰਧ",
                "ਪੰਜਾਬੀ ਵਿਆਕਰਣ",
                "ਭਾਵ ਅਤੇ ਵਿਚਾਰ"],
        "10": ["ਸੁਣੋ ਸਖੀਏ", "ਨਾਨਕ ਬਾਣੀ",
                "ਮੇਰਾ ਪੰਜਾਬ", "ਖੇਤਾਂ ਦੀ ਮਿੱਟੀ",
                "ਪੰਜਾਬੀਅਤ", "ਸੱਭਿਆਚਾਰ",
                "ਵਿਦਿਆ", "ਸੇਵਾ ਦਾ ਫਲ",
                "ਪੰਜਾਬੀ ਨਾਵਲ ਅੰਸ਼"],
        "11": ["ਪ੍ਰਾਚੀਨ ਪੰਜਾਬੀ ਸਾਹਿਤ",
                "ਮੱਧਕਾਲੀ ਸਾਹਿਤ",
                "ਅਧੁਨਿਕ ਸਾਹਿਤ", "ਕਹਾਣੀ",
                "ਨਾਵਲ", "ਪੰਜਾਬੀ ਭਾਸ਼ਾ ਇਤਿਹਾਸ",
                "ਭਾਸ਼ਾ ਵਿਗਿਆਨ"],
        "12": ["ਅਧੁਨਿਕ ਕਵਿਤਾ", "ਦਲਿਤ ਸਾਹਿਤ",
                "ਇਸਤਰੀ ਸਾਹਿਤ", "ਪੰਜਾਬੀ ਡਰਾਮਾ",
                "ਅਨੁਵਾਦ", "ਤੁਲਨਾਤਮਕ ਸਾਹਿਤ",
                "ਭਾਸ਼ਾ ਨੀਤੀ"],
    },

    "Odia": {  # Odisha Board (BSE / CHSE)
        "1":  ["ମୋ ଘର", "ମୋ ବିଦ୍ୟାଳୟ", "ପ୍ରାଣୀ", "ପକ୍ଷୀ",
                "ରଙ୍ଗ", "ଋତୁ", "ଉତ୍ସବ", "ପ୍ରକୃତି"],
        "2":  ["ମୋ ଗ୍ରାମ", "କୃଷକ", "ବର୍ଷା",
                "ବଣ", "ବନ୍ଧୁ", "ଘର", "ଓଡ଼ିଶା"],
        "3":  ["ଉତ୍କଳ ଗୌରବ", "ଭାରତ ଇତିହାସ",
                "ମା", "ପ୍ରକୃତି", "ଖେଳ", "ଶ୍ରେୟ"],
        "4":  ["ଉଟକଳ ଭୂମି", "ଜଗନ୍ନାଥ ଧାମ",
                "ମହାତ୍ମା ଗାନ୍ଧୀ", "ଭୀମ ଭୋଇ",
                "ଓଡ଼ିଶା ଇତିହାସ", "ଆମ ଓଡ଼ିଶା"],
        "5":  ["ଭୋଇ ମହିମା", "ଲୋକ ସଂଗୀତ",
                "ଜଗଦ୍ବାଣୀ", "ସ୍ୱାଧୀନତା",
                "ବୋଧ ଗ୍ରନ୍ଥ", "ଓଡ଼ିଆ ସାଂସ୍କୃତି"],
        "6":  ["ଓଡ଼ିଆ ଗଦ୍ୟ", "ଓଡ଼ିଆ ପଦ୍ୟ",
                "ପଞ୍ଚ ସଖା", "ଭଗବତ ଭଜ",
                "ସଂଖ୍ୟ ଦ୍ୟୋ", "ଆଧୁନିକ ସାହିତ୍ୟ",
                "ଓଡ଼ିଆ ବ୍ୟାକରଣ",
                "ଗ. ଦ. ୧", "ପ. ଦ. ୧"],
        "7":  ["ଗ. ଦ. ୨", "ପ. ଦ. ୨",
                "ସ. ଗ. ୧", "ଜ. ପ. ୧",
                "ଏ. ସ. ୧", "ଓ. ସ. ୧"],
        "8":  ["ସ. ଗ. ୨", "ଜ. ପ. ୨",
                "ଏ. ସ. ୨", "ଓ. ଦ. ୧",
                "ଗ. ଦ. ୩", "ପ. ଦ. ୩"],
        "9":  ["ଅଭିଲାଷ", "ଉଷା",
                "ଦ୍ୱୀପ ଥୋଇ ଯାଅ", "ଗୀତ",
                "ଆଧୁନିକ ଓଡ଼ିଆ", "ଓଡ଼ିଆ ବ୍ୟାକରଣ"],
        "10": ["ଆଧୁନିକ ଓ. ସ.", "ଓ. ଭ. ଇ.",
                "ଗ. ସ. ୪", "ସ. ପ. ୪",
                "ନ. ଲ. ୧", "ସ. ଲ. ୧"],
    },

    "Assamese": {  # Assam Board (SEBA / AHSEC)
        "1":  ["মোৰ পৰিয়াল", "মোৰ বিদ্যালয়", "পশু-পক্ষী",
                "ৰং", "সংখ্যা", "ঋতু", "উৎসৱ", "প্ৰকৃতি"],
        "2":  ["মোৰ গাঁও", "কৃষক", "বৰষুণ",
                "হাবি", "বন্ধুত্ব", "ঘৰ", "অসম"],
        "3":  ["বীৰত্ব", "শংকৰদেৱ",
                "মা", "প্ৰকৃতি", "খেল", "জ্ঞান"],
        "4":  ["লক্ষ্মীনাথ বেজবৰুৱা",
                "বিষ্ণু প্ৰসাদ ৰাভা",
                "অসম ইতিহাস", "আমাৰ অসম"],
        "5":  ["জ্যোতিপ্ৰসাদ আগৰৱালা",
                "ভূপেন হাজৰিকা",
                "অসমীয়া সংস্কৃতি",
                "প্ৰাকৃতিক পৰিৱেশ", "স্বাধীনতা"],
        "6":  ["অসমীয়া গদ্য", "অসমীয়া পদ্য",
                "বুৰঞ্জীমূলক সাহিত্য",
                "অংকীয়া নাট", "ফকৰা-যোজনা",
                "নাম-কীৰ্তন", "আধুনিক কবিতা",
                "চুটিগল্প", "অসমীয়া ব্যাকৰণ"],
        "7":  ["বুৰঞ্জী সাহিত্য", "আধুনিক সাহিত্য",
                "কবিতা — ৰোমান্টিক",
                "উপন্যাস", "গল্প", "নাটক",
                "প্ৰবন্ধ", "ভ্ৰমণ কাহিনী"],
        "8":  ["ৰামায়ণ — অসমীয়া",
                "মহাভাৰত — অসমীয়া",
                "বৈষ্ণৱ সাহিত্য", "বাৰোৱাৰী",
                "বেজবৰুৱাৰ সাহিত্য",
                "আধুনিক কবিতা", "চুটিগল্প"],
        "9":  ["অসমীয়া কবিতা", "অসমীয়া কথাসাহিত্য",
                "উপন্যাস খণ্ড", "নাটক খণ্ড",
                "অসমীয়া ব্যাকৰণ"],
        "10": ["সাহিত্য আলোচনা",
                "অসমীয়া কবিতা — নিৰ্বাচিত",
                "গদ্য — নিৰ্বাচিত",
                "ভাষা আৰু ব্যাকৰণ",
                "ৰচনা লিখন"],
    },

    "Urdu": {  # Jammu & Kashmir (primary language) & as second language in many boards
        "1":  ["میرا گھر", "میرا مدرسہ", "جانور", "پرندے",
                "رنگ", "گنتی", "موسم", "تہوار"],
        "2":  ["میرا گاؤں", "کسان", "بارش",
                "جنگل", "دوستی", "گھر", "اردو"],
        "3":  ["بہادری", "بچوں کی کہانی",
                "ماں", "فطرت", "کھیل", "علم"],
        "4":  ["غالب", "میر تقی میر",
                "فیض احمد فیض",
                "علامہ اقبال", "اردو ادب"],
        "5":  ["اردو شاعری", "اردو نثر",
                "ادب اطفال", "قصے کہانیاں",
                "تاریخ اردو", "ہندوستان"],
        "6":  ["غزل", "نظم", "قصیدہ",
                "مرثیہ", "افسانہ",
                "انشائیہ", "سفرنامہ",
                "اردو گرامر", "خط نویسی"],
        "7":  ["میر تقی میر — غزلیات",
                "غالب — کلام",
                "اقبال — نظمیں",
                "فیض — شاعری",
                "اردو افسانے", "ناول"],
        "8":  ["کلاسیکی شاعری", "جدید نظم",
                "ترقی پسند ادب", "اردو صحافت",
                "اردو ڈرامہ", "ادبی تنقید"],
        "9":  ["انتخاب کلام غالب",
                "اقبال کی شاعری",
                "اردو افسانہ نگاری",
                "اردو ناول", "اردو گرامر",
                "انشا پردازی"],
        "10": ["حالی اور شبلی",
                "جدید اردو ادب",
                "مختصر افسانے",
                "مضمون نگاری",
                "اردو زبان کی تاریخ"],
        "11": ["کلاسیکی ادب", "جدید ادب",
                "تنقید", "تحقیق",
                "اردو صرف و نحو", "عروض"],
        "12": ["انیسویں صدی کا ادب",
                "بیسویں صدی کا ادب",
                "ترقی پسند تحریک",
                "جدیدیت", "ما بعد جدیدیت",
                "اردو زبان — مستقبل"],
    },

    "Nepali": {  # Sikkim Board & Darjeeling Hills
        "6":  ["मेरो नेपाल", "नेपाली साहित्य",
                "कविता — भानुभक्त", "कविता — लेखनाथ",
                "गद्य — बालकृष्ण सम",
                "लोककथा", "व्याकरण"],
        "7":  ["भानुभक्त रामायण", "लेखनाथ पौड्याल",
                "लक्ष्मीप्रसाद देवकोटा", "बालकृष्ण सम",
                "गोपालप्रसाद रिमाल",
                "आधुनिक नेपाली कविता", "कथा"],
        "8":  ["देवकोटाको काव्य",
                "नेपाली उपन्यास",
                "नेपाली नाटक",
                "नेपाली कथासाहित्य",
                "नेपाली व्याकरण"],
        "9":  ["पुराना कविता", "नवीन कविता",
                "कथासंग्रह", "उपन्यास",
                "नेपाली भाषाको इतिहास",
                "व्याकरण"],
        "10": ["नेपाली साहित्य चयन",
                "कविता — निर्वाचित",
                "गद्य — निर्वाचित",
                "भाषा र व्याकरण",
                "निबन्ध लेखन"],
    },

    "Konkani": {  # Goa Board
        "1":  ["Mhoje Ghor", "Mhojem Iskol", "Janavari",
                "Pakxi", "Rong", "Rittu", "Utsov"],
        "2":  ["Mhozem Gaum", "Shetkari", "Pavsalem",
                "Ranam", "Bhorvanso", "Ghor", "Goa"],
        "3":  ["Goenkarponn", "Festo",
                "Aai", "Nisorgo", "Khel", "Jnan"],
        "6":  ["Konkani Kavita", "Konkani Gody",
                "Lokgeet", "Nachni",
                "Mando", "Dulpod",
                "Konkani Sahitya Itihas",
                "Konkani Vyakoran"],
        "7":  ["Kavita", "Katha",
                "Novell", "Natak",
                "Prabandh", "Patrakar"],
        "8":  ["Shenoi Goembab", "B.B. Borkar",
                "Manoharrai Sardessai",
                "Konkani Renaissance",
                "Sahitya Prakar"],
        "9":  ["Adhunik Konkani", "Kavita",
                "Katha", "Natak",
                "Vyakoran", "Lekhan"],
        "10": ["Sahitya Chayan",
                "Konkani Bhasha Itihas",
                "Goa — Sanskriti",
                "Nibandh", "Pariksha Lekhan"],
    },

    "Manipuri (Meitei)": {  # Manipur Board
        "6":  ["ꯃꯩꯇꯩꯂꯣꯟ ꯑꯋꯥꯕ", "ꯄꯥꯎꯔꯣꯜ",
                "Meitei Mayek Introduction",
                "Basic Grammar", "Prose", "Poetry"],
        "7":  ["Prose — Selected", "Poetry — Selected",
                "Meitei Literature",
                "Grammar", "Writing Skills"],
        "8":  ["Classical Meitei Literature",
                "Modern Prose", "Modern Poetry",
                "Drama", "Essay", "Grammar"],
        "9":  ["Meitei Sahitya", "Kavita",
                "Katha", "Natak",
                "Meitei Mayek", "Vyakaran"],
        "10": ["Literature — Selected",
                "Prose and Poetry",
                "Manipuri Culture",
                "Grammar", "Essay Writing"],
        "11": ["Classical Literature",
                "Modern Literature",
                "Drama", "Novel",
                "Manipuri Language History"],
        "12": ["Contemporary Literature",
                "Literary Criticism",
                "Translation Studies",
                "Language Policy"],
    },

    "Mizo": {  # Mizoram Board
        "6":  ["Mizo Thu leh Hla", "Zing Thlak",
                "Kan Mizo Tawng", "Grammar",
                "Prose", "Poetry"],
        "7":  ["Mizo Hla", "Thu Siamtu",
                "Prose Selected", "Poetry Selected",
                "Grammar", "Writing"],
        "8":  ["Mizo Zirlai Buk",
                "Classical Mizo",
                "Modern Mizo", "Drama",
                "Essay", "Grammar"],
        "9":  ["Mizo Literature",
                "Prose", "Poetry",
                "Grammar", "Essay Writing"],
        "10": ["Literature Selected",
                "Mizo Culture",
                "Language History",
                "Grammar", "Composition"],
        "11": ["Classical Literature",
                "Modern Literature",
                "Mizo Language Studies"],
        "12": ["Contemporary Literature",
                "Literary Criticism",
                "Mizo Language Policy"],
    },

    "Khasi": {  # Meghalaya Board
        "6":  ["Khasi Jingkieng", "Lum Sohpetbneng",
                "Basic Grammar", "Prose", "Poetry"],
        "7":  ["U Sier Lapalang", "Ka Pynhiar Syiem",
                "Khasi Literature",
                "Grammar", "Writing"],
        "8":  ["Classical Khasi Texts",
                "Modern Prose", "Modern Poetry",
                "Grammar", "Essay"],
        "9":  ["Khasi Literature",
                "Prose and Poetry",
                "Grammar", "Composition"],
        "10": ["Literature Selected",
                "Khasi Culture",
                "Language History",
                "Grammar", "Essay"],
    },

    "Nagamese": {  # Nagaland Board
        "6":  ["Nagamese Basic", "Prose",
                "Poetry", "Grammar", "Stories"],
        "7":  ["Selected Prose", "Selected Poetry",
                "Naga Culture", "Grammar"],
        "8":  ["Nagamese Literature",
                "Modern Prose", "Poetry",
                "Grammar", "Writing"],
        "9":  ["Literature", "Grammar",
                "Culture", "Composition"],
        "10": ["Selected Literature",
                "Nagamese Language",
                "Grammar", "Essay Writing"],
    },

    "Environmental Studies (EVS)": {
        "1": ["My Body", "Good Habits and Safety Rules", "Food We Eat", "Shelter",
               "Family", "Plants Around Us", "Animals Around Us", "Transport",
               "Festivals and Celebrations", "Water", "Air", "The Sky"],
        "2": ["My Family", "Foods We Eat", "Where Do Animals Live?",
               "Our Helpful Friends", "Clothes We Wear", "We All Play", "Keeping Safe",
               "Our Garden", "Water", "Our School"],
        "3": ["Poonam's Day Out", "The Plant Fairy", "Water O Water",
               "Our First School", "Chhotu's House", "Foods We Eat",
               "Saying Without Speaking", "Flying High", "It's Raining",
               "What is Cooking?", "From Here to There", "Work We Do",
               "Sharing Our Feelings", "The Story of Food"],
        "4": ["Going to School", "Ear to Ear", "A Day with Nandu",
               "The Story of Amrita", "Anita and the Honeybees", "Omana's Journey",
               "From the Window", "Reaching Grandmother's House", "Changing Families",
               "Hu Tu Tu, Hu Tu Tu", "The Valley of Flowers", "Changing Times",
               "A River's Tale", "Basva's Farm", "From Market to Home",
               "A Busy Month", "Nandita in Mumbai", "Too Much Water, Too Little Water",
               "Abdul in the Garden", "Eating Together", "Food and Fun",
               "The World in My Home"],
        "5": ["Super Senses", "A Snake Charmer's Story", "From Tasting to Digesting",
               "Mangoes Round the Year", "Seeds and Seeds", "Every Drop Counts",
               "Experiments with Water", "A Treat for Mosquitoes", "Up You Go!",
               "Walls Tell Stories", "Sunita in Space", "What if it Finishes?",
               "A Shelter So High!", "When the Earth Shook!", "Blow Hot, Blow Cold",
               "Who Will Do This Work?", "Across the Wall", "No Place for Us?",
               "A Seed Tells a Farmer's Story", "Whose Forests?",
               "Like Father, Like Daughter", "On the Move Again"],
    },
    "Economics": {
        "11": ["Indian Economy on the Eve of Independence",
                "Indian Economy 1950-1990",
                "Liberalisation, Privatisation and Globalisation: An Appraisal",
                "Poverty", "Human Capital Formation in India", "Rural Development",
                "Employment: Growth, Informalisation and Other Issues",
                "Infrastructure", "Environment and Sustainable Development",
                "Comparative Development Experiences of India and its Neighbours"],
        "12": ["Introduction to Microeconomics", "Theory of Consumer Behaviour",
                "Production and Costs",
                "The Theory of the Firm under Perfect Competition",
                "Market Equilibrium", "Non-competitive Markets",
                "Introduction to Macroeconomics", "National Income Accounting",
                "Money and Banking", "Determination of Income and Employment",
                "Government Budget and the Economy", "Open Economy Macroeconomics"],
    },
    "Business Studies": {
        "11": ["Nature and Purpose of Business", "Forms of Business Organisation",
                "Private, Public and Global Enterprises", "Business Services",
                "Emerging Modes of Business",
                "Social Responsibilities of Business and Business Ethics",
                "Formation of a Company", "Sources of Business Finance",
                "Small Business", "Internal Trade", "International Business"],
        "12": ["Nature and Significance of Management", "Principles of Management",
                "Business Environment", "Planning", "Organising", "Staffing",
                "Directing", "Controlling", "Financial Management",
                "Financial Markets", "Marketing Management", "Consumer Protection"],
    },
    "Accountancy": {
        "11": ["Introduction to Accounting", "Theory Base of Accounting",
                "Recording of Transactions – I", "Recording of Transactions – II",
                "Bank Reconciliation Statement",
                "Trial Balance and Rectification of Errors",
                "Depreciation, Provisions and Reserves", "Bill of Exchange",
                "Financial Statements – I", "Financial Statements – II",
                "Accounts from Incomplete Records",
                "Applications of Computers in Accounting",
                "Computerised Accounting System"],
        "12": ["Accounting for Partnership: Basic Concepts",
                "Change in Profit Sharing Ratio among the Existing Partners",
                "Admission of a Partner", "Retirement and Death of a Partner",
                "Dissolution of Partnership Firm", "Accounting for Share Capital",
                "Issue and Redemption of Debentures",
                "Financial Statements of a Company",
                "Analysis of Financial Statements", "Accounting Ratios",
                "Cash Flow Statement"],
    },
    "History": {
        "11": ["Writing and City Life", "An Empire across Three Continents",
                "An Early Empire", "The Central Islamic Lands", "Nomadic Empires",
                "The Three Orders", "Changing Cultural Traditions",
                "Confrontation of Cultures", "The Industrial Revolution",
                "Displacing Indigenous Peoples", "Paths to Modernisation"],
        "12": ["Bricks, Beads and Bones", "Kings, Farmers and Towns",
                "Kinship, Caste and Class", "Thinkers, Beliefs and Buildings",
                "Through the Eyes of Travellers", "Bhakti-Sufi Traditions",
                "An Imperial Capital: Vijayanagara",
                "Peasants, Zamindars and the State", "Kings and Chronicles",
                "Colonialism and the Countryside", "Rebels and the Raj",
                "Colonial Cities",
                "Mahatma Gandhi and the Nationalist Movement",
                "Understanding Partition", "Framing the Constitution"],
    },
    "Geography": {
        "11": ["Geography as a Discipline", "The Origin and Evolution of the Earth",
                "Interior of the Earth", "Distribution of Oceans and Continents",
                "Minerals and Rocks", "Geomorphic Processes",
                "Landforms and their Evolution",
                "Composition and Structure of Atmosphere",
                "Solar Radiation, Heat Balance and Temperature",
                "Atmospheric Circulation and Weather Systems",
                "Water in the Atmosphere", "World Climate and Climate Change",
                "Water (Oceans)", "Movements of Ocean Water",
                "Life on the Earth", "Biodiversity and Conservation"],
        "12": ["Population: Distribution, Density, Growth and Composition",
                "Migration: Types, Causes and Consequences", "Human Development",
                "Human Settlements", "Land Resources and Agriculture",
                "Water Resources", "Mineral and Energy Resources",
                "Manufacturing Industries",
                "Planning and Sustainable Development in Indian Context",
                "Transport and Communication", "International Trade",
                "Geographical Perspective on Selected Issues and Problems"],
    },
    "Political Science": {
        "11": ["Constitution: Why and How?", "Rights in the Indian Constitution",
                "Election and Representation", "Executive", "Legislature",
                "Judiciary", "Federalism", "Local Governments",
                "Constitution as a Living Document",
                "The Philosophy of the Constitution"],
        "12": ["Cold War Era", "The End of Bipolarity",
                "US Hegemony in World Politics", "Alternative Centres of Power",
                "Contemporary South Asia", "International Organisations",
                "Security in the Contemporary World",
                "Environment and Natural Resources", "Globalisation",
                "Challenges of Nation Building", "Era of One-Party Dominance",
                "Politics of Planned Development", "India's External Relations",
                "Challenges to and Restoration of the Congress System",
                "Crisis of the Constitutional Order", "Rise of Popular Movements",
                "Regional Aspirations", "Recent Developments in Indian Politics"],
    },
    "Computer Science": {
        "11": ["Computer Systems and Organisation", "Encoding Schemes and Number System",
                "Emerging Trends", "Problem Solving", "Getting Started with Python",
                "Flow of Control", "Functions", "Strings", "Lists",
                "Tuples and Dictionary", "Societal Impacts"],
        "12": ["Review of Python Basics", "Exception Handling", "File Handling",
                "Stacks", "Queues", "Sorting", "Searching",
                "Data Communication and Networks", "Security Aspects",
                "Database Concepts", "Structured Query Language"],
    },
    "Information Technology": {
        "9": ["Introduction to IT", "Communication Skills", "Self-Management Skills",
               "Basic IT Skills", "Entrepreneurial Skills"],
        "10": ["Communication Skills", "Self-Management Skills", "ICT Skills",
                "Entrepreneurial Skills", "Green Skills",
                "Web Applications and Security"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC DATA — SUBJECTS BY CLASS
# ═══════════════════════════════════════════════════════════════════════════════

SUBJECTS_BY_CLASS = {
    "1":  ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "2":  ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "3":  ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "4":  ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "5":  ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "6":  ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit"],
    "7":  ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit"],
    "8":  ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit"],
    "9":  ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit",
           "Information Technology"],
    "10": ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit",
           "Information Technology"],
    "11": ["Mathematics", "Physics", "Chemistry", "Biology", "English", "Hindi",
           "Economics", "Business Studies", "Accountancy", "History", "Geography",
           "Political Science", "Computer Science"],
    "12": ["Mathematics", "Physics", "Chemistry", "Biology", "English", "Hindi",
           "Economics", "Business Studies", "Accountancy", "History", "Geography",
           "Political Science", "Computer Science"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY SYLLABUS — old NCERT chapters (pre-2025-26) for subjects that have
# been updated. These are offered as an alternative when has_legacy is true.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Grammar Topics for Language subjects (English & Hindi) ────────────────────
# Used by /api/chapters to return topic choices alongside literature chapters.
GRAMMAR_TOPICS = {
    "English": {
        "1":  ["Naming Words (Nouns)", "Action Words (Verbs)", "Describing Words (Adjectives)",
               "One and Many (Singular/Plural)", "Pronouns (He/She/It/They)",
               "Capital Letters and Full Stops"],
        "2":  ["Types of Nouns", "Personal Pronouns", "Action Words and Helping Verbs",
               "Adjectives (Colour/Size/Number)", "Singular and Plural",
               "Question Words (Wh- Words)", "Punctuation (Comma/Full Stop/Question Mark)"],
        "3":  ["Common and Proper Nouns", "Personal Pronouns", "Adjectives and Degrees",
               "Verbs – Present and Past Tense", "Adverbs (How/When/Where)",
               "Prepositions (in/on/at/under/near)", "Conjunctions (and/but/or)",
               "Punctuation and Capital Letters", "Short Composition (3-5 sentences)"],
        "4":  ["Nouns (Common/Proper/Collective/Abstract)", "Pronouns", "Adjective Degrees (Comparison)",
               "Verb Tenses (Simple Present/Past/Future)", "Adverbs", "Prepositions",
               "Conjunctions", "Direct Speech and Punctuation",
               "Informal Letter Writing", "Paragraph Writing"],
        "5":  ["Noun and Its Kinds", "Pronoun Types (Personal/Demonstrative/Interrogative)",
               "Adjective Degrees (Positive/Comparative/Superlative)", "Tenses (Simple and Continuous)",
               "Adverbs (Manner/Time/Place/Degree)", "Prepositions", "Conjunctions",
               "Simple and Compound Sentences", "Formal and Informal Letter Writing", "Paragraph Writing"],
        "6":  ["Nouns (Number and Gender)", "Pronouns", "Adjectives", "Articles (a/an/the)",
               "Verbs and Tenses (Simple Present/Past/Future)", "Adverbs", "Prepositions",
               "Conjunctions", "Types of Sentences (Simple/Compound/Complex)",
               "Punctuation", "Letter Writing", "Paragraph/Story Writing"],
        "7":  ["Tenses (Simple and Continuous)", "Noun (Possessive)", "Pronoun Types",
               "Adjective Degrees", "Adverbs", "Articles", "Prepositions", "Conjunctions",
               "Active and Passive Voice (Introduction)", "Direct and Indirect Speech (Statements)",
               "Paragraph Writing", "Letter Writing (Formal/Informal)"],
        "8":  ["All Tenses (Simple/Continuous/Perfect)", "Active and Passive Voice",
               "Direct and Indirect Speech (Statements/Questions/Commands)",
               "Adjectives and Adverbs (Comparison)", "Prepositions", "Conjunctions",
               "Punctuation and Editing", "Omission Exercises",
               "Letter Writing (Formal/Informal)", "Paragraph Writing", "Notice Writing"],
        "9":  ["Tenses (All Forms)", "Active and Passive Voice",
               "Direct and Indirect Speech", "Modals (can/could/may/might/must/should/would)",
               "Determiners and Articles", "Prepositions", "Subject-Verb Agreement",
               "Gap Filling", "Error Correction and Editing", "Sentence Reordering",
               "Notice Writing", "Message Writing",
               "Formal Letter Writing (Complaint/Inquiry)", "Article Writing"],
        "10": ["Tenses", "Active and Passive Voice", "Narration (Direct/Indirect)",
               "Modals", "Determiners", "Prepositions", "Subject-Verb Agreement",
               "Sentence Transformation", "Rearranging Sentences",
               "Gap Filling", "Editing and Omission",
               "Formal Letter Writing", "Article Writing", "Report Writing"],
        "11": ["Tenses and Aspect", "Voice (Active and Passive)", "Narration (Direct and Indirect)",
               "Modals", "Determiners", "Prepositions", "Gap Filling",
               "Sentence Transformation", "Note Making and Summary",
               "Formal Letter Writing", "Article Writing",
               "Job Application and Resume Writing"],
        "12": ["Tenses", "Active and Passive Voice", "Narration (Direct/Indirect)",
               "Modals", "Determiners", "Gap Filling", "Sentence Rearrangement",
               "Editing and Proofreading", "Note Making and Summary",
               "Formal Letter Writing", "Article Writing",
               "Speech and Debate Writing", "Report Writing",
               "Classified Advertisements", "Job Application"],
    },
    "Hindi": {
        "1":  ["वर्णमाला एवं उच्चारण", "मात्राएँ (अ से अः)", "सरल शब्द निर्माण",
               "लिंग (पुल्लिंग / स्त्रीलिंग)", "वचन (एकवचन / बहुवचन)", "विलोम शब्द"],
        "2":  ["वर्ण-विचार", "संज्ञा (नाम)", "सर्वनाम", "क्रिया (काम करना)",
               "लिंग एवं वचन", "विपरीतार्थक शब्द", "श्रुतलेख"],
        "3":  ["संज्ञा और उसके भेद", "सर्वनाम", "विशेषण (गुण / रंग / संख्या)",
               "क्रिया और काल", "लिंग-वचन", "विलोम शब्द", "पर्यायवाची शब्द",
               "अनुच्छेद लेखन"],
        "4":  ["संज्ञा", "सर्वनाम", "विशेषण", "क्रिया",
               "काल (वर्तमान / भूत / भविष्यत्)", "लिंग-वचन",
               "मुहावरे", "पत्र लेखन (अनौपचारिक)", "अनुच्छेद लेखन"],
        "5":  ["संज्ञा के भेद", "सर्वनाम", "विशेषण (तुलनात्मक)", "क्रिया एवं काल",
               "कारक", "विलोम एवं पर्यायवाची शब्द",
               "मुहावरे एवं लोकोक्तियाँ", "पत्र लेखन", "निबंध लेखन"],
        "6":  ["संज्ञा और उसके भेद", "सर्वनाम", "विशेषण", "क्रिया",
               "काल (वर्तमान / भूत / भविष्यत्)", "कारक एवं विभक्ति",
               "विलोम शब्द", "पर्यायवाची शब्द",
               "मुहावरे एवं लोकोक्तियाँ", "पत्र लेखन", "अनुच्छेद लेखन"],
        "7":  ["संज्ञा", "सर्वनाम", "विशेषण", "क्रिया-विशेषण",
               "कारक", "काल", "वाच्य (परिचय)", "संधि (परिचय)", "समास (परिचय)",
               "मुहावरे एवं लोकोक्तियाँ", "अलंकार (उपमा / रूपक)",
               "पत्र लेखन", "निबंध लेखन", "अनुच्छेद लेखन"],
        "8":  ["संधि (स्वर / व्यंजन / विसर्ग)", "समास (सभी भेद)",
               "कारक एवं विभक्तियाँ", "काल (सभी भेद)",
               "वाच्य (कर्तृवाच्य / कर्मवाच्य / भाववाच्य)",
               "अलंकार (उपमा / रूपक / उत्प्रेक्षा / अनुप्रास / यमक)",
               "मुहावरे एवं लोकोक्तियाँ",
               "पत्र लेखन", "निबंध लेखन", "अनुच्छेद लेखन", "संवाद लेखन"],
        "9":  ["संधि", "समास", "कारक", "काल एवं क्रिया", "वाच्य",
               "अलंकार (शब्दालंकार / अर्थालंकार)", "रस और उनके भेद",
               "छन्द (दोहा / सोरठा / चौपाई)",
               "मुहावरे एवं लोकोक्तियाँ", "अपठित गद्यांश",
               "पत्र लेखन", "निबंध लेखन", "संवाद लेखन"],
        "10": ["संधि", "समास", "कारक", "वाच्य (परिवर्तन सहित)",
               "अलंकार", "रस", "छन्द",
               "मुहावरे एवं लोकोक्तियाँ",
               "अपठित गद्यांश एवं पद्यांश",
               "पत्र लेखन", "निबंध लेखन", "अनुच्छेद लेखन", "संवाद लेखन"],
        "11": ["संधि", "समास", "अलंकार", "रस", "छन्द", "मुहावरे", "वाच्य", "काल",
               "अपठित बोध (गद्यांश / पद्यांश)",
               "निबंध लेखन", "पत्र एवं प्रार्थना पत्र",
               "प्रतिवेदन (Report Writing)", "विज्ञापन लेखन",
               "संवाद लेखन", "आत्मकथा लेखन"],
        "12": ["संधि", "समास", "अलंकार", "रस", "छन्द",
               "मुहावरे एवं लोकोक्तियाँ", "वाच्य", "काल",
               "अपठित बोध (गद्यांश / पद्यांश)",
               "निबंध लेखन", "पत्र लेखन", "प्रतिवेदन",
               "विज्ञापन लेखन", "आवेदन पत्र", "संवाद लेखन"],
    },
}

NCERT_CHAPTERS_LEGACY = {
    "Mathematics": {
        # Old Ganita Prakash was not used for class 6; new syllabus since 2024-25
        "6": ["Knowing Our Numbers", "Whole Numbers", "Playing with Numbers",
               "Basic Geometrical Ideas", "Understanding Elementary Shapes", "Integers",
               "Fractions", "Decimals", "Data Handling", "Mensuration",
               "Algebra", "Ratio and Proportion", "Symmetry", "Practical Geometry"],
        # Old class 7 Math (before Ganita Prakash)
        "7": ["Integers", "Fractions and Decimals", "Data Handling",
               "Simple Equations", "Lines and Angles", "The Triangle and its Properties",
               "Comparing Quantities", "Rational Numbers", "Perimeter and Area",
               "Algebraic Expressions", "Exponents and Powers", "Symmetry",
               "Visualising Solid Shapes"],
        # Old class 8 Math (before Ganita Prakash)
        "8": ["Rational Numbers", "Linear Equations in One Variable",
               "Understanding Quadrilaterals", "Data Handling",
               "Squares and Square Roots", "Cubes and Cube Roots",
               "Comparing Quantities", "Algebraic Expressions and Identities",
               "Mensuration", "Exponents and Powers", "Direct and Inverse Proportions",
               "Factorisation", "Introduction to Graphs"],
    },
    "Science": {
        # Old class 6 Science (before Curiosity)
        "6": ["Food: Where Does It Come From?", "Components of Food",
               "Fibre to Fabric", "Sorting Materials into Groups",
               "Separation of Substances", "Changes Around Us",
               "Getting to Know Plants", "Body Movements",
               "The Living Organisms — Characteristics and Habitats",
               "Motion and Measurement of Distances",
               "Light, Shadows and Reflections", "Electricity and Circuits",
               "Fun with Magnets", "Water", "Air Around Us",
               "Garbage In, Garbage Out"],
        # Old class 7 Science (before Curiosity)
        "7": ["Nutrition in Plants", "Nutrition in Animals", "Fibre to Fabric", "Heat",
               "Acids, Bases and Salts", "Physical and Chemical Changes",
               "Weather, Climate and Adaptations of Animals to Climate",
               "Winds, Storms and Cyclones", "Soil", "Respiration in Organisms",
               "Transportation in Animals and Plants", "Reproduction in Plants",
               "Motion and Time", "Electric Current and its Effects", "Light",
               "Water: A Precious Resource", "Forests: Our Lifeline", "Wastewater Story"],
        # Old class 8 Science (before Curiosity)
        "8": ["Crop Production and Management", "Microorganisms: Friend and Foe",
               "Synthetic Fibres and Plastics", "Materials: Metals and Non-Metals",
               "Coal and Petroleum", "Combustion and Flame",
               "Conservation of Plants and Animals", "Cell Structure and Functions",
               "Reproduction in Animals", "Reaching the Age of Adolescence",
               "Force and Pressure", "Friction", "Sound",
               "Chemical Effects of Electric Current", "Some Natural Phenomena", "Light",
               "Stars and the Solar System", "Pollution of Air and Water"],
    },
    "Social Science": {
        # Old class 6 Social Science (before Exploring Society)
        "6": {
            "History": ["What, Where, How and When?", "On The Trail of the Earliest People",
                        "From Gathering to Growing Food", "In the Earliest Cities",
                        "What Books and Burials Tell Us", "Kingdoms, Kings and an Early Republic",
                        "New Questions and Ideas", "Ashoka, The Emperor Who Gave Up War",
                        "Vital Villages, Thriving Towns", "Traders, Kings and Pilgrims",
                        "New Empires and Kingdoms", "Buildings, Paintings and Books"],
            "Geography": ["The Earth in the Solar System", "Globe: Latitudes and Longitudes",
                          "Motions of the Earth", "Maps", "Major Domains of the Earth",
                          "Major Landforms of the Earth", "Our Country — India",
                          "India: Climate, Vegetation and Wildlife"],
            "Civics": ["Understanding Diversity", "Diversity and Discrimination",
                       "What is Government?", "Key Elements of a Democratic Government",
                       "Panchayati Raj", "Rural Administration", "Urban Administration",
                       "Rural Livelihoods", "Urban Livelihoods"],
        },
        # Old class 7 Social Science (before Exploring Society)
        "7": {
            "History": ["Tracing Changes Through A Thousand Years", "New Kings and Kingdoms",
                        "The Delhi Sultans", "The Mughal Empire", "Rulers and Buildings",
                        "Towns, Traders and Craftspersons", "Tribes, Nomads and Settled Communities",
                        "Devotional Paths to the Divine", "The Making of Regional Cultures",
                        "Eighteenth-Century Political Formations"],
            "Geography": ["Environment", "Inside Our Earth", "Our Changing Earth", "Air", "Water",
                          "Natural Vegetation and Wildlife",
                          "Human Environment – Settlement, Transport and Communication",
                          "Human-Environment Interactions – The Tropical and the Subtropical Region",
                          "Life in the Temperate Grasslands", "Life in the Deserts"],
            "Civics": ["On Equality", "Role of the Government in Health",
                       "How the State Government Works", "Growing up as Boys and Girls",
                       "Women Change the World", "Understanding Media", "Markets Around Us",
                       "A Shirt in the Market", "Struggles for Equality"],
        },
        # Old class 8 Social Science (before Exploring Society)
        "8": {
            "History": ["How, When and Where", "From Trade to Territory",
                        "Ruling the Countryside",
                        "Tribals, Dikus and the Vision of a Golden Age",
                        "When People Rebel", "Colonialism and the City",
                        "Weavers, Iron Smelters and Factory Owners",
                        "Civilising the 'Native', Educating the Nation",
                        "Women, Caste and Reform", "The Changing World of Visual Arts",
                        "The Making of the National Movement", "India After Independence"],
            "Geography": ["Resources", "Land, Soil, Water, Natural Vegetation and Wildlife Resources",
                          "Mineral and Power Resources", "Agriculture", "Industries",
                          "Human Resources"],
            "Civics": ["The Indian Constitution", "Understanding Secularism",
                       "Why Do We Need a Parliament?", "Understanding Laws", "Judiciary",
                       "Understanding Our Criminal Justice System",
                       "Understanding Marginalisation", "Confronting Marginalisation",
                       "Public Facilities", "Law and Social Justice"],
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC DATA — SUBJECT QUESTION TYPES
# ═══════════════════════════════════════════════════════════════════════════════

SUBJECT_QUESTION_TYPES = {
    "Mathematics": [
        {"key": "mcq",              "label": "Multiple Choice",          "icon": "check-circle",  "default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",       "label": "Fill in the Blanks",       "icon": "edit-3",        "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer",     "label": "Very Short Answer (VSA)",  "icon": "file-text",     "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "long_answer",      "label": "Proof / Derivation",       "icon": "book-open",     "default_count": 4,  "default_marks": 5, "enabled": True},
        {"key": "case_study",       "label": "Case Study / Passage",     "icon": "layers",        "default_count": 2,  "default_marks": 4, "enabled": True},
        {"key": "geometry_diagram", "label": "Geometric Construction",   "icon": "triangle",      "default_count": 2,  "default_marks": 3, "enabled": False},
        {"key": "construction",     "label": "Graph / Coordinate Work",  "icon": "pen-tool",      "default_count": 2,  "default_marks": 3, "enabled": False},
    ],
    "Science": [
        {"key": "mcq",          "label": "Multiple Choice",          "icon": "check-circle",  "default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",       "icon": "edit-3",        "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",             "icon": "file-text",     "default_count": 6,  "default_marks": 2, "enabled": True},
        {"key": "long_answer",  "label": "Long Answer",              "icon": "book-open",     "default_count": 3,  "default_marks": 5, "enabled": True},
        {"key": "diagram",      "label": "Label the Diagram",        "icon": "image",         "default_count": 2,  "default_marks": 3, "enabled": True},
        {"key": "case_study",   "label": "Case Study / Passage",     "icon": "layers",        "default_count": 1,  "default_marks": 4, "enabled": False},
    ],
    "Physics": [
        {"key": "mcq",           "label": "Multiple Choice",         "icon": "check-circle",  "default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "assertion_reason", "label": "Assertion & Reason",   "icon": "help-circle",   "badge": "A&R",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer",  "label": "Short Answer",            "icon": "file-text",     "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "long_answer",   "label": "Derivation / Proof",      "icon": "book-open",     "default_count": 3,  "default_marks": 5, "enabled": True},
        {"key": "numerical",     "label": "Numerical Problems",      "icon": "hash",          "default_count": 4,  "default_marks": 3, "enabled": True},
        {"key": "diagram",       "label": "Circuit / Ray Diagram",   "icon": "image",         "default_count": 2,  "default_marks": 3, "enabled": False},
    ],
    "Chemistry": [
        {"key": "mcq",           "label": "Multiple Choice",         "icon": "check-circle",  "default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "assertion_reason", "label": "Assertion & Reason",   "icon": "help-circle",   "badge": "A&R",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer",  "label": "Short Answer",            "icon": "file-text",     "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "long_answer",   "label": "Long Answer",             "icon": "book-open",     "default_count": 3,  "default_marks": 5, "enabled": True},
        {"key": "chemical_eq",   "label": "Equations / Reactions",   "icon": "zap",           "default_count": 4,  "default_marks": 2, "enabled": True},
        {"key": "numerical",     "label": "Numerical Problems",      "icon": "hash",          "default_count": 3,  "default_marks": 3, "enabled": False},
    ],
    "Biology": [
        {"key": "mcq",           "label": "Multiple Choice",         "icon": "check-circle",  "default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "assertion_reason", "label": "Assertion & Reason",   "icon": "help-circle",   "badge": "A&R",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer",  "label": "Short Answer",            "icon": "file-text",     "default_count": 6,  "default_marks": 2, "enabled": True},
        {"key": "long_answer",   "label": "Long Answer",             "icon": "book-open",     "default_count": 3,  "default_marks": 5, "enabled": True},
        {"key": "diagram",       "label": "Label the Parts",         "icon": "image",         "default_count": 2,  "default_marks": 3, "enabled": True},
        {"key": "match",         "label": "Match the Columns",       "icon": "shuffle",       "default_count": 1,  "default_marks": 4, "enabled": False},
    ],
    "English": [
        {"key": "reading_passage", "label": "Unseen Passage (2 types)", "icon": "book",       "badge": "RC",       "default_count": 2,  "default_marks": 10, "enabled": True},
        {"key": "mcq",             "label": "Extract-based MCQ",        "icon": "check-circle","default_count": 5,  "default_marks": 1,  "enabled": True},
        {"key": "short_answer",    "label": "Literature Short Answer",  "icon": "file-text",  "default_count": 5,  "default_marks": 3,  "enabled": True},
        {"key": "long_answer",     "label": "Literature Long Answer",   "icon": "book-open",  "default_count": 2,  "default_marks": 6,  "enabled": True},
        {"key": "grammar",         "label": "Grammar",                  "icon": "type",       "default_count": 1,  "default_marks": 10, "enabled": True},
        {"key": "writing",         "label": "Letter / Article / Notice / Report", "icon": "edit", "default_count": 2, "default_marks": 5, "enabled": True},
    ],
    "Hindi": [
        {"key": "reading_passage", "label": "अपठित गद्यांश",          "icon": "book",       "badge": "RC",       "default_count": 1,  "default_marks": 10, "enabled": True},
        {"key": "reading_poem",    "label": "अपठित पद्यांश",           "icon": "feather",    "default_count": 1,  "default_marks": 5,  "enabled": True},
        {"key": "grammar",         "label": "व्याकरण",                  "icon": "type",       "default_count": 1,  "default_marks": 15, "enabled": True},
        {"key": "literature_short","label": "साहित्य लघु-उत्तरीय",     "icon": "file-text",  "default_count": 5,  "default_marks": 2,  "enabled": True},
        {"key": "literature_long", "label": "साहित्य दीर्घ-उत्तरीय",   "icon": "book-open",  "default_count": 2,  "default_marks": 5,  "enabled": True},
        {"key": "writing",         "label": "पत्र / निबंध / अनुच्छेद", "icon": "edit",       "default_count": 2,  "default_marks": 5,  "enabled": True},
    ],
    "Sanskrit": [
        {"key": "unseen_passage",  "label": "अपठित (Unseen)",           "icon": "book",       "default_count": 1,  "default_marks": 10, "enabled": True},
        {"key": "grammar",         "label": "Sandhi / Samas / Karak",   "icon": "type",       "default_count": 1,  "default_marks": 15, "enabled": True},
        {"key": "translation",     "label": "Translation (Sanskrit↔Hindi)", "icon": "refresh-cw", "default_count": 3, "default_marks": 4, "enabled": True},
        {"key": "literature_short","label": "Short Answer (Literature)", "icon": "file-text",  "default_count": 4,  "default_marks": 2,  "enabled": True},
        {"key": "literature_long", "label": "Long Answer (Literature)",  "icon": "book-open",  "default_count": 2,  "default_marks": 5,  "enabled": True},
    ],
    "Social Science": [
        {"key": "mcq",          "label": "Multiple Choice",             "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",         "icon": "edit-3",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",               "icon": "file-text",   "default_count": 6,  "default_marks": 3, "enabled": True},
        {"key": "long_answer",  "label": "Long Answer",                "icon": "book-open",   "default_count": 3,  "default_marks": 5, "enabled": True},
        {"key": "map_work",     "label": "Outline Map Work",           "icon": "map",         "default_count": 2,  "default_marks": 3, "enabled": True},
        {"key": "source_based", "label": "Case Study / Source-Based",  "icon": "layers",      "default_count": 1,  "default_marks": 4, "enabled": False},
    ],
    "History": [
        {"key": "mcq",             "label": "Multiple Choice",         "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "short_answer",    "label": "Short Answer",            "icon": "file-text",   "default_count": 6,  "default_marks": 3, "enabled": True},
        {"key": "long_answer",     "label": "Long Answer",             "icon": "book-open",   "default_count": 3,  "default_marks": 8, "enabled": True},
        {"key": "source_analysis", "label": "Primary Source Analysis", "icon": "search",      "badge": "Source",   "default_count": 1,  "default_marks": 7, "enabled": True},
        {"key": "map_work",        "label": "Map Work",                "icon": "map",         "default_count": 1,  "default_marks": 5, "enabled": True},
        {"key": "timeline",        "label": "Timeline / Chronology",   "icon": "clock",       "default_count": 1,  "default_marks": 3, "enabled": False},
    ],
    "Geography": [
        {"key": "mcq",             "label": "Multiple Choice",         "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "short_answer",    "label": "Short Answer",            "icon": "file-text",   "default_count": 6,  "default_marks": 3, "enabled": True},
        {"key": "long_answer",     "label": "Long Answer",             "icon": "book-open",   "default_count": 3,  "default_marks": 5, "enabled": True},
        {"key": "map_work",        "label": "Map Work",                "icon": "map",         "default_count": 2,  "default_marks": 5, "enabled": True},
        {"key": "data_analysis",   "label": "Graph / Table Analysis",  "icon": "bar-chart-2", "default_count": 1,  "default_marks": 5, "enabled": False},
    ],
    "Political Science": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 6,  "default_marks": 3, "enabled": True},
        {"key": "long_answer",  "label": "Long Answer",               "icon": "book-open",   "default_count": 3,  "default_marks": 6, "enabled": True},
        {"key": "case_study",   "label": "Case Study",                "icon": "layers",      "default_count": 1,  "default_marks": 5, "enabled": True},
        {"key": "cartoon",      "label": "Political Cartoon Analysis", "icon": "image",      "default_count": 1,  "default_marks": 4, "enabled": False},
    ],
    "Economics": [
        {"key": "mcq",                "label": "Multiple Choice",      "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "short_answer",       "label": "Short Answer",         "icon": "file-text",   "default_count": 6,  "default_marks": 3, "enabled": True},
        {"key": "long_answer",        "label": "Long Answer",          "icon": "book-open",   "default_count": 3,  "default_marks": 6, "enabled": True},
        {"key": "case_study",         "label": "Case Study",           "icon": "layers",      "default_count": 1,  "default_marks": 5, "enabled": True},
        {"key": "data_interpretation","label": "Graph / Table",        "icon": "bar-chart-2", "default_count": 1,  "default_marks": 4, "enabled": False},
    ],
    "Business Studies": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 6,  "default_marks": 3, "enabled": True},
        {"key": "long_answer",  "label": "Long Answer",               "icon": "book-open",   "default_count": 3,  "default_marks": 6, "enabled": True},
        {"key": "case_study",   "label": "Case Study",                "icon": "layers",      "default_count": 2,  "default_marks": 5, "enabled": True},
    ],
    "Accountancy": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",        "icon": "edit-3",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 4,  "default_marks": 3, "enabled": True},
        {"key": "practical",    "label": "Journal / Ledger / T.B.",   "icon": "grid",        "badge": "Practical","default_count": 3,  "default_marks": 6, "enabled": True},
        {"key": "long_answer",  "label": "Final Accounts",            "icon": "book-open",   "default_count": 2,  "default_marks": 8, "enabled": True},
    ],
    "Computer Science": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",        "icon": "edit-3",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "program",      "label": "Code Writing",              "icon": "code",        "default_count": 3,  "default_marks": 4, "enabled": True},
        {"key": "output",       "label": "Find the Output",           "icon": "terminal",    "default_count": 3,  "default_marks": 2, "enabled": True},
        {"key": "error",        "label": "Debugging",                 "icon": "alert-triangle","default_count": 2, "default_marks": 2, "enabled": False},
    ],
    "Information Technology": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",        "icon": "edit-3",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "practical",    "label": "Practical / Application",   "icon": "monitor",     "default_count": 2,  "default_marks": 5, "enabled": True},
    ],
    "Environmental Studies (EVS)": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 8,  "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",        "icon": "edit-3",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "observation",  "label": "Activity / Observation",    "icon": "eye",         "default_count": 2,  "default_marks": 3, "enabled": True},
        {"key": "drawing",      "label": "Label the Drawing",         "icon": "image",       "default_count": 1,  "default_marks": 3, "enabled": False},
    ],
    # ── Regional Language question types ─────────────────────────────────────
    # All South/West/East Indian state-board languages share the same pattern.
    # A single "_regional_lang" template is referenced via the alias list below.
    "_regional_lang": [
        {"key": "reading_passage", "label": "Unseen Passage (Comprehension)", "icon": "book",      "badge": "RC",       "default_count": 1,  "default_marks": 10, "enabled": True},
        {"key": "grammar",         "label": "Grammar",                        "icon": "type",       "default_count": 1,  "default_marks": 15, "enabled": True},
        {"key": "literature_short","label": "Literature — Short Answer",      "icon": "file-text",  "default_count": 5,  "default_marks": 2,  "enabled": True},
        {"key": "literature_long", "label": "Literature — Long Answer",       "icon": "book-open",  "default_count": 2,  "default_marks": 5,  "enabled": True},
        {"key": "writing",         "label": "Letter / Essay / Notice",        "icon": "edit",       "default_count": 2,  "default_marks": 5,  "enabled": True},
        {"key": "mcq",             "label": "Multiple Choice (Extract)",      "icon": "check-circle","default_count": 5,  "default_marks": 1,  "enabled": False},
    ],
    "Marathi": None,          # resolved to _regional_lang at runtime
    "Tamil": None,
    "Telugu": None,
    "Kannada": None,
    "Malayalam": None,
    "Bengali": None,
    "Gujarati": None,
    "Punjabi": None,
    "Odia": None,
    "Assamese": None,
    "Urdu": None,
    "Nepali": None,
    "Konkani": None,
    "Manipuri (Meitei)": None,
    "Mizo": None,
    "Khasi": None,
    "Nagamese": None,
    "_default": [
        {"key": "mcq",          "label": "Multiple Choice",            "icon": "check-circle","default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",        "icon": "edit-3",      "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "match",        "label": "Match the Following",       "icon": "shuffle",     "default_count": 1,  "default_marks": 4, "enabled": True},
        {"key": "true_false",   "label": "True or False",             "icon": "toggle-left", "default_count": 5,  "default_marks": 1, "enabled": False},
        {"key": "short_answer", "label": "Short Answer",              "icon": "file-text",   "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "diagram",      "label": "Diagram / Long Answer",     "icon": "image",       "default_count": 2,  "default_marks": 5, "enabled": True},
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC DATA — QUESTION TYPE DESCRIPTIONS (for AI prompt)
# ═══════════════════════════════════════════════════════════════════════════════

QUESTION_TYPE_DESCRIPTIONS = {
    "mcq":                "Multiple Choice Questions – 4 options (A/B/C/D), only one correct answer",
    "fill_blank":         "Fill in the Blanks – one or two blanks per sentence, testing recall of key terms",
    "match":              "Match the Following – two columns with 4-6 pairs to match",
    "true_false":         "True or False – students identify whether a statement is correct",
    "short_answer":       "Short Answer – 2-4 sentence responses testing conceptual understanding",
    "long_answer":        "Long Answer – detailed paragraph or essay-style responses",
    "diagram":            "Diagram question – students draw and/or label a specified diagram",
    "case_study":         "Case Study / Passage-based – a short paragraph followed by sub-questions",
    "source_based":       "Source-based / Case Study – an extract (textual or visual) followed by analytical questions",
    "construction":       "Graph or Coordinate Construction – students construct a graph or coordinate plot with proper labelling and axes",
    "geometry_diagram":   "Geometric Diagram / Construction – students draw and label a specified geometric figure (triangle, circle, quadrilateral, angle bisector, perpendicular bisector, etc.); the question must include a 'figure_description' field describing the diagram to be drawn",
    "assertion_reason":   "Assertion-Reason – a pair of statements (Assertion and Reason); students choose from options: both true and reason explains assertion, both true but reason doesn't explain, assertion true reason false, assertion false",
    "numerical":          "Numerical Problems – step-by-step calculation questions requiring formula application and unit work",
    "chemical_eq":        "Chemical Equations / Reactions – write, balance, or identify products of chemical reactions",
    "map_work":           "Map Work – students identify, mark, or label places on an outline map of India or the world",
    "source_analysis":    "Primary Source Analysis – an excerpt from a historical document, treaty, or speech followed by analytical questions",
    "timeline":           "Timeline / Chronology – students arrange events in chronological order or fill a timeline",
    "data_analysis":      "Data Analysis – interpret a given graph, table, or statistical data and answer questions",
    "data_interpretation":"Data Interpretation – read and analyse an economic graph, chart, or statistical table",
    "cartoon":            "Political Cartoon Analysis – interpret a political cartoon and answer questions about its message and context",
    "practical":          "Practical / Application – hands-on accounting entries, ledger preparation, or IT application tasks",
    "program":            "Code Writing – write a complete program or function in Python/C++ to solve a stated problem",
    "output":             "Find the Output – trace through given code and write the correct output",
    "error":              "Debugging – identify and correct syntax or logical errors in given code",
    "reading_passage":    "Reading Comprehension – two unseen passages (one factual, one discursive) followed by MCQ and short-answer sub-questions",
    "reading_poem":       "Poetry Comprehension – an unseen poem (in Hindi) followed by short-answer and MCQ questions",
    "grammar":            "Grammar – questions on grammar rules (tenses, voice, narration, parts of speech, etc.) or Hindi/Sanskrit grammar topics",
    "writing":            "Writing – formal writing tasks such as letter, article, notice, speech, or report",
    "literature_short":   "Literature Short Answer – 2-3 sentence answers on prose/poetry from the prescribed textbook",
    "literature_long":    "Literature Long Answer – detailed analytical or descriptive response on a lesson or poem",
    "unseen_passage":     "Unseen Passage (Sanskrit) – अपठित गद्यांश with comprehension and grammar sub-questions",
    "translation":        "Translation – translate Sanskrit sentences into Hindi/English or vice versa",
    "observation":        "Activity / Observation – open-ended activity-based or observation question testing environmental awareness",
    "drawing":            "Label the Drawing – students identify and label parts in a given diagram related to nature or the environment",
    "source_analysis":    "Primary Source Analysis – an excerpt from a historical document, treaty, or speech followed by analytical questions",
}


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES — email/password (primary) + optional Google OAuth
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/auth/register', methods=['POST'])
def auth_register():
    """Create a new account with name, email, password."""
    data     = request.get_json(silent=True) or {}
    name     = data.get('name', '').strip()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not name or not email or not password:
        return jsonify({'error': 'All fields are required.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400
    if '@' not in email:
        return jsonify({'error': 'Please enter a valid email address.'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists.'}), 409

    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    login_user(user, remember=True)
    return jsonify({'success': True, 'name': user.name, 'email': user.email})


@app.route('/auth/login', methods=['POST'])
def auth_login():
    """Sign in with email and password."""
    data     = request.get_json(silent=True) or {}
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required.'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email or password.'}), 401

    login_user(user, remember=True)
    return jsonify({'success': True, 'name': user.name, 'email': user.email})


@app.route('/auth/google')
def auth_google():
    """Optional: sign in via Google OAuth (only works if GOOGLE_CLIENT_ID/SECRET are set)."""
    if not _OAUTH_CONFIGURED:
        return jsonify({'error': 'Google OAuth is not configured on this server.'}), 503
    redirect_uri = url_for('auth_callback', _external=True)
    return google_oauth.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def auth_callback():
    if not _OAUTH_CONFIGURED:
        return redirect('/')
    try:
        token     = google_oauth.authorize_access_token()
        user_info = token.get('userinfo') or google_oauth.userinfo()

        google_id = user_info['sub']
        email     = user_info.get('email', '')
        name      = user_info.get('name', '')
        picture   = user_info.get('picture', '')

        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            # Check if account exists by email (e.g. registered with password earlier)
            user = User.query.filter_by(email=email).first()
            if user:
                user.google_id = google_id
                user.picture   = picture
            else:
                user = User(google_id=google_id, email=email, name=name, picture=picture)
                db.session.add(user)
        else:
            user.name    = name
            user.picture = picture
        db.session.commit()

        login_user(user, remember=True)
        return redirect('/')
    except Exception as e:
        return redirect('/?auth_error=1')


@app.route('/auth/logout')
def auth_logout():
    logout_user()
    return redirect('/')


@app.route('/api/user')
def api_user():
    if current_user.is_authenticated:
        plan_key, plan_info = get_user_plan(current_user.id)
        usage = get_user_usage(current_user.id)
        return jsonify({
            'logged_in':       True,
            'name':            current_user.name,
            'email':           current_user.email,
            'picture':         current_user.picture,
            'plan':            plan_key,
            'plan_info':       plan_info,
            'usage':           usage,
            'is_admin':        current_user.email in ADMIN_EMAILS,
            'oauth_available': _OAUTH_CONFIGURED,
        })
    return jsonify({'logged_in': False, 'oauth_available': _OAUTH_CONFIGURED})


@app.route('/api/plans')
def api_plans():
    return jsonify({'plans': PLANS})


@app.route('/api/usage')
def api_usage():
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    plan_key, plan_info = get_user_plan(current_user.id)
    usage = get_user_usage(current_user.id)
    return jsonify({'plan': plan_key, 'plan_info': plan_info, 'usage': usage})


# ═══════════════════════════════════════════════════════════════════════════════
# BASIC API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/boards', methods=['GET'])
def get_boards():
    return jsonify({'boards': BOARDS})


def _extract_chapters(subject, class_num, version='new'):
    """Return chapter list for the given subject/class.
    version='new'    → look up NCERT_CHAPTERS (default, latest NCERT syllabus)
    version='legacy' → look up NCERT_CHAPTERS_LEGACY (old syllabus before 2025-26 revision)
    """
    source = NCERT_CHAPTERS_LEGACY if version == 'legacy' else NCERT_CHAPTERS
    chapters = []
    if subject in source:
        class_data = source[subject].get(class_num)
        if isinstance(class_data, list):
            chapters = class_data
        elif isinstance(class_data, dict):
            for sub_topic, ch_list in class_data.items():
                for ch in ch_list:
                    chapters.append(f"{sub_topic}: {ch}")
    # Fallback to new chapters if legacy requested but not found
    if not chapters and version == 'legacy' and subject in NCERT_CHAPTERS:
        class_data = NCERT_CHAPTERS[subject].get(class_num)
        if isinstance(class_data, list):
            chapters = class_data
        elif isinstance(class_data, dict):
            for sub_topic, ch_list in class_data.items():
                for ch in ch_list:
                    chapters.append(f"{sub_topic}: {ch}")
    return chapters


@app.route('/api/subjects', methods=['POST'])
def get_subjects():
    data      = request.get_json(force=True, silent=True) or {}
    class_num = str(data.get('class_num', ''))
    board     = data.get('board', 'CBSE')

    base = list(SUBJECTS_BY_CLASS.get(class_num, []))

    # Inject board-specific regional language(s) just before "Hindi".
    # The regional language is the mandatory first/medium language for state boards;
    # Hindi is kept as second-language option per the Three-Language Formula.
    regional = BOARD_REGIONAL_LANGUAGES.get(board, [])
    if regional:
        result, hindi_seen = [], False
        for s in base:
            if s == 'Hindi' and not hindi_seen:
                for lang in regional:
                    if lang not in result:
                        result.append(lang)
                hindi_seen = True
            result.append(s)
        if not hindi_seen:          # Hindi not in base (e.g. class 1-5 some boards)
            result = regional + result
    else:
        result = base

    return jsonify({'subjects': result})


@app.route('/api/chapters', methods=['POST'])
def get_chapters():
    data            = request.get_json(force=True, silent=True) or {}
    subject         = data.get('subject', '')
    class_num       = str(data.get('class_num', ''))
    syllabus_version = data.get('syllabus_version', 'new')  # 'new' or 'legacy'

    # Determine if a legacy alternative exists for this subject/class
    has_legacy = (
        subject in NCERT_CHAPTERS_LEGACY
        and class_num in NCERT_CHAPTERS_LEGACY[subject]
    )

    chapters = _extract_chapters(subject, class_num, version=syllabus_version)
    grammar_topics = []
    if subject in GRAMMAR_TOPICS:
        grammar_topics = GRAMMAR_TOPICS[subject].get(class_num, [])
    return jsonify({'chapters': chapters, 'has_legacy': has_legacy,
                    'grammar_topics': grammar_topics})


@app.route('/api/custom-chapters', methods=['GET'])
def list_custom_chapters():
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    subject   = request.args.get('subject', '')
    class_num = request.args.get('class_num', '')
    rows = CustomChapter.query.filter_by(
        user_id=current_user.id, subject=subject, class_num=class_num
    ).order_by(CustomChapter.created_at).all()
    return jsonify({'chapters': [{'id': r.id, 'chapter': r.chapter} for r in rows]})


@app.route('/api/custom-chapters', methods=['POST'])
def add_custom_chapter():
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    data      = request.json
    chapter   = (data.get('chapter') or '').strip()
    subject   = data.get('subject', '')
    class_num = str(data.get('class_num', ''))
    if not chapter:
        return jsonify({'error': 'Chapter name required'}), 400
    existing = CustomChapter.query.filter_by(
        user_id=current_user.id, subject=subject, class_num=class_num, chapter=chapter
    ).first()
    if existing:
        return jsonify({'id': existing.id, 'chapter': existing.chapter})
    c = CustomChapter(user_id=current_user.id, subject=subject, class_num=class_num, chapter=chapter)
    db.session.add(c)
    db.session.commit()
    return jsonify({'id': c.id, 'chapter': c.chapter}), 201


@app.route('/api/custom-chapters/<int:chapter_id>', methods=['DELETE'])
def delete_custom_chapter(chapter_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    c = db.session.get(CustomChapter, chapter_id)
    if not c or c.user_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})


def _get_question_types(subject, class_num, board='CBSE'):
    """Return question-type list filtered/adjusted for the given class and board.

    Class groupings:
      Primary   (1–5)  : only simple types; no derivations/assertion-reason
      Middle    (6–8)  : most types; remove assertion-reason, advanced practicals
      Secondary (9–10) : full list; assertion-reason enabled only for CBSE/ICSE
      Senior   (11–12) : full list unchanged
    """
    try:
        cls = int(class_num)
    except (ValueError, TypeError):
        cls = 10  # safe default

    # Resolve regional-language aliases (stored as None) to the shared template
    raw = SUBJECT_QUESTION_TYPES.get(subject)
    if raw is None:
        raw = SUBJECT_QUESTION_TYPES.get('_regional_lang', [])
    base = list(raw or SUBJECT_QUESTION_TYPES.get('_default', []))

    # ── Primary (Classes 1–5) ────────────────────────────────────────────────
    if cls <= 5:
        PRIMARY_OK = {'mcq', 'fill_blank', 'true_false', 'match',
                      'short_answer', 'drawing', 'observation', 'long_answer'}
        filtered = [t for t in base if t['key'] in PRIMARY_OK]
        if not filtered:
            filtered = base[:4]
        # Reduce question counts for young learners
        result = []
        for t in filtered:
            td = dict(t)
            td['default_count'] = max(2, t.get('default_count', 5) - 3)
            td['enabled'] = t.get('enabled', True)
            result.append(td)
        return result

    # ── Middle School (Classes 6–8) ──────────────────────────────────────────
    MIDDLE_EXCL = {'assertion_reason', 'source_analysis', 'cartoon', 'timeline',
                   'data_interpretation', 'practical'}
    if cls <= 8:
        return [t for t in base if t['key'] not in MIDDLE_EXCL]

    # ── Secondary (Classes 9–10) ─────────────────────────────────────────────
    if cls <= 10:
        CBSE_ICSE = {'CBSE', 'ICSE/ISC (CISCE)'}
        result = []
        for t in base:
            td = dict(t)
            # Assertion-Reason is part of CBSE/ICSE 9-10 pattern; disable for others
            if td['key'] == 'assertion_reason' and board not in CBSE_ICSE:
                td['enabled'] = False
            result.append(td)
        return result

    # ── Senior Secondary (Classes 11–12) ─────────────────────────────────────
    return base


@app.route('/api/question-types', methods=['GET'])
def get_question_types():
    subject   = request.args.get('subject', '')
    class_num = request.args.get('class_num', '10')
    board     = request.args.get('board', 'CBSE')
    types     = _get_question_types(subject, class_num, board)
    return jsonify({'question_types': types})


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY API ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/history', methods=['GET'])
def get_history():
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401

    view = request.args.get('view', 'active')

    # Auto-archive papers older than 6 months
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=182)
    old_papers = QuestionPaper.query.filter_by(
        user_id=current_user.id, archived=False
    ).filter(QuestionPaper.created_at < six_months_ago).all()
    if old_papers:
        now_utc = datetime.now(timezone.utc)
        for p in old_papers:
            p.archived = True
            p.archived_at = now_utc
        db.session.commit()

    if view == 'archived':
        papers = QuestionPaper.query.filter_by(
            user_id=current_user.id, archived=True
        ).order_by(QuestionPaper.created_at.desc()).all()
    else:
        papers = QuestionPaper.query.filter_by(
            user_id=current_user.id, archived=False
        ).order_by(QuestionPaper.created_at.desc()).all()

    result = []
    for p in papers:
        result.append({
            'id':               p.id,
            'board':            p.board,
            'class_num':        p.class_num,
            'subject':          p.subject,
            'exam_type':        p.exam_type,
            'teacher_name':     p.teacher_name,
            'total_marks':      p.total_marks,
            'created_at':       p.created_at.isoformat() if p.created_at else None,
            'evaluation_count': len(p.evaluations),
            'archived':         p.archived,
            'archived_at':      p.archived_at.isoformat() if p.archived_at else None,
        })
    return jsonify({'papers': result, 'view': view})


@app.route('/api/history/<int:paper_id>', methods=['GET'])
def get_history_paper(paper_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    paper = db.session.get(QuestionPaper, paper_id)
    if not paper:
        return jsonify({'error': 'Paper not found'}), 404

    # Access control: only owner can view
    if paper.user_id and paper.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    try:
        paper_data = json.loads(paper.paper_json) if paper.paper_json else {}
    except Exception:
        paper_data = {}

    evaluations = []
    for ev in paper.evaluations:
        try:
            report = json.loads(ev.report_json) if ev.report_json else {}
        except Exception:
            report = {}
        evaluations.append({
            'id':             ev.id,
            'student_name':   ev.student_name,
            'roll_no':        ev.roll_no,
            'total_obtained': ev.total_obtained,
            'total_marks':    ev.total_marks,
            'percentage':     ev.percentage,
            'grade':          ev.grade,
            'created_at':     ev.created_at.isoformat() if ev.created_at else None,
            'report':         report,
        })

    return jsonify({
        'id':           paper.id,
        'board':        paper.board,
        'class_num':    paper.class_num,
        'subject':      paper.subject,
        'exam_type':    paper.exam_type,
        'teacher_name': paper.teacher_name,
        'total_marks':  paper.total_marks,
        'created_at':   paper.created_at.isoformat() if paper.created_at else None,
        'paper':        paper_data,
        'evaluations':  evaluations,
    })


@app.route('/api/history/<int:paper_id>/archive', methods=['POST'])
def archive_paper(paper_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    paper = db.session.get(QuestionPaper, paper_id)
    if not paper or paper.user_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404
    paper.archived = True
    paper.archived_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/history/<int:paper_id>/unarchive', methods=['POST'])
def unarchive_paper(paper_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401
    paper = db.session.get(QuestionPaper, paper_id)
    if not paper or paper.user_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404
    paper.archived = False
    paper.archived_at = None
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/admin/test-email')
def test_email():
    """Diagnostic endpoint — visit while logged in to test email config."""
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401

    resend_key  = os.environ.get('RESEND_API_KEY', '').strip()
    smtp_user   = os.environ.get('SMTP_USER', '').strip()
    smtp_pass   = os.environ.get('SMTP_PASS', '').replace(' ', '').strip()
    active_service = 'resend' if resend_key else ('smtp' if smtp_user else 'none')

    ok, err = send_contact_email(
        name='Test', email=current_user.email,
        mobile='9999999999', school_name='Test School',
        message='This is a test email from ExamCraft India diagnostic.',
        request_type='contact',
    )
    return jsonify({
        'active_service': active_service,
        'resend_key_set': bool(resend_key),
        'smtp_user_set':  bool(smtp_user),
        'smtp_pass_set':  bool(smtp_pass),
        'smtp_host':      os.environ.get('SMTP_HOST', 'smtp.gmail.com'),
        'sent':  ok,
        'error': err,
    })


@app.route('/api/contact', methods=['POST'])
def submit_contact():
    data = request.get_json(silent=True) or {}
    name         = data.get('name', '').strip()
    email        = data.get('email', '').strip().lower()
    mobile       = data.get('mobile', '').strip()
    school_name  = data.get('school_name', '').strip()
    message      = data.get('message', '').strip()
    request_type = data.get('request_type', 'contact')

    if not name:
        return jsonify({'error': 'Name is required.'}), 400
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email is required.'}), 400
    if request_type == 'callback' and not mobile:
        return jsonify({'error': 'Mobile number is required for a callback request.'}), 400

    req = ContactRequest(
        name=name, email=email, mobile=mobile,
        school_name=school_name, message=message,
        request_type=request_type,
    )
    db.session.add(req)
    db.session.commit()

    email_sent, email_error = send_contact_email(name, email, mobile, school_name, message, request_type)
    return jsonify({'success': True, 'email_sent': email_sent, 'email_error': email_error})


# ═══════════════════════════════════════════════════════════════════════════════
# USER PROFILE ROUTES (teacher name, school name, school logo persistence)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/user-profile', methods=['GET'])
@login_required
def get_user_profile():
    """Return the logged-in user's saved profile (teacher name, school, logo)."""
    profile = UserProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        return jsonify({'teacher_name': '', 'school_name': '', 'school_logo': ''})
    return jsonify({
        'teacher_name': profile.teacher_name or '',
        'school_name':  profile.school_name  or '',
        'school_logo':  profile.school_logo  or '',
    })


@app.route('/api/user-profile', methods=['POST'])
@login_required
def save_user_profile():
    """Upsert the logged-in user's profile. Accepts JSON with any subset of
    teacher_name / school_name / school_logo keys."""
    data = request.get_json(silent=True) or {}
    profile = UserProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.session.add(profile)
    if 'teacher_name' in data:
        profile.teacher_name = (data['teacher_name'] or '')[:256]
    if 'school_name' in data:
        profile.school_name = (data['school_name'] or '')[:256]
    if 'school_logo' in data:
        # Accept '' to clear the logo
        profile.school_logo = data['school_logo'] or None
    profile.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    return jsonify({'success': True})


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATE PAPER ROUTE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/suggest-options', methods=['POST'])
def suggest_options():
    """Use Gemini to suggest 4 MCQ options + correct answer for a given question text."""
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401

    data         = request.get_json(force=True, silent=True) or {}
    question_txt = (data.get('question') or '').strip()
    subject      = (data.get('subject')  or '').strip()
    class_num    = str(data.get('class_num') or '').strip()

    if not question_txt:
        return jsonify({'error': 'question text is required'}), 400

    _gemini = get_gemini_client()
    if not _gemini:
        return jsonify({'error': 'AI service not configured'}), 503

    try:
        prompt = (
            f"You are an expert Indian school examiner for Class {class_num} {subject}.\n\n"
            f"Question: {question_txt}\n\n"
            "Generate exactly 4 MCQ options (A, B, C, D) — only one correct — "
            "and identify the correct answer.\n\n"
            "Respond with ONLY this JSON (no markdown, no extra text):\n"
            '{"options":["A) text","B) text","C) text","D) text"],'
            '"correct":"A","explanation":"One sentence why this answer is correct"}\n\n'
            "Rules:\n"
            f"- All 4 options must be plausible distractors appropriate for Class {class_num}\n"
            "- Only ONE option must be correct; the others must be clearly wrong but tempting\n"
            "- Keep each option concise (under 15 words)\n"
            "- The correct field must be exactly one letter: A, B, C, or D"
        )
        response = gemini_generate(
            _gemini,
            contents=[prompt],
            config=genai_types.GenerateContentConfig(
                max_output_tokens=400,
                temperature=0.4,
                response_mime_type='application/json',
            ),
        )
        raw = response.text.strip()
        result = json.loads(raw)
        # Normalise: ensure options list has exactly 4 entries
        opts   = result.get('options', [])
        labels = ['A', 'B', 'C', 'D']
        while len(opts) < 4:
            opts.append(f"{labels[len(opts)]}) —")
        result['options'] = opts[:4]
        return jsonify(result)
    except Exception as exc:
        app.logger.error(f'suggest_options error: {exc}')
        return jsonify({'error': str(exc)}), 500


@app.route('/api/generate-paper', methods=['POST'])
def generate_paper():
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401

    # Check paper limit for free plan
    plan_key, plan_info = get_user_plan(current_user.id)
    limit = plan_info.get('papers_per_month', 3)
    if limit != -1:
        usage = get_user_usage(current_user.id)
        if usage['papers'] >= limit:
            return jsonify({'error': 'limit_reached', 'plan': plan_key, 'limit': limit}), 403

    gemini = get_gemini_client()
    if not gemini:
        return jsonify({'error': 'GOOGLE_API_KEY not configured. Get a free key at aistudio.google.com, then run: $env:GOOGLE_API_KEY="your_key"'}), 500

    try:
        board         = request.form.get('board', 'CBSE')
        class_num     = request.form.get('class_num', '10')
        subject       = request.form.get('subject', 'Mathematics')
        exam_type     = request.form.get('exam_type', 'Annual')
        total_marks   = request.form.get('total_marks', '80')
        duration      = request.form.get('duration', '3 Hours')
        difficulty    = request.form.get('difficulty', 'Mixed')
        teacher_name  = request.form.get('teacher_name', '')
        exam_date     = request.form.get('exam_date', '').strip()
        chapters      = json.loads(request.form.get('chapters', '[]'))
        question_types= json.loads(request.form.get('question_types', '{}'))

        # Process uploaded chapter images as PIL Images for Gemini
        pil_images = []
        files = request.files.getlist('chapter_images')
        for f in files:
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit('.', 1)[1].lower()
                if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    img_bytes = f.read()
                    pil_images.append(Image.open(io.BytesIO(img_bytes)))

        # Build sections description using QUESTION_TYPE_DESCRIPTIONS
        sections_desc = []
        section_letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        sec_index = 0
        total_q_count = 0
        q_num_start = 1  # running Q-ID counter for explicit range hints
        # Resolve question types once for label lookup
        _all_qt_for_label = _get_question_types(subject, class_num, board)
        for key, cfg in question_types.items():
            count = cfg.get('count', 0)
            if count <= 0:
                continue
            marks      = float(cfg.get('marks', 1))
            sec_letter = section_letters[sec_index] if sec_index < len(section_letters) else str(sec_index + 1)
            type_label = next((t['label'] for t in _all_qt_for_label if t['key'] == key), key.replace('_', ' ').title())
            description= QUESTION_TYPE_DESCRIPTIONS.get(key, type_label)
            marks_fmt  = int(marks) if marks == int(marks) else marks
            total_sec  = count * marks
            total_sec_fmt = int(total_sec) if total_sec == int(total_sec) else total_sec
            q_num_end  = q_num_start + count - 1
            q_range    = f"Q{q_num_start}" if count == 1 else f"Q{q_num_start}–Q{q_num_end}"
            sections_desc.append(
                f"Section {sec_letter} – {type_label} ({description}): "
                f"EXACTLY {count} question(s) [{q_range}] × {marks_fmt} mark(s) each = {total_sec_fmt} marks"
            )
            sec_index     += 1
            total_q_count += count
            q_num_start    = q_num_end + 1

        chapters_str = ', '.join(chapters) if chapters else 'All chapters'

        difficulty_map = {
            'easy':   'Easy (80% Easy, 20% Medium)',
            'medium': 'Medium (20% Easy, 60% Medium, 20% Hard)',
            'hard':   'Hard (20% Medium, 80% Hard)',
            'mixed':  'Mixed (30% Easy, 50% Medium, 20% Hard)',
        }
        diff_desc = difficulty_map.get(difficulty.lower(), 'Mixed')

        teacher_line = f"- Teacher / Examiner: {teacher_name}" if teacher_name else ""
        date_line    = f"- Exam Date: {exam_date}" if exam_date else ""

        prompt_text = f"""You are an expert Indian school examiner creating an official question paper.

EXAM SPECIFICATIONS:
- Board: {board}
- Class: {class_num}
- Subject: {subject}
- Chapters Covered: {chapters_str}
- Exam Type: {exam_type} Examination
- Total Marks: {total_marks}
- Duration: {duration}
- Difficulty Level: {diff_desc}
{teacher_line}
{date_line}

QUESTION PAPER STRUCTURE:
{chr(10).join(sections_desc)}

INSTRUCTIONS FOR GENERATION:
1. Create curriculum-appropriate questions strictly based on NCERT content
2. Ensure questions test different cognitive levels (knowledge, understanding, application)
3. For MCQs: provide 4 options (A, B, C, D) — only one correct
4. For Match the Following: create two columns with 4-6 items each
5. For Fill in the Blanks: leave clear blanks (_____)
6. For Diagram questions: specify what to draw/label with clear instructions
6a. For geometry_diagram questions: add a "figure_description" field to each question describing the geometric figure the student must construct (e.g., "A triangle ABC with AB=6cm, angle B=60°, BC=4cm. Measure and write the length of AC."). This description will be shown as a dashed placeholder box in the printed paper where students draw their construction.
7. Include proper general instructions at the top
8. Add complete answer key at the end
9. Use ^{{text}} for superscripts (e.g., x^{{2}}) and _{{text}} for subscripts (e.g., H_{{2}}O). Do NOT use LaTeX backslash commands (no \\alpha, \\frac, \\sqrt, \\times etc.). Write fractions as a/b, roots as sqrt(x). Use these Unicode symbols DIRECTLY in the JSON text — copy-paste them exactly: Greek: α β γ δ ε ζ η θ ι κ λ μ ν ξ π ρ σ τ υ φ χ ψ ω  Γ Δ Θ Λ Ξ Π Σ Υ Φ Ψ Ω. Operators: × ÷ ± ≤ ≥ ≠ ≈ ≡ ∝ ∞ ∂ ∇ ∑ ∏ ∫ √ ∈ ∉ ∪ ∩ → ← ↔ ⇒ ∠ ⊥ ∥ °.
10. CRITICAL — EXACT QUESTION COUNT: You MUST generate EXACTLY the number of questions specified for each section (see QUESTION PAPER STRUCTURE above). No more, no fewer. The total across all sections must be exactly {total_q_count} questions. Count each question carefully before finalising the JSON.
11. For reading_passage and reading_poem sections: sub_questions MUST be a JSON array of objects — each object must have a "text" field (string) and a "marks" field (number). Do NOT use plain strings. The marks values across all sub_questions should sum to the section's marks-per-question. Example: "sub_questions": [{{"text": "What is the central theme of the passage?", "marks": 2}}, {{"text": "Why did the author use this metaphor? Explain.", "marks": 3}}]

CRITICAL JSON RULES (the output must be valid JSON):
- Do NOT use double-quote characters (") inside any string value. Use single quotes or rephrase.
- Do NOT include literal newlines or tab characters inside any string value — keep each value on a single line.
- Do NOT use backslash (\\) except for valid JSON escape sequences (\\", \\\\, \\n, \\t).
- Every string must be properly terminated with a closing double-quote.
- No trailing commas after the last element of arrays or objects.

{"Reference the uploaded chapter content/images for question creation." if pil_images else ""}

Return ONLY a valid JSON object (no markdown, no explanation, no text before or after the JSON) with this EXACT structure:
{{
  "paper_info": {{
    "board": "{board}",
    "class": "{class_num}",
    "subject": "{subject}",
    "exam_type": "{exam_type} Examination",
    "total_marks": {total_marks},
    "duration": "{duration}",
    "teacher_name": "{teacher_name}",
    "date": "{exam_date}",
    "chapters": "{chapters_str}"
  }},
  "instructions": [
    "All questions are compulsory.",
    "Read all questions carefully before answering.",
    "Write neatly and clearly."
  ],
  "sections": [
    {{
      "section_id": "A",
      "section_name": "Section A – Multiple Choice Questions",
      "type": "mcq",
      "instructions": "Choose the correct option. Each question carries 1 mark.",
      "questions": [
        {{
          "q_id": "Q1",
          "text": "Question text here?",
          "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
          "marks": 1,
          "difficulty": "easy",
          "correct_answer": "A",
          "explanation": "Brief explanation of why A is correct"
        }}
      ]
    }}
  ],
  "answer_key": [
    {{"q_id": "Q1", "section": "A", "answer": "A", "marks": 1}}
  ]
}}

Generate ALL {total_q_count} questions exactly as specified above. Each section must contain EXACTLY the number of questions stated — do not add extra questions, do not omit any. Make every question appropriate for Class {class_num} {subject} {board} students."""

        # Build Gemini content: images first, then the prompt text
        contents = pil_images + [prompt_text]

        # Lower temperature for technical subjects to reduce hallucination in JSON
        _TECHNICAL = {'Mathematics', 'Physics', 'Chemistry', 'Science', 'Accountancy',
                      'Computer Science', 'Information Technology'}
        gen_temp = 0.4 if subject in _TECHNICAL else 0.6

        response = gemini_generate(
            gemini,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=20000,
                temperature=gen_temp,
                response_mime_type='application/json',
            ),
        )

        response_text = response.text

        try:
            paper_json = extract_json(response_text)
        except (ValueError, json.JSONDecodeError) as e:
            return jsonify({
                'error': f'Failed to parse generated paper: {str(e)}',
                'raw_preview': response_text[:500],
            }), 500

        # Enforce exact counts, marks, and passage sub-question structure
        paper_json = _enforce_paper_specs(paper_json, question_types)

        session['question_paper'] = paper_json

        # Save to database
        sid         = get_session_id()
        user_id     = current_user.id if current_user.is_authenticated else None
        paper_record = QuestionPaper(
            user_id     = user_id,
            session_id  = sid,
            board       = board,
            class_num   = class_num,
            subject     = subject,
            exam_type   = exam_type,
            teacher_name= teacher_name,
            total_marks = int(total_marks),
            paper_json  = json.dumps(paper_json),
        )
        db.session.add(paper_record)
        db.session.commit()

        return jsonify({'success': True, 'paper': paper_json, 'paper_id': paper_record.id})

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Failed to parse generated paper: {str(e)}'}), 500
    except Exception as e:
        err_str = str(e)
        if any(x in err_str for x in ('503', 'UNAVAILABLE', 'high demand')):
            msg = ('The Gemini AI service is temporarily busy. '
                   'Please wait a moment and try again.')
        elif '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
            msg = 'API quota reached. Please try again in a minute.'
        else:
            msg = f'Generation failed: {err_str}'
        return jsonify({'error': msg}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# EVALUATE ROUTE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/evaluate', methods=['POST'])
def evaluate():
    if not current_user.is_authenticated:
        return jsonify({'error': 'auth_required'}), 401

    # Check eval limit for free plan
    plan_key, plan_info = get_user_plan(current_user.id)
    eval_limit = plan_info.get('evals_per_month', 5)
    if eval_limit != -1:
        usage = get_user_usage(current_user.id)
        if usage['evals'] >= eval_limit:
            return jsonify({'error': 'limit_reached', 'plan': plan_key, 'limit': eval_limit}), 403

    gemini = get_gemini_client()
    if not gemini:
        return jsonify({'error': 'GOOGLE_API_KEY not configured. Get a free key at aistudio.google.com'}), 500

    student_name   = request.form.get('student_name', 'Student')
    roll_no        = request.form.get('roll_no', 'N/A')
    paper_id_str   = request.form.get('paper_id', '')
    paper_json_str = request.form.get('question_paper', '')

    if paper_json_str:
        try:
            question_paper = json.loads(paper_json_str)
        except Exception:
            question_paper = session.get('question_paper', {})
    else:
        question_paper = session.get('question_paper', {})

    if not question_paper:
        return jsonify({'error': 'No question paper found. Please generate a paper first.'}), 400

    file = request.files.get('answer_sheet')
    if not file or not file.filename:
        return jsonify({'error': 'No answer sheet uploaded.'}), 400

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    if not allowed_file(filename):
        return jsonify({'error': f'File type .{ext} not supported. Use PNG, JPG, PDF, DOCX, or TXT.'}), 400

    temp_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(temp_path)

    answer_image = None
    answer_text  = ""

    try:
        if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            with open(temp_path, 'rb') as f:
                answer_image = Image.open(io.BytesIO(f.read()))
                answer_image.load()
            answer_text = "[Answer sheet provided as image — evaluate from the image]"
        elif ext == 'pdf':
            answer_text = extract_text_from_pdf(temp_path)
        elif ext in ['doc', 'docx']:
            answer_text = extract_text_from_docx(temp_path)
        elif ext == 'txt':
            with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
                answer_text = f.read()

        paper_summary = json.dumps(question_paper, indent=2)

        eval_prompt = f"""You are an experienced and fair Indian school examiner evaluating a student's answer sheet.

QUESTION PAPER:
{paper_summary}

STUDENT INFORMATION:
- Name: {student_name}
- Roll No: {roll_no}

STUDENT'S ANSWER SHEET:
{answer_text}

EVALUATION GUIDELINES:
1. Evaluate each question listed in the answer key carefully
2. Award full marks for completely correct answers
3. Award partial marks for partially correct answers (for short/long answer questions)
4. Award 0 marks if the answer is wrong or not attempted
5. For MCQ/True-False/Fill-blank: either full marks or 0 (no partial)
6. For Match the Following: award marks proportionally
7. For diagram questions: award marks based on accuracy, labels, and neatness described
8. If an answer is not found in the sheet, award 0 marks
9. Follow NCERT standard marking scheme

Return ONLY a valid JSON object (no markdown, no explanation) with this EXACT structure:
{{
  "student_name": "{student_name}",
  "roll_no": "{roll_no}",
  "evaluations": [
    {{
      "q_id": "Q1",
      "section": "A",
      "question_text": "The question text",
      "student_answer": "What the student wrote (or 'Not attempted')",
      "correct_answer": "The correct answer",
      "marks_obtained": 0,
      "max_marks": 1,
      "is_correct": false,
      "feedback": "Concise feedback on the answer"
    }}
  ],
  "section_wise_marks": [
    {{"section": "A", "section_name": "MCQ", "obtained": 0, "maximum": 10}}
  ],
  "total_obtained": 0,
  "total_marks": 80,
  "percentage": 0.0,
  "grade": "C",
  "remarks": "Overall performance remarks in 1-2 sentences"
}}

Grade scale: A+ (95-100%), A (85-94%), B+ (75-84%), B (65-74%), C (50-64%), D (35-49%), F (below 35%)
Be accurate and fair. Do not inflate or deflate marks."""

        contents = []
        if answer_image:
            contents.append(answer_image)
        contents.append(eval_prompt)

        response = gemini_generate(
            gemini,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=12000,
                temperature=0.3,
                response_mime_type='application/json',
            ),
        )

        response_text = response.text
        try:
            eval_json = extract_json(response_text)
        except (ValueError, json.JSONDecodeError) as e:
            return jsonify({'error': f'Evaluation parsing error: {str(e)}'}), 500

        # Save evaluation to database
        sid         = get_session_id()
        user_id     = current_user.id if current_user.is_authenticated else None
        paper_id    = int(paper_id_str) if paper_id_str.isdigit() else None

        ev_record = Evaluation(
            paper_id       = paper_id,
            user_id        = user_id,
            session_id     = sid,
            student_name   = student_name,
            roll_no        = roll_no,
            report_json    = json.dumps(eval_json),
            total_obtained = eval_json.get('total_obtained', 0),
            total_marks    = eval_json.get('total_marks', 0),
            percentage     = eval_json.get('percentage', 0.0),
            grade          = eval_json.get('grade', ''),
        )
        db.session.add(ev_record)
        db.session.commit()

        return jsonify({'success': True, 'report': eval_json, 'evaluation_id': ev_record.id})

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Evaluation parsing error: {str(e)}'}), 500
    except Exception as e:
        err_str = str(e)
        if any(x in err_str for x in ('503', 'UNAVAILABLE', 'high demand')):
            msg = ('The Gemini AI service is temporarily busy. '
                   'Please wait a moment and try again.')
        elif '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
            msg = 'API quota reached. Please try again in a minute.'
        else:
            msg = f'Evaluation failed: {err_str}'
        return jsonify({'error': msg}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# WORD DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/download-word', methods=['POST'])
def download_word():
    try:
        from docx import Document
        from docx.shared import Pt, Inches, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        paper_json_str = request.form.get('paper_json', '')
        if not paper_json_str:
            return jsonify({'error': 'No paper data provided'}), 400
        paper = json.loads(paper_json_str)

        school_name      = request.form.get('school_name', '').strip()
        school_logo_b64  = request.form.get('school_logo', '').strip()

        info = paper.get('paper_info', {})
        doc = Document()

        # ── Page margins ──────────────────────────────────────────────────────
        for section in doc.sections:
            section.top_margin    = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin   = Inches(1.2)
            section.right_margin  = Inches(1.2)

        # ── Helper: add styled paragraph ──────────────────────────────────────
        def add_para(text, bold=False, size=11, align=WD_ALIGN_PARAGRAPH.LEFT,
                     space_before=0, space_after=6, italic=False, color=None):
            p = doc.add_paragraph()
            p.alignment = align
            p.paragraph_format.space_before = Pt(space_before)
            p.paragraph_format.space_after  = Pt(space_after)
            run = p.add_run(text)
            run.bold   = bold
            run.italic = italic
            run.font.size = Pt(size)
            if color:
                run.font.color.rgb = RGBColor(*color)
            return p

        def add_formula_runs(paragraph, text, font_size=11, bold=False, color=None):
            """Split text on ^{...} and _{...} patterns and add runs with sup/sub formatting.
            Also normalises LaTeX Greek/maths commands and HTML entities to Unicode first."""
            import re as _re
            text = _normalize_symbols(str(text))   # Greek letters, math symbols → Unicode
            parts = _re.split(r'(\^{[^}]{1,30}}|_{[^}]{1,30}}|\^\d+|\^[a-zA-Z]\b|_\d+)', text)
            for part in parts:
                if not part:
                    continue
                run = paragraph.add_run(part)
                run.font.size = Pt(font_size)
                if bold:
                    run.bold = bold
                if color:
                    run.font.color.rgb = RGBColor(*color)
                sup_match = _re.match(r'^\^{([^}]{1,30})}$', part)
                sub_match = _re.match(r'^_{([^}]{1,30})}$', part)
                plain_sup = _re.match(r'^\^(\d+|[a-zA-Z])$', part)
                plain_sub = _re.match(r'^_(\d+)$', part)
                if sup_match or plain_sup:
                    run.font.superscript = True
                    # replace the raw notation with just the content
                    if sup_match:
                        run.text = sup_match.group(1)
                    elif plain_sup:
                        run.text = plain_sup.group(1)
                elif sub_match or plain_sub:
                    run.font.subscript = True
                    if sub_match:
                        run.text = sub_match.group(1)
                    elif plain_sub:
                        run.text = plain_sub.group(1)

        def add_horizontal_rule(doc):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after  = Pt(2)
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement('w:pBdr')
            bottom = OxmlElement('w:bottom')
            bottom.set(qn('w:val'), 'single')
            bottom.set(qn('w:sz'), '6')
            bottom.set(qn('w:space'), '1')
            bottom.set(qn('w:color'), '667eea')
            pBdr.append(bottom)
            pPr.append(pBdr)

        # ── Header — school branding ──────────────────────────────────────────
        # Decode logo once (used below)
        _logo_buf = None
        if school_logo_b64:
            try:
                import base64 as _b64
                _logo_data = _b64.b64decode(school_logo_b64.split(',', 1)[-1])
                _logo_buf  = io.BytesIO(_logo_data)
            except Exception:
                _logo_buf = None  # skip logo if decode fails

        if _logo_buf and school_name:
            # Side-by-side: logo left (≈20% width) | school name right (≈80%)
            tbl = doc.add_table(rows=1, cols=2)
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            # Remove all table borders
            def _no_border(cell):
                tc   = cell._tc
                tcPr = tc.get_or_add_tcPr()
                tcBorders = OxmlElement('w:tcBorders')
                for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
                    b = OxmlElement(f'w:{side}')
                    b.set(qn('w:val'), 'nil')
                    tcBorders.append(b)
                tcPr.append(tcBorders)
            _no_border(tbl.cell(0, 0))
            _no_border(tbl.cell(0, 1))
            # Set column widths (page ≈ 6 inches usable)
            tbl.columns[0].width = Inches(1.1)
            tbl.columns[1].width = Inches(4.9)
            # Logo in left cell
            logo_cell = tbl.cell(0, 0)
            logo_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            lp = logo_cell.paragraphs[0]
            lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            lp.paragraph_format.space_after = Pt(0)
            lr = lp.add_run()
            lr.add_picture(_logo_buf, height=Inches(0.75))
            # School name in right cell
            name_cell = tbl.cell(0, 1)
            name_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            np_ = name_cell.paragraphs[0]
            np_.alignment = WD_ALIGN_PARAGRAPH.LEFT
            np_.paragraph_format.space_after = Pt(0)
            nr = np_.add_run(school_name.upper())
            nr.bold = True
            nr.font.size = Pt(14)
            nr.font.color.rgb = RGBColor(26, 32, 44)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
        elif _logo_buf:
            logo_p = doc.add_paragraph()
            logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            logo_p.paragraph_format.space_after = Pt(4)
            logo_p.add_run().add_picture(_logo_buf, height=Inches(0.8))
        elif school_name:
            add_para(school_name.upper(),
                     bold=True, size=14, align=WD_ALIGN_PARAGRAPH.CENTER,
                     space_after=2, color=(26, 32, 44))

        board_text = info.get('board', '')
        add_para(f"{board_text} — NCERT Curriculum",
                 align=WD_ALIGN_PARAGRAPH.CENTER, size=10,
                 color=(102, 126, 234), space_after=2)

        subject = info.get('subject', '')
        add_para(subject.upper(),
                 bold=True, size=18, align=WD_ALIGN_PARAGRAPH.CENTER,
                 space_before=0, space_after=2)

        exam_type = info.get('exam_type', '')
        add_para(exam_type,
                 bold=True, size=13, align=WD_ALIGN_PARAGRAPH.CENTER,
                 space_after=6, color=(118, 75, 162))

        teacher_name = info.get('teacher_name', '')
        if teacher_name:
            add_para(f"Teacher: {teacher_name}",
                     align=WD_ALIGN_PARAGRAPH.CENTER, size=10, space_after=4)

        # Meta row (Class | Marks | Duration | Date)
        meta_parts = []
        if info.get('class'):     meta_parts.append(f"Class: {info['class']}")
        if info.get('total_marks'): meta_parts.append(f"Max. Marks: {info['total_marks']}")
        if info.get('duration'):  meta_parts.append(f"Duration: {info['duration']}")
        _doc_date = info.get('date', '').strip()
        meta_parts.append(f"Date: {_doc_date}" if _doc_date else "Date: ___________")
        add_para("   |   ".join(meta_parts),
                 align=WD_ALIGN_PARAGRAPH.CENTER, size=10, space_after=8)

        add_horizontal_rule(doc)

        # ── Instructions ──────────────────────────────────────────────────────
        instructions = paper.get('instructions', [])
        if instructions:
            add_para("General Instructions", bold=True, size=11,
                     space_before=8, space_after=4, color=(102, 126, 234))
            for i, inst in enumerate(instructions, 1):
                p = doc.add_paragraph(style='List Number')
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run(inst)
                run.font.size = Pt(10)
            doc.add_paragraph()

        # ── Sections ──────────────────────────────────────────────────────────
        q_num = 1
        for sec in paper.get('sections', []):
            sec_name = sec.get('section_name', '')
            sec_inst = sec.get('instructions', '')

            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after  = Pt(2)
            run = p.add_run(sec_name)
            run.bold = True
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(255, 255, 255)
            # Shade the paragraph
            pPr = p._p.get_or_add_pPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), '667eea')
            pPr.append(shd)

            if sec_inst:
                add_para(sec_inst, italic=True, size=9, space_before=2,
                         space_after=6, color=(113, 128, 150))

            q_type = sec.get('type', '')
            for q in sec.get('questions', []):
                marks = q.get('marks', 1)
                marks_str = f"[{marks} mark{'s' if marks > 1 else ''}]"

                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after  = Pt(2)

                # Question number
                r_num = p.add_run(f"{q_num}. ")
                r_num.bold = True
                r_num.font.size = Pt(11)
                r_num.font.color.rgb = RGBColor(102, 126, 234)

                # Question text (with formula runs for sup/sub)
                add_formula_runs(p, q.get('text', ''), font_size=11)

                # Marks
                tab_run = p.add_run(f"  {marks_str}")
                tab_run.font.size = Pt(9)
                tab_run.font.color.rgb = RGBColor(113, 128, 150)

                # Insert attached image (if any) below the question text — centred
                img_data_url = q.get('image_data_url', '')
                if img_data_url and ',' in img_data_url:
                    try:
                        import base64 as _b64
                        from docx.enum.text import WD_ALIGN_PARAGRAPH as _WD_ALIGN_P
                        img_b64 = img_data_url.split(',', 1)[1]
                        img_bytes = _b64.b64decode(img_b64)
                        img_stream = io.BytesIO(img_bytes)
                        # Scale: image_size is a percentage (20-100), max usable width ≈ 6 in
                        img_size_pct = max(20, min(100, int(q.get('image_size', 60))))
                        img_width_in = (img_size_pct / 100.0) * 6.0
                        img_para = doc.add_paragraph()
                        img_para.alignment = _WD_ALIGN_P.CENTER
                        img_para.paragraph_format.space_before = Pt(6)
                        img_para.paragraph_format.space_after  = Pt(6)
                        img_run = img_para.add_run()
                        img_run.add_picture(img_stream, width=Inches(img_width_in))
                    except Exception:
                        pass  # silently ignore malformed image data

                # Type-specific extras
                if q_type == 'mcq' and q.get('options'):
                    for idx, opt in enumerate(q['options']):
                        label = chr(65 + idx)  # A, B, C, D
                        op = doc.add_paragraph()
                        op.paragraph_format.left_indent = Inches(0.4)
                        op.paragraph_format.space_after = Pt(1)
                        r_lbl = op.add_run(f"({label}) ")
                        r_lbl.font.size = Pt(10)
                        # Strip any existing prefix like "A) ", "(A) ", "a) ", "A. " from the AI response
                        import re as _re2
                        opt_clean = _re2.sub(r'^[\(\[]?[A-Da-d][\)\]\.][\s]+', '', str(opt))
                        add_formula_runs(op, opt_clean, font_size=10)

                elif q_type == 'fill_blank':
                    pass  # blanks already in text as ___

                elif q_type == 'match' and q.get('column_a') and q.get('column_b'):
                    col_a = q['column_a']
                    col_b = q['column_b']
                    table = doc.add_table(rows=1, cols=2)
                    table.style = 'Table Grid'
                    hdr = table.rows[0].cells
                    hdr[0].text = 'Column A'
                    hdr[1].text = 'Column B'
                    for hc in hdr:
                        for r in hc.paragraphs:
                            for run in r.runs:
                                run.bold = True
                                run.font.size = Pt(9)
                    for i in range(max(len(col_a), len(col_b))):
                        row = table.add_row().cells
                        row[0].text = f"{i+1}. {col_a[i] if i < len(col_a) else ''}"
                        row[1].text = f"{chr(97+i)}) {col_b[i] if i < len(col_b) else ''}"
                        for c in row:
                            for para in c.paragraphs:
                                for run in para.runs:
                                    run.font.size = Pt(10)
                    doc.add_paragraph()

                elif q_type == 'reading_passage' and q.get('passage'):
                    pp = doc.add_paragraph()
                    pp.paragraph_format.left_indent  = Inches(0.3)
                    pp.paragraph_format.space_before = Pt(4)
                    pp.paragraph_format.space_after  = Pt(4)
                    r = pp.add_run(q['passage'])
                    r.font.size = Pt(10)
                    r.italic = True
                    if q.get('sub_questions'):
                        for si, sq in enumerate(q['sub_questions'], 1):
                            sp = doc.add_paragraph()
                            sp.paragraph_format.left_indent = Inches(0.4)
                            sp.paragraph_format.space_after = Pt(2)
                            r2 = sp.add_run(f"({si}) {sq}")
                            r2.font.size = Pt(10)

                elif q_type == 'true_false':
                    # Add True/False indicator
                    p.add_run("  [True / False]").font.size = Pt(10)

                elif q_type == 'geometry_diagram' and q.get('figure_description'):
                    # Dashed placeholder box for geometric construction
                    fig_para = doc.add_paragraph()
                    fig_para.paragraph_format.left_indent  = Inches(0.3)
                    fig_para.paragraph_format.space_before = Pt(6)
                    fig_para.paragraph_format.space_after  = Pt(4)
                    fig_run = fig_para.add_run(f"[Construction Space] {q['figure_description']}")
                    fig_run.font.size   = Pt(9)
                    fig_run.italic      = True
                    fig_run.font.color.rgb = RGBColor(99, 102, 241)
                    # Draw a simple bordered paragraph to mimic a dashed box
                    from docx.oxml.ns import qn as _qn
                    from docx.oxml import OxmlElement as _OxmlElement
                    box_para = doc.add_paragraph()
                    box_para.paragraph_format.left_indent  = Inches(0.3)
                    box_para.paragraph_format.space_before = Pt(2)
                    box_para.paragraph_format.space_after  = Pt(8)
                    box_run = box_para.add_run(" " * 80 + "\n" * 6)
                    box_run.font.size = Pt(10)
                    pPr = box_para._p.get_or_add_pPr()
                    pBdr = _OxmlElement('w:pBdr')
                    for side in ('top', 'left', 'bottom', 'right'):
                        bdr = _OxmlElement(f'w:{side}')
                        bdr.set(_qn('w:val'), 'dashed')
                        bdr.set(_qn('w:sz'), '6')
                        bdr.set(_qn('w:space'), '4')
                        bdr.set(_qn('w:color'), '6366F1')
                        pBdr.append(bdr)
                    pPr.append(pBdr)

                q_num += 1

        # ── Answer Key ────────────────────────────────────────────────────────
        answer_key = paper.get('answer_key', [])
        if answer_key:
            doc.add_page_break()
            add_para("ANSWER KEY", bold=True, size=14,
                     align=WD_ALIGN_PARAGRAPH.CENTER,
                     space_before=0, space_after=10, color=(72, 187, 120))
            add_horizontal_rule(doc)
            doc.add_paragraph()

            # Render in a 3-column table
            cols = 3
            rows_needed = (len(answer_key) + cols - 1) // cols
            table = doc.add_table(rows=rows_needed, cols=cols)
            table.style = 'Table Grid'
            idx = 0
            for row in table.rows:
                for cell in row.cells:
                    if idx < len(answer_key):
                        ak = answer_key[idx]
                        cell.text = f"{ak.get('q_id', '')}: {ak.get('answer', '')}"
                        for para in cell.paragraphs:
                            for run in para.runs:
                                run.font.size = Pt(9)
                        idx += 1

        # ── Save & return ─────────────────────────────────────────────────────
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        subject_slug = subject.replace(' ', '_')[:20]
        class_val    = info.get('class', 'X')
        filename     = f"QuestionPaper_{subject_slug}_Class{class_val}.docx"

        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE INITIALISATION & STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

with app.app_context():
    db.create_all()

    # ── Schema migrations for existing databases ──────────────────────────────
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    insp = sa_inspect(db.engine)
    if 'users' in insp.get_table_names():
        existing_cols = {c['name'] for c in insp.get_columns('users')}
        db_url = str(db.engine.url)

        with db.engine.connect() as conn:
            # Add password_hash column if missing
            if 'password_hash' not in existing_cols:
                try:
                    conn.execute(sa_text('ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)'))
                    conn.commit()
                except Exception:
                    pass

            # Make google_id nullable (PostgreSQL only — SQLite doesn't support this but
            # fresh SQLite DBs already have the correct nullable schema)
            if 'postgresql' in db_url:
                try:
                    conn.execute(sa_text('ALTER TABLE users ALTER COLUMN google_id DROP NOT NULL'))
                    conn.commit()
                except Exception:
                    pass

    # Migrate question_papers table
    if 'question_papers' in insp.get_table_names():
        qp_cols = {c['name'] for c in insp.get_columns('question_papers')}
        with db.engine.connect() as conn:
            if 'archived' not in qp_cols:
                try:
                    conn.execute(sa_text('ALTER TABLE question_papers ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0'))
                    conn.commit()
                except Exception:
                    pass
            if 'archived_at' not in qp_cols:
                try:
                    conn.execute(sa_text('ALTER TABLE question_papers ADD COLUMN archived_at DATETIME'))
                    conn.commit()
                except Exception:
                    pass

    # Migrate user_profiles table — ensure school_logo column exists
    if 'user_profiles' in insp.get_table_names():
        up_cols = {c['name'] for c in insp.get_columns('user_profiles')}
        with db.engine.connect() as conn:
            if 'school_logo' not in up_cols:
                try:
                    conn.execute(sa_text('ALTER TABLE user_profiles ADD COLUMN school_logo TEXT'))
                    conn.commit()
                except Exception:
                    pass
            if 'updated_at' not in up_cols:
                try:
                    conn.execute(sa_text('ALTER TABLE user_profiles ADD COLUMN updated_at DATETIME'))
                    conn.commit()
                except Exception:
                    pass


if __name__ == '__main__':
    print("\n" + "=" * 56)
    print("       ExamCraft India — AI-Powered Exam Platform")
    print("=" * 56)
    print("  Access: http://localhost:5000")
    if not os.environ.get('GOOGLE_API_KEY'):
        print("\n  [WARNING] GOOGLE_API_KEY is not set!")
        print("  Get a FREE key at: https://aistudio.google.com/apikey")
        print("  Then run: $env:GOOGLE_API_KEY = 'your_key_here'")
        print("  And restart the server.")
    if not _OAUTH_CONFIGURED:
        print("\n  [INFO] Google OAuth not configured (optional).")
        print("  Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable login.")
    print("=" * 56 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
