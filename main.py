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

# キャッシュ管理（スプレッドシートの負荷軽減）
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
    """スプレッドシートからQA知識とイベント情報を取得"""
    global cache_data
    now = time.time()
    if cache_data["last_updated"] > 0 and (now - cache_data["last_updated"] < CACHE_LIMIT):
        return
    
    print("--- スプレッドシート同期開始 ---", flush=True)
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(SPREADSHEET_ID)

        # イベント情報の読み込み
        e_sheet = workbook.worksheet("イベント情報")
        valid_events = [e for e in e_sheet.get_all_records() if e.get("タイトル")]
        
        # QA知識の読み込み
        qa_sheet = workbook.worksheet("QA")
        # すべての行をテキストとして結合してAIの知識にする
        qa_values = qa_sheet.get_all_values()
        knowledge = "\n".join([": ".join(map(str, row)) for row in qa_values])

        cache_data.update({"events": valid_events[-10:], "knowledge": knowledge, "last_updated": now})
        print("--- 同期成功 ---", flush=True)
    except Exception as e:
        print(f"!!! 同期エラー !!!: {e}", flush=True)

def get_ai_response(user_text, knowledge):
    """Gemini 2.0 Flash による回答生成（Web検索なし・スプレッドシート特化）"""
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    
    system_instruction = (
        "あなたは那須町のマスコット『きゅーびー』をイメージした観光コンシェルジュです。\n"
        "【回答ルール】\n"
        "1. 提供された『那須の知識（スプレッドシート）』に基づいて回答してください。\n"
        "2. 丁寧で誠実な標準語で話してください。\n"
        "3. 知識にない質問をされた場合は、無理に答えず『勉強不足で申し訳ありません。那須観光協会公式サイトなどをご確認いただけますでしょうか』と丁寧に案内してください。\n"
        "4. 回答は簡潔に、150文字以内でまとめてください。"
    )

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"parts": [{"text": f"那須の知識:\n{knowledge}\n\n質問: {user_text}"}]}]
        # Web検索ツール（tools）は削除しました
    }

    try:
        res = requests.post(api_url, json=payload, timeout=20)
        res_json = res.json()
        
        if 'candidates' in res_json:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"API Error Response: {res_json}", flush=True)
            return "申し訳ありません。うまく回答を生成できませんでした。もう一度短く聞いてみてください。"
    except Exception as e:
        print(f"AI通信エラー: {e}", flush=True)
        return "通信エラーが発生しました。時間を置いて再度お試しください。"

# --- Flask 窓口設定 ---

@app.route("/", methods=['GET', 'HEAD'])
def index():
    return "Nasu Concierge Bot: Active (Spreadsheet Mode)", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"Webhook Error: {e}")
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    fetch_all_data()

    if user_text == "AIチャットボット起動":
        reply_text = "こんにちは！那須AIコンシェルジュです。那須の観光情報について、お手伝いできることはありますか？"
        messages = [TextMessage(text=reply_text)]
    elif any(k in user_text for k in ["最新", "イベント"]):
        if not cache_data["events"]:
            messages = [TextMessage(text="現在、掲載中のイベント情報はありません。")]
        else:
            from linebot.v3.messaging import FlexMessage, FlexContainer
            # create_event_flex 関数が別途必要ですが、以前のものを流用
            # ここでは簡易的にテキストで返すか、以前の関数を上に定義してください
            messages = [TextMessage(text="最新イベント情報を読み込んでいます...")]
    else:
        reply_text = get_ai_response(user_text, cache_data["knowledge"])
        messages = [TextMessage(text=reply_text)]

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, 
            messages=messages
        ))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)