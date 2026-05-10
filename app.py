import os
import json
import io
import tempfile
import re
from flask import Flask, render_template, request, jsonify, session
from google import genai
from google.genai import types as genai_types
from PIL import Image
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'examcraft_india_secret_key_2024')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

UPLOAD_FOLDER = tempfile.mkdtemp()
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt'}

def get_gemini_client():
    api_key = os.environ.get('GOOGLE_API_KEY', '')
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

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
                "Linear Programming", "Probability"]
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
                "Our Environment", "Sustainable Management of Natural Resources"]
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
                "Semiconductor Electronics", "Communication Systems"]
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
                "Polymers", "Chemistry in Everyday Life"]
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
                "Ecosystem", "Biodiversity and Conservation", "Environmental Issues"]
    },
    "Social Science": {
        "6": {
            "History": ["What, Where, How and When?",
                        "From Hunting-Gathering to Growing Food",
                        "In the Earliest Cities",
                        "What Books and Burials Tell Us",
                        "Kingdoms, Kings and an Early Republic",
                        "New Questions and Ideas",
                        "Ashoka, The Emperor Who Gave Up War",
                        "Vital Villages, Thriving Towns",
                        "Traders, Kings and Pilgrims",
                        "New Empires and Kingdoms",
                        "Buildings, Paintings and Books"],
            "Geography": ["The Earth in the Solar System",
                          "Globe: Latitudes and Longitudes",
                          "Motions of the Earth", "Maps",
                          "Major Domains of the Earth",
                          "Major Landforms of the Earth",
                          "Our Country – India",
                          "India: Climate, Vegetation and Wildlife"],
            "Civics": ["Understanding Diversity", "Diversity and Discrimination",
                       "What is Government?",
                       "Key Elements of a Democratic Government",
                       "Panchayati Raj", "Rural Administration",
                       "Urban Administration", "Rural Livelihoods",
                       "Urban Livelihoods"]
        },
        "7": {
            "History": ["Tracing Changes Through A Thousand Years",
                        "New Kings and Kingdoms", "The Delhi Sultans",
                        "The Mughal Empire", "Rulers and Buildings",
                        "Towns, Traders and Craftspersons",
                        "Tribes, Nomads and Settled Communities",
                        "Devotional Paths to the Divine",
                        "The Making of Regional Cultures",
                        "Eighteenth-Century Political Formations"],
            "Geography": ["Environment", "Inside Our Earth",
                          "Our Changing Earth", "Air", "Water",
                          "Natural Vegetation and Wildlife",
                          "Human Environment – Settlement, Transport and Communication",
                          "Human-Environment Interactions – The Tropical and the Subtropical Region",
                          "Life in the Temperate Grasslands",
                          "Life in the Deserts"],
            "Civics": ["On Equality", "Role of the Government in Health",
                       "How the State Government Works",
                       "Growing up as Boys and Girls",
                       "Women Change the World", "Understanding Media",
                       "Markets Around Us", "A Shirt in the Market",
                       "Struggles for Equality"]
        },
        "8": {
            "History": ["How, When and Where", "From Trade to Territory",
                        "Ruling the Countryside",
                        "Tribals, Dikus and the Vision of a Golden Age",
                        "When People Rebel", "Colonialism and the City",
                        "Weavers, Iron Smelters and Factory Owners",
                        "Civilising the 'Native', Educating the Nation",
                        "Women, Caste and Reform",
                        "The Changing World of Visual Arts",
                        "The Making of the National Movement",
                        "India After Independence"],
            "Geography": ["Resources", "Land, Soil, Water, Natural Vegetation and Wildlife Resources",
                          "Mineral and Power Resources", "Agriculture",
                          "Industries", "Human Resources"],
            "Civics": ["The Indian Constitution", "Understanding Secularism",
                       "Why Do We Need a Parliament?", "Understanding Laws",
                       "Judiciary", "Understanding Our Criminal Justice System",
                       "Understanding Marginalisation",
                       "Confronting Marginalisation", "Public Facilities",
                       "Law and Social Justice"]
        },
        "9": {
            "History": ["The French Revolution",
                        "Socialism in Europe and the Russian Revolution",
                        "Nazism and the Rise of Hitler",
                        "Forest Society and Colonialism",
                        "Pastoralists in the Modern World"],
            "Geography": ["India – Size and Location",
                          "Physical Features of India", "Drainage",
                          "Climate", "Natural Vegetation and Wildlife",
                          "Population"],
            "Civics": ["What is Democracy? Why Democracy?",
                       "Constitutional Design", "Electoral Politics",
                       "Working of Institutions", "Democratic Rights"],
            "Economics": ["The Story of Village Palampur",
                          "People as Resource", "Poverty as a Challenge",
                          "Food Security in India"]
        },
        "10": {
            "History": ["The Rise of Nationalism in Europe",
                        "Nationalism in India",
                        "The Making of a Global World",
                        "The Age of Industrialisation",
                        "Print Culture and the Modern World"],
            "Geography": ["Resources and Development",
                          "Forest and Wildlife Resources", "Water Resources",
                          "Agriculture", "Minerals and Energy Resources",
                          "Manufacturing Industries",
                          "Lifelines of National Economy"],
            "Civics": ["Power Sharing", "Federalism",
                       "Gender, Religion and Caste", "Political Parties",
                       "Outcomes of Democracy", "Challenges to Democracy"],
            "Economics": ["Development",
                          "Sectors of the Indian Economy",
                          "Money and Credit",
                          "Globalisation and the Indian Economy",
                          "Consumer Rights"]
        }
    },
    "English": {
        "6": ["Who Did Patrick's Homework?", "How the Dog Found Himself a New Master!",
               "Taros's Reward", "An Indian – American Woman in Space: Kalpana Chawla",
               "A Different Kind of School", "Who I Am",
               "Fair Play", "A Game of Chance",
               "Desert Animals", "The Banyan Tree"],
        "7": ["Three Questions", "A Gift of Chappals", "Gopal and the Hilsa Fish",
               "The Ashes That Made Trees Bloom", "Quality",
               "Expert Detectives", "The Invention of Vita-Wonk",
               "Fire: Friend and Foe", "A Bicycle in Good Repair",
               "The Story of Cricket"],
        "8": ["The Best Christmas Present in the World", "The Tsunami",
               "Glimpses of the Past", "Bepin Choudhury's Lapse of Memory",
               "The Summit Within", "This is Jody's Fawn",
               "A Visit to Cambridge", "A Short Monsoon Diary",
               "The Great Stone Face–I", "The Great Stone Face–II"],
        "9": ["The Fun They Had", "The Sound of Music", "The Little Girl",
               "A Truly Beautiful Mind", "The Snake and the Mirror",
               "My Childhood", "Packing", "Reach for the Top",
               "The Bond of Love", "Kathmandu", "If I Were You"],
        "10": ["A Letter to God", "Nelson Mandela: Long Walk to Freedom",
                "Two Stories about Flying", "From the Diary of Anne Frank",
                "The Hundred Dresses–I", "The Hundred Dresses–II",
                "Glimpses of India", "Mijbil the Otter",
                "Madam Rides the Bus", "The Sermon at Benares", "The Proposal"],
        "11": ["The Portrait of a Lady", "We're Not Afraid to Die...",
                "Discovering Tut: the Saga Continues",
                "Landscape of the Soul",
                "The Ailing Planet: the Green Movement's Role",
                "The Browning Version", "The Adventure", "Silk Road"],
        "12": ["The Last Lesson", "Lost Spring", "Deep Water",
                "The Rattrap", "Indigo", "Poets and Pancakes",
                "The Interview", "Going Places"]
    },
    "Hindi": {
        "6": ["वह चिड़िया जो", "बचपन", "नादान दोस्त", "चाँद से थोड़ी सी गप्पें",
               "अक्षरों का महत्त्व", "पार नज़र के", "साथी हाथ बढ़ाना",
               "ऐसे–ऐसे", "टिकट–अलबम", "झाँसी की रानी",
               "जो देखकर भी नहीं देखते", "संसार पुस्तक है",
               "मैं सबसे छोटी होऊँ", "लोकगीत", "नौकर",
               "वन के मार्ग में", "साँस–साँस में बाँस"],
        "9": ["दो बैलों की कथा", "ल्हासा की ओर",
               "उपभोक्तावाद की संस्कृति", "साँवले सपनों की याद",
               "नाना साहब की पुत्री देवी मैना को भस्म कर दिया गया",
               "प्रेमचंद के फटे जूते", "मेरे बचपन के दिन",
               "एक कुत्ता और एक मैना"],
        "10": ["सूरदास के पद", "राम-लक्ष्मण-परशुराम संवाद",
                "सवैया और कवित्त", "आत्मकथ्य",
                "उत्साह और अट नहीं रही",
                "यह दंतुरहित मुस्कान और फसल",
                "छाया मत छूना", "कन्यादान", "संगतकार",
                "नेताजी का चश्मा", "बालगोबिन भगत",
                "लखनवी अंदाज़",
                "मानवीय करुणा की दिव्य चमक",
                "एक कहानी यह भी",
                "स्त्री शिक्षा के विरोधी कुतर्कों का खंडन",
                "नौबतखाने में इबादत", "संस्कृति"],
        "11": ["हम तौ एक एक करि जाना", "संतों देखत जग बौराना",
                "वे आँखें", "घर की याद",
                "चंपा काले काले अच्छर नहीं चीन्हती",
                "गालिब के पत्र", "ओ सदानीरा", "आत्मा का ताप"],
        "12": ["आत्म-परिचय, एक गीत", "पतंग",
                "कविता के बहाने, बात सीधी थी पर",
                "कैमरे में बंद अपाहिज", "सहर्ष स्वीकारा है",
                "उषा", "बादल राग",
                "कवितावली (उत्तर काण्ड से), लक्ष्मण-मूर्च्छा और राम का विलाप",
                "रुबाइयाँ, गज़ल",
                "छोटा मेरा खेत, बगुलों के पंख"]
    },
    "Sanskrit": {
        "6": ["सुभाषितानि", "दशमः त्वम् असि", "बालिका पाठशाला",
               "विद्यालयः", "वृक्षाः", "समुद्रतटः", "बकस्य प्रतिकारः",
               "सूक्तिस्तबकः", "क्रीडास्पर्धा", "कृषिकाः कर्मवीराः",
               "पुष्पोत्सवः", "दशमः त्वम् असि", "विमानयानं रचयाम"],
        "9": ["भारतीवसन्तगीतिः", "स्वर्णकाकः",
               "गोदोहनम्", "कल्पतरूः", "सूक्तिमौक्तिकम्",
               "भ्रान्तो बालः", "प्रत्यभिज्ञानम्",
               "लौहतुला", "सिकतासेतुः", "जटायोः शौर्यम्"],
        "10": ["शुचिपर्यावरणम्", "बुद्धिर्बलवती सदा",
                "शिशुलालनम्", "जननी तुल्यवत्सला",
                "सुभाषितानि", "सौहार्दं प्रकृतेः शोभा",
                "विचित्रः साक्षी", "सूक्तयः", "भारतीयसंस्काराः",
                "नीतिनवनीतम्"]
    },
    "Environmental Studies (EVS)": {
        "1": ["My Body", "Good Habits and Safety Rules", "Food We Eat", "Shelter",
               "Family", "Plants Around Us", "Animals Around Us",
               "Transport", "Festivals and Celebrations", "Water", "Air", "The Sky"],
        "2": ["My Family", "Foods We Eat", "Where Do Animals Live?",
               "Our Helpful Friends", "Clothes We Wear", "We All Play",
               "Keeping Safe", "Our Garden", "Water", "Our School"],
        "3": ["Poonam's Day Out", "The Plant Fairy", "Water O Water",
               "Our First School", "Chhotu's House", "Foods We Eat",
               "Saying Without Speaking", "Flying High", "It's Raining",
               "What is Cooking?", "From Here to There", "Work We Do",
               "Sharing Our Feelings", "The Story of Food"],
        "4": ["Going to School", "Ear to Ear", "A Day with Nandu",
               "The Story of Amrita", "Anita and the Honeybees",
               "Omana's Journey", "From the Window",
               "Reaching Grandmother's House", "Changing Families",
               "Hu Tu Tu, Hu Tu Tu", "The Valley of Flowers",
               "Changing Times", "A River's Tale", "Basva's Farm",
               "From Market to Home", "A Busy Month", "Nandita in Mumbai",
               "Too Much Water, Too Little Water", "Abdul in the Garden",
               "Eating Together", "Food and Fun", "The World in My Home"],
        "5": ["Super Senses", "A Snake Charmer's Story",
               "From Tasting to Digesting", "Mangoes Round the Year",
               "Seeds and Seeds", "Every Drop Counts",
               "Experiments with Water", "A Treat for Mosquitoes",
               "Up You Go!", "Walls Tell Stories", "Sunita in Space",
               "What if it Finishes?", "A Shelter So High!",
               "When the Earth Shook!", "Blow Hot, Blow Cold",
               "Who Will Do This Work?", "Across the Wall",
               "No Place for Us?", "A Seed Tells a Farmer's Story",
               "Whose Forests?", "Like Father, Like Daughter",
               "On the Move Again"]
    },
    "Economics": {
        "11": ["Indian Economy on the Eve of Independence",
                "Indian Economy 1950-1990",
                "Liberalisation, Privatisation and Globalisation: An Appraisal",
                "Poverty", "Human Capital Formation in India",
                "Rural Development",
                "Employment: Growth, Informalisation and Other Issues",
                "Infrastructure", "Environment and Sustainable Development",
                "Comparative Development Experiences of India and its Neighbours"],
        "12": ["Introduction to Microeconomics", "Theory of Consumer Behaviour",
                "Production and Costs",
                "The Theory of the Firm under Perfect Competition",
                "Market Equilibrium", "Non-competitive Markets",
                "Introduction to Macroeconomics", "National Income Accounting",
                "Money and Banking",
                "Determination of Income and Employment",
                "Government Budget and the Economy",
                "Open Economy Macroeconomics"]
    },
    "Business Studies": {
        "11": ["Nature and Purpose of Business",
                "Forms of Business Organisation",
                "Private, Public and Global Enterprises", "Business Services",
                "Emerging Modes of Business",
                "Social Responsibilities of Business and Business Ethics",
                "Formation of a Company", "Sources of Business Finance",
                "Small Business", "Internal Trade", "International Business"],
        "12": ["Nature and Significance of Management",
                "Principles of Management", "Business Environment", "Planning",
                "Organising", "Staffing", "Directing", "Controlling",
                "Financial Management", "Financial Markets",
                "Marketing Management", "Consumer Protection"]
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
                "Dissolution of Partnership Firm",
                "Accounting for Share Capital",
                "Issue and Redemption of Debentures",
                "Financial Statements of a Company",
                "Analysis of Financial Statements", "Accounting Ratios",
                "Cash Flow Statement"]
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
                "Peasants, Zamindars and the State",
                "Kings and Chronicles",
                "Colonialism and the Countryside", "Rebels and the Raj",
                "Colonial Cities",
                "Mahatma Gandhi and the Nationalist Movement",
                "Understanding Partition", "Framing the Constitution"]
    },
    "Geography": {
        "11": ["Geography as a Discipline",
                "The Origin and Evolution of the Earth",
                "Interior of the Earth",
                "Distribution of Oceans and Continents",
                "Minerals and Rocks", "Geomorphic Processes",
                "Landforms and their Evolution",
                "Composition and Structure of Atmosphere",
                "Solar Radiation, Heat Balance and Temperature",
                "Atmospheric Circulation and Weather Systems",
                "Water in the Atmosphere",
                "World Climate and Climate Change",
                "Water (Oceans)", "Movements of Ocean Water",
                "Life on the Earth", "Biodiversity and Conservation"],
        "12": ["Population: Distribution, Density, Growth and Composition",
                "Migration: Types, Causes and Consequences",
                "Human Development", "Human Settlements",
                "Land Resources and Agriculture", "Water Resources",
                "Mineral and Energy Resources", "Manufacturing Industries",
                "Planning and Sustainable Development in Indian Context",
                "Transport and Communication", "International Trade",
                "Geographical Perspective on Selected Issues and Problems"]
    },
    "Political Science": {
        "11": ["Constitution: Why and How?",
                "Rights in the Indian Constitution",
                "Election and Representation", "Executive", "Legislature",
                "Judiciary", "Federalism", "Local Governments",
                "Constitution as a Living Document",
                "The Philosophy of the Constitution"],
        "12": ["Cold War Era", "The End of Bipolarity",
                "US Hegemony in World Politics",
                "Alternative Centres of Power",
                "Contemporary South Asia", "International Organisations",
                "Security in the Contemporary World",
                "Environment and Natural Resources", "Globalisation",
                "Challenges of Nation Building",
                "Era of One-Party Dominance",
                "Politics of Planned Development",
                "India's External Relations",
                "Challenges to and Restoration of the Congress System",
                "Crisis of the Constitutional Order",
                "Rise of Popular Movements", "Regional Aspirations",
                "Recent Developments in Indian Politics"]
    },
    "Computer Science": {
        "11": ["Computer Systems and Organisation",
                "Encoding Schemes and Number System", "Emerging Trends",
                "Problem Solving", "Getting Started with Python",
                "Flow of Control", "Functions", "Strings", "Lists",
                "Tuples and Dictionary", "Societal Impacts"],
        "12": ["Review of Python Basics", "Exception Handling",
                "File Handling", "Stacks", "Queues", "Sorting",
                "Searching", "Data Communication and Networks",
                "Security Aspects", "Database Concepts",
                "Structured Query Language"]
    },
    "Information Technology": {
        "9": ["Introduction to IT", "Communication Skills", "Self-Management Skills",
               "Basic IT Skills", "Entrepreneurial Skills"],
        "10": ["Communication Skills", "Self-Management Skills",
                "ICT Skills", "Entrepreneurial Skills",
                "Green Skills", "Web Applications and Security"]
    }
}

