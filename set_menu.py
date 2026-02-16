from linebot import LineBotApi
from linebot.models import (
    RichMenu, RichMenuSize, RichMenuArea, 
    RichMenuBounds, MessageAction, URIAction
)

# --- 設定 ---
TOKEN = 'KoB1deUCMUCu2xmfUIxVrRvaSm9ecmZk3xtGAZnMgYhcSzbwmOPAvTpZZ8bUGLPiLUTiSuZumLuMUE0GX35wXxwOa5qnrmxp0NNWkiWwW4lXd9ONZLh+pGJfgop53ohwzsCrdeCw+c7WyqsEH+gK8wdB04t89/1O/w1cDnyilFU='
line_bot_api = LineBotApi(TOKEN)

# 12個のボタン設定（最新版：AIチャット復活）
button_configs = [
    # 1段目
    {"type": "uri",     "label": "card",     "data": "https://chusho-uand3.com/index.html#membership-card"},
    {"type": "uri",     "label": "stamp",    "data": "https://chusho-uand3.com/index.html#rally"},
    {"type": "uri",     "label": "coupons",  "data": "https://chusho-uand3.com/index.html#coupons"},
    {"type": "uri",     "label": "limited",  "data": "https://chusho-uand3.com/index.html#limited-events"}, # サイトへのリンク
    
    # 2段目
    {"type": "uri",     "label": "hotel",    "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri",     "label": "gurume",   "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri",     "label": "reja",     "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri",     "label": "onsen",    "data": "https://chusho-uand3.com/index.html#map"},
    
    # 3段目
    {"type": "uri",     "label": "pet",      "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri",     "label": "kanko",    "data": "https://www.nasukogen.org/"},
    {"type": "uri",     "label": "calendar", "data": "https://www.nasukogen.org/calendar/"},
    {"type": "message", "label": "chat",     "data": "AIチャットボット起動"} # AI起動メッセージ
]

def create_rich_menu():
    areas = []
    width = 625 
    height = 562
    
    for i, config in enumerate(button_configs):
        row = i // 4
        col = i % 4
        
        if config["type"] == "uri":
            action = URIAction(label=config["label"], uri=config["data"])
        else:
            action = MessageAction(label=config["label"], text=config["data"])
            
        area = RichMenuArea(
            bounds=RichMenuBounds(x=col * width, y=row * height, width=width, height=height),
            action=action
        )
        areas.append(area)
    
    return RichMenu(
        size=RichMenuSize(width=2500, height=1686),
        selected=True,
        name="Uand3-Integrated-Menu-Final",
        chat_bar_text="メニューを表示",
        areas=areas
    )

def main():
    try:
        # 1. 登録
        rich_menu_id = line_bot_api.create_rich_menu(rich_menu=create_rich_menu())
        # 2. 画像アップロード
        with open('menu_image.png', 'rb') as f:
            line_bot_api.set_rich_menu_image(rich_menu_id, 'image/png', f)
        # 3. デフォルト設定
        line_bot_api.set_default_rich_menu(rich_menu_id)
        
        print(f"成功！新しいID: {rich_menu_id}")
    except Exception as e:
        print(f"エラー: {e}")

if __name__ == "__main__":
    main()