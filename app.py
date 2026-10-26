import os
import pickle
import warnings
from datetime import datetime, timezone
from functools import wraps
import csv
import io

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import pandas as pd
from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, Response
)
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from werkzeug.security import generate_password_hash, check_password_hash

# Suppress sklearn unpickle version warnings
warnings.filterwarnings("ignore", category=UserWarning)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "student-management-secret-key-2026")

# ---------------- SECURE ADMIN CREDENTIALS FROM .ENV ----------------
ADMIN_NAME = os.getenv("ADMIN_NAME", "System Administrator").strip()
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@portal.edu").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminSecure#2026")
ADMIN_REGISTRATION_CODE = os.getenv("ADMIN_CODE", "ADMIN_SECURE_PASS_2026")

# ---------------- LOGIN MANAGER ----------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to access this page."
login_manager.login_message_category = "error"

# ---------------- MONGODB CONNECTION ----------------
client = None
students_collection = None
users_collection = None
db_error = None


def sync_admin_account():
    """
    Ensures that the admin email and password configured in .env are always
    synchronized into MongoDB with role 'admin'. Credentials remain private to .env.
    """
    if users_collection is not None and ADMIN_EMAIL and ADMIN_PASSWORD:
        try:
            users_collection.update_one(
                {"email": ADMIN_EMAIL},
                {"$set": {
                    "name": ADMIN_NAME,
                    "email": ADMIN_EMAIL,
                    "password": generate_password_hash(ADMIN_PASSWORD),
                    "role": "admin"
                }},
                upsert=True
            )
            print(f"Verified secure admin account from .env: {ADMIN_EMAIL}")
        except Exception as exc:
            print("Notice: Error syncing admin account from .env:", exc)


mongo_uri = os.getenv("MONGO_URI", "").strip()

if mongo_uri:
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")

        db = client["student_management"]
        students_collection = db["students"]
        users_collection = db["users"]

        # Helpful indexes
        try:
            students_collection.create_index("roll_number", unique=True)
            users_collection.create_index("email", unique=True)
        except Exception:
            pass

        print("MongoDB connected successfully.")
        sync_admin_account()

    except Exception as exc:
        db_error = str(exc)
        print("MongoDB connection failed:", db_error)
        client = None
        students_collection = None
        users_collection = None
else:
    db_error = "MONGO_URI is missing from .env"
    print(db_error)

# ---------------- LOAD MACHINE LEARNING MODEL ----------------
MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "model",
    "student_pass_fail_model.pkl"
)

model = None
model_error = None
features = [
    "Study_Hours",
    "Attendance",
    "Previous_Marks",
    "Assignment_Marks"
]
label_mapping = {0: "Fail", 1: "Pass"}

try:
    with open(MODEL_PATH, "rb") as file:
        package = pickle.load(file)

    if isinstance(package, dict) and "model" in package:
        model = package["model"]
        features = package.get("features", features)
        label_mapping = package.get("label_mapping", label_mapping)
    else:
        model = package

    print("ML model loaded successfully.")

except Exception as exc:
    model_error = str(exc)
    print("ML model loading failed:", model_error)


def predict_student_performance(study_hours, attendance, previous_marks, assignment_marks):
    """
    Predicts student pass/fail outcome along with probability score,
    risk level, and actionable academic advice.
    """
    if model is None:
        raise RuntimeError("ML model is not loaded. Please verify model/student_pass_fail_model.pkl")

    values = {
        "Study_Hours": float(study_hours),
        "Attendance": float(attendance),
        "Previous_Marks": float(previous_marks),
        "Assignment_Marks": float(assignment_marks)
    }

    input_df = pd.DataFrame([[values[f] for f in features]], columns=features)
    raw_pred = model.predict(input_df)[0]
    
    # Calculate probabilities if supported
    pass_proba = 50.0
    fail_proba = 50.0
    if hasattr(model, "predict_proba"):
        probas = model.predict_proba(input_df)[0]
        # Classes: 0 is Fail, 1 is Pass
        fail_proba = round(float(probas[0]) * 100, 1)
        pass_proba = round(float(probas[1]) * 100, 1)

    status = str(label_mapping.get(raw_pred, "Pass" if raw_pred == 1 else "Fail"))
    confidence = pass_proba if status == "Pass" else fail_proba

    # Determine risk level
    if status == "Pass":
        if pass_proba >= 85:
            risk_level = "Very Low Risk (Strong Standing)"
        else:
            risk_level = "Moderate Standing (Borderline Pass)"
    else:
        if fail_proba >= 85:
            risk_level = "High Academic Risk (Critical Attention Required)"
        else:
            risk_level = "At-Risk (Recoverable with immediate effort)"

    # Generate personalized recommendations
    tips = []
    if attendance < 75:
        tips.append("Attendance is currently below the recommended 75% benchmark. Improving lecture attendance is vital.")
    if study_hours < 3.5:
        tips.append("Daily study time is lower than average. Dedicate at least 3 to 5 hours daily for revision.")
    if assignment_marks < 60:
        tips.append("Assignment marks need improvement. Timely submission of coursework will significantly safeguard passing.")
    if previous_marks < 50:
        tips.append("Foundational exam marks were weak. Review previous test concepts and seek tutorial support.")

    if not tips:
        tips.append("Excellent performance across all indicators! Maintain your consistent study routine.")

    recommendation = " ".join(tips)

    return {
        "status": status,
        "pass_probability": pass_proba,
        "fail_probability": fail_proba,
        "confidence": confidence,
        "risk_level": risk_level,
        "recommendation": recommendation
    }


