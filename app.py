import eventlet
eventlet.monkey_patch(all=True)
import random
import string
import uuid
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room, emit
from pymongo import MongoClient
from pymongo.errors import OperationFailure
import threading
import os
import smtplib
from email.message import EmailMessage
import logging
from dotenv import load_dotenv
import json
from datetime import datetime,timezone,timedelta
import requests

#import pandas library to read excel file
import pandas as pd
import cloudinary
import cloudinary.uploader

#imports for firebase messaging
import firebase_admin 
from firebase_admin import credentials, messaging

#initialize firebase admin sdk with service account json file
cred = credentials.Certificate('digital-pass-fcm-service-account.json')
firebase_admin.initialize_app(cred)


# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Allow requests from GitHub Pages and local dev
CORS(app, origins=[
    "https://yogeshsaini7172.github.io",
    "http://localhost:5173",
    "http://localhost:3000"
])

# mongodb://localhost:27017/
#setup of mongodb connection with localhost and default port 27017 and database name localDB1
client = MongoClient(os.getenv('MONGODB_URI', '')) 

#here we have database named localDB1 and collection named users to store user details and collection named roleDepartment to store role and department details and collection named campus to store campus details and collection named departmentBatch to store batches of each department and collection named managementMemberBatch to store batches of management members and collection named leveledBatches to store batch details with level1 and level2 for each batch
db = client['localDB1']
users_collection = db['users']
roleDepartmentCollection = db['roleDepartment']

#configure cloudinary for image upload
cloudinary.config(
  cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME', 'dtdo4gzfh'),
  api_key = os.getenv('CLOUDINARY_API_KEY', '758814595517121'),
    api_secret = os.getenv('CLOUDINARY_API_SECRET', 'n0X7qobF6_dTtwM-X4QwnKmAdPY')
)

#common function to upload image to cloudinary and return the url of uploaded image
def upload_image_to_cloudinary(public_id, image_file):
    try:
        #also add invalidate and overwrite parameters in upload method to remove the previous image or upload new image to cloudinary
        result = cloudinary.uploader.upload(image_file, public_id=public_id, overwrite=True, invalidate=True)
        return result['secure_url']
            
    except Exception as e:
        print(f"Error uploading image: {e}")
        return None
    

#to upload profile image of user and update the img field in database with url of uploaded image
@app.route('/upload-profile-image', methods=['POST'])
def upload_profile_image():
    print("Received a request to /upload-profile-image")
    if 'img' not in request.files:
        return jsonify({"message": "No image file in the request"}), 400
    image_file = request.files['img']
    token = request.form.get('token')
    if not token:
        return jsonify({"message": "Token is required"}), 400
    requester = users_collection.find_one({"token": token})
    if not requester:
        return jsonify({"message": "User not found"}), 404
    
    #create a unique public id for each image with user email 
    public_id = "profile_images/" + requester['email']
    image_url = upload_image_to_cloudinary(public_id, image_file)
    
    #upload image to cloudinary if image of user is not existing or user want to change the existing image so the existing image will be replaced by new image and url of new image will be updated in database and cloudinary will automatically remove the previous image to save the space in cloudinary
    if(requester['img'].strip()==""):
        users_collection.update_one({"token": token}, {"$set": {"img":public_id}})
        
    if image_url:
        return jsonify({"message": "Profile image uploaded successfully!"}), 200
    else:
        return jsonify({"message": "Failed to upload profile image"}), 500

