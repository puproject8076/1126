import firebase_admin
from firebase_admin import credentials, auth, firestore

# 初始化 Firebase Admin SDK
cred = credentials.Certificate("firebase_api.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
