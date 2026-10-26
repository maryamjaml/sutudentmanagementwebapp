import os
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime

load_dotenv()
mongo_uri = os.getenv("MONGO_URI")

if mongo_uri:
    client = MongoClient(mongo_uri)
    db = client["student_management"]

    # Update passwords
    db.users.update_one(
        {"email": "maryam123@gmail.com"},
        {"$set": {"password": generate_password_hash("admin123"), "role": "admin"}}
    )
    db.users.update_one(
        {"email": "ali123@gmail.com"},
        {"$set": {"password": generate_password_hash("student123"), "role": "student"}}
    )

    # Ensure admin@system.com
    if not db.users.find_one({"email": "admin@system.com"}):
        db.users.insert_one({
            "name": "Admin Maryam",
            "email": "admin@system.com",
            "password": generate_password_hash("admin123"),
            "role": "admin",
            "created_at": datetime.utcnow()
        })

    # Ensure student@system.com
    if not db.users.find_one({"email": "student@system.com"}):
        db.users.insert_one({
            "name": "Ali Khan",
            "email": "student@system.com",
            "password": generate_password_hash("student123"),
            "role": "student",
            "created_at": datetime.utcnow()
        })

    # Ensure student records
    if not db.students.find_one({"email": "student@system.com"}):
        db.students.insert_one({
            "name": "Ali Khan",
            "email": "student@system.com",
            "roll_number": "STD-2026-01",
            "Study_Hours": 5.5,
            "Attendance": 85.0,
            "Previous_Marks": 72.0,
            "Assignment_Marks": 80.0,
            "predicted_status": "Pass",
            "pass_probability": 98.4,
            "created_at": datetime.utcnow()
        })

    if not db.students.find_one({"email": "ali123@gmail.com"}):
        db.students.insert_one({
            "name": "Ali",
            "email": "ali123@gmail.com",
            "roll_number": "STD-2026-02",
            "Study_Hours": 3.0,
            "Attendance": 65.0,
            "Previous_Marks": 55.0,
            "Assignment_Marks": 60.0,
            "predicted_status": "Pass",
            "pass_probability": 76.2,
            "created_at": datetime.utcnow()
        })

    print("Demo data synced successfully.")
    for u in db.users.find({}, {"password": 0}):
        print(u)
