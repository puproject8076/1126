import firebase_admin
from firebase_admin import credentials, auth, firestore
import re
from flask_cors import CORS
from config import GROQ_API_KEY
from playwright.sync_api import Playwright, sync_playwright
import ddddocr
import sys
import contextlib
import uuid
import os
import time
from openpyxl import Workbook
#from 語音驗證碼 import *
from datetime import datetime
from flask import Flask, request, jsonify
import requests
import pytz

# 先嘗試導入 Groq，如果失敗則使用模擬客戶端
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError as e:
    print(f"Groq 導入失敗: {e}")
    GROQ_AVAILABLE = False

# 如果 Groq 不可用，創建模擬客戶端
if not GROQ_AVAILABLE:
    class MockGroqClient:
        def chat(self, **kwargs):
            return type('obj', (object,), {
                'choices': [
                    type('obj', (object,), {
                        'message': type('obj', (object,), {
                            'content': "Groq服務暫時不可用，請檢查依賴版本或API密鑰"
                        })
                    })
                ]
            })()
    
    Groq = MockGroqClient

model="openai/gpt-oss-120b"

app = Flask(__name__)
CORS(app)  # 啟用跨域支援，否則 Flutter Web 會被擋

# 初始化 Firebase
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)
taipei = pytz.timezone('Asia/Taipei')
db = firestore.client()

# 密碼長度驗證
def is_valid_password(password):
    return len(password) >= 6

# Email 格式驗證
def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def products_type(_type, date):
    try:
        # 如果 Groq 不可用，返回默認分類
        if not GROQ_AVAILABLE:
            return '其他'
            
        conversation_history = [
            {
                "role": "user",
                "content": f"""你是一位商品分類專家，請幫我將以下商品名稱分類為下列其中之一：
                『食品』『飲料』『交通』『書籍』『寵物』，如果不在這些範圍內就是『其他』。
                請只回覆分類名稱，不要加註解。

                商品名稱：""" + _type,
            }
        ]

        # 與模型進行第一次對話
        chat_completion = client.chat.completions.create(
            messages=conversation_history,
            model='llama-3.3-70b-versatile',
        )

        # 獲取回應內容
        response_content = chat_completion.choices[0].message.content

        if (response_content == '食品'):
            if (date[-8] != '0'):
                time = int(date[-8:-6])
                if (time < 11):
                    response_content = '早餐'
                elif (time < 15):
                    response_content = '午餐'
                else:
                    response_content = '晚餐'
            else:
                if (int(date[-9]) > 5):
                    response_content = '早餐'
                else:
                    response_content = '宵夜'

        return response_content
    except Exception as e:
        print(f"商品分類錯誤: {e}")
        return '其他'

# 初始化 Groq 客戶端（帶錯誤處理）
def initialize_groq_client():
    try:
        # 方法1：嘗試不帶額外參數初始化
        client = Groq(api_key=GROQ_API_KEY)
        print("Groq 客戶端初始化成功")
        return client
    except TypeError as e:
        if "proxies" in str(e):
            print("檢測到 proxies 參數問題，嘗試替代方案...")
            try:
                # 方法2：嘗試使用環境變量
                import os
                os.environ['GROQ_API_KEY'] = GROQ_API_KEY
                client = Groq()
                print("Groq 客戶端通過環境變量初始化成功")
                return client
            except Exception as e2:
                print(f"環境變量方法也失敗: {e2}")
                # 方法3：返回模擬客戶端
                print("使用模擬 Groq 客戶端")
                return MockGroqClient()
        else:
            print(f"其他初始化錯誤: {e}")
            return MockGroqClient()
    except Exception as e:
        print(f"Groq 初始化失敗: {e}")
        return MockGroqClient()

# 初始化客戶端
client = initialize_groq_client()

# 其餘的程式碼保持不變...
# [其餘的 route 和函數保持原樣]

# otp_store = {}  # 暫存 OTP 驗證碼

# @app.route('/send_otp', methods=['POST'])
# def send_otp():
#     data = request.get_json()
#     email = data.get('email')

#     if not email:
#         return jsonify({'error': '缺少 email'}), 400

