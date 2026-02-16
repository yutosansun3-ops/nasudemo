import os
import re
import requests
import gspread
import time
from flask import Flask, request, abort
from google.oauth2.service_account import Credentials
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# --- 環境変数設定（Renderの管理画面で設定します） ---
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_KEY')

handler = WebhookHandler(LINE_SECRET)
configuration = Configuration(access_token=LINE_ACCESS_TOKEN)

# キャッシュ管理（10分間保持）
cache_data = {"events": [], "knowledge": "", "last_updated": 0}
CACHE_LIMIT = 600 

def convert_to_direct_url(raw_url):
    """Googleドライブ等のURLを直リンクに変換"""
    if not raw_url or not str(raw_url).startswith('http'):
        return "https://via.placeholder.com/1000x650.png?text=No+Image"
    file_id = ""
    if "/d/" in raw_url:
        match = re.search(r'd/([^/]+)', raw_url)
        if match: file_id = match.group(1)
    elif "id=" in raw_url:
        match = re.search(r'id=([^&]+)', raw_url)
        if match: file_id = match.group(1)
    return f"https://drive.google.com/uc?export=view&id={file_id}" if file_id else raw_url

def fetch_all_data():
    """スプレッドシートからイベントとQA情報を取得"""
    global cache_data
    now = time.time()
    if cache_data["last_updated"] > 0 and (now - cache_data["last_updated"] < CACHE_LIMIT):
        return
    
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        # Render上の credentials.json を使用
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(SPREADSHEET_ID)

        # イベント情報取得（最新10件）
        e_sheet = workbook.worksheet("イベント情報")
        e_all = e_sheet.get_all_records()
        valid_events = [e for e in e_all if e.get("タイトル")]
        latest_events = valid_events[-10:] 

        # QA知識取得
        qa_sheet = workbook.worksheet("QA")
        knowledge = "\n".join([",".join(row) for row in qa_sheet.get_all_values()])

        cache_data.update({"events": latest_events, "knowledge": knowledge, "last_updated": now})
    except Exception as e:
        print(f"Fetch Error: {e}")

def create_event_flex(events):
    """イベント10件をカルーセル（横スクロール）にする"""
    bubbles = []
    for e in events:
        bubble = {
            "type": "bubble",
            "hero": {"type": "image", "url": convert_to_direct_url(e.get("画像URL", "")), "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": e.get("タイトル", "Event"), "weight": "bold", "size": "xl", "wrap": True},
                    {"type": "text", "text": str(e.get("開催日", "")), "size": "sm", "color": "#999999", "margin": "md"}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "button", "action": {"type": "uri", "label": "詳細を見る", "uri": str(e.get("詳細URL", "https://line.me"))}, "style": "primary", "color": "#00b900"}
                ]
            }
        }
        bubbles.append(bubble)
    return {"type": "carousel", "contents": bubbles}

@app.route("/", methods=['GET', 'HEAD'])
def index():
    return "Bot is running", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text
    fetch_all_data()

    # 1. イベント表示要求への反応
    if any(k in user_text for k in ["limited", "イベント", "最新"]):
        if not cache_data["events"]:
            reply = [TextMessage(text="現在イベント情報はありません。")]
        else:
            flex = create_event_flex(cache_data["events"])
            reply = [FlexMessage(alt_text="最新イベント一覧", contents=FlexContainer.from_dict(flex))]
        
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=reply))
        return

    # 2. Gemini AI回答
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    prompt = f"知識:\n{cache_data['knowledge']}\n質問: {user_text}\n100字以内で答えて。知らないことは「わかりかねます」と伝えて。"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(api_url, json=payload, timeout=10)
        reply_text = res.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        reply_text = "（AIチャットは一時停止中です）"

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]
        ))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)