import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from supabase import create_client, Client
from dotenv import load_dotenv
from google import genai


# ============================================================
# LOAD .ENV
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")


# ============================================================
# CHECK ENVIRONMENT VARIABLES
# ============================================================

if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is missing from your .env file."
    )

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'



if not SUPABASE_PUBLISHABLE_KEY:
    raise RuntimeError(
        "SUPABASE_PUBLISHABLE_KEY is missing from your .env file."
    )

if not FLASK_SECRET_KEY:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing from your .env file."
    )


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'


# ============================================================
# GEMINI
# ============================================================

gemini_client = None

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )
    except Exception as e:
        print(f"Warning: Could not initialize Gemini client: {e}")


# ============================================================
# SUPABASE CLIENT
# ============================================================

def get_client() -> Client:

    client = create_client(
        SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY
    )

    token = session.get("access_token")

    if token:
        client.postgrest.auth(token)

    return client


# ============================================================
# CURRENT USER
# ============================================================

def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    return {
        "id": user_id,
        "email": session.get("email")
    }


# ============================================================
# CURRENT PROFILE
# ============================================================

def current_profile(client: Client):

    user_id = session.get("user_id")

    if not user_id:
        return None

    try:

        result = (
            client
            .table("profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )

        return result.data

    except Exception as e:
        print(f"Error fetching profile: {e}")
        return None


# ============================================================
# CREATE USER PROFILE
# ============================================================

def create_user_profile(client: Client, user_id: str, email: str, full_name: str):
    """Create a profile record for a new user"""
    
    try:
        client.table("profiles").insert(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": "user",
                "is_verified": False
            }
        ).execute()
        
        print(f"Profile created for user: {user_id}")
        return True
        
    except Exception as e:
        print(f"Error creating profile: {e}")
        return False


# ============================================================
# MAKE USER AVAILABLE TO HTML
# ============================================================

@app.context_processor
def inject_globals():

    return {
        "user": current_user()
    }


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():

    client = get_client()

    problems = []
    error = None

    try:

        result = (
            client
            .table("problems")
            .select("*")
            .order(
                "created_at",
                desc=True
            )
            .limit(20)
            .execute()
        )

        problems = result.data or []

    except Exception as e:

        error = str(e)

    return render_template(
        "index.html",
        problems=problems,
        error=error
    )


# ============================================================
# SIGN UP
# ============================================================

@app.route("/signup", methods=["POST"])
def signup():

    email = request.form.get(
        "email",
        ""
    ).strip()

    password = request.form.get(
        "password",
        ""
    )

    full_name = request.form.get(
        "full_name",
        ""
    ).strip()

    if not email or not password:

        flash(
            "Email and password are required.",
            "error"
        )

        return redirect(url_for("home"))

    if len(password) < 6:

        flash(
            "Password must be at least 6 characters.",
            "error"
        )

        return redirect(url_for("home"))

    if not full_name:

        full_name = email.split("@")[0]

    try:

        client = create_client(
            SUPABASE_URL,
            SUPABASE_PUBLISHABLE_KEY
        )

        result = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "full_name": full_name
                    }
                }
            }
        )

        if result.user is None:

            flash(
                "Signup failed. Could not create account.",
                "error"
            )

            return redirect(url_for("home"))

        # Create profile immediately after signup
        user_id = result.user.id
        
        # Authenticate client with the new user's token if available
        if result.session:
            client.postgrest.auth(result.session.access_token)
        
        # Create the profile
        if not create_user_profile(client, user_id, email, full_name):
            print(f"Warning: Profile creation failed for {user_id}, but account exists")

        # Email confirmation enabled
        if result.session is None:

            flash(
                "Account created! Check your email to confirm your account, then log in.",
                "info"
            )

            return redirect(url_for("home"))

        # No email confirmation needed - log in immediately
        start_session(result)

        flash(
            "Welcome to MarvTec AI Solver!",
            "success"
        )

        return redirect(url_for("home"))

    except Exception as e:

        print("SIGNUP ERROR:", repr(e))

        flash(
            f"Sign up failed: {str(e)[:100]}",
            "error"
        )

        return redirect(url_for("home"))


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["POST"])
def login():

    email = request.form.get(
        "email",
        ""
    ).strip()

    password = request.form.get(
        "password",
        ""
    )

    if not email or not password:

        flash(
            "Email and password are required.",
            "error"
        )

        return redirect(url_for("home"))

    try:

        client = create_client(
            SUPABASE_URL,
            SUPABASE_PUBLISHABLE_KEY
        )

        result = client.auth.sign_in_with_password(
            {
                "email": email,
                "password": password
            }
        )

        if not result.user or not result.session:

            flash(
                "Invalid email or password.",
                "error"
            )

            return redirect(url_for("home"))

        start_session(result)

        flash(
            "Login successful!",
            "success"
        )

        return redirect(url_for("home"))

    except Exception as e:

        print("LOGIN ERROR:", repr(e))

        flash(
            f"Login failed: {str(e)[:100]}",
            "error"
        )

        return redirect(url_for("home"))


