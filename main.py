import os
import functions_framework
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for
from google.cloud import secretmanager
from PIL import Image, ImageDraw, ImageFont
import base64
import io

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


# --- Image Overlay Function ---
def add_overlay(image_data):
    """在圖片上添加文字和標誌浮水印。"""
    try:
        # 1. 獲取當前程式碼檔案 (main.py) 所在的絕對路徑
        base_path = os.path.dirname(os.path.abspath(__file__))
        
        # 2. 組合出資源檔案的絕對路徑
        logo_path = os.path.join(base_path, "google_icon.png")
        font_path = os.path.join(base_path, "arial.ttf")
        
        # 除錯：印出路徑確認
        print(f"Logo Path: {logo_path}")

        # 3. 檢查 Logo 是否存在 (避免直接崩潰)
        if not os.path.exists(logo_path):
            print(f"嚴重錯誤：找不到 Logo 檔案！請確認 google_icon.png 有被上傳。")
            return image_data
        image = Image.open(io.BytesIO(image_data)).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")

        # 調整標誌大小
        logo_width = image.width // 6
        logo_height = int(logo.height * (logo_width / logo.width))
        logo = logo.resize((logo_width, logo_height))

        # 建立一個可以繪製的圖像
        draw = ImageDraw.Draw(image)

        # 設定文字內容和字體
        text = "HKGCC International Business Summit 2025\nTheme: [Theme Placeholder]\nDate: [Date Placeholder]"
        try:
            font = ImageFont.truetype("arial.ttf", size=image.width // 25)
        except IOError:
            font = ImageFont.load_default()

        text_color = (255, 255, 255, 255)  # 白色

        # 計算文字位置
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        text_x = image.width // 20
        text_y = image.height - text_height - image.height // 10

        # 添加半透明背景到文字後面
        bg_color = (255, 255, 255, 180)
        draw.rectangle(
            [(text_x - 5, text_y - 5),
             (text_x + text_width + 5, text_y + text_height + 5)],
            fill=bg_color
        )

        # 添加文字
        draw.text((text_x, text_y), text, font=font, fill=text_color)

        # 計算標誌位置 (右下角)
        logo_x = image.width - logo_width - image.width // 20
        logo_y = image.height - logo_height - image.height // 10

        # 貼上標誌
        image.paste(logo, (logo_x, logo_y), logo)

        # 將圖像轉換回字節
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()
    except Exception as e:
        print(f"添加浮水印時發生錯誤: {e}")
        return image_data # 如果出錯則回傳原始圖片

# --- 路由定義 ---

@app.route('/')
def root():
    """將根路徑重定向到第一個表格。"""
    return redirect(url_for('index', id=4))

@app.route('/<int:id>')
def index(id):
    """根據 id 提供主要的 HTML 網頁。"""
    if id not in [4, 5, 6]:
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
        
        api_response = response.json()

        # 提取生成的圖像數據
        if api_response.get("candidates") and len(api_response["candidates"]) > 0:
            parts = api_response["candidates"][0].get("content", {}).get("parts", [])
            image_part = next((p for p in parts if "inlineData" in p), None)
            
            if image_part:
                image_data = base64.b64decode(image_part["inlineData"]["data"])
                mime_type = image_part["inlineData"]["mimeType"]

                # 添加浮水印
                modified_image_data = add_overlay(image_data)
                
                # 將修改後的圖像轉換回 base64
                modified_image_base64 = base64.b64encode(modified_image_data).decode('utf-8')
                
                # 更新 API 回應中的圖像數據
                image_part["inlineData"]["data"] = modified_image_base64
                image_part["inlineData"]["mimeType"] = "image/png" # 因為我們保存為 PNG

        # 將修改後的 Gemini API 回應回傳給前端
        return jsonify(api_response)


    except requests.exceptions.RequestException as e:
        # 處理呼叫 Gemini API 時的網路或錯誤回應
        print(f"呼叫 Gemini API 時發生錯誤: {e}")
        status_code = getattr(e.response, 'status_code', 502)

        error_message_html = 'Due to high traffic, the server is temporarily unavailable, please try later. <br>Please also follow our generation guidance <a href="https://policies.google.com/terms/generative-ai/use-policy?hl=en" target="_blank" class="underline text-white">here</a> to avoid failure.'

        return jsonify({"error": {"message": error_message_html}}), status_code

# --- Cloud Function 進入點 ---
@functions_framework.http
def nano_banana_app(request):
    """
    Cloud Function 的主要進入點。
    它會將所有傳入的 HTTP 請求交由 Flask 應用程式處理。
    """
    with app.request_context(request.environ):
        return app.full_dispatch_request()
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)