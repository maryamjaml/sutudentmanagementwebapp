
import os
from getpass import getpass

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from werkzeug.security import generate_password_hash

load_dotenv()

uri = os.getenv("MONGO_URI", "").strip()

if not uri:
    raise SystemExit("MONGO_URI .env file mein set nahi hai.")

client = None

try:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    users = client["student_management"]["users"]

    print("\n=== Create Admin Account ===")
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass("Admin password (minimum 8 characters): ")

    if not name or not email:
        raise SystemExit("Name aur email required hain.")

    if len(password) < 8:
        raise SystemExit("Password kam az kam 8 characters ka hona chahiye.")

    existing = users.find_one({"email": email})

    if existing:
        confirm = input(
            "Is email ka account already hai. "
            "Kya is account ko admin banana hai? (yes/no): "
        ).strip().lower()

        if confirm != "yes":
            raise SystemExit("Cancelled.")

        users.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "name": name,
                "password": generate_password_hash(password),
                "role": "admin"
            }}
        )
    else:
        users.insert_one({
            "name": name,
            "email": email,
            "password": generate_password_hash(password),
            "role": "admin"
        })

    print("\nAdmin account successfully created!")

except PyMongoError as error:
    print("MongoDB error:", error)

finally:
    if client is not None:
        client.close()
