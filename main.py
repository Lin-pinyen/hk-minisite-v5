import os
import functions_framework
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for
from google.cloud import secretmanager

# 初始化 Flask 應用程式
app = Flask(__name__)

# --- 組態設定 ---
# 從環境變數中獲取 GCP 專案 ID 和金鑰名稱
# 這些將在 Cloud Function 的部署設定中設定
PROJECT_ID = os.environ.get('GCP_PROJECT')
SECRET_ID = "HK_MINISITE_GEMINI_API_KEY"  # 您在 Secret Manager 中建立的金鑰名稱
SECRET_VERSION = "latest"   # 總是使用最新版本的金鑰

# --- Secret Manager 輔助函式 ---
def get_gemini_api_key():
    """從 Google Cloud Secret Manager 獲取 Gemini API 金鑰。"""
    if not PROJECT_ID:
        print("錯誤：GCP_PROJECT 環境變數未設定。")
        return None
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{SECRET_ID}/versions/{SECRET_VERSION}"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"存取金鑰時發生錯誤: {e}")
        return None


# --- 路由定義 ---

@app.route('/')
def root():
    """將根路徑重定向到第一個表格。"""
    return redirect(url_for('index', id=1))

@app.route('/<int:id>')
def index(id):
    """根據 id 提供主要的 HTML 網頁。"""
    if id not in [1, 2, 3]:
        return "Please enter an ID between 1 and 3.", 404
    return render_template('index.html', id=id)

@app.route('/generate', methods=['POST'])
def handle_generate():
    """
    
    作為 Gemini API 的安全代理。
    前端將請求（prompt 和圖片）傳到這裡，此函式會附上儲存
    在後端的 API 金鑰，然後將請求轉發給 Google。
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return jsonify({"error": "伺服器設定錯誤：無法讀取 API 金鑰。"}), 500

    # 從前端請求中獲取 JSON 資料
    client_payload = request.get_json()
    if not client_payload:
        return jsonify({"error": "無效的請求內容。"}), 400

    # 建立 Gemini API 的請求 URL
    model = "gemini-2.5-flash-image-preview"
    gemini_api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    try:
        # 將請求轉發給 Gemini API
        response = requests.post(gemini_api_url, json=client_payload, headers={'Content-Type': 'application/json'})
        response.raise_for_status()  # 如果 API 回傳錯誤碼 (4xx or 5xx)，則拋出例外
        
        # 將 Gemini API 的原始回應直接回傳給前端
        return jsonify(response.json())

    except requests.exceptions.RequestException as e:
        # 處理呼叫 Gemini API 時的網路或錯誤回應
        print(f"呼叫 Gemini API 時發生錯誤: {e}")
        error_json = e.response.json() if e.response else {"error": str(e)}
        return jsonify(error_json), getattr(e.response, 'status_code', 502)

# --- Cloud Function 進入點 ---
@functions_framework.http
def nano_banana_app(request):
    """
    Cloud Function 的主要進入點。
    它會將所有傳入的 HTTP 請求交由 Flask 應用程式處理。
    """
    with app.request_context(request.environ):
        return app.full_dispatch_request()