SUBJECTS_BY_CLASS = {
    "1": ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "2": ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "3": ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "4": ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "5": ["Mathematics", "English", "Hindi", "Environmental Studies (EVS)"],
    "6": ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit"],
    "7": ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit"],
    "8": ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit"],
    "9": ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit",
           "Information Technology"],
    "10": ["Mathematics", "Science", "Social Science", "English", "Hindi", "Sanskrit",
            "Information Technology"],
    "11": ["Mathematics", "Physics", "Chemistry", "Biology", "English", "Hindi",
            "Economics", "Business Studies", "Accountancy", "History", "Geography",
            "Political Science", "Computer Science"],
    "12": ["Mathematics", "Physics", "Chemistry", "Biology", "English", "Hindi",
            "Economics", "Business Studies", "Accountancy", "History", "Geography",
            "Political Science", "Computer Science"]
}

BOARDS = [
    "CBSE", "ICSE", "Maharashtra State Board", "Karnataka State Board",
    "Tamil Nadu State Board", "Rajasthan Board (RBSE)", "UP Board (UPMSP)",
    "Gujarat Secondary Education Board (GSEB)", "West Bengal Board (WBBSE)",
    "Madhya Pradesh Board (MPBSE)", "Bihar School Examination Board (BSEB)",
    "Kerala Board (SCERT)", "Andhra Pradesh Board (BSEAP)",
    "Telangana Board (BSE Telangana)", "Punjab School Education Board (PSEB)"
]