# ============================================================
# START SESSION
# ============================================================

def start_session(auth_result):

    session["access_token"] = (
        auth_result.session.access_token
    )

    session["refresh_token"] = (
        auth_result.session.refresh_token
    )

    session["user_id"] = (
        auth_result.user.id
    )

    session["email"] = (
        auth_result.user.email
    )
    
    session.permanent = True


# ============================================================
# LOGOUT
# ============================================================

@app.route(
    "/logout",
    methods=["POST"]
)
def logout():

    session.clear()

    flash(
        "Logged out successfully.",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# POST PROBLEM
# ============================================================

@app.route(
    "/post-problem",
    methods=["POST"]
)
def post_problem():

    if not current_user():

        flash(
            "Log in first.",
            "error"
        )

        return redirect(url_for("home"))

    title = request.form.get(
        "title",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    category = request.form.get(
        "category",
        "Software"
    ).strip()

    if not title or not description:

        flash(
            "Title and description are required.",
            "error"
        )

        return redirect(url_for("home"))

    client = get_client()

    try:

        client.table("problems").insert(
            {
                "title": title,
                "description": description,
                "category": category,
                "user_id": session["user_id"]
            }
        ).execute()

        flash(
            "Problem posted successfully.",
            "success"
        )

    except Exception as e:

        print(
            "POST PROBLEM ERROR:",
            repr(e)
        )

        flash(
            f"Could not post problem: {str(e)[:100]}",
            "error"
        )

    return redirect(url_for("home"))


# ============================================================
# VIEW PROBLEM
# ============================================================

@app.route(
    "/problem/<problem_id>"
)
def problem_detail(problem_id):

    client = get_client()

    problem = None
    responses = []
    profile = current_profile(client)
    error = None

    try:

        problem_result = (
            client
            .table("problems")
            .select("*")
            .eq("id", problem_id)
            .single()
            .execute()
        )

        problem = problem_result.data

        response_result = (
            client
            .table("responses")
            .select(
                "*, profiles(full_name)"
            )
            .eq(
                "problem_id",
                problem_id
            )
            .execute()
        )

        responses = (
            response_result.data or []
        )

    except Exception as e:

        error = str(e)

    return render_template(
        "problem.html",
        problem=problem,
        responses=responses,
        profile=profile,
        error=error
    )


# ============================================================
# REPLY TO PROBLEM
# ============================================================

@app.route(
    "/problem/<problem_id>/reply",
    methods=["POST"]
)
def reply(problem_id):

    client = get_client()

    profile = current_profile(client)

    if not profile:

        flash(
            "You must be logged in.",
            "error"
        )

        return redirect(
            url_for(
                "problem_detail",
                problem_id=problem_id
            )
        )

    if not profile.get(
        "is_verified"
    ):

        flash(
            "Only verified techs can reply.",
            "error"
        )

        return redirect(
            url_for(
                "problem_detail",
                problem_id=problem_id
            )
        )

    message = request.form.get(
        "message",
        ""
    ).strip()

    if not message:

        flash(
            "Message cannot be empty.",
            "error"
        )

        return redirect(
            url_for(
                "problem_detail",
                problem_id=problem_id
            )
        )

    try:

        client.table(
            "responses"
        ).insert(
            {
                "problem_id": problem_id,
                "tech_id": profile["id"],
                "message": message
            }
        ).execute()

        flash(
            "Reply sent successfully.",
            "success"
        )

    except Exception as e:

        print(
            "REPLY ERROR:",
            repr(e)
        )

        flash(
            f"Could not send reply: {str(e)[:100]}",
            "error"
        )

    return redirect(
        url_for(
            "problem_detail",
            problem_id=problem_id
        )
    )


# ============================================================
# ADMIN PAGE
# ============================================================

@app.route("/admin")
def admin():

    client = get_client()

    profile = current_profile(client)

    if not profile:

        flash(
            "You must be logged in.",
            "error"
        )

        return redirect(url_for("home"))

    if profile.get("role") != "admin":

        flash(
            "Admins only.",
            "error"
        )

        return redirect(url_for("home"))

    techs = []
    error = None

    try:

        result = (
            client
            .table("profiles")
            .select("*")
            .eq("role", "tech")
            .eq("is_verified", False)
            .execute()
        )

        techs = result.data or []

    except Exception as e:

        error = str(e)

    return render_template(
        "admin.html",
        techs=techs,
        error=error
    )


# ============================================================
# VERIFY TECH
# ============================================================

@app.route(
    "/admin/verify/<tech_id>",
    methods=["POST"]
)
def verify_tech(tech_id):

    client = get_client()

    profile = current_profile(client)

    if not profile:

        flash(
            "You must be logged in.",
            "error"
        )

        return redirect(url_for("home"))

    if profile.get("role") != "admin":

        flash(
            "Admins only.",
            "error"
        )

        return redirect(url_for("home"))

    try:

        client.table(
            "profiles"
        ).update(
            {
                "is_verified": True
            }
        ).eq(
            "id",
            tech_id
        ).execute()

        flash(
            "Tech verified successfully.",
            "success"
        )

    except Exception as e:

        flash(
            f"Could not verify tech: {str(e)[:100]}",
            "error"
        )

    return redirect(
        url_for("admin")
    )


# ============================================================
# MARVTEC AI SOLVER
# ============================================================

@app.route(
    "/ask-ai",
    methods=["POST"]
)
def ask_ai():

    prompt = request.form.get(
        "prompt",
        ""
    ).strip()

    category = request.form.get(
        "category",
        "Software"
    ).strip()

    answer = None
    error = None

    # --------------------------------------------------------
    # CHECK USER PROMPT
    # --------------------------------------------------------

    if not prompt:

        error = (
            "Please describe your problem first."
        )

    # --------------------------------------------------------
    # CHECK GEMINI KEY
    # --------------------------------------------------------

    elif not GEMINI_API_KEY:

        error = (
            "GEMINI_API_KEY is missing from .env."
        )

    # --------------------------------------------------------
    # CHECK GEMINI CLIENT
    # --------------------------------------------------------

    elif not gemini_client:

        error = (
            "AI client not initialized. Check GEMINI_API_KEY."
        )

    # --------------------------------------------------------
    # ASK GEMINI
    # --------------------------------------------------------

    else:

        try:

            response = (
                gemini_client
                .models
                .generate_content(
                    model="gemini-1.5-flash",
                    contents=(
                        "You are MarvTec AI Solver, "
                        "a technical problem-solving assistant.\n\n"

                        f"Technical category: {category}\n\n"

                        f"User's problem:\n{prompt}\n\n"

                        "Give a clear and practical solution. "
                        "Break the solution into numbered steps. "
                        "Explain technical terms when necessary. "
                        "Do not invent facts. "
                        "If more information is needed, "
                        "clearly state what information is missing."
                    )
                )
            )

            answer = response.text

            if not answer:

                error = (
                    "AI did not return an answer. "
                    "Please try again."
                )

        except Exception as e:

            print(
                "GEMINI ERROR:",
                repr(e)
            )

            error = (
                f"AI request failed: {str(e)[:100]}"
            )

    # --------------------------------------------------------
    # LOAD PROBLEMS
    # --------------------------------------------------------

    client = get_client()

    problems = []

    try:

        result = (
            client
            .table("problems")
            .select("*")
            .order(
                "created_at",
                desc=True
            )
            .limit(20)
            .execute()
        )

        problems = (
            result.data or []
        )

    except Exception:

        pass

    return render_template(
        "index.html",
        problems=problems,
        ai_answer=answer,
        ai_error=error,
        ai_prompt=prompt
    )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="0.0.0.0",
        port=3000,
        use_reloader=False
    )