# ---------------- USER MODEL ----------------
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.name = user_data.get("name", "User")
        self.email = user_data.get("email", "")
        self.role = user_data.get("role", "student")


@login_manager.user_loader
def load_user(user_id):
    if users_collection is None:
        return None

    try:
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        if user_data:
            return User(user_data)
    except Exception:
        return None

    return None


# ---------------- ROLE SECURITY DECORATOR ----------------
def admin_required(view_function):
    @wraps(view_function)
    @login_required
    def wrapped_view(*args, **kwargs):
        if current_user.role != "admin":
            flash("Admin access required. Redirected to your student dashboard.", "error")
            return redirect(url_for("student_dashboard"))
        return view_function(*args, **kwargs)
    return wrapped_view


# ---------------- AUTH ROUTES ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("index"))
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        if users_collection is None:
            flash("Database connection unavailable. Please check MongoDB settings.", "error")
            return render_template("login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            user_data = users_collection.find_one({"email": email})

            if user_data and check_password_hash(user_data.get("password", ""), password):
                user_obj = User(user_data)
                login_user(user_obj)
                flash(f"Welcome back, {user_obj.name}!", "success")

                if user_obj.role == "admin":
                    return redirect(url_for("index"))
                return redirect(url_for("student_dashboard"))

            flash("Invalid email or password. Please try again.", "error")

        except PyMongoError:
            app.logger.exception("Login database error")
            flash("Database error during login. Please try again.", "error")

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("index"))
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        if users_collection is None:
            flash("Database connection unavailable. Please check MongoDB settings.", "error")
            return render_template("signup.html")

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "student").strip().lower()
        admin_code = request.form.get("admin_code", "").strip()

        if not name or not email or not password:
            flash("All required fields must be completed.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif role == "admin" and admin_code != ADMIN_REGISTRATION_CODE:
            flash("Invalid Admin Security Passcode. Please provide the secret passcode configured in .env.", "error")
        elif users_collection.find_one({"email": email}):
            flash("An account with this email is already registered.", "error")
        else:
            try:
                users_collection.insert_one({
                    "name": name,
                    "email": email,
                    "password": generate_password_hash(password),
                    "role": role if role in ("admin", "student") else "student",
                    "created_at": datetime.now(timezone.utc)
                })

                flash("Account created successfully! You can now log in.", "success")
                return redirect(url_for("login"))

            except PyMongoError:
                app.logger.exception("Signup database error")
                flash("Signup failed due to database error. Please try again.", "error")

    return render_template("signup.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out successfully.", "success")
    return redirect(url_for("login"))


# ---------------- ADMIN DASHBOARD ----------------
@app.route("/")
@admin_required
def index():
    total_students = 0
    pass_count = 0
    fail_count = 0
    avg_attendance = 0.0
    avg_marks = 0.0
    recent_students = []

    if students_collection is not None:
        try:
            total_students = students_collection.count_documents({})
            pass_count = students_collection.count_documents({"predicted_status": "Pass"})
            fail_count = students_collection.count_documents({"predicted_status": "Fail"})
            
            recent_students = list(students_collection.find().sort("_id", -1).limit(6))

            # Calculate averages if students exist
            if total_students > 0:
                pipeline = [
                    {
                        "$group": {
                            "_id": None,
                            "avg_att": {"$avg": "$Attendance"},
                            "avg_prev": {"$avg": "$Previous_Marks"}
                        }
                    }
                ]
                agg = list(students_collection.aggregate(pipeline))
                if agg:
                    avg_attendance = round(agg[0].get("avg_att", 0) or 0, 1)
                    avg_marks = round(agg[0].get("avg_prev", 0) or 0, 1)

        except PyMongoError:
            app.logger.exception("Dashboard error")
            flash("Error loading dashboard metrics.", "error")

    pass_rate = round((pass_count / total_students * 100), 1) if total_students > 0 else 0.0

    return render_template(
        "index.html",
        total_students=total_students,
        pass_count=pass_count,
        fail_count=fail_count,
        pass_rate=pass_rate,
        avg_attendance=avg_attendance,
        avg_marks=avg_marks,
        recent_students=recent_students,
        db_connected=students_collection is not None,
        model_loaded=model is not None
    )


# ---------------- INTERACTIVE ML PREDICTOR PLAYGROUND ----------------
@app.route("/predictor", methods=["GET", "POST"])
@login_required
def predictor():
    result = None
    inputs = {
        "study_hours": 5.0,
        "attendance": 80.0,
        "previous_marks": 70.0,
        "assignment_marks": 75.0
    }

    if request.method == "POST":
        try:
            inputs["study_hours"] = float(request.form.get("study_hours", 5.0))
            inputs["attendance"] = float(request.form.get("attendance", 80.0))
            inputs["previous_marks"] = float(request.form.get("previous_marks", 70.0))
            inputs["assignment_marks"] = float(request.form.get("assignment_marks", 75.0))

            result = predict_student_performance(
                inputs["study_hours"],
                inputs["attendance"],
                inputs["previous_marks"],
                inputs["assignment_marks"]
            )
        except Exception as exc:
            flash(f"Prediction calculation error: {exc}", "error")

    return render_template("predictor.html", result=result, inputs=inputs)


# ---------------- REAL-TIME PREDICTION API (JSON) ----------------
@app.route("/api/predict", methods=["POST"])
def api_predict():
    try:
        data = request.get_json(force=True) if request.is_json else request.form
        study_hours = float(data.get("study_hours", 0))
        attendance = float(data.get("attendance", 0))
        previous_marks = float(data.get("previous_marks", 0))
        assignment_marks = float(data.get("assignment_marks", 0))

        prediction = predict_student_performance(
            study_hours,
            attendance,
            previous_marks,
            assignment_marks
        )
        return jsonify(prediction)

    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ---------------- ADD STUDENT (ADMIN ONLY) ----------------
@app.route("/add", methods=["GET", "POST"])
@admin_required
def add_student():
    if request.method == "POST":
        if students_collection is None:
            flash("Database not connected.", "error")
            return redirect(url_for("add_student"))

        try:
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            roll_number = request.form.get("roll_number", "").strip()

            if not name or not roll_number:
                raise ValueError("Student name and roll number are mandatory.")

            study_hours = float(request.form.get("study_hours", 0))
            attendance = float(request.form.get("attendance", 0))
            previous_marks = float(request.form.get("previous_marks", 0))
            assignment_marks = float(request.form.get("assignment_marks", 0))

            if not (0 <= study_hours <= 24):
                raise ValueError("Study hours must be between 0 and 24.")
            if not (0 <= attendance <= 100):
                raise ValueError("Attendance must be between 0 and 100%.")
            if not (0 <= previous_marks <= 100):
                raise ValueError("Previous marks must be between 0 and 100.")
            if not (0 <= assignment_marks <= 100):
                raise ValueError("Assignment marks must be between 0 and 100.")

            # Run ML prediction
            pred_data = predict_student_performance(
                study_hours,
                attendance,
                previous_marks,
                assignment_marks
            )

            student_doc = {
                "name": name,
                "email": email,
                "roll_number": roll_number,
                "Study_Hours": study_hours,
                "Attendance": attendance,
                "Previous_Marks": previous_marks,
                "Assignment_Marks": assignment_marks,
                "predicted_status": pred_data["status"],
                "pass_probability": pred_data["pass_probability"],
                "risk_level": pred_data["risk_level"],
                "recommendation": pred_data["recommendation"],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }

            students_collection.insert_one(student_doc)

            flash(
                f"Student record added successfully! Predicted Outcome: {pred_data['status']} ({pred_data['pass_probability']}% Pass Probability)",
                "success"
            )
            return redirect(url_for("students"))

        except ValueError as exc:
            flash(str(exc), "error")
        except PyMongoError:
            app.logger.exception("Student save error")
            flash("Failed to save student record. Roll number or email may already exist.", "error")
        except Exception as exc:
            app.logger.exception("Unexpected error")
            flash(f"Error: {exc}", "error")

    return render_template("add_student.html")


# ---------------- EDIT STUDENT (ADMIN ONLY) ----------------
@app.route("/edit/<student_id>", methods=["GET", "POST"])
@admin_required
def edit_student(student_id):
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("students"))

    try:
        student = students_collection.find_one({"_id": ObjectId(student_id)})
        if not student:
            flash("Student record not found.", "error")
            return redirect(url_for("students"))
    except Exception:
        flash("Invalid student record identifier.", "error")
        return redirect(url_for("students"))

    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            roll_number = request.form.get("roll_number", "").strip()

            study_hours = float(request.form.get("study_hours", 0))
            attendance = float(request.form.get("attendance", 0))
            previous_marks = float(request.form.get("previous_marks", 0))
            assignment_marks = float(request.form.get("assignment_marks", 0))

            # Re-run ML Prediction with updated metrics
            pred_data = predict_student_performance(
                study_hours,
                attendance,
                previous_marks,
                assignment_marks
            )

            students_collection.update_one(
                {"_id": ObjectId(student_id)},
                {"$set": {
                    "name": name,
                    "email": email,
                    "roll_number": roll_number,
                    "Study_Hours": study_hours,
                    "Attendance": attendance,
                    "Previous_Marks": previous_marks,
                    "Assignment_Marks": assignment_marks,
                    "predicted_status": pred_data["status"],
                    "pass_probability": pred_data["pass_probability"],
                    "risk_level": pred_data["risk_level"],
                    "recommendation": pred_data["recommendation"],
                    "updated_at": datetime.now(timezone.utc)
                }}
            )

            flash(f"Updated record for {name}. New Predicted Status: {pred_data['status']}", "success")
            return redirect(url_for("students"))

        except Exception as exc:
            flash(f"Error updating student: {exc}", "error")

    return render_template("edit_student.html", student=student)


