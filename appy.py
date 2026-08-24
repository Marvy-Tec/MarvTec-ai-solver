import os
import base64
import json

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
from groq import Groq


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")


# ============================================================
# CHECK ENVIRONMENT VARIABLES
# ============================================================

if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is missing from your environment variables."
    )

if not SUPABASE_PUBLISHABLE_KEY:
    raise RuntimeError(
        "SUPABASE_PUBLISHABLE_KEY is missing from your environment variables."
    )

if not FLASK_SECRET_KEY:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing from your environment variables."
    )

if not GROQ_API_KEY:
    print(
        "WARNING: GROQ_API_KEY is missing from environment variables."
    )


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.secret_key = FLASK_SECRET_KEY

app.config["SESSION_PERMANENT"] = False


# ============================================================
# GROQ CLIENT
# ============================================================

groq_client = None

if GROQ_API_KEY:

    try:

        groq_client = Groq(
            api_key=GROQ_API_KEY
        )

        print(
            "Groq client initialized successfully."
        )

    except Exception as e:

        print(
            "GROQ INITIALIZATION ERROR:",
            repr(e)
        )


# ============================================================
# SUPABASE CLIENT
# ============================================================

def create_supabase_client():

    return create_client(
        SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY
    )


# ============================================================
# CHECK JWT EXPIRATION
# ============================================================

def token_is_expired(token):

    try:

        parts = token.split(".")

        if len(parts) != 3:
            return True

        payload = parts[1]

        payload += "=" * (
            4 - len(payload) % 4
        )

        decoded = base64.urlsafe_b64decode(
            payload
        )

        data = json.loads(
            decoded.decode("utf-8")
        )

        exp = data.get("exp")

        if not exp:
            return True

        import time

        return time.time() >= exp

    except Exception:

        return True


# ============================================================
# REFRESH SUPABASE SESSION
# ============================================================

def refresh_supabase_session():

    refresh_token = session.get(
        "refresh_token"
    )

    if not refresh_token:

        return False

    try:

        client = create_supabase_client()

        result = client.auth.refresh_session(
            refresh_token
        )

        if not result.session:

            return False

        session["access_token"] = (
            result.session.access_token
        )

        session["refresh_token"] = (
            result.session.refresh_token
        )

        session["user_id"] = (
            result.user.id
        )

        session["email"] = (
            result.user.email
        )

        print(
            "Supabase session refreshed successfully."
        )

        return True

    except Exception as e:

        print(
            "SUPABASE REFRESH ERROR:",
            repr(e)
        )

        session.clear()

        return False


# ============================================================
# SUPABASE CLIENT WITH CURRENT USER TOKEN
# ============================================================

def get_client() -> Client:

    client = create_supabase_client()

    token = session.get(
        "access_token"
    )

    if token:

        if token_is_expired(token):

            print(
                "Supabase access token expired. Refreshing..."
            )

            if refresh_supabase_session():

                token = session.get(
                    "access_token"
                )

            else:

                token = None

        if token:

            client.postgrest.auth(
                token
            )

    return client


# ============================================================
# CURRENT USER
# ============================================================

def current_user():

    user_id = session.get(
        "user_id"
    )

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

    user_id = session.get(
        "user_id"
    )

    if not user_id:
        return None

    try:

        result = (
            client
            .table("profiles")
            .select("*")
            .eq(
                "id",
                user_id
            )
            .single()
            .execute()
        )

        return result.data

    except Exception as e:

        print(
            "PROFILE ERROR:",
            repr(e)
        )

        return None


# ============================================================
# CREATE USER PROFILE
# ============================================================

def create_user_profile(
    client: Client,
    user_id: str,
    email: str,
    full_name: str
):

    try:

        client.table(
            "profiles"
        ).insert(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": "user",
                "is_verified": False
            }
        ).execute()

        print(
            "Profile created successfully."
        )

        return True

    except Exception as e:

        print(
            "PROFILE CREATION ERROR:",
            repr(e)
        )

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
# HOME
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

        print(
            "HOME ERROR:",
            repr(e)
        )

        error = str(e)

    return render_template(
        "index.html",
        problems=problems,
        error=error
    )


# ============================================================
# SIGN UP
# ============================================================

