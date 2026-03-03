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
    """スプレッドシートから知識とイベント情報を取得"""
    global cache_data
    now = time.time()
    if cache_data["last_updated"] > 0 and (now - cache_data["last_updated"] < CACHE_LIMIT):
        return
    
    print("--- データの同期を開始します ---", flush=True)
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        # RenderのSecret Filesに保存したcredentials.jsonを読み込み
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(SPREADSHEET_ID)

        # イベント情報
        e_sheet = workbook.worksheet("イベント情報")
        valid_events = [e for e in e_sheet.get_all_records() if e.get("タイトル")]
        
        # QA知識（AIのカンペ）
        qa_sheet = workbook.worksheet("QA")
        knowledge = "\n".join([": ".join(map(str, row)) for row in qa_sheet.get_all_values()])

        cache_data.update({"events": valid_events[-10:], "knowledge": knowledge, "last_updated": now})
        print("--- データの同期に成功しました ---", flush=True)
    except Exception as e:
        print(f"!!! データ同期エラー !!!: {e}", flush=True)

def create_event_flex(events):
    """最新イベントをカルーセルで表示（Flex Message）"""
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

def get_ai_response(user_text, knowledge):
    """Gemini 2.0 Flash + Web検索（スプレッドシート補完モード）"""
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    
    # AIへの「補完」指示
    system_instruction = (
        "あなたは那須町のマスコット『きゅーびー』をイメージした観光コンシェルジュです。\n"
        "【回答ルール】\n"
        "1. 提供された『那須の知識（スプレッドシート）』を第一の正解として扱ってください。\n"
        "2. スプレッドシートにある情報に対して、WEB検索を使って『現在の混雑状況』『今日の営業時間』『最新の口コミ』などの動的な情報を付け加えて補完してください。\n"
        "3. スプレッドシートに全くない情報は、WEB検索で得た信頼できる情報に基づいて回答してください。\n"
        "4. 回答は150文字以内で、丁寧な標準語でまとめてください。\n"
        "5. 最後に『那須での時間が素晴らしいものになりますように。』と添えてください。"
    )

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"parts": [{"text": f"那須の知識:\n{knowledge}\n\n質問: {user_text}"}]}],
        "tools": [{"google_search_retrieval": {"dynamic_retrieval_config": {"mode": "MODE_DYNAMIC", "dynamic_threshold": 0.3}}}]
    }

    try:
        res = requests.post(api_url, json=payload, timeout=25)
        res_json = res.json()
        if 'candidates' in res_json:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"API Error: {res_json}", flush=True)
            return "情報を確認中です。もう一度、別の言い方で聞いてみてください。"
    except Exception as e:
        print(f"AI通信エラー: {e}")
        return "通信エラーが発生しました。那須の山奥で少し電波が届きにくいようです。"

# --- Flask ルート設定 ---

@app.route("/", methods=['GET', 'HEAD'])
def index():
    return "Nasu Concierge Bot: Active (Hybrid Mode)", 200

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
        reply_text = "こんにちは！那須AIコンシェルジュです。那須の観光情報や最新の状況など、何でもお手伝いいたします！"
        messages = [TextMessage(text=reply_text)]
    elif any(k in user_text for k in ["最新", "イベント"]):
        if not cache_data["events"]:
            messages = [TextMessage(text="現在、掲載中のイベント情報はありません。")]
        else:
            flex_content = create_event_flex(cache_data["events"])
            messages = [FlexMessage(alt_text="最新イベント一覧", contents=FlexContainer.from_dict(flex_content))]
    else:
        # AI回答（スプレッドシート + WEB検索）
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