# ---------------- VIEW ALL STUDENTS (ADMIN ONLY) ----------------
@app.route("/students")
@admin_required
def students():
    records = []
    if students_collection is not None:
        try:
            records = list(students_collection.find().sort("_id", -1))
        except PyMongoError:
            app.logger.exception("Student loading error")
            flash("Error loading student records.", "error")

    return render_template("students.html", students=records)


# ---------------- DELETE STUDENT (ADMIN ONLY) ----------------
@app.route("/delete/<student_id>", methods=["POST"])
@admin_required
def delete_student(student_id):
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("students"))

    try:
        result = students_collection.delete_one({"_id": ObjectId(student_id)})
        if result.deleted_count:
            flash("Student record deleted successfully.", "success")
        else:
            flash("Record could not be found.", "error")
    except Exception:
        flash("Failed to delete record.", "error")

    return redirect(url_for("students"))


# ---------------- DATA EXPORT HELPERS (CSV & EXCEL) ----------------
def prepare_student_export_dataset(records):
    """
    Standardizes student records into a pandas DataFrame including all
    machine learning prediction metrics, probabilities, and academic advice.
    Dynamically computes predictions if missing from older database records.
    """
    dataset = []
    for r in records:
        study_hours = float(r.get("Study_Hours", 0) or 0)
        attendance = float(r.get("Attendance", 0) or 0)
        previous_marks = float(r.get("Previous_Marks", 0) or 0)
        assignment_marks = float(r.get("Assignment_Marks", 0) or 0)

        pred_status = r.get("predicted_status")
        pass_prob = r.get("pass_probability")
        risk_level = r.get("risk_level")
        recommendation = r.get("recommendation")

        # Fallback to model if prediction fields are not stored
        if not pred_status or pass_prob is None or not risk_level:
            try:
                pred = predict_student_performance(study_hours, attendance, previous_marks, assignment_marks)
                pred_status = pred_status or pred["status"]
                pass_prob = pass_prob if pass_prob is not None else pred["pass_probability"]
                risk_level = risk_level or pred["risk_level"]
                recommendation = recommendation or pred["recommendation"]
            except Exception:
                pred_status = pred_status or "Unknown"
                pass_prob = pass_prob if pass_prob is not None else 0.0
                risk_level = risk_level or "Unassessed"
                recommendation = recommendation or "No recommendation available."

        dataset.append({
            "Student Name": r.get("name", "N/A"),
            "Roll Number": r.get("roll_number", "N/A"),
            "Email Address": r.get("email", "N/A"),
            "Daily Study Hours": study_hours,
            "Attendance (%)": attendance,
            "Previous Exam Marks": previous_marks,
            "Assignment Marks": assignment_marks,
            "Predicted Status": pred_status,
            "Pass Probability (%)": pass_prob,
            "Academic Risk Level": risk_level,
            "AI Guidance & Recommendation": recommendation
        })
    return pd.DataFrame(dataset)


