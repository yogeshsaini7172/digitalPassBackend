from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")

try:
    status = client.admin.command("replSetGetStatus")
    print("Replica set status:", status)
except Exception as e:
    print("Error:", e)

client.close()