#     # 產生 6 位數 OTP
#     otp = str(random.randint(100000, 999999))
#     expire_time = datetime.utcnow() + timedelta(minutes=5)
#     otp_store[email] = {'otp': otp, 'expire': expire_time}

#     # 這裡可改成你自己的寄信方式
#     print(f"[OTP] 已發送到 {email}: {otp}")  # 測試用印出

#     return jsonify({'message': '驗證碼已發送，請在 5 分鐘內輸入'}), 200

@app.route('/google_login', methods=['POST'])
def google_login():
    try:
        data = request.get_json()
        id_token = data.get('idToken')

        if not id_token:
            return jsonify({'error': '缺少 idToken'}), 400

        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token.get('uid')
        email = decoded_token.get('email')
        name = decoded_token.get('name', '')

        # Firestore 確認/新增使用者
        db.collection('users').document(uid).set({
            'name': name,
            'email': email,
            'user_id': uid,
            'created_at': datetime.utcnow().isoformat()
        }, merge=True)  # merge=True 避免覆蓋

        return jsonify({'message': 'Google 登入成功', 'uid': uid}), 200

    except Exception as e:
        print("Google login error:", e)
        return jsonify({'error': str(e)}), 400

@app.route('/record_transaction', methods=['POST'])
def record_transaction():
    try:
        data = request.get_json()
        print("Received data:", data)

        required_fields = ['類型', '日期', '類別', '金額', '備註', 'user_id']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要欄位: {field}"}), 400

        if not isinstance(data['金額'], (int, float)):
            return jsonify({"error": "金額必須是數字"}), 400

        type_ = data.get('類型')  # 收入 或 支出
        date = data.get('日期')  # 日期（字串格式，如 2025-04-29）
        category = data.get('類別')
        amount = float(data.get('金額'))
        note = data.get('備註')
        user_id = data.get('user_id')

        # 寫入 Firestore
        doc_ref = db.collection('transactions').document()
        doc_ref.set({
            '類型': type_,
            '日期': date,
            '類別': category,
            '金額': amount,
            '備註': note,
            'user_id': user_id,
        })

        return jsonify({'message': '資料儲存成功'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    if not all([name, email, password, confirm_password]):
        return jsonify({'error': '所有欄位皆為必填'}), 400

    if not is_valid_email(email):
        return jsonify({'error': '電子郵件格式錯誤'}), 400

    if password != confirm_password:
        return jsonify({'error': '密碼與確認密碼不一致'}), 400

    if not is_valid_password(password):
        return jsonify({'error': '密碼長度至少需 6 碼'}), 400

    try:
        user = auth.create_user(email=email, password=password)
        uid = user.uid
    except auth.EmailAlreadyExistsError:
        try:
            user = auth.get_user_by_email(email)
            uid = user.uid
        except Exception as e:
            return jsonify({'error': f'無法取得現有帳號資訊: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'註冊時發生錯誤: {str(e)}'}), 500

    try:
        db.collection('users').document(uid).set({
            'name': name,
            'email': email,
            'created_at': datetime.utcnow().isoformat(),
            'user_id': uid
        })
        return jsonify({'message': '註冊成功'}), 200
    except Exception as e:
        return jsonify({'error': f'Firestore 寫入失敗: {str(e)}'}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'message': '請填寫所有欄位'}), 400

    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        return jsonify({'message': '帳號不存在'}), 400
    except Exception as e:
        return jsonify({'message': f'發生錯誤: {str(e)}'}), 500

    return jsonify({'message': '登入成功'}), 200

@app.route('/update_user', methods=['POST'])
def update_user():
    try:
        data = request.json
        uid = data.get('uid')
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')

        auth.update_user(uid, email=email, password=password)
        db.collection('users').document(uid).update({'name': name, 'email': email})

        return jsonify({'message': '使用者資料已更新'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/delete_user', methods=['POST'])
def delete_user():
    try:
        data = request.json
        uid = data.get('uid')

        if not uid:
            return jsonify({'error': '缺少 uid'}), 400

        try:
            auth.delete_user(uid)
        except Exception as e:
            print(f"[警告] 無法刪除 FirebaseAuth 帳戶：{e}")

        try:
            db.collection('users').document(uid).delete()
        except Exception as e:
            print(f"[警告] 無法刪除 Firestore 資料：{e}")

        return jsonify({'message': '使用者帳戶已刪除'}), 200
    except Exception as e:
        print(f"[錯誤] 刪除帳戶失敗: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/save_financial_goal', methods=['POST'])
def save_financial_goal():
    try:
        data = request.get_json()
        print("Received financial goal data:", data)

        # 必要欄位
        required_fields = ['user_id', '日期', '類別', '金額', '時間', 'type']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要欄位: {field}"}), 400

        # 金額必須是數字
        if not isinstance(data['金額'], (int, float)):
            return jsonify({"error": "金額必須是數字"}), 400

        # 讀取欄位並去掉前後空白
        user_id = str(data['user_id']).strip()
        date = str(data['日期']).strip()
        category = str(data['類別']).strip()
        amount = float(data['金額'])
        time = str(data['時間']).strip()
        type_ = str(data['type']).strip()  # 去掉前後空白

        # 儲存到 Firestore
        doc_ref = db.collection('financial').document()
        doc_ref.set({
            'user_id': user_id,
            '日期': date,
            '類別': category,
            '金額': amount,
            '時間': time,
            'type': type_,
        })

        return jsonify({'message': '財務目標儲存成功'}), 200

    except Exception as e:
        # 捕捉其他錯誤，回傳 400
        return jsonify({'error': str(e)}), 400

@app.route('/get_financial_goals', methods=['POST'])
def get_financial_goals():
    try:
        data = request.get_json()
        print("Received get_financial_goals request:", data)
        user_id = data.get('user_id')

        if not user_id:
            print("缺少 user_id，拒絕請求")
            return jsonify({"error": "缺少 user_id"}), 400

        goals_ref = db.collection('financial').where('user_id', '==', user_id).get()
        goals = []
        for goal in goals_ref:
            goal_data = goal.to_dict()
            goal_data['id'] = goal.id
            goals.append(goal_data)

        return jsonify({'goals': goals}), 200

    except Exception as e:
        print(f"獲取目標失敗: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/delete_financial_goal', methods=['POST'])
def delete_financial_goal():
    try:
        data = request.get_json()
        print("Received delete_financial_goal request:", data)
        goal_id = data.get('goal_id')

        if not goal_id:
            print("缺少 goal_id，拒絕請求")
            return jsonify({"error": "缺少 goal_id"}), 400

        db.collection('financial').document(goal_id).delete()
        return jsonify({'message': '目標已刪除'}), 200

    except Exception as e:
        print(f"刪除目標失敗: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/clear_all_expense_goals', methods=['POST'])
def clear_all_expense_goals():
    try:
        data = request.get_json()
        print("Received clear_all_expense_goals request:", data)
        user_id = data.get('user_id')

        if not user_id:
            print("缺少 user_id，拒絕請求")
            return jsonify({"error": "缺少 user_id"}), 400

        # 首先獲取所有文檔以檢查數據
        all_docs = db.collection('financial').where(field_path='user_id', op_string='==', value=user_id).get()
        print(f"找到的所有文檔: {[doc.to_dict() for doc in all_docs]}")

        # 嘗試查詢類型為支出的文檔
        goals_ref = (db.collection('financial')
                     .where(field_path='user_id', op_string='==', value=user_id)
                     .where(field_path='type', op_string='==', value='支出')
                     .get())
        deleted_count = 0
        for goal in goals_ref:
            print(f"正在刪除支出目標，ID: {goal.id}, 數據: {goal.to_dict()}")
            db.collection('financial').document(goal.id).delete()
            deleted_count += 1

        print(f"所有支出目標已清空，刪除數量: {deleted_count}")
        return jsonify({'message': '所有支出目標已清空'}), 200

    except Exception as e:
        print(f"清空支出目標失敗: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/clear_all_saving_goals', methods=['POST'])
def clear_all_saving_goals():
    try:
        data = request.get_json()
        print("Received clear_all_saving_goals request:", data)
        user_id = data.get('user_id')

        if not user_id:
            print("缺少 user_id，拒絕請求")
            return jsonify({"error": "缺少 user_id"}), 400

        # 首先獲取所有文檔以檢查數據
        all_docs = db.collection('financial').where(field_path='user_id', op_string='==', value=user_id).get()
        print(f"找到的所有文檔: {[doc.to_dict() for doc in all_docs]}")

        # 嘗試查詢類型為儲蓄的文檔
        goals_ref = (db.collection('financial')
                     .where(field_path='user_id', op_string='==', value=user_id)
                     .where(field_path='type', op_string='==', value='儲蓄')
                     .get())
        deleted_count = 0
        for goal in goals_ref:
            print(f"正在刪除儲蓄目標，ID: {goal.id}, 數據: {goal.to_dict()}")
            db.collection('financial').document(goal.id).delete()
            deleted_count += 1

        print(f"所有儲蓄目標已清空，刪除數量: {deleted_count}")
        return jsonify({'message': '所有儲蓄目標已清空'}), 200

    except Exception as e:
        print(f"清空儲蓄目標失敗: {str(e)}")
        return jsonify({'error': str(e)}), 400

# 角色 prompt
role_prompts = {
    "狐狸": "請用機智、靈活、帶點狡猾感的語氣回覆，回覆的最後要加上“呵呵~”，像狐狸般聰明、擅長制定策略。投資型態偏向『積極型』，善於捕捉市場波動、靈活調整投資組合，但仍以專業且合理的金融知識回答問題。",
    "熊貓": "請用溫柔、親切、撒嬌的語氣回覆，回覆的最後要加上“嗚～”或“嘻嘻”。像慢慢咀嚼竹子的熊貓一樣，投資型態偏向『穩健保守型』，習慣以低風險產品與長期持有為主，以專業且合理的理財知識回覆。",
    "狗": "請用活潑、熱情、興奮的語氣回覆，回覆的最後要加上“汪汪！”或“嗨嗨～”。像狗狗一樣充滿動力，投資型態偏向『中度平衡型』，願意適度承擔風險並追求穩健成長，以專業知識提供理財方向。",
    "老虎": "請用果斷、強勢、自信的語氣回覆，回覆的最後要加上“吼！”或“唔！”。像叢林王者般無畏，投資型態是『積極進取型』，擅長高報酬、高風險的市場布局，但仍會以專業且合理的金融觀點分析。",
    "豬": "用憨厚、可愛、直率的語氣回覆，回覆最後要加上“哼哼～”或“咕嚕咕嚕”。像小豬般單純樂觀，投資型態偏向『保守型』，重視穩定、安全，偏好固定收益與低波動產品，用專業知識解釋財務內容。",
    "水獺": "請用活潑、聰明、好奇的語氣回覆，最後加上“咕嚕～”或“嘰嘰”。像水獺在水中靈活穿梭，投資型態偏向『成長型』，樂於研究市場趨勢、嘗試新興科技投資，同時保持合理的風險評估。",
    "貓": "請用高冷、理性、傲嬌的語氣回覆，最後加上“喵～”或“嗚…”。像貓咪一樣謹慎觀察，投資型態偏向『穩健型』，注重風險控管、精挑細選標的，以冷靜且專業的金融知識提供回答。",
    "企鵝": "請用呆萌、親切、稍慢的語氣回覆，最後加上“嘎嘎～”或“嗚～”。像企鵝一步步向前走，投資型態偏向『保守穩健型』，重視穩定收益與長期投資，以簡單易懂的方式提供專業理財知識。",
    "預設": "請用機智、靈活、帶點狡猾感的語氣回覆，回覆的最後要加上“呵呵~”，像狐狸般聰明、擅長制定策略。投資型態偏向『積極型』，善於捕捉市場波動、靈活調整投資組合，但仍以專業且合理的金融知識回答問題。"
}

def call_rag_space(user_message, chat_history=[]):
    payload = {"data": [user_message, chat_history]}
    try:
        response = requests.post("https://yukali58822-financial-rag-chatbot.hf.space", json=payload)
        response.raise_for_status()
        result = response.json()

        if isinstance(result.get("data"), list) and len(result["data"]) > 1:
            new_chat_history = result["data"][1]
            ai_reply = new_chat_history[-1][1] if new_chat_history else ""
            return ai_reply, new_chat_history
        else:
            return "(RAG 回傳格式異常)", chat_history
    except Exception as e:
        return f"(RAG 呼叫失敗: {e})", chat_history

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message')
    user_id = data.get('user_id', 'unknown_user')

    if not user_message:
        return jsonify({"error": "消息內容不可為空"}), 400

    # -------- 1. 抓取使用者角色 --------
    user_doc = db.collection('users').document(user_id).get()
    selected_role = user_doc.to_dict().get('selectedCharacter') if user_doc.exists else "預設"
    role_prompt = role_prompts.get(selected_role, role_prompts["預設"])

    # -------- 2. 呼叫 RAG Space --------
    chat_history_rag = []
    rag_text, chat_history_rag = call_rag_space(user_message, chat_history_rag)

    # -------- 3. GPT prompt：一次完成 RAG + 角色語氣 + 繁體中文回答 --------
    try:
        conversation_history = [
            {
                "role": "user",
                "content": (
                    f"{role_prompt} 根據以下資訊回答問題，"
                    f"保持簡短明確並使用繁體中文：\n\n{rag_text}\n\n問題：{user_message}"
                )
            }
        ]

        chat_completion = client.chat.completions.create(
            messages=conversation_history,
            model=model,
        )
        response_content = chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Groq API 呼叫失敗: {e}")
        response_content = f"抱歉，目前無法提供AI回應。錯誤: {str(e)}"

    # -------- 4. 儲存對話紀錄 --------
    try:
        user_ref = db.collection('chat').document(user_id)
        user_ref.set({
            'user_id': user_id,
            'conversation': firestore.ArrayUnion([{
                "timestamp": datetime.now(pytz.timezone('Asia/Taipei')),
                "user_message": user_message,
                "rag_context": rag_text,
                "bot_response": response_content,
                "role": selected_role
            }])
        }, merge=True)
    except Exception as e:
        print(f"儲存對話紀錄失敗: {e}")

    # -------- 5. 返回最終繁體中文答案 --------
    return jsonify({'response': response_content})

@app.route('/process_invoice', methods=['POST'])
def process_invoice():
    try:
        data = request.get_json()
        print(f"收到的發票數據: {data}")
        
        invoice_number1 = data.get('invoice_number')
        purchase_date1 = data.get('purchase_date')
        random_code1 = data.get('random_code')
        user_id = data.get('user_id', 'unknown_user')
        
        print(f"收到發票處理請求 - 發票號碼: {invoice_number1}, 用戶: {user_id}")

        # 基本驗證
        if not all([invoice_number1, purchase_date1, random_code1]):
            error_msg = "缺少必要的發票信息"
            print(error_msg)
            return jsonify({"status": "error", "message": error_msg}), 400

        # 檢查 Playwright 是否可用
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            error_msg = f"Playwright 不可用: {e}"
            print(error_msg)
            return jsonify({"status": "error", "message": "發票掃描功能暫時不可用"}), 400

        # 由於 Render 環境限制，提供模擬功能
        return handle_invoice_simulation(invoice_number1, purchase_date1, random_code1, user_id)

    except Exception as e:
        error_msg = f"發票處理整體錯誤：{e}"
        print(error_msg)
        return jsonify({"status": "error", "message": f"系統錯誤: {str(e)}"}), 500

def handle_invoice_simulation(invoice_number, purchase_date, random_code, user_id):
    """處理發票模擬（用於雲端環境）"""
    try:
        print("使用發票模擬模式")
        
        # 模擬發票數據
        mock_invoice_data = {
            '發票日期': f"{purchase_date} 12:00:00",
            '店家': '模擬商家 - 雲端測試',
            '購買商品': [
                "品名: 測試商品A\n金額: 150\n\n",
                "品名: 測試商品B\n金額: 80\n\n",
                "品名: 測試商品C\n金額: 200\n\n"
            ],
            '總花費': '430',
            'user_id': user_id,
        }

        # 儲存到 Firestore
        doc_ref = db.collection('invoice').document()
        doc_ref.set(mock_invoice_data)
        print("發票數據已保存到 Firestore")

        # 添加到交易記錄
        transactions_added = 0
        products = [
            {"name": "測試商品A", "amount": 150, "type": "食品"},
            {"name": "測試商品B", "amount": 80, "type": "飲料"}, 
            {"name": "測試商品C", "amount": 200, "type": "其他"}
        ]

        for product in products:
            try:
                transaction_ref = db.collection('transactions').document()
                transaction_ref.set({
                    '類型': "支出",
                    '日期': purchase_date,
                    '類別': product['type'],
                    '金額': product['amount'],
                    '備註': f"{product['name']}(發票模擬)",
                    'user_id': user_id,
                })
                transactions_added += 1
            except Exception as e:
                print(f"添加交易記錄失敗: {e}")

        print(f"成功添加 {transactions_added} 筆交易記錄")

        return jsonify({
            "status": "success", 
            "message": "發票模擬處理成功（雲端測試模式）",
            "data": {
                "發票號碼": invoice_number,
                "日期": purchase_date,
                "總金額": 430,
                "商品數量": 3,
                "模式": "模擬測試"
            }
        }), 200

    except Exception as e:
        error_msg = f"發票模擬處理失敗: {e}"
        print(error_msg)
        return jsonify({"status": "error", "message": error_msg}), 500

@app.route('/get_invoices', methods=['POST'])
def get_invoices():
    try:
        invoices_ref = db.collection('invoice').get()
        invoices = []
        for invoice in invoices_ref:
            invoice_data = invoice.to_dict()
            invoice_data['id'] = invoice.id
            invoices.append(invoice_data)
        return jsonify({'invoices': invoices}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/export_transactions', methods=['POST'])
def export_transactions():
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        user_id = data.get('user_id')

        if not all([start_date, end_date, user_id]):
            return jsonify({'error': '缺少 start_date, end_date 或 user_id'}), 400

        # 查詢 Firestore 中的 transactions
        transactions_ref = db.collection('transactions').where('user_id', '==', user_id).get()
        transactions = []
        for transaction in transactions_ref:
            transaction_data = transaction.to_dict()
            transaction_date = datetime.strptime(transaction_data['日期'], '%Y-%m-%d').date()
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            if start_date_obj <= transaction_date <= end_date_obj:
                transactions.append(transaction_data)

        # 創建 Excel 檔案
        wb = Workbook()
        ws = wb.active
        ws.title = "Transactions"
        headers = ['類型', '日期', '類別', '金額', '備註', 'user_id']
        ws.append(headers)

        for transaction in transactions:
            row = [transaction.get(header, '') for header in headers]
            ws.append(row)

        # 儲存 Excel 檔案
        excel_file = f"transactions_{user_id}_{start_date}_to_{end_date}.xlsx"
        wb.save(excel_file)

        # 回傳檔案給前端下載
        with open(excel_file, 'rb') as f:
            response = jsonify({'message': '匯出成功', 'file': excel_file})
            response.headers['Content-Disposition'] = f'attachment; filename={excel_file}'
            response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            return response

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/')
def health_check():
    return jsonify({
        'status': 'healthy', 
        'message': '服務運行正常',
        'timestamp': datetime.now(pytz.timezone('Asia/Taipei')).isoformat()
    })

@app.route('/check_api_keys', methods=['GET'])
def check_api_keys():
    """檢查 API 金鑰狀態"""
    groq_status = "有效" if not isinstance(client, MockGroqClient) else "無效/未設置"
    groq_key_length = len(GROQ_API_KEY) if GROQ_API_KEY else 0
    
    return jsonify({
        'groq_api_key': {
            'status': groq_status,
            'length': groq_key_length,
            'set': bool(GROQ_API_KEY)
        },
        'firebase': '已初始化',
        'timestamp': datetime.now(pytz.timezone('Asia/Taipei')).isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


