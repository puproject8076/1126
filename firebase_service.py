print("Starting firebase_service.py...")  # 這裡添加一行
import firebase_admin
from firebase_admin import credentials, firestore

# 初始化 Firebase
cred = credentials.Certificate('firebase_api.json')  # 注意路徑，等等會講
try:
    firebase_admin.initialize_app(cred)
    print("Firebase initialized successfully.")
except Exception as e:
    print("Firebase initialization failed:", e)

# 拿到 Firestore 的 client
db = firestore.client()

# 新增使用者
def register_user(name, email, password):
    try:
        users_ref = db.collection('users')
        user_doc = users_ref.document(email).get()
        if user_doc.exists:
            print(f"User with email {email} already exists.")
            return False
        else:
            users_ref.document(email).set({
                'name': name,
                'email': email,
                'password': password,
            })
            print(f"User {email} registered successfully.")
            return True
    except Exception as e:
        print("🔥 發生錯誤！錯誤內容：", e)
        return False

# 檢查使用者登入資訊
def login_user(email, password):
    try:
        users_ref = db.collection('users')
        user_doc = users_ref.document(email).get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data['password'] == password:
                print(f"User {email} login successful.")
                return True
            else:
                print(f"Incorrect password for {email}.")
                return False
        else:
            print(f"No user found with email {email}.")
            return False
    except Exception as e:
        print("🔥 發生登入錯誤：", e)
        return False
