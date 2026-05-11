import os
import json
import io
import uuid
import tempfile
import re
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

# SQLite database
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(BASE_DIR, 'examcraft.db')}"
)
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
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')


def send_contact_email(name, email, mobile, school_name, message, request_type):
    if not SMTP_USER or not SMTP_PASS:
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'ExamCraft India - {"Callback Request" if request_type == "callback" else "Contact Request"} from {name}'
        msg['From'] = SMTP_USER
        msg['To'] = CONTACT_EMAIL
        msg['Reply-To'] = email
        body = f"""ExamCraft India - New {request_type.title()} Request

Name: {name}
Email: {email}
Mobile: {mobile or 'Not provided'}
School: {school_name or 'Not provided'}
Type: {request_type.title()}

Message:
{message or 'No message provided'}

---
Received at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
"""
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, CONTACT_EMAIL, msg.as_string())
        return True
    except Exception as e:
        print(f'Email send error: {e}')
        return False


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


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ═══════════════════════════════════════════════════════════════════════════════
# PLANS & SUBSCRIPTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

PLANS = {
    'free':   {'name': 'Free',   'price_monthly': 0,    'papers_per_month': 3,  'evals_per_month': 5,  'features': ['3 papers / month', '5 evaluations / month', 'All boards & subjects', 'PDF & Word download']},
    'pro':    {'name': 'Pro',    'price_monthly': 299,  'papers_per_month': -1, 'evals_per_month': -1, 'features': ['Unlimited papers', 'Unlimited evaluations', 'Word download', 'Priority support', 'Everything in Free']},
    'school': {'name': 'School', 'price_monthly': 2999, 'papers_per_month': -1, 'evals_per_month': -1, 'features': ['Everything in Pro', 'Up to 10 teacher accounts', 'School branding', 'Dedicated support']},
}


def get_user_plan(user_id):
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


