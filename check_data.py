from pymongo import MongoClient

# Connect to MongoDB (same as in your app.py)
client = MongoClient("mongodb://localhost:27017/")

# List all databases
print("Available databases:")
for db_name in client.list_database_names():
    print(f"  - {db_name}")
    db_check = client[db_name]
    collections = db_check.list_collection_names()
    if collections:
        print(f"    Collections: {collections}")
        for coll in collections[:2]:  # Show first 2 collections
            docs = list(db_check[coll].find().limit(1))
            if docs:
                print(f"      Sample from {coll}: {docs[0]}")
    print()

# Also check 'test' db which is default
print("Checking 'test' database:")
test_db = client['test']
test_collections = test_db.list_collection_names()
if test_collections:
    print(f"  Collections in 'test': {test_collections}")
    for coll in test_collections[:2]:
        docs = list(test_db[coll].find().limit(1))
        if docs:
            print(f"    Sample from {coll}: {docs[0]}")
else:
    print("  No collections in 'test'.")

# Also check 'localdb1' lowercase
print("Checking 'localdb1' database:")
localdb1 = client['localdb1']
local_collections = localdb1.list_collection_names()
if local_collections:
    print(f"  Collections in 'localdb1': {local_collections}")
    for coll in local_collections[:2]:
        docs = list(localdb1[coll].find().limit(1))
        if docs:
            print(f"    Sample from {coll}: {docs[0]}")
else:
    print("  No collections in 'localdb1'.")

# Check for existing replset config
print("Checking for existing replica set config:")
try:
    repl_config = list(client.local.system.replset.find())
    if repl_config:
        print(f"  Existing config: {repl_config[0]}")
    else:
        print("  No existing replset config.")
except Exception as e:
    print(f"  Error checking replset: {e}")

# Focus on your main database 'localDB1'
db = client['localDB1']

# List collections in localDB1
print("\nCollections in 'localDB1':")
for collection_name in db.list_collection_names():
    print(f"  - {collection_name}")
    collection = db[collection_name]
    # Show a sample of documents (up to 3 per collection)
    docs = list(collection.find().limit(3))
    if docs:
        print(f"    Sample documents ({len(docs)} shown):")
        for doc in docs:
            print(f"      {doc}")
    else:
        print("    No documents found.")
    print()  # Blank line for readability

# Close the connection
client.close()