def extract_json(text):
    """Extract JSON from model response, handling markdown code fences."""
    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text.strip(), flags=re.MULTILINE)
    # Find outermost JSON object
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
    subject = data.get('subject', '')
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


@app.route('/api/generate-paper', methods=['POST'])
def generate_paper():
    gemini = get_gemini_client()
    if not gemini:
        return jsonify({'error': 'GOOGLE_API_KEY not configured. Get a free key at aistudio.google.com, then run: $env:GOOGLE_API_KEY="your_key"'}), 500

    try:
        board = request.form.get('board', 'CBSE')
        class_num = request.form.get('class_num', '10')
        subject = request.form.get('subject', 'Mathematics')
        exam_type = request.form.get('exam_type', 'Annual')
        total_marks = request.form.get('total_marks', '80')
        duration = request.form.get('duration', '3 Hours')
        difficulty = request.form.get('difficulty', 'Mixed')
        chapters = json.loads(request.form.get('chapters', '[]'))
        question_types = json.loads(request.form.get('question_types', '{}'))

        # Process uploaded chapter images as PIL Images for Gemini
        pil_images = []
        files = request.files.getlist('chapter_images')
        for f in files:
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit('.', 1)[1].lower()
                if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    img_bytes = f.read()
                    pil_images.append(Image.open(io.BytesIO(img_bytes)))

        # Build sections description
        sections_desc = []
        qt = question_types
        section_map = {
            'mcq': ('A', 'Multiple Choice Questions (MCQ)'),
            'fill_blank': ('B', 'Fill in the Blanks'),
            'match': ('C', 'Match the Following'),
            'true_false': ('D', 'True or False'),
            'short_answer': ('E', 'Short Answer Type'),
            'diagram': ('F', 'Diagram / Long Answer Type')
        }

        for key, (sec_id, sec_name) in section_map.items():
            if qt.get(key, {}).get('count', 0) > 0:
                count = qt[key]['count']
                marks = qt[key]['marks']
                sections_desc.append(
                    f"Section {sec_id} – {sec_name}: {count} question(s) × {marks} mark(s) each = {count * marks} marks"
                )

        chapters_str = ', '.join(chapters) if chapters else 'All chapters'

        difficulty_map = {
            'easy': 'Easy (80% Easy, 20% Medium)',
            'medium': 'Medium (20% Easy, 60% Medium, 20% Hard)',
            'hard': 'Hard (20% Medium, 80% Hard)',
            'mixed': 'Mixed (30% Easy, 50% Medium, 20% Hard)'
        }
        diff_desc = difficulty_map.get(difficulty.lower(), 'Mixed')

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
                response_mime_type='application/json'
            )
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
        return jsonify({'success': True, 'paper': paper_json})

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Failed to parse generated paper: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/evaluate', methods=['POST'])
def evaluate():
    gemini = get_gemini_client()
    if not gemini:
        return jsonify({'error': 'GOOGLE_API_KEY not configured. Get a free key at aistudio.google.com'}), 500

    student_name = request.form.get('student_name', 'Student')
    roll_no = request.form.get('roll_no', 'N/A')
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
    answer_text = ""

    try:
        if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            with open(temp_path, 'rb') as f:
                answer_image = Image.open(io.BytesIO(f.read()))
                answer_image.load()  # force load before file closes
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

        # Build Gemini content: image (if any) + prompt
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
                response_mime_type='application/json'
            )
        )

        response_text = response.text
        try:
            eval_json = json.loads(response_text)
        except json.JSONDecodeError:
            try:
                eval_json = extract_json(response_text)
            except (ValueError, json.JSONDecodeError) as e:
                return jsonify({'error': f'Evaluation parsing error: {str(e)}'}), 500

        return jsonify({'success': True, 'report': eval_json})

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Evaluation parsing error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


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
    print("=" * 56 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
