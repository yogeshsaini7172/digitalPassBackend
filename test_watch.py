from pymongo import MongoClient
from datetime import datetime
from zoneinfo import ZoneInfo

client = MongoClient("mongodb://localhost:27017/")
db = client['localDB1']

# Test: Insert a new visitor
test_visitor = {
    "name": "Test Visitor",
    "email": "test@example.com",
    "phone": "9876543210",
    "purpose": "Testing watch stream",
    "img": "test_image_id",
    "campus": "Main Campus",
    "entryDate": datetime.now(ZoneInfo("Asia/Kolkata")),
    "status": "pending",
    "visitorId": 999,
    "department": "IT"
}

result = db["visitor"].insert_one(test_visitor)
print(f"✓ Inserted test visitor with ID: {result.inserted_id}")
print("Check the app terminal - you should see '>>> CHANGE DETECTED' output!")

client.close()