def extract_json(text):
    """Extract JSON from model response, handling markdown code fences."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text.strip(), flags=re.MULTILINE)
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("No JSON object found in response")
    return json.loads(match.group())


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
        "6": ["Knowing Our Numbers", "Whole Numbers", "Playing with Numbers",
               "Basic Geometrical Ideas", "Understanding Elementary Shapes", "Integers",
               "Fractions", "Decimals", "Data Handling", "Mensuration", "Algebra",
               "Ratio and Proportion", "Symmetry", "Practical Geometry"],
        "7": ["Integers", "Fractions and Decimals", "Data Handling", "Simple Equations",
               "Lines and Angles", "The Triangle and its Properties", "Congruence of Triangles",
               "Comparing Quantities", "Rational Numbers", "Practical Geometry",
               "Perimeter and Area", "Algebraic Expressions", "Exponents and Powers",
               "Symmetry", "Visualising Solid Shapes"],
        "8": ["Rational Numbers", "Linear Equations in One Variable",
               "Understanding Quadrilaterals", "Practical Geometry", "Data Handling",
               "Squares and Square Roots", "Cubes and Cube Roots", "Comparing Quantities",
               "Algebraic Expressions and Identities", "Visualising Solid Shapes",
               "Mensuration", "Exponents and Powers", "Direct and Inverse Proportions",
               "Factorisation", "Introduction to Graphs", "Playing with Numbers"],
        "9": ["Number Systems", "Polynomials", "Coordinate Geometry",
               "Linear Equations in Two Variables", "Introduction to Euclid's Geometry",
               "Lines and Angles", "Triangles", "Quadrilaterals",
               "Areas of Parallelograms and Triangles", "Circles", "Constructions",
               "Heron's Formula", "Surface Areas and Volumes", "Statistics", "Probability"],
        "10": ["Real Numbers", "Polynomials", "Pair of Linear Equations in Two Variables",
                "Quadratic Equations", "Arithmetic Progressions", "Triangles",
                "Coordinate Geometry", "Introduction to Trigonometry",
                "Some Applications of Trigonometry", "Circles", "Constructions",
                "Areas Related to Circles", "Surface Areas and Volumes", "Statistics", "Probability"],
        "11": ["Sets", "Relations and Functions", "Trigonometric Functions",
                "Principle of Mathematical Induction",
                "Complex Numbers and Quadratic Equations", "Linear Inequalities",
                "Permutations and Combinations", "Binomial Theorem", "Sequences and Series",
                "Straight Lines", "Conic Sections",
                "Introduction to Three Dimensional Geometry",
                "Limits and Derivatives", "Mathematical Reasoning", "Statistics", "Probability"],
        "12": ["Relations and Functions", "Inverse Trigonometric Functions", "Matrices",
                "Determinants", "Continuity and Differentiability",
                "Application of Derivatives", "Integrals", "Application of Integrals",
                "Differential Equations", "Vector Algebra", "Three Dimensional Geometry",
                "Linear Programming", "Probability"],
    },
    "Science": {
        "6": ["Food: Where Does It Come From?", "Components of Food", "Fibre to Fabric",
               "Sorting Materials into Groups", "Separation of Substances", "Changes Around Us",
               "Getting to Know Plants", "Body Movements",
               "The Living Organisms and Their Surroundings",
               "Motion and Measurement of Distances", "Light, Shadows and Reflections",
               "Electricity and Circuits", "Fun with Magnets", "Water", "Air Around Us",
               "Garbage In, Garbage Out"],
        "7": ["Nutrition in Plants", "Nutrition in Animals", "Fibre to Fabric", "Heat",
               "Acids, Bases and Salts", "Physical and Chemical Changes",
               "Weather, Climate and Adaptations of Animals to Climate",
               "Winds, Storms and Cyclones", "Soil", "Respiration in Organisms",
               "Transportation in Animals and Plants", "Reproduction in Plants",
               "Motion and Time", "Electric Current and its Effects", "Light",
               "Water: A Precious Resource", "Forests: Our Lifeline", "Wastewater Story"],
        "8": ["Crop Production and Management", "Microorganisms: Friend and Foe",
               "Synthetic Fibres and Plastics", "Materials: Metals and Non-Metals",
               "Coal and Petroleum", "Combustion and Flame",
               "Conservation of Plants and Animals", "Cell Structure and Functions",
               "Reproduction in Animals", "Reaching the Age of Adolescence",
               "Force and Pressure", "Friction", "Sound",
               "Chemical Effects of Electric Current", "Some Natural Phenomena", "Light",
               "Stars and the Solar System", "Pollution of Air and Water"],
        "9": ["Matter in Our Surroundings", "Is Matter Around Us Pure?",
               "Atoms and Molecules", "Structure of the Atom",
               "The Fundamental Unit of Life", "Tissues",
               "Diversity in Living Organisms", "Motion", "Force and Laws of Motion",
               "Gravitation", "Work and Energy", "Sound", "Why Do We Fall Ill?",
               "Natural Resources", "Improvement in Food Resources"],
        "10": ["Chemical Reactions and Equations", "Acids, Bases and Salts",
                "Metals and Non-metals", "Carbon and its Compounds",
                "Periodic Classification of Elements", "Life Processes",
                "Control and Coordination", "How do Organisms Reproduce?",
                "Heredity and Evolution", "Light – Reflection and Refraction",
                "Human Eye and Colourful World", "Electricity",
                "Magnetic Effects of Electric Current", "Sources of Energy",
                "Our Environment", "Sustainable Management of Natural Resources"],
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
                "Semiconductor Electronics", "Communication Systems"],
    },
    "Chemistry": {
        "11": ["Some Basic Concepts of Chemistry", "Structure of Atom",
                "Classification of Elements and Periodicity in Properties",
                "Chemical Bonding and Molecular Structure", "States of Matter",
                "Thermodynamics", "Equilibrium", "Redox Reactions", "Hydrogen",
                "The s-Block Elements", "The p-Block Elements",
                "Organic Chemistry – Some Basic Principles and Techniques",
                "Hydrocarbons", "Environmental Chemistry"],
        "12": ["The Solid State", "Solutions", "Electrochemistry", "Chemical Kinetics",
                "Surface Chemistry",
                "General Principles and Processes of Isolation of Elements",
                "The p-Block Elements", "The d- and f-Block Elements",
                "Coordination Compounds", "Haloalkanes and Haloarenes",
                "Alcohols, Phenols and Ethers",
                "Aldehydes, Ketones and Carboxylic Acids", "Amines", "Biomolecules",
                "Polymers", "Chemistry in Everyday Life"],
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
                "Ecosystem", "Biodiversity and Conservation", "Environmental Issues"],
    },
    "Social Science": {
        "6": {
            "History": ["What, Where, How and When?", "From Hunting-Gathering to Growing Food",
                        "In the Earliest Cities", "What Books and Burials Tell Us",
                        "Kingdoms, Kings and an Early Republic", "New Questions and Ideas",
                        "Ashoka, The Emperor Who Gave Up War", "Vital Villages, Thriving Towns",
                        "Traders, Kings and Pilgrims", "New Empires and Kingdoms",
                        "Buildings, Paintings and Books"],
            "Geography": ["The Earth in the Solar System", "Globe: Latitudes and Longitudes",
                          "Motions of the Earth", "Maps", "Major Domains of the Earth",
                          "Major Landforms of the Earth", "Our Country – India",
                          "India: Climate, Vegetation and Wildlife"],
            "Civics": ["Understanding Diversity", "Diversity and Discrimination",
                       "What is Government?", "Key Elements of a Democratic Government",
                       "Panchayati Raj", "Rural Administration", "Urban Administration",
                       "Rural Livelihoods", "Urban Livelihoods"],
        },
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
        "6": ["वह चिड़िया जो", "बचपन", "नादान दोस्त", "चाँद से थोड़ी सी गप्पें",
               "अक्षरों का महत्त्व", "पार नज़र के", "साथी हाथ बढ़ाना", "ऐसे–ऐसे",
               "टिकट–अलबम", "झाँसी की रानी", "जो देखकर भी नहीं देखते",
               "संसार पुस्तक है", "मैं सबसे छोटी होऊँ", "लोकगीत", "नौकर",
               "वन के मार्ग में", "साँस–साँस में बाँस"],
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
               "दशमः त्वम् असि", "विमानयानं रचयाम"],
        "9": ["भारतीवसन्तगीतिः", "स्वर्णकाकः", "गोदोहनम्", "कल्पतरूः",
               "सूक्तिमौक्तिकम्", "भ्रान्तो बालः", "प्रत्यभिज्ञानम्",
               "लौहतुला", "सिकतासेतुः", "जटायोः शौर्यम्"],
        "10": ["शुचिपर्यावरणम्", "बुद्धिर्बलवती सदा", "शिशुलालनम्",
                "जननी तुल्यवत्सला", "सुभाषितानि", "सौहार्दं प्रकृतेः शोभा",
                "विचित्रः साक्षी", "सूक्तयः", "भारतीयसंस्काराः", "नीतिनवनीतम्"],
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
# STATIC DATA — SUBJECT QUESTION TYPES
# ═══════════════════════════════════════════════════════════════════════════════

SUBJECT_QUESTION_TYPES = {
    "Mathematics": [
        {"key": "mcq",          "label": "Multiple Choice",          "icon": "check-circle",  "default_count": 10, "default_marks": 1, "enabled": True},
        {"key": "fill_blank",   "label": "Fill in the Blanks",       "icon": "edit-3",        "default_count": 5,  "default_marks": 1, "enabled": True},
        {"key": "short_answer", "label": "Very Short Answer (VSA)",  "icon": "file-text",     "default_count": 5,  "default_marks": 2, "enabled": True},
        {"key": "long_answer",  "label": "Proof / Derivation",       "icon": "book-open",     "default_count": 4,  "default_marks": 5, "enabled": True},
        {"key": "case_study",   "label": "Case Study / Passage",     "icon": "layers",        "default_count": 2,  "default_marks": 4, "enabled": True},
        {"key": "construction", "label": "Graph / Coordinate Work",  "icon": "pen-tool",      "default_count": 2,  "default_marks": 3, "enabled": False},
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
    "construction":       "Graph or Geometric Construction – students construct a graph, geometric figure, or coordinate plot with proper labelling",
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


@app.route('/api/subjects', methods=['POST'])
def get_subjects():
    data = request.json
    class_num = str(data.get('class_num', ''))
    subjects = SUBJECTS_BY_CLASS.get(class_num, [])
    return jsonify({'subjects': subjects})


@app.route('/api/chapters', methods=['POST'])
def get_chapters():
    data = request.json
    subject   = data.get('subject', '')
    class_num = str(data.get('class_num', ''))

    chapters = []
    if subject in NCERT_CHAPTERS:
        subj_data = NCERT_CHAPTERS[subject]
        if class_num in subj_data:
            class_data = subj_data[class_num]
            if isinstance(class_data, list):
                chapters = class_data
            elif isinstance(class_data, dict):
                for sub_topic, ch_list in class_data.items():
                    for ch in ch_list:
                        chapters.append(f"{sub_topic}: {ch}")

    return jsonify({'chapters': chapters})


@app.route('/api/question-types', methods=['GET'])
def get_question_types():
    subject = request.args.get('subject', '')
    types   = SUBJECT_QUESTION_TYPES.get(subject) or SUBJECT_QUESTION_TYPES.get('_default', [])
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

    email_sent = send_contact_email(name, email, mobile, school_name, message, request_type)
    return jsonify({'success': True, 'email_sent': email_sent})


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATE PAPER ROUTE
# ═══════════════════════════════════════════════════════════════════════════════

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
        for key, cfg in question_types.items():
            count = cfg.get('count', 0)
            if count <= 0:
                continue
            marks      = cfg.get('marks', 1)
            sec_letter = section_letters[sec_index] if sec_index < len(section_letters) else str(sec_index + 1)
            # Get the human-readable label from SUBJECT_QUESTION_TYPES
            all_types  = SUBJECT_QUESTION_TYPES.get(subject, SUBJECT_QUESTION_TYPES['_default'])
            type_label = next((t['label'] for t in all_types if t['key'] == key), key.replace('_', ' ').title())
            description= QUESTION_TYPE_DESCRIPTIONS.get(key, type_label)
            sections_desc.append(
                f"Section {sec_letter} – {type_label} ({description}): "
                f"{count} question(s) × {marks} mark(s) each = {count * marks} marks"
            )
            sec_index += 1

        chapters_str = ', '.join(chapters) if chapters else 'All chapters'

        difficulty_map = {
            'easy':   'Easy (80% Easy, 20% Medium)',
            'medium': 'Medium (20% Easy, 60% Medium, 20% Hard)',
            'hard':   'Hard (20% Medium, 80% Hard)',
            'mixed':  'Mixed (30% Easy, 50% Medium, 20% Hard)',
        }
        diff_desc = difficulty_map.get(difficulty.lower(), 'Mixed')

        teacher_line = f"- Teacher / Examiner: {teacher_name}" if teacher_name else ""

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

QUESTION PAPER STRUCTURE:
{chr(10).join(sections_desc)}

INSTRUCTIONS FOR GENERATION:
1. Create curriculum-appropriate questions strictly based on NCERT content
2. Ensure questions test different cognitive levels (knowledge, understanding, application)
3. For MCQs: provide 4 options (A, B, C, D) — only one correct
4. For Match the Following: create two columns with 4-6 items each
5. For Fill in the Blanks: leave clear blanks (_____)
6. For Diagram questions: specify what to draw/label with clear instructions
7. Include proper general instructions at the top
8. Add complete answer key at the end
9. Use ^{{text}} for superscripts (e.g., x^{{2}}, CO_2^{{-}}) and _{{text}} for subscripts (e.g., H_{{2}}O, CO_{{2}}). Use these for all chemical formulas and math expressions.

{"Reference the uploaded chapter content/images for question creation." if pil_images else ""}

Return ONLY a valid JSON object (no markdown, no explanation) with this EXACT structure:
{{
  "paper_info": {{
    "board": "{board}",
    "class": "{class_num}",
    "subject": "{subject}",
    "exam_type": "{exam_type} Examination",
    "total_marks": {total_marks},
    "duration": "{duration}",
    "teacher_name": "{teacher_name}",
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

Generate all questions as specified. Make them appropriate for Class {class_num} {subject} {board} students."""

        # Build Gemini content: images first, then the prompt text
        contents = pil_images + [prompt_text]

        response = gemini.models.generate_content(
            model='models/gemini-2.5-flash',
            contents=contents,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=16000,
                temperature=0.7,
                response_mime_type='application/json',
            ),
        )

        response_text = response.text

        try:
            paper_json = json.loads(response_text)
        except json.JSONDecodeError:
            try:
                paper_json = extract_json(response_text)
            except (ValueError, json.JSONDecodeError) as e:
                return jsonify({'error': f'Failed to parse generated paper: {str(e)}', 'raw_preview': response_text[:300]}), 500

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
        return jsonify({'error': str(e)}), 500


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

        response = gemini.models.generate_content(
            model='models/gemini-2.5-flash',
            contents=contents,
            config=genai_types.GenerateContentConfig(
                max_output_tokens=12000,
                temperature=0.3,
                response_mime_type='application/json',
            ),
        )

        response_text = response.text
        try:
            eval_json = json.loads(response_text)
        except json.JSONDecodeError:
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
        return jsonify({'error': str(e)}), 500
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
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        paper_json_str = request.form.get('paper_json', '')
        if not paper_json_str:
            return jsonify({'error': 'No paper data provided'}), 400
        paper = json.loads(paper_json_str)

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
            """Split text on ^{...} and _{...} patterns and add runs with sup/sub formatting."""
            import re as _re
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

        # ── Header ────────────────────────────────────────────────────────────
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
        meta_parts.append("Date: ___________")
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

                # Type-specific extras
                if q_type == 'mcq' and q.get('options'):
                    for idx, opt in enumerate(q['options']):
                        label = chr(65 + idx)  # A, B, C, D
                        op = doc.add_paragraph()
                        op.paragraph_format.left_indent = Inches(0.4)
                        op.paragraph_format.space_after = Pt(1)
                        r_lbl = op.add_run(f"({label}) ")
                        r_lbl.font.size = Pt(10)
                        add_formula_runs(op, str(opt), font_size=10)

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
