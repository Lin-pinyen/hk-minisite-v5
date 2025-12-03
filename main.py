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



def process_image(image_data, overlay_text="Made Possible By Google"):
    """
    整合圖片處理：添加底部 Banner 與 右下角文字。
    使用系統內建的 DejaVuSans-Bold 字體。
    """
    try:
        # 1. 一次性開啟圖片 (優化 I/O)
        image = Image.open(io.BytesIO(image_data)).convert("RGBA")
        base_path = os.path.dirname(os.path.abspath(__file__))

        # --- 步驟 A: 貼上底部 Banner ---
        banner_path = os.path.join(base_path, "hk2025.jpeg")
        if os.path.exists(banner_path):
            banner = Image.open(banner_path).convert("RGBA")
            # 調整橫幅大小以匹配圖片寬度
            banner_width = image.width
            banner_height = int(banner.height * (banner_width / banner.width))
            banner = banner.resize((banner_width, banner_height))
            
            # 計算橫幅位置 (底部)
            banner_y = image.height - banner_height
            image.paste(banner, (0, banner_y)) # 若 banner 沒有透明度，可省略 mask
        else:
            print("警告：找不到 hk2025.jpeg")

        # --- 步驟 B: 添加文字 (使用你找到的路徑) ---
        # 這是你 CLI 找到的確切路徑
        font_path = "./GoogleSans-Bold.ttf"
        font_size = int(image.width * 0.05) 
        font_size = max(80, font_size) # 確保至少有 40px
        try:
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            # 萬一 Cloud Functions 的正式環境真的沒有這個檔，會自動降級回預設字體
            print(f"警告：在路徑 {font_path} 找不到字體，將使用預設字體。")
            font = ImageFont.load_default()

        draw = ImageDraw.Draw(image)
        
        # 計算文字大小
        bbox = draw.textbbox((0, 0), overlay_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # 計算文字位置 (右下角，留 15px 邊距)
        margin = 15
        x = image.width - text_width - margin
        y = image.height - text_height - margin

        # # (選用) 畫一個黑色陰影，讓白字在任何背景都清楚
        # draw.text((x+1, y+1), overlay_text, font=font, fill=(0, 0, 0)) 
        
        # 畫上白色主文字 with a black stroke
        draw.text((x, y), overlay_text, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))

        # --- 步驟 C: 輸出結果 ---
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()

    except Exception as e:
        print(f"圖片處理發生錯誤: {e}")
        return image_data # 如果出錯，至少回傳原始圖片不要讓程式掛掉

# --- 路由定義 ---

@app.route('/')
def root():
    """提供主要的 HTML 網頁。"""
    return render_template('index.html')

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
    # model = "gemini-3-pro-image-preview"
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
                
                # 使用新的整合函式，直接傳入你想要的文字
                final_image_data = process_image(image_data, overlay_text="Made Possible By Google")
                
                # 轉回 base64
                modified_image_base64 = base64.b64encode(final_image_data).decode('utf-8')
                
                # 更新回應
                image_part["inlineData"]["data"] = modified_image_base64
                image_part["inlineData"]["mimeType"] = "image/png"

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