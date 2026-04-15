from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/?directConnection=true")

# Replica set config
config = {
    "_id": "rs0",
    "members": [
        {"_id": 0, "host": "localhost:27017"}
    ]
}

# Initiate replica set
try:
    result = client.admin.command("replSetInitiate", config)
    print("Replica set initiated:", result)
except Exception as e:
    print("Error initiating replica set:", e)

# Close connection
client.close()