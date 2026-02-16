# set_menu_final.py
from linebot import LineBotApi
from linebot.models import RichMenu, RichMenuSize, RichMenuArea, RichMenuBounds, MessageAction, URIAction

TOKEN = 'KoB1deUCMUCu2xmfUIxVrRvaSm9ecmZk3xtGAZnMgYhcSzbwmOPAvTpZZ8bUGLPiLUTiSuZumLuMUE0GX35wXxwOa5qnrmxp0NNWkiWwW4lXd9ONZLh+pGJfgop53ohwzsCrdeCw+c7WyqsEH+gK8wdB04t89/1O/w1cDnyilFU='
line_bot_api = LineBotApi(TOKEN)

button_configs = [
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#membership-card"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#rally"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#coupons"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#limited-events"}, # 4番目はリンク
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri", "data": "https://chusho-uand3.com/index.html#map"},
    {"type": "uri", "data": "https://www.nasukogen.org/"},
    {"type": "uri", "data": "https://www.nasukogen.org/calendar/"},
    {"type": "message", "data": "AIチャットボット起動"} # 12番目はAI起動メッセージ
]

def main():
    # 既存のメニューを一旦クリア（整理のため）
    menus = line_bot_api.get_rich_menu_list()
    for m in menus:
        line_bot_api.delete_rich_menu(m.rich_menu_id)
        
    # 新規作成
    areas = []
    w, h = 625, 562
    for i, config in enumerate(button_configs):
        action = URIAction(uri=config["data"]) if config["type"] == "uri" else MessageAction(text=config["data"])
        areas.append(RichMenuArea(bounds=RichMenuBounds(x=(i%4)*w, y=(i//4)*h, width=w, height=h), action=action))
    
    rm = RichMenu(size=RichMenuSize(width=2500, height=1686), selected=True, name="FinalMenu", chat_bar_text="メニュー", areas=areas)
    rid = line_bot_api.create_rich_menu(rich_menu=rm)
    with open('menu_image.png', 'rb') as f:
        line_bot_api.set_rich_menu_image(rid, 'image/png', f)
    line_bot_api.set_default_rich_menu(rid)
    print(f"成功！新しいリッチメニューID: {rid}")

if __name__ == "__main__":
    main()