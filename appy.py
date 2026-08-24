import os
import time

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


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")


# ============================================================
# CHECK REQUIRED ENVIRONMENT VARIABLES
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


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.secret_key = FLASK_SECRET_KEY

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"


# ============================================================
# GEMINI
# ============================================================

gemini_client = None

if GEMINI_API_KEY:

    try:

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print(
            "Gemini client initialized successfully."
        )

    except Exception as e:

        print(
            "WARNING: Could not initialize Gemini client:",
            repr(e)
        )


# ============================================================
# SUPABASE CLIENT
# ============================================================

def get_client() -> Client:

    client = create_client(
        SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY
    )

    access_token = session.get(
        "access_token"
    )

    refresh_token = session.get(
        "refresh_token"
    )

    # --------------------------------------------------------
    # Restore / refresh Supabase session
    # --------------------------------------------------------

    if access_token and refresh_token:

        try:

            auth_response = client.auth.set_session(
                access_token,
                refresh_token
            )

            if auth_response.session:

                new_access_token = (
                    auth_response.session.access_token
                )

                new_refresh_token = (
                    auth_response.session.refresh_token
                )

                session["access_token"] = (
                    new_access_token
                )

                session["refresh_token"] = (
                    new_refresh_token
                )

                client.postgrest.auth(
                    new_access_token
                )

        except Exception as e:

            print(
                "SUPABASE SESSION ERROR:",
                repr(e)
            )

            # Session can no longer be used.
            # Force a fresh login.
            session.clear()

    elif access_token:

        client.postgrest.auth(
            access_token
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

def current_profile(
    client: Client
):

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
            .eq("id", user_id)
            .single()
            .execute()
        )

        return result.data

    except Exception as e:

        print(
            "Error fetching profile:",
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
            f"Profile created for user: {user_id}"
        )

        return True

    except Exception as e:

        print(
            "Error creating profile:",
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

            return redirect(
                url_for("home")
            )

        user_id = result.user.id

        if result.session:

            client.postgrest.auth(
                result.session.access_token
            )

        if not create_user_profile(
            client,
            user_id,
            email,
            full_name
        ):

            print(
                f"Warning: Profile creation failed for {user_id}"
            )

        if result.session is None:

            flash(
                "Account created! Check your email to confirm your account, then log in.",
                "info"
            )

            return redirect(
                url_for("home")
            )

        start_session(
            result
        )

        flash(
            "Welcome to MarvTec AI Solver!",
            "success"
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
            f"Sign up failed: {str(e)[:100]}",
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
            f"Login failed: {str(e)[:100]}",
            "error"
        )

        return redirect(
            url_for("home")
        )


# ============================================================
# START SESSION
# ============================================================

def start_session(
    auth_result
):

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

    session.permanent = False


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
            f"Could not post problem: {str(e)[:100]}",
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
def problem_detail(
    problem_id
):

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
def reply(
    problem_id
):

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

    if profile.get(
        "role"
    ) != "admin":

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
def verify_tech(
    tech_id
):

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

    if profile.get(
        "role"
    ) != "admin":

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
    # CHECK PROMPT
    # --------------------------------------------------------

    if not prompt:

        error = (
            "Please describe your problem first."
        )

    # --------------------------------------------------------
    # CHECK API KEY
    # --------------------------------------------------------

    elif not GEMINI_API_KEY:

        error = (
            "GEMINI_API_KEY is missing from the environment variables."
        )

    # --------------------------------------------------------
    # CHECK CLIENT
    # --------------------------------------------------------

    elif not gemini_client:

        error = (
            "AI client was not initialized. "
            "Please check GEMINI_API_KEY."
        )

    # --------------------------------------------------------
    # ASK GEMINI
    # --------------------------------------------------------

    else:

        try:

            ai_prompt = (
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

            response = None

            max_attempts = 3

            for attempt in range(
                1,
                max_attempts + 1
            ):

                try:

                    print(
                        f"GEMINI REQUEST ATTEMPT {attempt}"
                    )

                    response = (
                        gemini_client
                        .models
                        .generate_content(
                            model="gemini-3.7-flash",
                            contents=ai_prompt
                        )
                    )

                    break

                except Exception as gemini_error:

                    error_text = str(
                        gemini_error
                    ).lower()

                    print(
                        f"GEMINI ATTEMPT {attempt} ERROR:",
                        repr(gemini_error)
                    )

                    temporary_error = (
                        "503" in error_text
                        or "unavailable" in error_text
                        or "high demand" in error_text
                        or "429" in error_text
                        or "rate limit" in error_text
                    )

                    if (
                        temporary_error
                        and attempt < max_attempts
                    ):

                        wait_time = (
                            5 * (2 ** (attempt - 1))
                        )

                        print(
                            f"Gemini temporarily unavailable. "
                            f"Retrying in {wait_time} seconds..."
                        )

                        time.sleep(
                            wait_time
                        )

                        continue

                    raise

            if response:

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

            error_text = str(e)

            if "404" in error_text:

                error = (
                    "The Gemini model was not found. "
                    "Please make sure Render is running "
                    "the latest version of appy.py."
                )

            elif "503" in error_text:

                error = (
                    "Gemini is temporarily busy. "
                    "Please try again in a few moments."
                )

            elif "429" in error_text:

                error = (
                    "Gemini request limit reached. "
                    "Please wait a little and try again."
                )

            else:

                error = (
                    f"AI request failed: "
                    f"{error_text[:150]}"
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