#create the configuration for SMTP email server
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 465))
SMTP_USER = os.getenv('SMTP_USER', 'yogeshsaini8213@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'fxiz tpni mftf qiih')
FROM_EMAIL = os.getenv('FROM_EMAIL', 'digitalpass@DP.com')

@app.route('/')
def home():
    return "Server is Running! (Andro-Python Middleware)"

def sendEmail(to_email,subject,body):
    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        msg.set_content(body)

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")

#check requester and new user role and department
def checkRequsterAndNewUserRoleDepartment(requester,newUser):
    roleHierarchy={
        "admin": 4,
        "principal": 3,
        "hod": 2,
        "faculty": 1,
        "student": 0,
        "security guard": 1,
        "reception": 1
    }
    #we will check the authenticity of requester to add new user based on role,department and campus if requester role is admin then he can add any user if requester role is principal then he can add user with role hod,faculty,student and with any department if requester role is hod then he can add user with role faculty and student and with his department only if requester role is faculty then he can add user with role student and with his department only if requester role is security guard or reception then they cannot add any user
    if requester['role']=="admin":
        return True
    elif roleHierarchy[requester['role']] > roleHierarchy[newUser['role']]:
        if requester['role']=="principal":
            return True
        elif requester['role']=="hod":
            if requester['department']==newUser['department']:
                return True
            else:
                return False
        elif requester['role']=="faculty":
            if requester['department']==newUser['department'] and newUser['role']=="student":
                return True
            else:
                return False
        else:
            return False
    else:
        return False
    

#login user
@app.route('/login-user', methods=['POST'])
def login_user():

    
    data=request.json
    email=data['email']
    password=data['password']

    print("Received a request to /login-user")
    if email!="" and password!="":
        user = users_collection.find_one({"email": email, "password": password},{"_id":0,"name":1,"department":1,"role":1,"img":1,"batch":1,"email":1,"campus":1,"phone":1,"uid":1,"fathername":1,"fatherphone":1})
        if user:
            #generate token for user
            token = str(uuid.uuid4())

            #insert token in database for that user
            users_collection.update_one({"email": email}, {"$set": {"token": token}})
            user['token']=token
            threading.Thread(target=sendEmail,args=(email,'Login Alert for Digital Pass',f"Dear {user['name']},\n\nYou have successfully logged in to your account in Digital Pass.\nIf this was not you, please contact the administration immediately.\n\nBest regards,\n Digital Pass"),daemon=True).start()
            return jsonify(user), 200
        else:
            return jsonify({"message": "Invalid email or password"}), 401
    elif password!="" :
        #when password is not empty that means this is token
        user = users_collection.find_one({"token": password},{"_id":0,"name":1,"department":1,"role":1,"img":1,"batch":1,"email":1,"campus":1,"phone":1,"uid":1,"fathername":1,"fatherphone":1})
        if user:
            return jsonify(user), 200
        else:
            return jsonify({"message": "Invalid token"}), 401
    else: 
        return jsonify({"message": "Email and password cannot be empty"}), 400
    
#to get campus and department
@app.route('/get-campus-and-department', methods=['POST'])
def get_campus_and_department():
    print("Received a request to /get-campus-and-department")
    data = request.json 
    user = users_collection.find_one({"token": data})
    if user:
        departments = roleDepartmentCollection.find_one({}, {"_id": 0, "department": 1})["department"]
        if user['role']=="admin":
            campus=db["campus"].find_one({},{"_id":0,"campus":1})["campus"]
            return jsonify({"campus": campus, "department": departments}), 200
        elif user['role']=="principal":
            return jsonify({"campus":[],"department": departments}), 200
        elif user['role']=="hod" or user['role']=="faculty":
            return jsonify({"campus":[],"department": [user['department']]}), 200
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404
    

#to get role based on department
@app.route('/get-role-based-on-department', methods=['POST'])
def get_role_based_on_department():
    print("Received a request to /get-role-based-on-department")
    data = request.json 
    user = users_collection.find_one({"token": data['token']})
    if user:
        if data['department'] == "ADMINISTRATION":
            if user['role']=="admin":
                return jsonify(["admin", "principal", "hod","security guard","reception"]), 200
            elif user['role']=="principal":
                return jsonify(["hod","security guard","reception"]), 200
            elif user['role']=="hod":
                return jsonify(["security guard","reception"]), 200
            else:
                return jsonify({"message": "Role not authorized"}), 400
        else:
            if user['role']=="admin" or user['role']=="principal":
                return jsonify(["hod","faculty","student"]), 200
            elif user['role']=="hod":
                return jsonify(["faculty","student"]), 200
            elif user['role']=="faculty":
                return jsonify(["student"]), 200
            else:
                return jsonify({"message": "Role not authorized"}), 400
            
#to get batches based on department
@app.route('/get-batches-based-on-department', methods=['POST'])
def get_batches_based_on_department():
    print("Received a request to /get-batches-based-on-department")
    data = request.json 
    user = users_collection.find_one({"token": data['token']})
    if user:
        if data["role"]=="student":
            #if user is admin put the value of campus from data['campus'] else put user campus
            campus=data['campus'] if user['role']=="admin" else user['campus']


            if user['role']=="admin"or user['role']=="principal" or user['role']=="hod" or user['role']=="faculty":
                #fetch batches from departmentBatch collection based on department and campus
                batches= db["departmentBatch"].find_one({"department": data['department'], "campus": campus}, {"_id": 0, "batches": 1})
                if batches and "batches" in batches:
                    return jsonify(batches["batches"]), 200
                else:
                    return jsonify({"message": "No batches found for this department and campus"}), 404
            else:
                return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404

#add new user
@app.route('/add-new-user', methods=['POST'])
def add_new_user():
    data = request.json
    #we have check that the data must contain name,email,phone,role,department fields and those fields cannot be empty
    if not all(key in data for key in ['name', 'email', 'phone', 'role', 'department']):
        return jsonify({"message": "Missing required fields"}), 400
    print("Received a request to /add-new-user")
    #check the role of the requester
    requester = users_collection.find_one({"token": data['token']})
    if requester:
        if checkRequsterAndNewUserRoleDepartment(requester,data)==False:
            return jsonify({"message": "You are not authorized to add this user"}), 403
    else:
        return jsonify({"message": "Requester not found"}), 404
    #check if user already exists
    existing_user = users_collection.find_one({"email": data['email']})
    if existing_user:
        return jsonify({"message": "User with this email already exists"}), 400
    data["token"]="" #add empty token for new user
    data["img"]="" #add empty img for new user
    #set random password for new user and send it to user email
    data["password"]=''.join(random.choices(string.ascii_letters + string.digits, k=8))
    #set campus same as requester campus if requester is not admin
    if requester['role']!="admin":
            data['campus']=requester['campus'] 

    #check if new user is not a student then batch will be check for that user
    if data['role']!="student":
        data['batch']=data['campus']+"-"+data['department']+"-"+data['role']
        if not db["managementMemberBatch"].find_one({"department": data['department'],"campus": data['campus'], "batches": data['batch']}):
            db["managementMemberBatch"].update_one({"department": data['department'],"campus": data['campus']}, {"$push": {"batches": data['batch']}}, upsert=True)


    #add user to database
    try:
        users_collection.insert_one(data)
        thToAddedUser=threading.Thread(target=sendEmail,args=('yogeshsaini7172@gmail.com','Account Created in Digital Pass',f"Dear {data['name']},\n\nYour account has been created in Digital Pass.\nYour login credentials are:\nEmail: {data['email']}\nPassword: {data['password']}\n\nPlease change your password after logging in for the first time.\n\nBest regards,\n Digital Pass"),daemon=True)
        # thToAddedUser.start()
        return jsonify({"message": "User added successfully!"}), 200
    except Exception as e:
        print(f"Error occurred: {e}")



#to add bulk users with excel file, we will receive the data in list of user details and we will add those users in database
#here excel file will come in multipart form data with key "file" and also come token of current user with key "token" in form data to check the authorization of requester
@app.route('/upload-excel-users', methods=['POST'])
def upload_excel_users():
    print("Received a request to /upload-excel-users")
    if 'file' not in request.files:
        return jsonify({"message": "No file part in the request"}), 400
    file = request.files['file']
    token = request.form.get('token')
    if not token:
        return jsonify({"message": "Token is required"}), 400
    requester = users_collection.find_one({"token": token})
    if not requester:
        return jsonify({"message": "Requester not found"}), 404
    #we will read the excel file and convert it into list of user details and then we will add those users in database
    #we will use pandas library to read excel file
    #in the excel file the user can have any role but we have to check the authorization of requester to add those users based on role and department of requester and new user like in add new user api
    #also we have to take all the fields of user details from excel file  in lowercase
    try:
        dataFrame = pd.read_excel(file)
        users_list = dataFrame.to_dict(orient='records')

        # set for batch of students and management members
        studentBatch = set()
        managementMemberBatch = set()

        # clean up rows from Excel; convert keys to lowercase, strip values, drop NaNs
        cleaned_users = []
        required_fields = ['name', 'email', 'phone', 'role', 'department']

        for raw_user in users_list:
            user = {}
            for k, v in raw_user.items():
                # drop missing values coming from pandas (NaN)
                if pd.isna(v):
                    continue
                user[k.lower()] =str(v).strip()


            # skip row if any required field is missing
            if not all(field in user for field in required_fields):
                continue

            #set value of role in lowercase and department in upercase
            user['role'] = user['role'].lower()
            user['department'] = user['department'].upper()

            # authorization check
            if not checkRequsterAndNewUserRoleDepartment(requester, user):
                continue

            # skip already existing users
            if users_collection.find_one({"email": user['email']}):
                continue

            user["token"] = ""
            user["img"] = ""
            user["password"] = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            if requester['role'] != "admin":
                user['campus'] = requester['campus']

            if user['role'] == "student":
                #check if user batch is already exist in studentBatch set
                if user["batch"] not in studentBatch:
                    #if not exist then we will add it in studentBatch set and also add it in departmentBatch collection
                    studentBatch.add(user['batch'])
                    if not db["departmentBatch"].find_one({"department": user['department'], "campus": user['campus'], "batches": user['batch']}):
                        db["departmentBatch"].update_one({"department": user['department'], "campus": user['campus']}, {"$push": {"batches": user['batch']}}, upsert=True)

            else:
                #when new added user is not student then we have to create it batch
                user['batch'] = user['campus'] + "-" + user['department'] + "-" + user['role']
                #check if user batch is already exist in managementMemberBatch set
                if user['batch'] not in managementMemberBatch:
                    #if not exist then we will add it in managementMemberBatch set and also add it in managementMemberBatch collection
                    managementMemberBatch.add(user['batch'])
                    if not db["managementMemberBatch"].find_one({"department": user['department'], "campus": user['campus'], "batches": user['batch']}):
                        db["managementMemberBatch"].update_one({"department": user['department'], "campus": user['campus']}, {"$push": {"batches": user['batch']}}, upsert=True)

            

            cleaned_users.append(user)

        users_list = cleaned_users
        
        #add users in database
        if len(users_list)>0:
            users_collection.insert_many(users_list)

            #send email to added users
            # for user in users_list:
            #     thToAddedUser=threading.Thread(target=sendEmailToAddedUser,args=(user['email'],'Account Created in Digital Pass',f"Dear {user['name']},\n\nYour account has been created in Digital Pass.\nYour login credentials are:\nEmail: {user['email']}\nPassword: {user['password']}\n\nPlease change your password after logging in for the first time.\n\nBest regards,\n Digital Pass"),daemon=True)
            #     thToAddedUser.start()
        return jsonify({"message": "Users added successfully!"}), 200
    
    except Exception as e:
        print(f"Error occurred: {e}")
        return jsonify({"message": "An error occurred while processing the file"}), 500


#api to get batches from departmentBatch and managementMemeber collection based on campus,department and role of requester
@app.route('/get-all-batches', methods=['POST'])
def get_allBatches_basedOn_campus():
    print("Received a request to /get-all-batches")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        if requester['role']=="admin":
            batchesFromDepartmentBatchCollection=db["departmentBatch"].find({"campus":data["campus"]},{"_id":0,"batches":1})
            batchesFromManagementMemberBatchCollection=db["managementMemberBatch"].find({"campus":data["campus"]},{"_id":0,"batches":1})
            studentBatch=[]
            for item in batchesFromDepartmentBatchCollection:
                studentBatch.extend(item['batches'])

            memberBatch=[]
            for item in batchesFromManagementMemberBatchCollection:
                memberBatch.extend(item['batches'])
            return jsonify({"student": studentBatch, "member": memberBatch}), 200
        elif requester['role']=="principal":
            batchesFromDepartmentBatchCollection=db["departmentBatch"].find({"campus": requester['campus']},{"_id":0,"batches":1})
            batchesFromManagementMemberBatchCollection=db["managementMemberBatch"].find({"campus": requester['campus']},{"_id":0,"batches":1})
            studentBatch=[]
            for item in batchesFromDepartmentBatchCollection:
                studentBatch.extend(item['batches'])
                
            memberBatch=[]
            for item in batchesFromManagementMemberBatchCollection:
                memberBatch.extend(item['batches'])

            return jsonify({"student": studentBatch, "member": memberBatch}), 200
        
        elif requester['role']=="hod" :
            batchesFromDepartmentBatchCollection=db["departmentBatch"].find_one({"department": requester['department'], "campus": requester['campus']},{"_id":0,"batches":1})
            batchesFromManagementMemberBatchCollection=db["managementMemberBatch"].find_one({"department": requester['department'], "campus": requester['campus']},{"_id":0,"batches":1})

            studentBatch=batchesFromDepartmentBatchCollection['batches'] if batchesFromDepartmentBatchCollection and "batches" in batchesFromDepartmentBatchCollection else []
            memberBatch=batchesFromManagementMemberBatchCollection['batches'] if batchesFromManagementMemberBatchCollection and "batches" in batchesFromManagementMemberBatchCollection else []

            return jsonify({"student": studentBatch, "member": memberBatch}), 200
        
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else :
        return jsonify({"message": "User not found"}), 404    


#api to remove batch from departmentBatch collection and remove batch from batch collection of each student in that batch
@app.route('/remove-batch', methods=['POST'])
def remove_batch():
    print("Received a request to /remove-batch")
    data = request.json 
    currentUser= users_collection.find_one({"token": data['token']})

    if currentUser:
        campus=data['campus'] if currentUser['role']=="admin" else currentUser['campus']

        if currentUser['role']=="admin" or currentUser['role']=="principal" or currentUser['role']=="hod":

            #we will check the batch is belongs to their campus or not
            if currentUser["role"]!="admin":
                if not data['batchName'].startswith(campus+"-"):
                    return jsonify({"message": "Batch not belongs to your campus"}), 400
                
            #remove this batch from leveledBatches collection
            db["leveledBatches"].delete_one({"batchName": data['batchName']})

            #student batch format is campus-year-department-section and management member batch format is campus-department-role

            #now we will check the batch is student batch or management member batch by checking the format of batch name if batch name contain A,B,C,D,E,F,G,H,I,J then it is student batch otherwise it is management member batch
            if data['batchName'].endswith(tuple(["-A","-B","-C","-D","-E","-F","-G","-H","-I","-J"])):
                #remove batch from departmentBatch collection
                db["departmentBatch"].update_one({"campus": campus, "batches": data['batchName']}, {"$pull": {"batches": data['batchName']}})
                #remove batch from batch collection of each student in that batch
                users_collection.update_many({"campus": campus, "batch": data['batchName']}, {"$set": {"batch": ""}})
                
            else:
                #remove batch from managementMemberBatch collection
                db["managementMemberBatch"].update_one({"campus": campus, "batches": data['batchName']}, {"$pull": {"batches": data['batchName']}})
                #remove batch from batch collection of each management member in that batch
                users_collection.update_many({"campus": campus, "batch": data['batchName']}, {"$set": {"batch": ""}})
                

            return jsonify({"message": "Batch removed successfully!"}), 200
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404        


#api to edit batch details like level1 and level2 in batch collection of each student in that batch
@app.route('/edit-batch', methods=['POST'])
def edit_batch():
    print("Received a request to /edit-batch")
    data = request.json 
    currentUser= users_collection.find_one({"token": data['token']})

    if currentUser:
        if currentUser['role']=="admin" or currentUser['role']=="principal" or currentUser['role']=="hod":
            #edit batch details like level1 and level2 in batch collection
            batchName=data['batchName']

            #we check the batch is belongs to their campus or not
            if currentUser["role"]!="admin":
                if not batchName.startswith(currentUser['campus']+"-"):
                    return jsonify({"message": "Batch not belongs to your campus"}), 400
                
            db["leveledBatches"].update_one({"batchName": batchName}, {"$set": {"level1": data['level1'], "level2": data['level2']}}, upsert=True)
            return jsonify({"message": "Batch details updated successfully!"}), 200
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404



#get users for level
@app.route('/get-all-members-for-level', methods=['POST'])
def get_users_for_level():
    print("Received a request to /get-all-members-for-level")
    data = request.json 
    currentUser= users_collection.find_one({"token": data["token"]})
    if currentUser:
        campus=currentUser['campus'] if currentUser['role']!="admin" else data['campus']

        if currentUser['role']=="admin" or currentUser['role']=="principal" or currentUser['role']=="hod":
            users=users_collection.find({"campus":campus,"$or":[{'role':'principal'},{'role':'hod'},{'role':'faculty'}]})
            newUsers=[]
            for user in users:
                newUsers.append({
                    "img":user['img'],
                    "name":user['name'],
                    "email":user['email'],
                    "department":user['department']})
                
            return jsonify(newUsers), 200
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404


#api to get batch data with year,department and sections
@app.route('/get-data-for-batch', methods=['POST'])
def get_data_for_batch():
    print("Received a request to /get-data-for-batch")
    data = request.json 
    currentUser= users_collection.find_one({"token": data})

    if currentUser:
        if currentUser['role']=="admin" or currentUser['role']=="principal":
            # #fetch department list from roleDepartment collection
            department=roleDepartmentCollection.find_one({},{"_id":0,"department":1})["department"]
        elif currentUser['role']=="hod":
            department=[currentUser['department']]
        else:
            return jsonify({"message": "Role not authorized"}), 400
        #create a list with current year and next 4 years fetched from system date
        yearList=[]
        currentYear=datetime.now().year
        for i in range(5):
            yearList.append(str(currentYear+i))

        #if user is admin then we will also send campus list
        if currentUser['role']=="admin":
            campus=db["campus"].find_one({},{"_id":0,"campus":1})["campus"]
            return jsonify({"campus": campus,"department":department,"year":yearList,"section":["A","B","C","D","E"]}), 200


        return jsonify({"department":department,"year":yearList,"section":["A","B","C","D","E"]}), 200
    else:
        return jsonify({"message": "User not found"}), 404


#create batch with insert batch data in departmentBatch collection and add batch in batch collection of each student in that batch
@app.route('/add-new-batch', methods=['POST'])
def add_new_batch():
    print("Received a request to /add-new-batch")
    data = request.json 
    currentUser= users_collection.find_one({"token": data['token']})


    if currentUser:
        if currentUser['role']=="admin" or currentUser['role']=="principal" or currentUser['role']=="hod":
           
            batchName=data['batchName']

            #requester is not admin then we will add campus name in starting of batch name
            if currentUser['role']!="admin":
                batchName=currentUser['campus']+"-"+batchName

            #first we insert this batch in leveledBatches collection 
            db["leveledBatches"].update_one({"batchName": batchName}, {"$set": {"level1": data['level1'], "level2": data['level2']}}, upsert=True)

            #then we will check the batch is student batch or management member batch by checking the format of batch name if batch name contain A,B,C,D,E,F,G,H,I,J then it is student batch otherwise it is management member batch
            if batchName.endswith(tuple(["-A","-B","-C","-D","-E","-F","-G","-H","-I","-J"])):
                #now we extract data from batch name like campus-year-department-section
                batchSplitedDetails=batchName.split("-")
                campus=batchSplitedDetails[0] if currentUser["role"]=="admin" else currentUser['campus']
                department=batchSplitedDetails[-2]
                #insert batch in departmentBatch collection if it is not exist
                if not db["departmentBatch"].find_one({"department": department, "campus": campus, "batches": batchName}):
                    db["departmentBatch"].update_one({"department": department, "campus": campus}, {"$push": {"batches": batchName}}, upsert=True)
            
            else:
                #now we extract data from batch name like campus-department-role
                batchSplitedDetails=batchName.split("-")
                campus=batchSplitedDetails[0] if currentUser["role"]=="admin" else currentUser['campus']
                department=batchSplitedDetails[1]
                #insert batch in managementMemberBatch collection if it is not exist
                if not db["managementMemberBatch"].find_one({"department": department, "campus": campus, "batches": batchName}):
                    db["managementMemberBatch"].update_one({"department": department, "campus": campus}, {"$push": {"batches": batchName}}, upsert=True)

            return jsonify({"message": "Batch added successfully!"}), 200

            
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404


#get members for user management
@app.route('/get-members-for-user-management', methods=['POST'])
def get_members_for_user_management():
    data = request.json 
    currentUser= users_collection.find_one({"token": data})
    if currentUser:
       filter={"_id":0,"password":0,"token":0,"lastGatePassDate":0,"verificationCode":0,"lastVerificationCodeTime":0,"fcmToken":0}
       if currentUser['role']=="admin":
           #fetch all users from database without password and token and id fetch all data as in document exist in database
            users=users_collection.find({},filter)
            return jsonify(list(users)), 200
       elif currentUser['role']=="principal":
           user=users_collection.find({"campus": currentUser['campus'], "$or":[{"role":"hod"},{"role":"faculty"},{"role":"student"},{"role":"reception"},{"role":"security guard"}]},filter)
           return jsonify(list(user)), 200
       elif currentUser['role']=="hod":
              user=users_collection.find({"campus": currentUser['campus'], "department": currentUser['department'], "$or":[{"role":"faculty"},{"role":"student"},{"role":"reception"},{"role":"security guard"}]},filter)
              return jsonify(list(user)), 200
       elif currentUser['role']=="faculty":
           user=users_collection.find({"campus": currentUser['campus'], "department": currentUser['department'], "role":"student"},filter)
           return jsonify(list(user)), 200
       else:
           return jsonify({"message": "Role not authorized"}), 400


#this api will remove user
@app.route('/remove-user', methods=['POST'])
def remove_user():
    print("Received a request to /remove-user")
    data = request.json

    #check the authorization of the requester
    requester = users_collection.find_one({"token": data['token']})
    if requester:
        user_to_remove = users_collection.find_one({"email": data['removeEmail']})
        if user_to_remove:
            if checkRequsterAndNewUserRoleDepartment(requester,user_to_remove)==False:
                return jsonify({"message": "You are not authorized to remove this user"}), 403
        else:
            return jsonify({"message": "User to remove not found"}), 404
    else:
        return jsonify({"message": "Requester not found"}), 404
    
    # Remove user

    try:
     users_collection.delete_one({"email": data['removeEmail']})
    #  thToRemoveUser=threading.Thread(target=sendEmailToAddedUser,args=('yogeshsaini7172@gmail.com','Account Removed in Digital Pass',f"Dear {data['removeEmail']},\n\nYour account has been removed from Digital Pass.\n\nBest regards,\n Digital Pass"),daemon=True)
    #  thToRemoveUser.start()
     return jsonify({"message": "User removed successfully!"}), 200
    except Exception as e:
     print(f"Error occurred: {e}")
     return jsonify({"message": "An error occurred while removing the user"}), 500


#api to edit the user details
@app.route('/edit-user', methods=['POST'])
def edit_user():
    print("Received a request to /edit-user")
    data = request.json

    #check the authorization of the requester
    requester = users_collection.find_one({"token": data['token']})
    if requester:
        user_to_edit = users_collection.find_one({"email": data['previousEmail']})
        if user_to_edit:
            if checkRequsterAndNewUserRoleDepartment(requester,user_to_edit)==False or checkRequsterAndNewUserRoleDepartment(requester,data)==False:
                return jsonify({"message": "You are not authorized to edit this user"}), 403
        else:
            return jsonify({"message": "User to edit not found"}), 404
    else:
        return jsonify({"message": "Requester not found"}), 404
    
    # Edit user details

    try:
     previousEmail=data['previousEmail']
     #remove previousEmail and token from data before updating
     data.pop('previousEmail', None)
     data.pop('token', None)

     #before editing we have check the email of this user that there is any user
     exisitingUser=users_collection.find_one({"email": data["email"]})
     if exisitingUser and exisitingUser['email']!=previousEmail:
         return jsonify({"message": "A user with this email already exists"}), 400
     #set campus of user as requester campus if requester is not admin
     if requester["role"]!="admin":
         data["campus"]=requester["campus"]
     
     #set batch if user role is not a student with format campus-department-role
     if data['role']!="student":
        data['batch']=data['campus']+"-"+data['department']+"-"+data['role']
        if not db["managementMemberBatch"].find_one({"department": data['department'],"campus": data['campus'], "batches": data['batch']}):
            db["managementMemberBatch"].update_one({"department": data['department'],"campus": data['campus']}, {"$push": {"batches": data['batch']}}, upsert=True)

     users_collection.update_one({"email": previousEmail}, {"$set": data})

     #send email to edited user
     #  thToEditedUser=threading.Thread(target=sendEmailToAddedUser,args=('yogeshsaini7172@gmail.com','Account Updated in Digital Pass',f"Dear {previousEmail},\n\nYour account details have been updated in Digital Pass.\n\nBest regards,\n Digital Pass"),daemon=True)
     #  thToEditedUser.start()

    
     return jsonify({"message": "User details updated successfully!"}), 200
    except Exception as e:
     print(f"Error occurred: {e}")
     return jsonify({"message": "An error occurred while updating the user details"}), 500


#api to get leveled member from batch collection based on batch name
@app.route('/get-leveled-member', methods=['POST'])
def get_leveled_member():
    print("Received a request to /get-leveled-member")
    data = request.json 
    currentUser= users_collection.find_one({"token": data['token']})
    if currentUser:
        if currentUser['role']=="admin" or currentUser['role']=="principal" or currentUser['role']=="hod":
            #fetch leveled member from batch collection of each student in that batch based on batch name
            leveledBatchesCollection=db['leveledBatches']
            leveledBatch=leveledBatchesCollection.find_one({"batchName": data['batchName']},{"_id":0,"level1":1,"level2":1})
            if leveledBatch:
                level1=leveledBatch["level1"]
                level2=leveledBatch["level2"]
                #level1 and level 2 contains list of email, now using email we will fetch user details from users collection and send response with user details
                level1Users=[]
                for email in level1:
                    user=users_collection.find_one({"email": email},{"_id":0,"name":1,"email":1,"department":1,"img":1})
                    if user:
                        level1Users.append(user)
                level2Users=[]
                for email in level2:
                    user=users_collection.find_one({"email": email},{"_id":0,"name":1,"email":1,"department":1,"img":1})
                    if user:
                        level2Users.append(user)
                return jsonify({"level1": level1Users, "level2": level2Users}), 200
            else:
                return jsonify({"message": "Batch not found"}), 404
        else:
            return jsonify({"message": "Role not authorized"}), 400


#api to get campus for allotment for admin and other user
@app.route('/get-campus-for-allotment', methods=['POST'])
def get_all_campus():
    print("Received a request to /get-campus-for-allotment")
    data= request.json
    requester = users_collection.find_one({"token":data})
    if requester:
        if requester['role']=="admin":
            campus=db["campus"].find_one({},{"_id":0,"campus":1})["campus"]
            return jsonify(campus), 200
        else:
            return jsonify([requester['campus']]), 200
    else:
        return jsonify({"message": "User not found"}), 404


#to get all allotted security guard on the basis of campus for admin and other user
@app.route('/get-allotted-security-guard', methods=['POST'])
def get_allotted_security_guard():
    print("Received a request to /get-allotted-security-guard")
    data= request.json
    requester = users_collection.find_one({"token":data['token']})
    if requester:
        if requester['role']=="admin":
            securityGuard=users_collection.find({"role":"security guard","campus":data['campus']},{"_id":0,"name":1,"email":1,"department":1,"img":1})
            allotted=db["allotment"].find_one({"campus": data['campus']},{"_id":0,"security":1})
            if allotted:
                allotted=allotted["security"]
        elif requester['role']=="principal" or (requester['role']=="hod" and requester['department']=="ADMINISTRATION"):
            securityGuard=users_collection.find({"role":"security guard","campus":requester['campus']},{"_id":0,"name":1,"email":1,"department":1,"img":1})
            allotted=db["allotment"].find_one({"campus": requester['campus']},{"_id":0,"security":1})
            if allotted:
                allotted=allotted["security"]

        else:
                return jsonify({"message": "Role not authorized"}), 400

        if not allotted:
            return jsonify({"allotted": [], "unallotted": list(securityGuard)}), 200
        #filter security guard based on allotted security guard email because allotted security guard contains email of security guard
        allottedSecurityGuard=[]
        unallottedSecurityGuard=[]
        for guard in securityGuard:
            if guard['email'] in allotted:
                allottedSecurityGuard.append(guard)
                allotted.remove(guard['email'])
            else:
                unallottedSecurityGuard.append(guard)

        return jsonify({"allotted": allottedSecurityGuard, "unallotted": unallottedSecurityGuard}), 200
        
    else:
        return jsonify({"message": "User not found"}), 404
    

#to save allotted security guard in allotment collection based on campus
@app.route('/save-allotted-security-guard', methods=['POST'])
def save_allotted_security_guard():
    print("Received a request to /save-allotted-security-guard")
    data= request.json
    requester = users_collection.find_one({"token":data['token']})
    if requester:
        if requester['role']=="admin":
            db["allotment"].update_one({"campus": data['campus']}, {"$set": {"security": data['allottedSecurityGuard']}}, upsert=True)
            return jsonify({"message": "Allotted security guard saved successfully!"}), 200
        elif requester['role']=="principal" or (requester['role']=="hod" and requester['department']=="ADMINISTRATION"):
            db["allotment"].update_one({"campus": requester['campus']}, {"$set": {"security": data['allottedSecurityGuard']}}, upsert=True)
            return jsonify({"message": "Allotted security guard saved successfully!"}), 200
    else:
        return jsonify({"message": "User not found"}), 404

    
#to check the permission of security guard for access the campus based on allotment collection
@app.route('/check-permission-of-security-guard', methods=['POST'])
def check_permission_of_security_guard():
    print("Received a request to /check-permission-of-security-guard")
    data= request.json
    requester = users_collection.find_one({"token":data},{"_id":0,"email":1,"role":1,"campus":1})
    if requester:
        if requester['role']=="security guard":
            allotted=db["allotment"].find_one({"campus": requester['campus']},{"_id":0,"security":1})
            if allotted and requester['email'] in allotted["security"]:
                return jsonify({"message": "Permission granted"}), 200
            else:
                return jsonify({"message": "Permission denied"}), 403
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404


#to get all member for visitor based on campus that is requested by security guard
@app.route('/get-all-member-for-visitor', methods=['POST'])
def get_all_member_for_visitor():
    print("Received a request to /get-all-member-for-visitor")
    data= request.json
    requester = users_collection.find_one({"token":data})
    if requester:
        if requester['role']=="security guard" or requester['role']=="reception" or requester['role']=="faculty" or requester['role']=="hod" or requester['role']=="principal":
            members=users_collection.find({"campus": requester['campus'], "$or":[{"role":"principal"},{"role":"hod"},{"role":"faculty"},{"role":"reception"}]},{"_id":0,"name":1,"email":1,"department":1,"img":1,"phone":1})
            return jsonify(list(members)), 200
        elif requester['role']=="admin":
            members=users_collection.find({"$or":[{"role":"principal"},{"role":"hod"},{"role":"faculty"},{"role":"reception"}]},{"_id":0,"name":1,"email":1,"department":1,"img":1,"phone":1})
            return jsonify(list(members)), 200
        else:
            return jsonify({"message": "Role not authorized"}), 400
    else:
        return jsonify({"message": "User not found"}), 404



#here using multipart form data received with img file,visitor hash and token of security guard
@app.route('/enter-visitor', methods=['POST'])
def enter_visitor():
    print("Received a request to /enter-visitor")
    if 'img' not in request.files:
        return jsonify({"message": "No image part in the request"}), 400
    img = request.files['img']

    data = request.form
    token = data.get('token')
    visitorString = data.get('visitor')
    #visitor string will be in json format but in string format so we will convert it into json object
    try:
        visitor = json.loads(visitorString)
    except json.JSONDecodeError:
        return jsonify({"message": "Invalid visitor data format"}), 400

    if not token or not visitor:
        return jsonify({"message": "Token and visitor hash are required"}), 400
    requester = users_collection.find_one({"token": token})
    if not requester:
        return jsonify({"message": "Requester not found"}), 404
    if requester['role'] != "security guard":
        return jsonify({"message": "Role not authorized"}), 403
    
    #find id for visitor from visitorID collection,in this collections document we will fetch default value of id attribe and increase it by one 
    # by using findOneUpadateOne method
    visitorID=db["visitorID"].find_one_and_update({}, {"$inc": {"id": 1}},{'id':1,"_id":0})['id']

    #upload image of visitor 
    publicId="profile_images/"+visitor['name']+str(visitorID)
    publicId=publicId.replace(" ","")
    imgUrl=upload_image_to_cloudinary(publicId,img)
    if not imgUrl:
        return jsonify({"message": "Image upload failed"}), 500
    
    #insert visitor data in visitor collection with status pending and also add img,campus,entry date time for zone India
    
    #also we have to add lastUpadetdBy attribute so that we will not send the notification to the same user
    visitor.update({
        "img": publicId,
        "campus": requester['campus'],
        "entryDate": datetime.now(ZoneInfo("Asia/Kolkata")),
        "status": "pending",
        "visitorId": visitorID,
        "lastUpdatedBy": requester['email']
    })
    db["visitor"].insert_one(visitor)
    return jsonify({"message": "Visitor entry recorded successfully!"}), 200


#to get recent visitor list from visitor collection based on campus,department and role of requester
@app.route('/get-recent-visitor-list', methods=['POST'])
def get_recent_visitor_list():
    print("Received a request to /get-recent-visitor-list")
    data = request.json 
    requester = users_collection.find_one({"token": data})
    if requester:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if requester['role']=="admin":
            #fetch visitor list of todays date and status is pending or meet
            visitorList=db["visitor"].find({"entryDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["pending", "meet"]}},{"_id":0}).sort("entryDate", -1)
            
        elif requester['role']=="principal" or requester['role']=="reception" or requester['role']=="security guard":
            visitorList=db["visitor"].find({"campus": requester['campus'],"entryDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["pending", "meet"]}},{"_id":0}).sort("entryDate", -1)
            
        elif requester['role']=="hod":
            visitorList=db["visitor"].find({"campus": requester['campus'], "meetDepartment": requester['department'], "entryDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["pending", "meet"]}},{"_id":0}).sort("entryDate", -1)
            
        elif requester['role']=="faculty":
            visitorList=db["visitor"].find({"campus": requester['campus'],"meetEmail": requester['email'], "entryDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["pending", "meet"]}},{"_id":0}).sort("entryDate", -1)
            
        else:
            return jsonify({"message": "Role not authorized"}), 400
        #convert datetime to string in visitor list before sending response
        visitorList=list(visitorList)
        for visitor in visitorList:
            if isinstance(visitor['entryDate'], datetime):
                # Assuming entryDate is naive UTC from MongoDB
                utc_dt = visitor['entryDate'].replace(tzinfo=timezone.utc)
                kolkata_dt = utc_dt.astimezone(ZoneInfo("Asia/Kolkata"))
                visitor['entryDate'] = kolkata_dt.strftime('%Y-%m-%d %H:%M:%S')  
        return jsonify(visitorList), 200
    else:
        return jsonify({"message": "User not found"}), 404
        

#to meet visitor by current user no basis of user role and visitor status
@app.route('/meet-visitor', methods=['POST'])
def meet_visitor():
    print("Received a request to /meet-visitor")
    data = request.json 
    requester = users_collection.find_one({"token": data['token']})
    if requester:
        today=datetime.now(ZoneInfo("Asia/Kolkata"))
        #check the entry date, if todays date and entry date is same then continue
        #also we have to get meetEmail,status and remark if exist for this visitor
        visitor=db["visitor"].find_one({"visitorId":int(data["visitorId"]),"entryDate":{"$gte": datetime.combine(today.date(), datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today.date(), datetime.max.time(), ZoneInfo("Asia/Kolkata"))},"status": {"$in": ["pending", "meet"]}},{"meetEmail":1,"status":1,"_id":0,"remark":1})
        
        if not visitor:
            return jsonify({"message": "Visitor not found"}), 404
        
        if requester['role']=="admin":
            db["visitor"].update_one({"visitorId":int(data["visitorId"])},{"$set":{"status":"meet",}})
            return jsonify({"message": "Visitor entry recorded successfully!"}), 200
        
        if requester['role']=="principal" or requester['role']=="reception" or requester['role']=="hod" or requester['role']=="faculty":

            #these users can only meet visitor if visitor status is pending 
            if visitor['status']!="pending":
                return jsonify({"message": "Visitor is not available for meeting"}), 400
            
            #if the requester email==meetEmail of visitor,then status will be updated to meet and also append meet time in remark attribute if this attribute is already present otherwise create remark attribute and set meet time in it
            remark=f"Visitor met with {requester['name']} at {today.strftime('%H:%M:%S')}"

            if visitor['meetEmail']!=requester['email']:
                #check remark exist or not
                if "remark" not in data:
                    return jsonify({"message": "Remark is required"}), 400
                #also append data["remark"]
                remark=remark+"\n with remark:"+data["remark"]
            if 'remark' in visitor:
                remark=visitor['remark']+"\n \n"+remark
            db["visitor"].update_one({"visitorId":int(data["visitorId"])},{"$set":{"status":"meet","remark":remark,"lastUpdatedBy": requester['email']}})
            return jsonify({"message": "Visitor entry recorded successfully!"}), 200
        
        elif requester['role']=="security guard":
            #firstly we have check that this security guard is allotted for this campus or not by checking allotment collection, if security guard is allotted for this campus then only we will check visitor details otherwise we will return not authorized message
            allotted=db["allotment"].find_one({"campus": requester['campus']},{"_id":0,"security":1})
            if not (allotted and requester['email'] in allotted["security"]):
                return jsonify({"message": "You are not authorized to exit this visitor"}), 400
            #if the requester is security guard then requester mark status as exit when status is pending and meet
            remark=f"Visitor exited by {requester['name']} at {today.strftime('%H:%M:%S')}"
            if visitor['status']=="pending":
                #check remark exist or not
                if "remark" not in data:
                    return jsonify({"message": "Remark is required for exiting visitor with pending status"}), 400
                remark=remark+"\n with remark:"+data["remark"]
            if 'remark' in visitor:
                remark=visitor['remark']+"\n \n"+remark
            
            db["visitor"].update_one({"visitorId":int(data["visitorId"])},{"$set":{"status":"exit","remark":remark,"lastUpdatedBy": requester['email']}})
            return jsonify({"message": "Visitor exit recorded successfully!"}), 200
    
    return jsonify({"message": "User not found"}), 404
            
#to edit visitor details here data comes that are changed
@app.route('/edit-visitor', methods=['POST'])
def edit_visitor():
    print("Received a request to /edit-visitor")
    #here using multipart form data received with img file,visitor hash with visitorId and token 
    #visitor hash will be in json format but in string format so we will convert it into json object
    visitorString = request.form.get('visitor')
    try:
        visitor = json.loads(visitorString)
    except json.JSONDecodeError:
        return jsonify({"message": "Invalid visitor data format"}), 400
    requester = users_collection.find_one({"token":visitor['token']})
    
    if requester:
            
        #fetch visitor details based on visitorId
        existingVisitor=db["visitor"].find_one({"visitorId":int(visitor['visitorId']),"status":"pending"},{"_id":0})
        if not existingVisitor or existingVisitor['entryDate'].date()!=datetime.now().date():
            return jsonify({"message": "Visitor is not available for editing"}), 400
        
        #if requester is security guard then check the authenticity
        if requester['role']=="security guard":
            allotted=db["allotment"].find_one({"campus": requester['campus']},{"_id":0,"security":1})
            if not (allotted and requester['email'] in allotted["security"]):
                return jsonify({"message": "You are not authorized to edit this visitor"}), 400
            
        elif requester['role']=="hod":
            if existingVisitor['meetDepartment']!=requester['department']:
                return jsonify({"message": "You are not authorized to edit this visitor"}), 400
        elif requester['role']=="faculty":
            if existingVisitor['meetEmail']!=requester['email']:
                return jsonify({"message": "You are not authorized to edit this visitor"}), 400
        elif requester['role']=="student":
            return jsonify({"message": "You are not authorized to edit this visitor"}), 400
        
        #now the requester is authenticated
        #in requester.file there will be null or there will be img file if requester want to change the image of visitor, if there is img file then we will update the image of visitor otherwise we will update other details of visitor except image
        if 'img' in request.files:
            img=request.files['img']
            imageURL=upload_image_to_cloudinary(existingVisitor['img'],img)
            if not imageURL:
                return jsonify({"message": "Image upload failed"}), 500
        
        #update visitor details in visitor collection based on visitorId except img because we have already updated img separately
        visitor.pop('token', None)
        visitorId=visitor['visitorId']
        visitor.pop('visitorId', None)

        #also add changes in remark attribute
        remark=f"Visitor details edited by {requester['name']} at {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"
        if 'remark' in existingVisitor:
            remark=existingVisitor['remark']+"\n \n"+remark
        visitor['remark']=remark
        visitor['lastUpdatedBy']=requester['email']

        db["visitor"].update_one({"visitorId": int(visitorId)}, {"$set": visitor})
        return jsonify({"message": "Visitor details updated successfully!"}), 200
    
    return jsonify({"message": "User not found"}), 404
            
            
#now we have to implement live syncing part here 
# we will use flask socketio for live syncing and we will emit event from server to client whenever there is any change in visitor collection like new visitor entry, visitor meet, visitor exit and visitor edit, 
# so that client can listen to these events and update the visitor list in real time without refreshing the page

socket=SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

watcher_started = False

@socket.on("connect")
def connect():
    global watcher_started
    print("user connected")
    if not watcher_started:
        print("Starting background database watchers...")
        socket.start_background_task(lambda: start_watcher(watch_visitor_collection))
        socket.start_background_task(lambda: start_watcher(watchGatePassCollection))
        watcher_started = True

#to joinRoom by using users token
@socket.on("joinRoom")
def joinRoom(data):
    print("Received a request to join room")
    currentUser= users_collection.find_one({"token": data})
    if currentUser:
        if currentUser['role']=="admin":
            join_room("adminroom")
        elif currentUser['role']=="security guard" or currentUser['role']=="reception":
            room=currentUser['campus']+currentUser['role'].replace(" ", "")+"room"
            join_room(room)
        elif currentUser['role']=="principal":
            room=currentUser['campus']+"principalroom"
            join_room(room)
        elif currentUser['role']=="hod":
            room=currentUser['campus']+currentUser['department']+"hodroom"
            join_room(room)
            #also hod will join with emailroom for the gatePass
            join_room(currentUser['email']+"room")
        elif currentUser["role"]=="faculty" or currentUser["role"]=="student":
            room=currentUser["email"]+"room"
            join_room(room)
    else:
        print("User not found for joining room")


def watch_visitor_collection():
    #we have to fetch minimal visitor data
    #also fetch operationType
    #we have also get updated field in case of update operation
    pipeline=[
        {"$match": {"operationType": {"$in": ["insert", "update"]}}},

        {"$project": {"operationType": 1, "fullDocument.visitorId": 1, "fullDocument.status": 1, "fullDocument.campus": 1, "fullDocument.meetDepartment": 1, "fullDocument.meetEmail": 1,"fullDocument.img":1,"fullDocument.name":1,"fullDocument.lastUpdatedBy": 1, "updateDescription": 1}}
        
    ]

    try:
        print("Creating watch stream on visitor collection...")
        with db["visitor"].watch(pipeline, full_document='updateLookup') as stream:
            for change in stream:
                try:
                    
                    operation = change.get('operationType')
                    full_doc = change.get('fullDocument', {})
                    updatedFields = change.get('updateDescription', {}).get('updatedFields', {})
                    
                    if not full_doc:
                        print(" No fullDocument found, skipping...")
                        continue
                    
                    visitorId = str(full_doc.get('visitorId'))
                    status = full_doc.get('status')
                    campus = full_doc.get('campus')
                    department = full_doc.get('meetDepartment')  
                    meetEmail = full_doc.get('meetEmail')
                    

                    if operation == "update":
                        if "status" in updatedFields:
                            operation=status

                        
                        socket.emit("visitorUpdate", {"operation": operation, "visitorId": visitorId}, room="adminroom")
                        socket.emit("visitorUpdate", {"operation": operation, "visitorId": visitorId}, room=campus+"securityguardroom")
                        socket.emit("visitorUpdate", {"operation": operation, "visitorId": visitorId}, room=campus+"receptionroom")
                        socket.emit("visitorUpdate", {"operation": operation, "visitorId": visitorId}, room=campus+"principalroom")
                        socket.emit("visitorUpdate", {"operation": operation, "visitorId": visitorId}, room=campus+department+"hodroom")
                        socket.emit("visitorUpdate", {"operation": operation, "visitorId": visitorId}, room=meetEmail+"room")
                        print(f"Emitted visitor Update")

                        #check there is any upadted field like meetEmail and status
                        operationType=""
                        if "meetEmail" in updatedFields:
                            operationType="meetEmailUpdate"
                        elif "status" in updatedFields:
                            operationType="statusUpdate"

                        if operationType!="":
                            dataExtractingBeforeSendingNotificationForVisitor(status=status,operationType=operationType,lastUpdatedBy=full_doc.get("lastUpdatedBy"),meetEmail=meetEmail,campus=campus,department=department,notificationData={"visitorId": visitorId,"img":full_doc.get("img"),"name":full_doc.get("name")})
                        
                    
                    elif operation == "insert":
                        if campus and department and meetEmail:
                            socket.emit("visitorInsert", {"visitorId": visitorId}, room="adminroom")
                            socket.emit("visitorInsert", {"visitorId": visitorId}, room=campus+"securityguardroom")
                            socket.emit("visitorInsert", {"visitorId": visitorId}, room=campus+"receptionroom")
                            socket.emit("visitorInsert", {"visitorId": visitorId}, room=campus+"principalroom")
                            socket.emit("visitorInsert", {"visitorId": visitorId}, room=campus+department+"hodroom")
                            socket.emit("visitorInsert", {"visitorId": visitorId}, room=meetEmail+"room")
                            print("Emitted visitor Insert")

                            dataExtractingBeforeSendingNotificationForVisitor(status=status,operationType="insert",lastUpdatedBy=full_doc.get("lastUpdatedBy"),meetEmail=meetEmail,campus=campus,department=department,notificationData={"visitorId": visitorId,"img":full_doc.get("img"),"name":full_doc.get("name")})
                        else:
                            print("Cannot emit: missing campus, department, or meetEmail")
                except Exception as e:
                    print(f"Error processing change: {e}")
                    import traceback
                    traceback.print_exc()
    except OperationFailure as e:
        print(f"OperationFailure in watch stream: {e}")
        return
    except Exception as e:
        print(f"Unexpected error in watch_visitor_collection: {e}")
        import traceback
        traceback.print_exc()
        return


#to get recent updated visitor
@app.route('/get-recent-updated-visitor', methods=['POST'])
def get_recent_updated_visitor():
    print("Received a request to /get-recent-updated-visitor")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if requester['role']!="student":
            updatedVisitor=db["visitor"].find_one({"visitorId":int(data["visitorId"]), "entryDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["pending", "meet"]}},{"_id":0})
            if updatedVisitor:
                utc=updatedVisitor['entryDate'].replace(tzinfo=timezone.utc)
                updatedVisitor['entryDate']=utc.astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')
                return jsonify(updatedVisitor), 200
            
    return jsonify({"message": "User not found"}), 404



#to store fcm token of user
@app.route('/store-fcm-token', methods=['POST'])
def store_fcm_token():
    print("store fcm token calling")
    data=request.json
    users_collection.update_one({"token":data["token"]},{"$set":{"fcmToken":data["fcmToken"]}})
    return jsonify({"message": "FCM token stored successfully!"}), 200

#to logout user we will remove fcm token from database
@app.route('/logout', methods=['POST'])
def logout():
    print("logout calling")
    data=request.json
    if users_collection.find_one({"token": data}):
        users_collection.update_one({"token": data},{"$unset":{"fcmToken":""}})
        return jsonify({"message": "Logged out successfully!"}), 200
    return jsonify({"message": "User not found"}), 404
            


#we will extract data for sending notificattion to meetEmail,reception,security guard with insertion of proper description in notificationData 
#also we will skip lastupdatedBy user to send notification because this user is already aware about the change
def dataExtractingBeforeSendingNotificationForVisitor(status,operationType,lastUpdatedBy,meetEmail,campus,department,notificationData):
    
    #first we have to send notification to meetEmail
    if meetEmail!=lastUpdatedBy:
        
        if operationType=="statusUpdate":
            #then we have to notifiy meetEmail that the visitor has met by other user instead of you
            #now we have to set a formal description in notificationData based on status
            if status=="meet":
                notificationData["title"]="Visitor met"
                notificationData["body"]=f"Visitor has been marked as met by other user instead of you"
            elif status=="exit":
                notificationData["title"]="Visitor exited"
                notificationData["body"]=f"Visitor has been exited by security guard"
            sendNotification(meetEmail,notificationData)
        else:
            #then we have to notify meetEmail that there is new visitor entry for you
            notificationData["title"]="New Visitor Entry"
            notificationData["body"]=f"There is new visitor entry for you, please check the details"
            sendNotification(meetEmail,notificationData)

    #then we have to send notifiction to reception of this campus
    receptions=db["users"].find({"role":"reception","campus":campus},{"_id":0,"email":1})
    for reception in receptions:
        if reception["email"]!=lastUpdatedBy:
            
            notificationData["title"]="Visitor Update"
            #the description will be based on operation type and status
            if operationType=="insert":
                notificationData["body"]=f"There is new visitor entry in your campus, please check the details"
            elif operationType=="statusUpdate":
                notificationData["body"]=f"Visitor status has been updated to {status}"
            else:
                notificationData["body"]=f"Visitor details has been updated"
            sendNotification(reception["email"],notificationData)

    #then we have to send notification to security guard that are allotted for this campus
    securityGuards=db["allotment"].find_one({"campus": campus},{"_id":0,"security":1})
    if securityGuards:
        securityGuards=securityGuards["security"]
        for guardEmail in securityGuards:
            if guardEmail!=lastUpdatedBy:
                
                notificationData["title"]="Visitor Update"
                #the description will be based on operation type and status
                if operationType=="insert":
                    notificationData["body"]=f"There is new visitor entry in your campus, please check the details"
                elif operationType=="statusUpdate":
                    notificationData["body"]=f"Visitor status has been updated to {status}"
                else:
                    notificationData["body"]=f"Visitor details has been updated"
                sendNotification(guardEmail,notificationData)
        




#implementation of sending notification to user
def sendNotification(email,notificationData):
    user=users_collection.find_one({"email":email},{"_id":0,"fcmToken":1})
    if user and "fcmToken" in user:
        fcmToken=user["fcmToken"]
        """message = messaging.Message(
            notification=messaging.Notification(
                title="Test Notification",
                body="This is a test notification from Digital Pass",
            ),
            token=fcmToken,
        )"""
        message=messaging.Message(token=fcmToken,data=notificationData)
        
        try:
            response = messaging.send(message)
            print("Successfully sent message:", response)
        except Exception as e:
            print("Error sending message:", e)
    else:
        print("User not found or FCM token missing")


#to apply for gate pass
@app.route('/apply-for-gate-pass', methods=['POST'])
def apply_for_gate_pass():
    print("Received a request to /apply-for-gate-pass")

    data = request.json 
    if data["reason"]=="" or data["reason"]==None:
        return jsonify({"message": "Reason for gate pass is required"}), 400
    
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        #check this user have batch or not
        if "batch" not in requester or requester["batch"]=="":
            return jsonify({"message": "Batch is not found"}), 404


        #here we have to check if this user is student then it must contain uid,fathername,fatherphone
        if requester["role"]=="student":
            if "uid" not in requester:
                return jsonify({"message": "UID is required for student"}), 400
            if "fathername" not in requester:
                return jsonify({"message": "Father name is required for student"}), 400
            if "fatherphone" not in requester:
                return jsonify({"message": "Father phone number is required for student"}), 400

        today=datetime.now().date()
        #check last gate pass date and also check that date if is none
        if "lastGatePassDate" in requester:
            if requester["lastGatePassDate"].date() == today:
                return jsonify({"message": "You have already applied for gate pass today"}), 400
        
        #fetching levels for users batch
        levels=db["leveledBatches"].find_one({"batchName": requester['batch']},{"_id":0,"level1":1,"level2":1})
        
        if not levels:
            return jsonify({"message":" Batch levels not found, please contact administration"}), 404
        
        #get gate pass id from gatePassID collection and increase it by one
        gatePassID=db["gatePassID"].find_one_and_update({}, {"$inc": {"id": 1}},{'id':1,"_id":0})['id']
        #also we are inserting lastUpdatedBy attribute so that we will not send notification to the same user
        gatePass={
            "applyEmail": requester["email"],
            "applyDate": datetime.now(ZoneInfo("Asia/Kolkata")),
            "reason": data["reason"],
            "status": "pending",
            "gatePassId": gatePassID,
            "level1": levels["level1"],
            "level2": levels["level2"],
            "campus": requester["campus"],
            "department": requester["department"],
            "remark":"",
            "lastUpdatedBy": requester["email"]
        }

        db["gatePass"].insert_one(gatePass)
        #update last gate pass date in users collection for this user
        users_collection.update_one({"email": requester["email"]}, {"$set": {"lastGatePassDate": datetime.now(ZoneInfo("Asia/Kolkata"))}})
        #create gate pass data to send to the user
        gatePass.pop("_id", None)
        gatePass.pop("level1",None)
        gatePass.pop("level2",None)
        gatePass.pop("applyEmail",None)
        gatePass.pop("campus",None)
        gatePass.pop("department",None)
        gatePass["applyDate"]=gatePass["applyDate"].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify(gatePass), 200
    else:
        return jsonify({"message":"User not found"}),404
    

#to get recent self user gate pass based on token
@app.route('/get-self-user-gate-pass', methods=['POST'])
def get_recent_self_user_gate_pass():
    print("Received a request to /get-recent-self-user-gate-pass")
    data = request.json 
    requester = users_collection.find_one({"token": data})

    if requester:
        #fetch all gate pass of this user based on email and also sort it by applyDate in descending order
        gatePasses=db["gatePass"].find({"applyEmail": requester["email"]},{"applyEmail":0,"level1":0,"level2":0,"campus":0,"department":0,"_id":0}).sort("applyDate", -1)
        gatePassList=[]
        for gatePass in gatePasses:
            #convert datetime utc then convert it to kolkata timezone and then convert it to string
            utcTime=gatePass["applyDate"].replace(tzinfo=timezone.utc)
            gatePass["applyDate"]=utcTime.astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')
            gatePassList.append(gatePass)
        return jsonify(gatePassList), 200
    else:
        return jsonify({"message":"User not found"}),404


#to remove gate pass by self user
@app.route('/remove-gate-pass-by-self-user', methods=['POST'])
def remove_gate_pass_by_self_user():
    print("Received a request to /remove-gate-pass-by-self-user")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        #fetch gate pass details based on gatePassId
        gatePass=db["gatePass"].find_one({"gatePassId": int(data["gatePassId"]), "applyEmail": requester["email"]})
        if not gatePass:
            return jsonify({"message": "Gate pass not found"}), 404
        if gatePass["status"]!="pending" or gatePass["applyDate"].date()!=datetime.now().date():
            return jsonify({"message": "You can not remove this gate pass"}), 400
        db["gatePass"].delete_one({"gatePassId": int(data["gatePassId"])})

        #also unset lastGatePassDate in users collection for this user because user can apply for gate pass again after removing gate pass
        users_collection.update_one({"email": requester["email"]}, {"$unset": {"lastGatePassDate": ""}})
        return jsonify({"message": "Gate pass removed successfully!"}), 200
    else:
        return jsonify({"message":"User not found"}),404


#to edit gate pass by self user when gate pass status is pending, here we have to edit only gate pass reason
@app.route('/edit-gate-pass-by-self-user', methods=['POST'])
def edit_gate_pass_by_self_user():
    print("Received a request to /edit-gate-pass-by-self-user")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        #fetch gate pass details based on gatePassId
        gatePass=db["gatePass"].find_one({"gatePassId": int(data["gatePassId"]), "applyEmail": requester["email"]})
        if not gatePass:
            return jsonify({"message": "Gate pass not found"}), 404
        if gatePass["status"]!="pending" or gatePass["applyDate"].date()!=datetime.now().date():
            return jsonify({"message": "You can not edit this gate pass"}), 400
        db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": {"reason": data["reason"],"lastUpdatedBy": requester["email"]}})
        return jsonify({"message": "Gate pass reason updated successfully!"}), 200
    else:
        return jsonify({"message":"User not found"}),404


#to get recent gate pass list on the basis of user role and if that user email in level1 or level2 of gate pass then only show that gate pass to user otherwise not show that gate pass to user
@app.route('/get-recent-gate-pass-list', methods=['POST'])
def get_recent_gate_pass_list():
    print("Received a request to /get-recent-gate-pass-list")
    data = request.json 
    requester = users_collection.find_one({"token": data})
    
    if requester:
        today=datetime.now().date()
        #also get gate pass list when status is not exit or not reject
        if requester['role']=="admin":
            gatePassList=db["gatePass"].find({"status": {"$nin": ["exit", "rejected"]}, "applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
        elif requester["role"]=="principal":
            gatePassList=db["gatePass"].find({"campus": requester["campus"], "status": {"$nin": ["exit", "rejected"]}, "applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
        elif requester["role"]=="security guard":
            #we have to get all recent gate pass of there campus when the status is approved
            gatePassList=db["gatePass"].find({"campus": requester["campus"], "status": "approved", "applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
        else:
            #we have to get all recent gate pass, if users email in level1 or level2 array of gate pass
            gatePassList=db["gatePass"].find({"$or":[{"level1": requester["email"]},{"level2": requester["email"]}], "status": {"$nin": ["exit", "rejected"]}, "applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lt": datetime.combine(today, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)

        gatePassList=list(gatePassList)
        if not gatePassList:
            return jsonify([]), 200
        
        #now we have a list of gate pass and here we have also add some data like img,name,role and phone of user by fetching user data by applyEmail
        for gatePass in gatePassList:
            #we have also fetch data like uid,batch,fathername and fatherphone for student
            user=users_collection.find_one({"email": gatePass["applyEmail"]},{"_id":0,"name":1,"img":1,"role":1,"phone":1,"batch":1,"fathername":1,"fatherphone":1,"uid":1})
            if user:
                gatePass["name"]=user["name"]
                gatePass["img"]=user["img"]
                gatePass["role"]=user["role"]
                gatePass["phone"]=user["phone"]

                if user["role"]=="student":
                    gatePass["batch"]=user["batch"]
                    gatePass["fathername"]=user["fathername"]
                    gatePass["fatherphone"]=user["fatherphone"]
                    gatePass["uid"]=user["uid"]

            gatePass["applyDate"]=gatePass["applyDate"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')
        
        
        return jsonify(gatePassList), 200
    else:
        return jsonify({"message":"User not found"}),404


#to reject gate pass by admin,principal,level1 and level2 approver
@app.route('/reject-gate-pass', methods=['POST'])
def reject_gate_pass():
    print("Received a request to /reject-gate-pass")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        gatePass=db["gatePass"].find_one({"gatePassId": int(data["gatePassId"]), "status": {"$in":["pending","approving"]}})
        if not gatePass or gatePass["applyDate"].date()!=datetime.now().date():
            return jsonify({"message":"Gate pass is not available for rejecting"}), 404
        
        if requester["role"]=="admin" or requester["role"]=="principal" or requester["email"] in gatePass["level1"] or requester["email"] in gatePass["level2"]:
            remark=f"Gate pass rejected by {requester['name']} at {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"

            remark=gatePass["remark"]+"\n \n"+remark
            db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": {"status": "rejected","remark": remark,"lastUpdatedBy": requester["email"]}})
            return jsonify({"message": "Gate pass rejected successfully!"}), 200
        else:
            return jsonify({"message": "You are not authorized to reject this gate pass"}), 403
    else:     
        return jsonify({"message":"User not found"}),404
    

#to approve gate pass by admin,principal,level1 and level2 approver
#here only admin,pricipal and level2 approver can mark status as approved and level1 approver can only mark status as approving 
#security guard can also mark status as exit when gate pass status is approved
@app.route('/approve-gate-pass', methods=['POST'])
def approve_gate_pass():
    print("Received a request to /approve-gate-pass")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        gatePass=db["gatePass"].find_one({"gatePassId": int(data["gatePassId"]), "status": {"$in":["pending","approving","approved"]}})
        if not gatePass or gatePass["applyDate"].date()!=datetime.now().date():
            return jsonify({"message":"Gate pass is not available for approving"}), 404
        
        #we have to check for tgRemark
        if "tgRemark" not in gatePass and "tgRemark" not in data:
            return jsonify({"message": "TG remark is required for approving this gate pass"}), 400
        
        if requester["role"]=="admin" or requester["role"]=="principal" or requester["email"] in gatePass["level2"]:
            if gatePass["status"]!="pending" and gatePass["status"]!="approving":
                return jsonify({"message": "Gate pass is not available for approving"}), 400
            remark=f"Gate pass approved by {requester['name']} at {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"
            remark=gatePass["remark"]+"\n \n"+remark
            if "tgRemark" in data:
                remark=remark+"\n with TG remark"
                db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": {"tgRemark": data["tgRemark"],"status": "approved","remark": remark,"lastUpdatedBy": requester["email"]}})
            else:
                db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": {"status": "approved","remark": remark,"lastUpdatedBy": requester["email"]}})
            return jsonify({"message": "Gate pass approved successfully!"}), 200
        
        elif requester["email"] in gatePass["level1"]:
            if gatePass["status"]!="pending":
                return jsonify({"message": "Gate pass is not available for approving"}), 400
            remark=f"Gate pass marked as approving by {requester['name']} at {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"
            remark=gatePass["remark"]+"\n \n"+remark
            
            remark=remark+"\n with TG remark"
            db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": {"tgRemark": data["tgRemark"],"status": "approving","remark": remark,"lastUpdatedBy": requester["email"]}})
            
            return jsonify({"message": "Gate pass marked as approving successfully!"}), 200
        
        elif requester["role"]=="security guard":
            if gatePass["status"]!="approved":
                return jsonify({"message": "Gate pass is not available for exit marking"}), 400
            
            #check the allotement of security guard for this campus
            allotted=db["allotment"].find_one({"campus": requester['campus']},{"_id":0,"security":1})
            if not (allotted and requester['email'] in allotted["security"]):
                return jsonify({"message": "You are not authorized to mark exit for this gate pass"}), 403
            remark=f"Gate pass exit marked by {requester['name']} at {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"
            remark=gatePass["remark"]+"\n \n"+remark

            db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": {"status": "exit","remark": remark,"lastUpdatedBy": requester["email"]}})
            return jsonify({"message": "Gate pass exit marked successfully!"}), 200
        
    return jsonify({"message":"User not found"}),404
            
            
#to edit gate pass reason or tgRemark by approver when gate pass status is pending or approving
@app.route('/edit-gate-pass', methods=['POST'])
def edit_gate_pass():
    print("Received a request to /edit-gate-pass")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        gatePass=db["gatePass"].find_one({"gatePassId": int(data["gatePassId"]), "status": {"$in":["pending","approving"]}})
        if not gatePass or gatePass["applyDate"].date()!=datetime.now().date():
            return jsonify({"message":"Gate pass is not available for editing"}), 404
        
        if requester["role"]=="admin" or requester["role"]=="principal" or requester["email"] in gatePass["level1"] or requester["email"] in gatePass["level2"]:
            updateData={}
            remark=f"Gate pass edited by {requester['name']} at {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"
            remark=gatePass["remark"]+"\n \n"+remark
            updateData["lastUpdatedBy"]=requester["email"]
            if "reason" in data:
                updateData["reason"]=data["reason"]
                remark=remark+"\n with reason change"
            if "tgRemark" in data:
                updateData["tgRemark"]=data["tgRemark"]
                remark=remark+"\n with TG remark"
            updateData["remark"]=remark
            db["gatePass"].update_one({"gatePassId": int(data["gatePassId"])}, {"$set": updateData})
            return jsonify({"message": "Gate pass updated successfully!"}), 200


#now we have to implement live syncing part for gatePass collection
def watchGatePassCollection():
    pipeline=[
        {"$match": {"operationType": {"$in": ["update","insert"]}}},
        {"$project":{"operationType":1,"fullDocument.gatePassId":1,"fullDocument.status":1,"fullDocument.applyEmail":1,"fullDocument.campus":1,"fullDocument.lastUpdatedBy":1,"fullDocument.level1":1,"fullDocument.level2":1,"updateDescription":1}}
    ]
    with db["gatePass"].watch(pipeline, full_document='updateLookup')as stream:
        for change in stream:
            try:
                print("Change detected in gatePass collection")
                operation=change.get("operationType")
                full_doc=change.get("fullDocument",{})
                updatedFields=change.get("updateDescription",{}).get("updatedFields",{})
                if not full_doc:
                    print("No fullDocument found, skipping...")
                    continue
                gatePassId=str(full_doc.get("gatePassId"))
                status=full_doc.get("status")
                campus=full_doc.get("campus")
                level1=full_doc.get("level1",[])
                level2=full_doc.get("level2",[])

                #img for apply user
                img="profile_images/"+full_doc.get("applyEmail")

                #for insert operation 
                if operation=="insert":
                    socket.emit("gatePassInsert",{"gatePassId": gatePassId},room="adminroom")
                    socket.emit("gatePassInsert",{"gatePassId": gatePassId},room=campus+"principalroom")
                    for level1Email in level1:
                        socket.emit("gatePassInsert",{"gatePassId": gatePassId},room=level1Email+"room")
                    for level2Email in level2:
                        socket.emit("gatePassInsert",{"gatePassId": gatePassId},room=level2Email+"room")
                    
                    #send the notification to level1 approver
                    applyUserName=users_collection.find_one({"email": full_doc.get("applyEmail")},{"_id":0,"name":1})["name"]   
                    for level1Email in level1:
                        notificationData={
                            "title":"New Gate Pass Application",
                            "body":f"There is new gate pass application with gate pass id {gatePassId} for you, please check the details",
                            "gatePassId": gatePassId,
                            "img": img,
                            "name": applyUserName
                        }
                        sendNotification(level1Email, notificationData)

                else:
                    #we have to check there is any updated field like status
                    if "status" not in updatedFields:
                        #the update field can be reason and tgRemark we have to send this data in real time update
                        updatedGatePassData={"gatePassId": gatePassId}
                        if "reason" in updatedFields:
                            updatedGatePassData["reason"]=updatedFields["reason"]
                        if "tgRemark" in updatedFields:
                            updatedGatePassData["tgRemark"]=updatedFields["tgRemark"]

                        
                        socket.emit("gatePassUpdate", updatedGatePassData, room="adminroom")
                        socket.emit("gatePassUpdate", updatedGatePassData, room=campus+"principalroom")
                        for level1Email in level1:
                            socket.emit("gatePassUpdate", updatedGatePassData, room=level1Email+"room")
                        for level2Email in level2:
                            socket.emit("gatePassUpdate", updatedGatePassData, room=level2Email+"room")
                    else:
                        #when the status is updated then only we have to send current status and gatePassId
                        socket.emit("gatePassStatusUpdate", {"gatePassId": gatePassId, "status": status}, room="adminroom")
                        socket.emit("gatePassStatusUpdate", {"gatePassId": gatePassId, "status": status}, room=campus+"principalroom")
                        for level1Email in level1:
                            socket.emit("gatePassStatusUpdate", {"gatePassId": gatePassId, "status": status}, room=level1Email+"room")
                        for level2Email in level2:
                            socket.emit("gatePassStatusUpdate", {"gatePassId": gatePassId, "status": status}, room=level2Email+"room")
                        
                        #if status is updated to approved then we have sync it to security guard
                        if status=="approved":
                            #then we will emit socket with gatePass inserted
                            socket.emit("gatePassInsert",{"gatePassId": gatePassId},room=campus+"securityguardroom")
                        elif status=="exit":
                            #then we will emit socket with gatePass status update to exit
                            socket.emit("gatePassStatusUpdate", {"gatePassId": gatePassId, "status": status}, room=campus+"securityguardroom")


                        #if status is updated then we will perform some operation based on status like approving,approved,exit and rejected,here we will send notification to the user like applyEmail,level1,level2 approver also we send notifiction to allotted security guard for this campus
                        allotted=db["allotment"].find_one({"campus": campus},{"_id":0,"security":1})

                        applyUserName=users_collection.find_one({"email": full_doc.get("applyEmail")},{"_id":0,"name":1})["name"]

                        if status=="approving":
                            #we have to send notification applyEmail,level1 and level2 user
                            #for applyEmail
                            sendNotification(full_doc.get("applyEmail"), {
                                "title": "Gate Pass Marked as Approving",
                                "body": f"Your gate pass application with gate pass id {gatePassId} has been marked as approving by {full_doc.get('lastUpdatedBy')}, please wait for final approval",
                                "gatePassId": gatePassId,
                                "img": img,
                                "name": applyUserName
                            })
                            #for level1 approver
                            for level1Email in level1:
                                if level1Email!=full_doc.get("lastUpdatedBy"):
                                    sendNotification(level1Email, {
                                        "title": "Gate Pass Marked as Approving",
                                        "body": f"Gate pass application with gate pass id {gatePassId} has been marked as approving by {full_doc.get('lastUpdatedBy')}",
                                        "gatePassId": gatePassId,
                                        "img": img,
                                        "name": applyUserName
                                    })

                            #for level2 approver
                            for level2Email in level2:
                                sendNotification(level2Email, {
                                    "title": "Gate Pass Marked as Approving",
                                    "body": f"Gate pass application with gate pass id {gatePassId} has been marked as approving by {full_doc.get('lastUpdatedBy')}, please mark approved for final approval",
                                    "gatePassId": gatePassId,
                                    "img": img,
                                    "name": applyUserName
                                })

                        elif status=="approved":
                            #we have to send notification to applyEmail,level1 and level2 approver and also security guard of this campus
                            #for applyEmail
                            sendNotification(full_doc.get("applyEmail"), {
                                "title": "Gate Pass Approved",
                                "body": f"Your gate pass application with gate pass id {gatePassId} has been approved, please check the details",
                                "gatePassId": gatePassId,
                                "img": img,
                                "name": applyUserName
                            })
                            #for level1 approver
                            for level1Email in level1:
                                if level1Email!=full_doc.get("lastUpdatedBy"):
                                    sendNotification(level1Email, {
                                        "title": "Gate Pass Approved",
                                        "body": f"Gate pass application with gate pass id {gatePassId} has been approved by {full_doc.get('lastUpdatedBy')}",
                                        "gatePassId": gatePassId,
                                        "img": img,
                                        "name": applyUserName
                                    })

                            #for level2 approver
                            for level2Email in level2:
                                if level2Email!=full_doc.get("lastUpdatedBy"):
                                    sendNotification(level2Email, {
                                        "title": "Gate Pass Approved",
                                        "body": f"Gate pass application with gate pass id {gatePassId} has been approved by {full_doc.get('lastUpdatedBy')}",
                                        "gatePassId": gatePassId,
                                        "img": img,
                                        "name": applyUserName
                                    })
                            
                            #for security guard
                            if allotted and "security" in allotted:
                                for guardEmail in allotted["security"]:
                                    sendNotification(guardEmail, {
                                        "title": "Gate Pass Approved",
                                        "body": f"Gate pass application with gate pass id {gatePassId} has been approved for your campus, please check the details and prepare for gate pass exit marking",
                                        "gatePassId": gatePassId,
                                        "img": img,
                                        "name": applyUserName
                                    })
                                        
                        elif status=="exit":
                            #for applyEmail
                            sendNotification(full_doc.get("applyEmail"), {
                                "title": "You are exited successfully",
                                "body": f"Your gate pass application with gate pass id {gatePassId} has been marked as exit by security guard, please check the details",
                                "gatePassId": gatePassId,
                                "img": img,
                                "name": applyUserName
                            })
                            #for level1 approver
                            for level1Email in level1:
                                sendNotification(level1Email,{"title":"Gate Pass Exit Marked","body": f"Gate pass application with gate pass id {gatePassId} has been marked as exit by security guard","gatePassId": gatePassId,"img": img,"name": applyUserName})
                            #for level2 approver
                            for level2Email in level2:
                                sendNotification(level2Email,{"title":"Gate Pass Exit Marked","body": f"Gate pass application with gate pass id {gatePassId} has been marked as exit by security guard","gatePassId": gatePassId,"img": img,"name": applyUserName})
                            
                            #for other security also
                            if allotted and "security" in allotted:
                                for guardEmail in allotted["security"]:
                                    if guardEmail!=full_doc.get("lastUpdatedBy"):
                                        sendNotification(guardEmail,{"title":"Gate Pass Exit Marked","body": f"Gate pass application with gate pass id {gatePassId} has been marked as exit by security guard","gatePassId": gatePassId,"img": img,"name": applyUserName})

                        elif status=="rejected":
                            #we have to notify only applyEmail
                            sendNotification(full_doc.get("applyEmail"), {
                                "title": "Gate Pass Rejected",
                                "body": f"Your gate pass application with gate pass id {gatePassId} has been rejected by {full_doc.get('lastUpdatedBy')}",
                                "gatePassId": gatePassId,
                                "img": img,
                                "name": applyUserName
                            })

            
            except Exception as e:
                print(f"Error processing change in gatePass collection: {e}")
                import traceback
                traceback.print_exc()


#to get recent updated gate pass by gatePassId
@app.route('/get-recent-updated-gate-pass', methods=['POST'])
def get_recent_updated_gate_pass():
    print("Received a request to /get-recent-updated-gate-pass")
    data = request.json 
    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        gatePass=db["gatePass"].find_one({"gatePassId": int(data["gatePassId"])},{"_id":0,"level1":0,"level2":0})
        if not gatePass:
            return jsonify({"message":"Gate pass not found"}),404
        
        #we have also add some data like img,name,role and phone of user by fetching user data by applyEmail
        user=users_collection.find_one({"email": gatePass["applyEmail"]})
        if user:
            gatePass["name"]=user["name"]
            gatePass["img"]=user["img"]
            gatePass["role"]=user["role"]
            gatePass["phone"]=user["phone"]

            if user["role"]=="student":
                gatePass["batch"]=user["batch"]
                gatePass["fathername"]=user["fathername"]
                gatePass["fatherphone"]=user["fatherphone"]
                gatePass["uid"]=user["uid"]

        gatePass["applyDate"]=gatePass["applyDate"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify(gatePass), 200
    else:
        return jsonify({"message":"User not found"}),404
                
        
#to get visitor list history with filter of date like fromDate and toDate or also without date filter to get last 30 passes 
#admin,principal,security guard,receptionist and administration department hod can access visitor list history 
#hod of other department can access visitor list history on the basis of meetDepartment
#faculty can access based on meetEmail
@app.route('/get-visitor-list-history', methods=['POST'])
def get_visitor_list_history():
    print("Received a request to /get-visitor-list-history")
    data = request.json
    #for without date we have fromDate="" or toDate="" and for with date we have yyyy-mm-dd format in fromDate and toDate
    if "fromDate" in data and "toDate" in data:
        if data["fromDate"]=="" or data["toDate"]=="":
            fetchType="withoutDate"
        else:
            fetchType="withDate"
            fromDate=datetime.strptime(data["fromDate"], "%Y-%m-%d").date()
            toDate=datetime.strptime(data["toDate"], "%Y-%m-%d").date()
    else:
        return jsonify({"message":"fromDate and toDate are required"}),400

    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        if requester["role"]=="admin":
            if fetchType=="withoutDate":
                visitorList=db["visitor"].find({},{"_id":0}).sort("entryDate", -1).limit(30)
            else:
                visitorList=db["visitor"].find({"entryDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}}, {"_id":0}).sort("entryDate", -1)

        elif requester["department"]=="ADMINISTRATION" and requester["role"] in ["principal","security guard","reception","hod"]:
            #now we have to get visitor with for there campus
            if fetchType=="withoutDate":
                visitorList=db["visitor"].find({"campus": requester["campus"]}, {"_id":0}).sort("entryDate", -1).limit(30)
            else:
                visitorList=db["visitor"].find({"campus": requester["campus"], "entryDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}}, {"_id":0}).sort("entryDate", -1)

        elif requester["role"]=="hod":
            #here we have to get visitor list on the basis of meetDepartment and users campus
            if fetchType=="withoutDate":
                visitorList=db["visitor"].find({"campus": requester["campus"], "meetDepartment": requester["department"]}, {"_id":0}).sort("entryDate", -1).limit(30)
            else:
                visitorList=db["visitor"].find({"campus": requester["campus"], "meetDepartment": requester["department"], "entryDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}}, {"_id":0}).sort("entryDate", -1)
        elif requester["role"]=="faculty":
            #here we have to get visitor list on the basis of meetEmail and users campus
            if fetchType=="withoutDate":
                visitorList=db["visitor"].find({"campus": requester["campus"], "meetEmail": requester["email"]}, {"_id":0}).sort("entryDate", -1).limit(30)
            else:
                visitorList=db["visitor"].find({"campus": requester["campus"], "meetEmail": requester["email"], "entryDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}}, {"_id":0}).sort("entryDate", -1)
        else:
            return jsonify({"message":"You are not authorized to access visitor list history"}),403
        
        visitorList=list(visitorList)
        for visitor in visitorList:
            visitor["entryDate"]=visitor["entryDate"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')
            
        return jsonify(visitorList), 200
    else:
        return jsonify({"message":"User not found"}),404
            

#to get gate pass list history, we are fetching gate pass list like as we are getting visitor list history
#but here we fetch passes like (privous dates gate pass)+(current date gate pass with exit and rejected status)
@app.route('/get-gate-pass-list-history', methods=['POST'])
def get_gate_pass_list_history():
    print("Received a request to /get-gate-pass-list-history")
    data = request.json
    #for without date we have fromDate="" or toDate="" and for with date we have yyyy-mm-dd format in fromDate and toDate
    if "fromDate" in data and "toDate" in data:
        if data["fromDate"]=="" or data["toDate"]=="":
            fetchType="withoutDate"
        else:
            fetchType="withDate"
            fromDate=datetime.strptime(data["fromDate"], "%Y-%m-%d").date()
            toDate=datetime.strptime(data["toDate"], "%Y-%m-%d").date()
    else:
        return jsonify({"message":"fromDate and toDate are required"}),400

    requester = users_collection.find_one({"token": data["token"]})
    if requester:
        today=datetime.now().date()
        if requester["role"]=="admin":
            if fetchType=="withoutDate":
                gatePassList=db["gatePass"].find({"$or":[{"applyDate": {"$lt": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}},{"applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["exit", "rejected"]}}]},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1).limit(30)
            else:
                #we will fetch gate pass list on the basis of fromDate and toDate
                gatePassList=db["gatePass"].find({"applyDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
            
        elif requester["department"]=="ADMINISTRATION" and requester["role"] in ["principal","security guard","reception","hod"]:
            if fetchType=="withoutDate":
                gatePassList=db["gatePass"].find({"campus": requester["campus"], "$or":[{"applyDate": {"$lt": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}},{"applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["exit", "rejected"]}}]},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1).limit(30)
            else:
                gatePassList=db["gatePass"].find({"campus": requester["campus"], "applyDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
            
        elif requester["role"]=="hod":
            #here we have to get gate pass list on the basis of department and users campus
            if fetchType=="withoutDate":
                gatePassList=db["gatePass"].find({"campus": requester["campus"], "department": requester["department"], "$or":[{"applyDate": {"$lt": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}},{"applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["exit", "rejected"]}}]},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1).limit(30)
            else:
                gatePassList=db["gatePass"].find({"campus": requester["campus"], "department": requester["department"], "applyDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
        elif requester["role"]=="faculty":
            #here we have to get gate pass list on the basis of meetEmail and users campus
            if fetchType=="withoutDate":
                gatePassList=db["gatePass"].find({"campus": requester["campus"], "meetEmail": requester["email"], "$or":[{"applyDate": {"$lt": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}},{"applyDate": {"$gte": datetime.combine(today, datetime.min.time(), ZoneInfo("Asia/Kolkata"))}, "status": {"$in": ["exit", "rejected"]}}]},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1).limit(30)
            else:
                gatePassList=db["gatePass"].find({"campus": requester["campus"], "meetEmail": requester["email"], "applyDate": {"$gte": datetime.combine(fromDate, datetime.min.time(), ZoneInfo("Asia/Kolkata")), "$lte": datetime.combine(toDate, datetime.max.time(), ZoneInfo("Asia/Kolkata"))}},{"_id":0,"level1":0,"level2":0}).sort("applyDate", -1)
        else:
            return jsonify({"message":"You are not authorized to access gate pass list history"}),403
        
        gatePassList=list(gatePassList)
        for gatePass in gatePassList:
            #we have also add some data like img,name,role and phone of user by fetching user data by applyEmail
            user=users_collection.find_one({"email": gatePass["applyEmail"]},{"_id":0,"name":1,"img":1,"role":1,"phone":1,"batch":1,"fathername":1,"fatherphone":1,"uid":1})
            if user:
                gatePass["name"]=user["name"]
                gatePass["img"]=user["img"]
                gatePass["role"]=user["role"]
                gatePass["phone"]=user["phone"]

                if user["role"]=="student":
                    gatePass["batch"]=user["batch"]
                    gatePass["fathername"]=user["fathername"]
                    gatePass["fatherphone"]=user["fatherphone"]
                    gatePass["uid"]=user["uid"]

                gatePass["applyDate"]=gatePass["applyDate"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).strftime('%Y-%m-%d %H:%M:%S')

        return jsonify(gatePassList), 200
    else:
        return jsonify({"message":"User not found"}),404

#now we have to implement forget password
#to send verification code to user email to forget password,at this time we will also store this verification code and current datetime in database for verification of code and also we will set expiry time of code 5 minutes
@app.route('/send-verification-code', methods=['POST'])
def send_verification_code():
    print("Received a request to /send-verification-code")
    requester=users_collection.find_one({"email": request.json})
    
    if requester:
        #generate 4 to 6 digit random verification code
        verification_code=str(random.randint(1000,99999999))
        #store this code and current datetime in database for verification of code and also we will set
        users_collection.update_one({"email": request.json}, {"$set": {"verificationCode":verification_code,"lastVerificationCodeTime": datetime.now(ZoneInfo("Asia/Kolkata"))}})

        #send verification code to this email with proper format of email
        threading.Thread(target=sendEmail,args=(requester["email"],'Password Reset Verification Code',f"Dear {requester['name']},\n\nYour password reset verification code for Digital Pass is: {verification_code}\nThis code is valid for 5 minutes.\n\nIf you did not request a password reset, please ignore this email.\n\nBest regards,\n Digital Pass"),daemon=True).start()
        return jsonify({"message":"Verification code sent to your email"}),200
    else:
        return jsonify({"message":"User not found"}),404
    
#to verify verification code
@app.route('/verify-verification-code', methods=['POST'])
def verify_verification_code():
    print("Received a request to /verify-verification-code")
    data=request.json
    requester=users_collection.find_one({"email": data["email"]})
    if requester:
        if "verificationCode" in requester and "lastVerificationCodeTime" in requester:
            if requester["verificationCode"]==data["verificationCode"]:
                #check the expiry time of code is 5 minutes
                if datetime.now(ZoneInfo("Asia/Kolkata"))<=requester["lastVerificationCodeTime"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))+timedelta(minutes=5):
                    return jsonify({"message":"Verification code is valid"}),200
                else:
                    return jsonify({"message":"Verification code has expired"}),400
            else:
                return jsonify({"message":"Invalid verification code"}),400
        else:
            return jsonify({"message":"No verification code found for this user"}),404
    else:
        return jsonify({"message":"User not found"}),404
    

#to update password
@app.route('/update-password', methods=['POST'])
def update_password():
    print("Received a request to /update-password")
    data=request.json
    requester=users_collection.find_one({"email": data["email"]})
    if requester:
        if "verificationCode" in requester and "lastVerificationCodeTime" in requester:
            if requester["verificationCode"]==data["verificationCode"]:
                #check the expiry time of code is 5 minutes
                if datetime.now(ZoneInfo("Asia/Kolkata"))<=requester["lastVerificationCodeTime"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))+timedelta(minutes=5):
                    #update password in database
                    #also we have to update the token
                    token=str(uuid.uuid4())
                    users_collection.update_one({"email": data["email"]}, {"$set": {"password": data["newPassword"], "token": token}, "$unset": {"verificationCode": "", "lastVerificationCodeTime": ""}})
                    #send email to user for password update confirmation
                    threading.Thread(target=sendEmail,args=(requester["email"],'Password Updated Successfully',f"Dear {requester['name']},\n\nYour password for Digital Pass has been updated successfully.\nIf you did not perform this action, please contact support immediately.\n\nBest regards,\n Digital Pass"),daemon=True).start()
                    return jsonify(token),200
                else:
                    return jsonify({"message":"Verification code has expired"}),400
            else:
                return jsonify({"message":"Invalid verification code"}),400
        else:
            return jsonify({"message":"No verification code found for this user"}),404






##################



# yogeshsaini7172@gmail.com
# Move background tasks outside __main__ so Gunicorn runs them
def start_watcher(func):
    """Helper to keep watchers running even if they fail due to connection drops"""
    while True:
        try:
            func()
        except Exception as e:
            print(f"Watcher {func.__name__} failed, restarting in 5s... Error: {e}")
            eventlet.sleep(5)

# Background tasks are now started in the 'connect' event to ensure 
# they only run once the server is fully initialized by Gunicorn.

if __name__ == '__main__':
    
    #we have to create a thread for watching changes in visitor collection and whenever there is any change in visitor collection we will emit event to client for real time update of visitor list without refreshing the page
    socket.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

#ipconfig | findstr "IPv4"
#& "C:\Program Files\MongoDB\Server\8.2\bin\mongod.exe" --replSet rs0 --dbpath C:\data\db --logpath C:\data\log\mongodb.log