def generate_styled_excel(df, report_title="Student Academic Predictions Registry"):
    """
    Generates a professionally formatted Excel spreadsheet (.xlsx) with title banner,
    styled table headers, alternating row colors, pass/fail highlights, and auto-sized columns.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Academic Predictions"
    ws.views.sheetView[0].showGridLines = True

    # Styling Palette
    title_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_fill = PatternFill(start_color="312E81", end_color="312E81", fill_type="solid")
    pass_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    fail_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    font_title = Font(name="Segoe UI", size=15, bold=True, color="FFFFFF")
    font_sub = Font(name="Segoe UI", size=9, italic=True, color="CBD5E1")
    font_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Segoe UI", size=9.5)
    font_pass = Font(name="Segoe UI", size=9.5, bold=True, color="166534")
    font_fail = Font(name="Segoe UI", size=9.5, bold=True, color="991B1B")

    thin_border_side = Side(border_style="thin", color="E2E8F0")
    cell_border = Border(top=thin_border_side, left=thin_border_side, right=thin_border_side, bottom=thin_border_side)

    col_count = len(df.columns) if len(df.columns) > 0 else 1

    # 1. Title Banner
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    t_cell = ws.cell(row=1, column=1, value=f"🎓 {report_title}")
    t_cell.font = font_title
    t_cell.fill = title_fill
    t_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=col_count)
    timestamp_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    sub_cell = ws.cell(row=2, column=1, value=f"Report Generated: {timestamp_str} | EduPredict AI Machine Learning Engine")
    sub_cell.font = font_sub
    sub_cell.fill = title_fill
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18

    # Spacer Row
    ws.row_dimensions[3].height = 10

    # 2. Table Headers (Row 4)
    start_row = 4
    ws.row_dimensions[start_row].height = 26
    for idx, col_name in enumerate(df.columns, 1):
        cell = ws.cell(row=start_row, column=idx, value=col_name)
        cell.font = font_header
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    # 3. Data Rows
    for r_idx, row in enumerate(df.itertuples(index=False), start=start_row + 1):
        ws.row_dimensions[r_idx].height = 22
        row_fill = zebra_fill if (r_idx % 2 == 0) else white_fill

        for c_idx, val in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = font_data
            cell.fill = row_fill
            cell.border = cell_border

            header_name = df.columns[c_idx - 1]
            if header_name in ["Daily Study Hours", "Attendance (%)", "Previous Exam Marks", "Assignment Marks", "Pass Probability (%)"]:
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif header_name in ["Roll Number", "Predicted Status"]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            # Conditional Highlights for Predicted Status
            if header_name == "Predicted Status":
                val_lower = str(val).lower()
                if val_lower == "pass":
                    cell.fill = pass_fill
                    cell.font = font_pass
                elif val_lower == "fail":
                    cell.fill = fail_fill
                    cell.font = font_fail

    # Auto-adjust column widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col[3:]:
            max_len = max(max_len, len(str(cell.value or "")))
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 48)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def generate_csv_bytes(df):
    """
    Generates UTF-8 with BOM (utf-8-sig) encoded CSV content
    for seamless opening across Microsoft Excel, Sheets, and Text Editors.
    """
    csv_str = df.to_csv(index=False)
    return csv_str.encode("utf-8-sig")


# ---------------- EXPORT PREDICTIONS (ADMIN) ----------------
@app.route("/export-students")
@app.route("/export-students/csv")
@admin_required
def export_students_csv():
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("students"))

    records = list(students_collection.find().sort("name", 1))
    df = prepare_student_export_dataset(records)
    csv_bytes = generate_csv_bytes(df)

    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=all_student_predictions.csv"}
    )


@app.route("/export-students/excel")
@admin_required
def export_students_excel():
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("students"))

    records = list(students_collection.find().sort("name", 1))
    df = prepare_student_export_dataset(records)
    excel_bytes = generate_styled_excel(df, report_title="All Students Academic & Prediction Registry")

    return Response(
        excel_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=all_student_predictions.xlsx"}
    )


@app.route("/export-student/<student_id>/excel")
@admin_required
def export_student_excel(student_id):
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("students"))

    try:
        student = students_collection.find_one({"_id": ObjectId(student_id)})
        if not student:
            flash("Student record not found.", "error")
            return redirect(url_for("students"))

        df = prepare_student_export_dataset([student])
        roll = student.get("roll_number", "record").replace(" ", "_")
        excel_bytes = generate_styled_excel(df, report_title=f"Academic Prediction Card: {student.get('name', 'Student')}")

        return Response(
            excel_bytes,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=student_{roll}_prediction.xlsx"}
        )
    except Exception as exc:
        flash(f"Export error: {exc}", "error")
        return redirect(url_for("students"))


@app.route("/export-student/<student_id>/csv")
@admin_required
def export_student_csv(student_id):
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("students"))

    try:
        student = students_collection.find_one({"_id": ObjectId(student_id)})
        if not student:
            flash("Student record not found.", "error")
            return redirect(url_for("students"))

        df = prepare_student_export_dataset([student])
        roll = student.get("roll_number", "record").replace(" ", "_")
        csv_bytes = generate_csv_bytes(df)

        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=student_{roll}_prediction.csv"}
        )
    except Exception as exc:
        flash(f"Export error: {exc}", "error")
        return redirect(url_for("students"))


# ---------------- EXPORT PREDICTIONS (STUDENT PORTAL) ----------------
@app.route("/student/export/excel")
@login_required
def student_export_excel():
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("student_dashboard"))

    student_record = students_collection.find_one({"email": current_user.email})
    if not student_record:
        student_record = students_collection.find_one(
            {"name": {"$regex": f"^{current_user.name}$", "$options": "i"}}
        )

    if not student_record:
        flash("No official faculty record found associated with your account.", "warning")
        return redirect(url_for("student_dashboard"))

    df = prepare_student_export_dataset([student_record])
    roll = student_record.get("roll_number", "my_record").replace(" ", "_")
    excel_bytes = generate_styled_excel(df, report_title=f"My Academic Standing & AI Prediction: {current_user.name}")

    return Response(
        excel_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=my_prediction_{roll}.xlsx"}
    )


@app.route("/student/export/csv")
@login_required
def student_export_csv():
    if students_collection is None:
        flash("Database not connected.", "error")
        return redirect(url_for("student_dashboard"))

    student_record = students_collection.find_one({"email": current_user.email})
    if not student_record:
        student_record = students_collection.find_one(
            {"name": {"$regex": f"^{current_user.name}$", "$options": "i"}}
        )

    if not student_record:
        flash("No official faculty record found associated with your account.", "warning")
        return redirect(url_for("student_dashboard"))

    df = prepare_student_export_dataset([student_record])
    roll = student_record.get("roll_number", "my_record").replace(" ", "_")
    csv_bytes = generate_csv_bytes(df)

    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=my_prediction_{roll}.csv"}
    )


# ---------------- STUDENT DASHBOARD ----------------
@app.route("/student-dashboard")
@login_required
def student_dashboard():
    if current_user.role == "admin":
        return redirect(url_for("index"))

    student_record = None

    if students_collection is not None:
        try:
            # Search by email matching current student
            student_record = students_collection.find_one({"email": current_user.email})
            
            # If not found by email, try matching user name
            if not student_record:
                student_record = students_collection.find_one(
                    {"name": {"$regex": f"^{current_user.name}$", "$options": "i"}}
                )

        except PyMongoError:
            app.logger.exception("Student dashboard query error")
            flash("Could not retrieve student record.", "error")

    return render_template(
        "student_dashboard.html",
        student=student_record
    )


# ---------------- HEALTH STATUS ----------------
@app.route("/health")
def health():
    return {
        "status": "healthy",
        "mongodb_connected": students_collection is not None,
        "model_loaded": model is not None,
        "mongodb_error": db_error,
        "model_error": model_error
    }


if __name__ == "__main__":
    app.run(debug=True)