@app.route(
    "/signup",
    methods=["POST"]
)
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

        return redirect(
            url_for("home")
        )

    if len(password) < 6:

        flash(
            "Password must be at least 6 characters.",
            "error"
        )

        return redirect(
            url_for("home")
        )

    if not full_name:

        full_name = email.split("@")[0]

    try:

        client = create_supabase_client()

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

        if not result.user:

            flash(
                "Signup failed. Could not create account.",
                "error"
            )

            return redirect(
                url_for("home")
            )

        user_id = result.user.id

        if result.session:

            client.postgrest.auth(
                result.session.access_token
            )

            create_user_profile(
                client,
                user_id,
                email,
                full_name
            )

            start_session(
                result
            )

            flash(
                "Welcome to MarvTec AI Solver!",
                "success"
            )

        else:

            flash(
                "Account created! Check your email to confirm your account, then log in.",
                "info"
            )

        return redirect(
            url_for("home")
        )

    except Exception as e:

        print(
            "SIGNUP ERROR:",
            repr(e)
        )

        flash(
            f"Sign up failed: {str(e)[:150]}",
            "error"
        )

        return redirect(
            url_for("home")
        )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["POST"]
)
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

        return redirect(
            url_for("home")
        )

    try:

        client = create_supabase_client()

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

            return redirect(
                url_for("home")
            )

        start_session(
            result
        )

        flash(
            "Login successful!",
            "success"
        )

        return redirect(
            url_for("home")
        )

    except Exception as e:

        print(
            "LOGIN ERROR:",
            repr(e)
        )

        flash(
            f"Login failed: {str(e)[:150]}",
            "error"
        )

        return redirect(
            url_for("home")
        )


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

    return redirect(
        url_for("home")
    )


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

        return redirect(
            url_for("home")
        )

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

        return redirect(
            url_for("home")
        )

    client = get_client()

    try:

        client.table(
            "problems"
        ).insert(
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
            f"Could not post problem: {str(e)[:150]}",
            "error"
        )

    return redirect(
        url_for("home")
    )


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
    profile = current_profile(
        client
    )
    error = None

    try:

        problem_result = (
            client
            .table("problems")
            .select("*")
            .eq(
                "id",
                problem_id
            )
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

        print(
            "PROBLEM DETAIL ERROR:",
            repr(e)
        )

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

    profile = current_profile(
        client
    )

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
            f"Could not send reply: {str(e)[:150]}",
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

    profile = current_profile(
        client
    )

    if not profile:

        flash(
            "You must be logged in.",
            "error"
        )

        return redirect(
            url_for("home")
        )

    if profile.get("role") != "admin":

        flash(
            "Admins only.",
            "error"
        )

        return redirect(
            url_for("home")
        )

    techs = []
    error = None

    try:

        result = (
            client
            .table("profiles")
            .select("*")
            .eq(
                "role",
                "tech"
            )
            .eq(
                "is_verified",
                False
            )
            .execute()
        )

        techs = result.data or []

    except Exception as e:

        print(
            "ADMIN ERROR:",
            repr(e)
        )

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

    profile = current_profile(
        client
    )

    if not profile:

        flash(
            "You must be logged in.",
            "error"
        )

        return redirect(
            url_for("home")
        )

    if profile.get("role") != "admin":

        flash(
            "Admins only.",
            "error"
        )

        return redirect(
            url_for("home")
        )

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

        print(
            "VERIFY TECH ERROR:",
            repr(e)
        )

        flash(
            f"Could not verify tech: {str(e)[:150]}",
            "error"
        )

    return redirect(
        url_for("admin")
    )


# ============================================================
# MARVTEC AI SOLVER - GROQ
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
    # CHECK PROMPT
    # --------------------------------------------------------

    if not prompt:

        error = (
            "Please describe your problem first."
        )

    # --------------------------------------------------------
    # CHECK GROQ KEY
    # --------------------------------------------------------

    elif not GROQ_API_KEY:

        error = (
            "GROQ_API_KEY is missing from Render environment variables."
        )

    # --------------------------------------------------------
    # CHECK GROQ CLIENT
    # --------------------------------------------------------

    elif not groq_client:

        error = (
            "Groq client was not initialized."
        )

    # --------------------------------------------------------
    # ASK GROQ
    # --------------------------------------------------------

    else:

        try:

            system_message = (
                "You are MarvTec AI Solver, "
                "a technical problem-solving assistant.\n\n"

                "Give clear, practical and accurate solutions.\n"

                "Break solutions into numbered steps.\n"

                "Explain technical terms when necessary.\n"

                "Do not invent facts.\n"

                "If important information is missing, "
                "clearly state what information is needed."
            )

            user_message = (
                f"Technical category: {category}\n\n"
                f"User's problem:\n{prompt}"
            )

            completion = (
                groq_client
                .chat
                .completions
                .create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": system_message
                        },
                        {
                            "role": "user",
                            "content": user_message
                        }
                    ],
                    temperature=0.3,
                    max_completion_tokens=1024
                )
            )

            answer = (
                completion
                .choices[0]
                .message
                .content
            )

            if not answer:

                error = (
                    "AI did not return an answer. "
                    "Please try again."
                )

        except Exception as e:

            print(
                "GROQ ERROR:",
                repr(e)
            )

            error = (
                f"AI request failed: {str(e)[:200]}"
            )

    # ========================================================
    # LOAD PROBLEMS
    # ========================================================

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

    except Exception as e:

        print(
            "LOAD PROBLEMS ERROR:",
            repr(e)
        )

    # ========================================================
    # RETURN PAGE
    # ========================================================

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

    port = int(
        os.environ.get(
            "PORT",
            3000
        )
    )

    app.run(
        debug=False,
        host="0.0.0.0",
        port=port
    )
