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

# --- 1. 環境変数の取得 ---
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')
SPREADSHEET_ID = os.getenv('SPREADSHEET_KEY')

handler = WebhookHandler(LINE_SECRET)
configuration = Configuration(access_token=LINE_ACCESS_TOKEN)

# キャッシュ管理（スプレッドシート用）
cache_data = {"events": [], "knowledge": "", "last_updated": 0}
CACHE_LIMIT = 600 

# --- 会話履歴の保存用（メモリ上に保持） ---
# 構造: { "user_id": [{"role": "user", "parts": [...]}, {"role": "model", "parts": [...]}] }
user_chat_histories = {}
MAX_HISTORY = 6  # 過去3往復（6メッセージ）分を記憶

def convert_to_direct_url(raw_url):
    if not raw_url or not str(raw_url).startswith('http'):
        return "https://via.placeholder.com/1000x650.png?text=No+Image"
    file_id = ""
    if "/d/" in raw_url:
        match = re.search(r'd/([^/]+)', raw_url)
        if match: file_id = match.group(1)
    return f"https://drive.google.com/uc?export=view&id={file_id}" if file_id else raw_url

def fetch_all_data():
    global cache_data
    now = time.time()
    if cache_data["last_updated"] > 0 and (now - cache_data["last_updated"] < CACHE_LIMIT):
        return
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        base_path = os.path.dirname(__file__)
        creds_path = os.path.join(base_path, 'credentials.json')
        if not os.path.exists(creds_path): creds_path = 'credentials.json'
        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(SPREADSHEET_ID)
        e_sheet = workbook.worksheet("イベント情報")
        valid_events = [e for e in e_sheet.get_all_records() if e.get("タイトル")]
        qa_sheet = workbook.worksheet("QA")
        knowledge = "\n".join([": ".join(map(str, row)) for row in qa_sheet.get_all_values()])
        cache_data.update({"events": valid_events[-10:], "knowledge": knowledge, "last_updated": now})
    except Exception as e:
        print(f"Sync Error: {e}", flush=True)

def get_ai_response(user_id, user_text, knowledge):
    """会話履歴を考慮してGeminiから回答を取得"""
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    
    # ユーザーの過去の履歴を取得（なければ空リスト）
    history = user_chat_histories.get(user_id, [])

    system_instruction = (
        "あなたは那須町の観光コンシェルジュです。柔和で丁寧な敬語で案内してください。\n"
        "【回答ルール】\n"
        "1. スプレッドシートの知識を最優先し、最新の天気や状況はWEB検索で補完してください。\n"
        "2. これまでの会話の流れを汲み取って、自然な対話を行ってください。\n"
        "3. 回答は150文字以内で、最後は文脈に合わせた自然な挨拶で締めてください。"
    )

    # Geminiに送るメッセージの構成
    # 履歴 + 今回の質問 という形にする
    contents = history + [{"role": "user", "parts": [{"text": f"那須の知識:\n{knowledge}\n\n質問: {user_text}"}]}]

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "tools": [{"google_search": {}}]
    }

    try:
        res = requests.post(api_url, json=payload, timeout=25)
        res_json = res.json()
        
        if 'candidates' in res_json:
            answer = res_json['candidates'][0]['content']['parts'][0]['text']
            
            # 今回の往復を履歴に追加
            history.append({"role": "user", "parts": [{"text": user_text}]})
            history.append({"role": "model", "parts": [{"text": answer}]})
            # 履歴が長くなりすぎないよう制限
            user_chat_histories[user_id] = history[-MAX_HISTORY:]
            
            return answer
        else:
            return "申し訳ございません。うまくお答えできませんでした。"
    except Exception as e:
        print(f"AI Error: {e}")
        return "通信エラーが発生しました。"

# --- Flask Routes ---

@app.route("/", methods=['GET', 'HEAD'])
def index():
    return "Nasu Concierge Bot: Context Mode Active", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id # ユーザーを識別するID
    user_text = event.message.text.strip()
    fetch_all_data()

    if user_text == "AIチャットボット起動":
        user_chat_histories[user_id] = [] # 履歴をリセット
        reply_text = "こんにちは。那須観光コンシェルジュです。何かお手伝いできることはありますか？"
        messages = [TextMessage(text=reply_text)]
    elif any(k in user_text for k in ["イベント", "最新"]):
        flex_content = {"type": "carousel", "contents": []} # 略（必要に応じて前のcreate_event_flexを使用）
        messages = [TextMessage(text="最新のイベント情報ですね。少々お待ちください。")]
    else:
        # 履歴を考慮した回答を取得
        reply_text = get_ai_response(user_id, user_text, cache_data["knowledge"])
        messages = [TextMessage(text=reply_text)]

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, messages=messages
        ))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)