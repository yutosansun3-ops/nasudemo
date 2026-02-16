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

# --- 1. 環境変数の取得（Renderの設定画面から） ---
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_KEY')

handler = WebhookHandler(LINE_SECRET)
configuration = Configuration(access_token=LINE_ACCESS_TOKEN)

# キャッシュ管理
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
    """スプレッドシートから店舗知識とイベント情報を取得"""
    global cache_data
    now = time.time()
    if cache_data["last_updated"] > 0 and (now - cache_data["last_updated"] < CACHE_LIMIT):
        return
    
    print("--- データの同期を開始します ---", flush=True)
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        # RenderのSecret Filesに保存したcredentials.jsonを使用
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(SPREADSHEET_ID)

        # イベント情報
        e_sheet = workbook.worksheet("イベント情報")
        valid_events = [e for e in e_sheet.get_all_records() if e.get("タイトル")]
        
        # QA知識
        qa_sheet = workbook.worksheet("QA")
        knowledge = "\n".join([",".join(map(str, row)) for row in qa_sheet.get_all_values()])

        cache_data.update({"events": valid_events[-10:], "knowledge": knowledge, "last_updated": now})
        print("--- データの同期に成功しました ---", flush=True)
    except Exception as e:
        print(f"!!! データ同期エラー !!!: {e}", flush=True)

def create_event_flex(events):
    """最新イベント10件をカルーセルで表示"""
    bubbles = []
    for e in events:
        bubble = {
            "type": "bubble",
            "hero": {"type": "image", "url": convert_to_direct_url(e.get("画像URL", "")), "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": str(e.get("タイトル", "イベント")), "weight": "bold", "size": "xl", "wrap": True},
                    {"type": "text", "text": f"開催日: {str(e.get('開催日', ''))}", "size": "sm", "color": "#999999", "margin": "md"}
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
    return "Event Bot: Active (Gemini 2.0 Flash Mode)", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"!!! Webhook Error !!!: {e}", flush=True)
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text
    print(f"メッセージ受信: {user_text}", flush=True)
    fetch_all_data()

    # A. AI起動ボタンへの反応
    if "AIチャットボット起動" in user_text:
        reply_text = "承知いたしました！AIコンシェルジュがご質問にお答えします。那須の観光情報について、何でも聞いてくださいね。"
        messages = [TextMessage(text=reply_text)]

    # B. イベント表示（キーワード判定）
    elif any(k in user_text for k in ["最新", "イベント"]):
        if not cache_data["events"]:
            messages = [TextMessage(text="現在、掲載中のイベント情報はありません。")]
        else:
            flex_content = create_event_flex(cache_data["events"])
            messages = [FlexMessage(alt_text="最新イベント一覧", contents=FlexContainer.from_dict(flex_content))]

    # C. Gemini 2.0 Flash による回答
    else:
        # 最新の安定版 v1 窓口と gemini-2.0-flash モデルを指定
        api_url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
        
        prompt = f"店舗知識:\n{cache_data['knowledge']}\n\n質問: {user_text}\n\n100字以内で親切に答えて。知らないことは「わかりかねます」と伝えて。"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            res = requests.post(api_url, json=payload, timeout=10)
            if res.status_code == 200:
                reply_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                # 安定版でダメな場合は一時的なエラーメッセージを出す
                reply_text = "AIの応答に失敗しました。時間をおいて再度お試しください。"
                print(f"Gemini API Error: {res.text}", flush=True)
        except Exception as e:
            reply_text = "接続エラーが発生しました。"
            print(f"Connection Error: {e}", flush=True)
        
        messages = [TextMessage(text=reply_text)]

    # 返信実行
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, 
            messages=messages
        ))

if __name__ == "__main__":
    # Renderのポート設定
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)