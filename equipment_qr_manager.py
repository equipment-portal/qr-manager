import streamlit as st
import pandas as pd
import qrcode
import os
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
import io
import base64
import json

# --- Excel操作用ライブラリ ---
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter

# --- 画像処理用ライブラリ ---
from PIL import Image, ImageDraw, ImageFont, ImageOps

# --- 初期設定 ---
DB_CSV = Path("devices.csv")
QR_DIR = Path("qr_codes")
MANUAL_DIR = Path("manuals")
EXCEL_LABEL_PATH = Path("print_labels.xlsx")

# --- 履歴管理用の設定 ---
LABEL_HISTORY_FILE = Path("label_history.json")
TEMP_LABEL_DIR = Path("temp_labels")
QR_DIR.mkdir(exist_ok=True)
MANUAL_DIR.mkdir(exist_ok=True)
TEMP_LABEL_DIR.mkdir(exist_ok=True)

# グローバルフォント設定
cloud_font_path = "BIZUDGothic-Regular.ttf"

def setup_fonts():
    if not os.path.exists(cloud_font_path):
        try:
            font_url = "https://github.com/googlefonts/morisawa-biz-ud-gothic/raw/main/fonts/ttf/BIZUDGothic-Regular.ttf"
            urllib.request.urlretrieve(font_url, cloud_font_path)
        except Exception as e:
            pass

setup_fonts()

def safe_filename(name):
    keepcharacters = (' ', '.', '_', '-')
    return "".join(c for c in name if c.isalnum() or c in keepcharacters).rstrip()

# ==========================================
# --- 縦長「機器情報ページ」画像 生成関数 ---
# ==========================================
def create_manual_image(data, output_path):
    W = 1600  
    margin = 80
    content_w = W - margin * 2

    try:
        font_title = ImageFont.truetype(cloud_font_path, 80)
        font_sub = ImageFont.truetype(cloud_font_path, 55)
        font_text = ImageFont.truetype(cloud_font_path, 45)
    except:
        font_title = font_sub = font_text = ImageFont.load_default()

    sections = []
    
    header_h = 380
    header_img = Image.new('RGB', (W, header_h), 'white')
    draw = ImageDraw.Draw(header_img)
    
    draw.rectangle([0, 0, W, 100], fill=(255, 215, 0))
    draw.text((W - margin, 25), f"管理番号: {data['id']}", fill="black", font=font_text, anchor="ra")
    draw.text((margin, 150), data['name'], fill="black", font=font_title)
    draw.rectangle([margin, 280, W - margin, 340], fill=(242, 155, 33))
    power_text = data['power'] if data['power'] else "未設定"
    draw.text((margin + 20, 285), f"■ 使用電源: AC {power_text}", fill="white", font=font_text)
    
    sections.append(header_img)

    def process_img_section(img_file, title):
        if img_file is None:
            box_h = 200
            sec_img = Image.new('RGB', (W, box_h), 'white')
            s_draw = ImageDraw.Draw(sec_img)
            s_draw.text((margin, 20), title, fill="black", font=font_sub)
            s_draw.rectangle([margin, 90, W - margin, box_h - 10], outline="gray", width=3)
            s_draw.text((W // 2, 145), "画像なし", fill="gray", font=font_text, anchor="mm")
            return sec_img
        
        try:
            if hasattr(img_file, 'read'):
                img_data = img_file.read()
                pil_img = Image.open(io.BytesIO(img_data))
            else:
                pil_img = Image.open(img_file)
            
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode in ('RGBA', 'P'):
                pil_img = pil_img.convert('RGB')
            
            img_ratio = pil_img.height / pil_img.width
            new_h = int(content_w * img_ratio)
            pil_img = pil_img.resize((content_w, new_h), Image.Resampling.LANCZOS)
            
            sec_h = 90 + new_h + 50 
            sec_img = Image.new('RGB', (W, sec_h), 'white')
            s_draw = ImageDraw.Draw(sec_img)
            
            s_draw.text((margin, 20), title, fill="black", font=font_sub)
            sec_img.paste(pil_img, (margin, 90))
            s_draw.rectangle([margin, 90, margin + content_w, 90 + new_h], outline="gray", width=3)
            
            return sec_img
        except Exception as e:
            print(f"画像エラー: {e}")
            return None

    img_list = [
        (data.get('img_exterior'), "機器外観"),
        (data.get('img_outlet'), "コンセント位置"),
        (data.get('img_label'), "資産管理ラベル")
    ]
    
    loto_title1 = "LOTO手順書（関連機器）Page 1" if data.get('is_related_loto') else "LOTO手順書 Page 1"
    loto_title2 = "LOTO手順書（関連機器）Page 2" if data.get('is_related_loto') else "LOTO手順書 Page 2"
    
    img_list.append((data.get('img_loto1'), loto_title1))
    img_list.append((data.get('img_loto2'), loto_title2))

    for f, t in img_list:
        sec = process_img_section(f, t)
        if sec:
            sections.append(sec)

    total_h = sum(s.height for s in sections) + 100
    final_img = Image.new('RGB', (W, total_h), 'white')
    
    curr_y = 0
    for s in sections:
        final_img.paste(s, (0, curr_y))
        curr_y += s.height
        
    final_img.save(str(output_path), format="PNG", quality=90)


# ==========================================
# --- 印刷用ラベル生成関数（当初の綺麗なデザインを復元） ---
# ==========================================
def create_label_image(data):
    scale = 4  
    
    font_path = cloud_font_path
    try:
        font_lg = ImageFont.truetype(font_path, 20 * scale)
        font_md = ImageFont.truetype(font_path, 26 * scale)
        font_sm = ImageFont.truetype(font_path, 11 * scale)
        font_xs = ImageFont.truetype(font_path, 9 * scale)
    except Exception as e:
        font_lg = font_md = font_sm = font_xs = ImageFont.load_default()
        
    device_name = data.get('name', '不明')
    device_power = data.get('power', '不明')
    
    # 文字列の長さに合わせて自動で枠を広げる（当初のKaizen）
    dummy_img = Image.new('RGB', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), f"{device_name}", font=font_md)
    text_width = bbox[2] - bbox[0]
    
    x_text = 165 * scale
    padding_right = 25 * scale
    
    base_w = 380 * scale
    required_w = x_text + text_width + padding_right
    w_px = max(base_w, int(required_w))
    h_px = 205 * scale
    
    label_img = Image.new('RGB', (w_px, h_px), 'white')
    draw = ImageDraw.Draw(label_img)
    
    border_color = (255, 255, 0)
    border_width = 12 * scale
    draw.rectangle([0, 0, w_px - 1, h_px - 1], outline=border_color, width=border_width)
    
    title_y = 20 * scale
    draw.text((20 * scale, title_y), "≡", fill="black", font=font_lg)
    draw.text((50 * scale, title_y), "機器情報・LOTO確認ラベル", fill="black", font=font_lg)
    
    if 'img_qr' in data and data['img_qr'] is not None:
        try:
            qr_pil_img = data['img_qr']
            if hasattr(qr_pil_img, 'convert'):
                qr_pil_img = qr_pil_img.convert('RGB')
            qr_pil_img = qr_pil_img.resize((145 * scale, 145 * scale))
            label_img.paste(qr_pil_img, (15 * scale, 48 * scale))
        except Exception as e:
            pass
    
    draw.text((x_text, 55 * scale), "機器名称:", fill="black", font=font_sm)
    draw.text((x_text, 70 * scale), f"{device_name}", fill="black", font=font_md)
    
    draw.text((x_text, 110 * scale), "使用電源:", fill="black", font=font_sm)
    draw.text((x_text, 125 * scale), f"AC {device_power}", fill="black", font=font_md)
    
    y_line = 165 * scale
    draw.line((x_text, y_line, w_px - 15 * scale, y_line), fill="gray", width=1 * scale)
    draw.text((x_text, y_line + 8 * scale), "[QR] 詳細スキャン (LOTO･外観･ｺﾝｾﾝﾄ)", fill="black", font=font_xs)
    
    return label_img


# ==========================================
# --- 高度なExcel履歴管理・再構築システム ---
# ==========================================
def rebuild_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "印刷用ラベルシート"
    
    # --- 【新規】A4横向きの印刷設定 ---
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5
    
    history = []
    if LABEL_HISTORY_FILE.exists():
        try:
            with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass
            
    col_widths = {}
    
    # 40%縮小設定
    shrink_ratio = 0.40
    
    # A4横設定のため、縦には5個並べる
    rows_per_col = 5
    # 間隔を広く取るため、ラベルと空白で2列/2行を1セットにする
    col_multiplier = 2
    row_multiplier = 2

    for count, item in enumerate(history):
        img_path = TEMP_LABEL_DIR / item["img_filename"]
        if not img_path.exists():
            continue
            
        with Image.open(img_path) as tmp_img:
            orig_w = tmp_img.width
            orig_h = tmp_img.height
            
            # --- 画像を40%に縮小したサイズを計算 ---
            target_w = int(orig_w * shrink_ratio)
            target_h = int(orig_h * shrink_ratio)
            
        col_group = count // rows_per_col
        row_in_group = count % rows_per_col

        cell_col = 1 + (col_group * col_multiplier)
        cell_row = 1 + (row_in_group * row_multiplier)
        
        col_letter = get_column_letter(cell_col)
        cell_ref = f"{col_letter}{cell_row}"

        # セルの幅と高さを、40%縮小した画像にぴったり合わせる
        req_col_width = target_w / 7.2
        col_widths[col_letter] = max(col_widths.get(col_letter, 10), req_col_width)
        ws.row_dimensions[cell_row].height = target_h * 0.75
        
        # --- 切り取りやすいように、間隔（空白セル）を広く取る ---
        ws.row_dimensions[cell_row + 1].height = (target_h * 0.75) * 0.8 # 縦の隙間（画像の80%分）
        empty_col_letter = get_column_letter(cell_col + 1)
        col_widths[empty_col_letter] = req_col_width * 0.5 # 横の隙間（画像の半分）

        # 縮小したサイズでExcelに画像を貼り付け
        xl_img = XLImage(str(img_path))
        xl_img.width = target_w
        xl_img.height = target_h
        xl_img.anchor = cell_ref
        ws.add_image(xl_img)

    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    wb.save(EXCEL_LABEL_PATH)

def add_label_to_history(name, label_img):
    history = []
    if LABEL_HISTORY_FILE.exists():
        try:
            with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass
    
    filename = f"label_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    img_path = TEMP_LABEL_DIR / filename
    
    # 履歴保存時は、画質を保つために等倍（380x205ベース）で保存しておく
    orig_w, orig_h = label_img.size
    print_h = 205
    print_w = int((orig_w / orig_h) * print_h)
    
    resized_img = label_img.resize((print_w, print_h), Image.Resampling.LANCZOS)
    resized_img.save(img_path, format='PNG')
    
    history.append({"name": name, "img_filename": filename})
    
    with open(LABEL_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        
    rebuild_excel()

def delete_label_from_history(index):
    history = []
    if LABEL_HISTORY_FILE.exists():
        try:
            with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass
            
    if 0 <= index < len(history):
        img_path = TEMP_LABEL_DIR / history[index]["img_filename"]
        if img_path.exists():
            try:
                img_path.unlink()
            except:
                pass
        history.pop(index)
        
        with open(LABEL_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
            
        rebuild_excel()

def clear_history():
    if EXCEL_LABEL_PATH.exists():
        try: EXCEL_LABEL_PATH.unlink()
        except: pass
    if LABEL_HISTORY_FILE.exists():
        try: LABEL_HISTORY_FILE.unlink()
        except: pass
    for f in TEMP_LABEL_DIR.glob("*.png"):
        try: f.unlink()
        except: pass

# ==========================================
# --- メインアプリ ---
# ==========================================
def main():
    query_params = st.query_params
    is_redirect_mode = "id" in query_params
    
    if is_redirect_mode:
        st.set_page_config(page_title="機器情報ページ", layout="centered")
        
        hide_streamlit_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
        st.markdown(hide_streamlit_style, unsafe_allow_html=True)

        target_id = query_params["id"]
        
        if DB_CSV.exists():
            try:
                df = pd.read_csv(DB_CSV)
                match = df[df["ID"].astype(str) == str(target_id)]
                
                if not match.empty:
                    target_url = match.iloc[-1]["URL"]
                    
                    img_cdn_url = target_url
                    if "github.com" in target_url and "/blob/" in target_url:
                        img_cdn_url = target_url.replace("https://github.com/", "https://cdn.jsdelivr.net/gh/").replace("/blob/", "@")
                        
                    link_html = f"""
                    <div style="text-align: center; margin-top: 60px;">
                        <p style="font-size: 20px; font-weight: bold; color: #333;">✅ 機器情報ページの準備ができました</p>
                        <a href="{img_cdn_url}" style="
                            display: inline-block;
                            margin-top: 15px;
                            padding: 20px 40px;
                            background-color: #28a745;
                            color: white;
                            font-size: 22px;
                            font-weight: bold;
                            text-decoration: none;
                            border-radius: 8px;
                            box-shadow: 0 4px 6px rgba(0,0,0,0.2);
                        ">
                            📱 機器情報ページを開く
                        </a>
                    </div>
                    """
                    st.markdown(link_html, unsafe_allow_html=True)
                else:
                    st.error(f"エラー: 管理番号 '{target_id}' は見つかりませんでした。")
            except Exception as e:
                st.error(f"データベース読み込みエラー: {str(e)}")
        else:
            st.error("エラー: データベースが見つかりません。")
            
    else:
        st.set_page_config(page_title="機器情報ページ＆QR管理", layout="wide", initial_sidebar_state="expanded")
        
        # --- 【新規追加】データベース連動用の裏側ロジック ---
        def load_data_callback():
            selected = st.session_state.db_select
            if selected == "✨ 新規登録 (クリア)":
                st.session_state.input_did = ""
                st.session_state.input_name = ""
                st.session_state.input_power = None
            else:
                did_str = selected.split(" : ")[0]
                df = pd.read_csv(DB_CSV)
                match = df[df["ID"].astype(str) == did_str]
                if not match.empty:
                    row = match.iloc[-1]
                    st.session_state.input_did = str(row["ID"])
                    st.session_state.input_name = str(row["Name"])
                    st.session_state.input_power = str(row["Power"]) if pd.notna(row["Power"]) else None

        hide_streamlit_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
        st.markdown(hide_streamlit_style, unsafe_allow_html=True)
        
        # --- 【新規追加】サイドバー：データベース管理機能 ---
        st.sidebar.header("🗄️ 登録済み機器データベース")
        if DB_CSV.exists():
            df = pd.read_csv(DB_CSV)
            if not df.empty:
                options = ["✨ 新規登録 (クリア)"] + (df["ID"].astype(str) + " : " + df["Name"]).tolist()
                
                selected_edit = st.sidebar.selectbox("編集・確認する機器を選択:", options, key="db_select", on_change=load_data_callback)
                
                if selected_edit != "✨ 新規登録 (クリア)":
                    st.sidebar.warning("⚠️ 過去の写真は保存されていないため、再発行時は画像の再選択が必要です。")
                    if st.sidebar.button("🗑️ この機器をデータベースから削除"):
                        did_to_del = selected_edit.split(" : ")[0]
                        df = df[df["ID"].astype(str) != did_to_del]
                        df.to_csv(DB_CSV, index=False)
                        st.sidebar.success("削除しました！")
                        # 削除後にフォームをクリアしてリロード
                        st.session_state.input_did = ""
                        st.session_state.input_name = ""
                        st.session_state.input_power = None
                        # エラー回避：無理に書き換えず、記憶(セッション)を削除して初期化する
                        if "db_select" in st.session_state:
                            del st.session_state["db_select"]
                        st.rerun()
        
        st.sidebar.markdown("---")
        st.sidebar.header("⚙️ システム詳細設定")
        
        st.sidebar.subheader("💾 自動保存モード設定")
        save_mode = st.sidebar.radio(
            "機器情報ページとQRコードの保存方式を選択:",
            ["1. 手動ダウンロードのみ", "2. システム専用データベースへ自動保存", "3. 社内共有フォルダへ自動保存"],
            index=1,
            key="save_mode_radio"
        )
        
        if save_mode == "2. システム専用データベースへ自動保存":
            st.sidebar.info("💡 データベースの接続キーを設定すると全自動化されます。")
            github_repo = st.sidebar.text_input("データベース領域名", value="equipment-portal/qr-manager")
            
            default_token = st.secrets.get("github_token", "")
            github_token = st.sidebar.text_input(
                "システム接続キー (トークン)", 
                value=default_token, 
                type="password", 
                key="github_token_input"
            )
            
        elif save_mode == "3. 社内共有フォルダへ自動保存":
            st.sidebar.warning("※機能実装準備中※\n会社のPCで直接アプリを動かす（オンプレミス稼働）環境への移行が必要です。")
            local_path = st.sidebar.text_input("共有フォルダのパス (例: Z:\\LOTO手順書)", value=r"C:\Equipment_Manuals")

        st.sidebar.markdown("---")
        st.sidebar.subheader("📄 ファイル名出力設定")
        include_equip_name = st.sidebar.checkbox("ダウンロードファイル名に「機器名称」を含める", value=True)
        
        st.title("📱 機器情報ページ＆QR管理システム")
        st.info("※ この画面はPCでの機器情報ページ作成・台帳登録用です。")
        
        # --- 【強化版】フラグを検知して一番上へ自動スクロールさせる魔法 ---
        if st.session_state.get("scroll_to_top"):
            import streamlit.components.v1 as components
            import time
            # 毎回必ず魔法が発動するようにタイムスタンプを埋め込み、すべてのスクロール領域を強制リセットする
            js = f"""
            <script>
                var ts = "{time.time()}"; 
                var targets = [
                    window.parent.document.querySelector('[data-testid="stAppViewContainer"]'),
                    window.parent.document.querySelector('.main'),
                    window.parent.document.documentElement,
                    window.parent.document.body,
                    window.document.documentElement,
                    window.document.body
                ];
                targets.forEach(function(target) {{
                    if (target) {{
                        target.scrollTo({{top: 0, behavior: 'smooth'}});
                        target.scrollTop = 0;
                    }}
                }});
            </script>
            """
            components.html(js, height=0)
            st.session_state["scroll_to_top"] = False
            
        col1, col2 = st.columns(2)
        
        with col1:
            st.header("1. 基本情報入力")
            # 【変更】セッションステート（記憶領域）と連動
            did = st.text_input("管理番号 (例: 2699)", key="input_did")
            name = st.text_input("機器名称 (例: 5t金型反転機)", key="input_name")
            power = st.selectbox("使用電源", ["100V", "200V"], index=None, placeholder="選択してください", key="input_power")
            
        with col2:
            st.header("2. 画像の指定")
            # 【変更】リセット機能のためにキーを付与
            img_exterior = st.file_uploader("機器外観", type=["png", "jpg", "jpeg"], key="img_exterior")
            img_outlet = st.file_uploader("コンセント位置", type=["png", "jpg", "jpeg"], key="img_outlet")
            img_label = st.file_uploader("資産管理ラベル", type=["png", "jpg", "jpeg"], key="img_label")
            
            is_related_loto = st.checkbox("関連機器・付帯設備のLOTO手順書として登録する")
            
            img_loto1 = st.file_uploader("LOTO手順書（1ページ目）", type=["png", "jpg", "jpeg"], key="img_loto1")
            img_loto2 = st.file_uploader("LOTO手順書（2ページ目）", type=["png", "jpg", "jpeg"], key="img_loto2")
            
        st.markdown("---")
        st.header("3. 機器情報ページ プレビュー確認")
        st.info("💡 発行（データ登録）する前に、まずはここでスマホ用画面の出来栄えや画像の向きをチェックしてください。")
        
        if st.button("🔍 機器情報ページを生成してプレビュー", type="secondary"):
            if did and name and power:
                with st.spinner("プレビューを作成中..."):
                    try:
                        data = {
                            "id": did,
                            "name": name,
                            "power": power,
                            "img_exterior": img_exterior,
                            "img_outlet": img_outlet,
                            "img_label": img_label,
                            "img_loto1": img_loto1,
                            "img_loto2": img_loto2,
                            "is_related_loto": is_related_loto
                        }
                        
                        safe_id = safe_filename(did)
                        manual_path = MANUAL_DIR / f"{safe_id}.png"
                        
                        create_manual_image(data, manual_path)
                        
                        if manual_path.exists():
                            st.success("✨ プレビューの作成に成功しました！内容に問題がなければ、下の「4. データ登録 ＆ 印刷用ラベル発行」に進んでください。")
                            
                            import streamlit.components.v1 as components
                            with open(manual_path, "rb") as f:
                                img_base64 = base64.b64encode(f.read()).decode("utf-8")
                            img_html = f"""
                            <div style="max-height: 500px; overflow-y: scroll; border: 2px solid #ddd; padding: 10px; border-radius: 5px;">
                                <img src="data:image/png;base64,{img_base64}" style="width: 100%; height: auto;">
                            </div>
                            """
                            components.html(img_html, height=520)
                            
                            dl_file_name = f"{safe_id}_{safe_filename(name)}.png" if include_equip_name else f"{safe_id}.png"
                            with open(manual_path, "rb") as img_file:
                                st.download_button(
                                    label="📥 (手動用) プレビューした画像をダウンロード",
                                    data=img_file,
                                    file_name=dl_file_name,
                                    mime="image/png"
                                )
                        else:
                            st.error("エラー：画像の保存に失敗しました。")
                    except Exception as e:
                        st.error(f"プレビュー生成エラー: {str(e)}")
            else:
                st.error("管理番号、機器名称、使用電源は全て必須です。")

        st.markdown("---")
        st.header("4. データ登録 ＆ 印刷用ラベル発行")
        
        if save_mode == "1. 手動ダウンロードのみ":
            long_url = st.text_input("パソコンで画像を開いた時の【上部アドレスバーの長いURL】（登録先等のURL）を貼り付け")
            if st.button("🖨️ 手動設定で印刷用QRラベルを発行する", type="primary"):
                if long_url and did and name and power:
                    try:
                        safe_id = safe_filename(did)
                        qr_path = QR_DIR / f"{safe_id}_qr.png"
                        
                        img_qr = qrcode.make(long_url)
                        img_qr.save(qr_path)
                        
                        if DB_CSV.exists():
                            df = pd.read_csv(DB_CSV)
                            df = df[df["ID"].astype(str) != str(did)]
                        else:
                            df = pd.DataFrame(columns=["ID", "Name", "Power", "URL", "Updated"])
                        
                        new_data = {"ID": did, "Name": name, "Power": power, "URL": long_url, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                        df.to_csv(DB_CSV, index=False)
                        st.success("手動設定でのQRコード生成と台帳登録が完了しました！")
                        
                        st.markdown("---")
                        st.subheader("🏷️ コンセント・タグ用ラベルのダウンロード")
                        label_data = {"name": name, "power": power, "img_qr": img_qr}
                        
                        label_img = create_label_image(label_data)
                        add_label_to_history(name, label_img)
                        
                        buf = io.BytesIO()
                        label_img.save(buf, format="PNG")
                        st.image(label_img, caption="印刷用ラベル（Excelへ自動追記されました）", width=300)
                        
                        label_dl_name = f"{safe_id}_{safe_filename(name)}_label.png" if include_equip_name else f"{safe_id}_label.png"
                        st.download_button(label="📥 画像のみ(PNG)をダウンロード", data=buf.getvalue(), file_name=label_dl_name, mime="image/png")
                    except Exception as e:
                        st.error(f"エラー: {str(e)}")
                else:
                    st.error("「管理番号」「機器名称」「使用電源」「URL」の全てを入力してください。")
                    
        elif save_mode == "2. システム専用データベースへ自動保存":
            st.info("💡 プレビューで問題がなければ、ボタン1つで【データ登録 ＋ QR発行】を全自動で行います。")
            if st.button("🖨️ 【全自動】機器情報ページを登録し、印刷用QRラベルを発行する", type="primary"):
                if not github_repo or not github_token:
                    st.error("左の「⚙️ システム詳細設定」から、データベース領域名と接続キーを入力してください。")
                elif did and name and power:
                    with st.spinner("🔄 データベースへ登録中...（約5〜10秒かかります）"):
                        try:
                            data = {
                                "id": did,
                                "name": name,
                                "power": power,
                                "img_exterior": img_exterior,
                                "img_outlet": img_outlet,
                                "img_label": img_label,
                                "img_loto1": img_loto1,
                                "img_loto2": img_loto2,
                                "is_related_loto": is_related_loto
                            }
                            safe_id = safe_filename(did)
                            manual_path = MANUAL_DIR / f"{safe_id}.png"
                            
                            create_manual_image(data, manual_path)
                            
                            with open(manual_path, "rb") as f:
                                encoded_content = base64.b64encode(f.read()).decode("utf-8")
                            
                            file_name_for_github = f"{safe_id}_{safe_filename(name)}.png" if include_equip_name else f"{safe_id}.png"
                            
                            encoded_file_name = urllib.parse.quote(file_name_for_github)
                            api_url = f"https://api.github.com/repos/{github_repo}/contents/manuals/{encoded_file_name}"
                            
                            sha = None
                            try:
                                req_check = urllib.request.Request(api_url)
                                req_check.add_header("Authorization", f"token {github_token}")
                                with urllib.request.urlopen(req_check) as response:
                                    res_data = json.loads(response.read().decode("utf-8"))
                                    sha = res_data["sha"]
                            except:
                                pass
                                
                            payload = {
                                "message": f"Auto upload {file_name_for_github} from App",
                                "content": encoded_content,
                                "branch": "main"
                            }
                            if sha:
                                payload["sha"] = sha
                                
                            req = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), method="PUT")
                            req.add_header("Authorization", f"token {github_token}")
                            req.add_header("Content-Type", "application/json")
                            req.add_header("Accept", "application/vnd.github.v3+json")
                            
                            with urllib.request.urlopen(req) as response:
                                res_data = json.loads(response.read().decode("utf-8"))
                                github_img_url = res_data["content"]["html_url"]
                            
                            img_cdn_url = github_img_url.replace("https://github.com/", "https://cdn.jsdelivr.net/gh/").replace("/blob/", "@")
                            long_url = img_cdn_url
                            
                            qr_path = QR_DIR / f"{safe_id}_qr.png"
                            
                            img_qr = qrcode.make(img_cdn_url)
                            img_qr.save(qr_path)
                            
                            if DB_CSV.exists():
                                df = pd.read_csv(DB_CSV)
                                df = df[df["ID"].astype(str) != str(did)]
                            else:
                                df = pd.DataFrame(columns=["ID", "Name", "Power", "URL", "Updated"])
                            
                            new_data = {"ID": did, "Name": name, "Power": power, "URL": long_url, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                            df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                            df.to_csv(DB_CSV, index=False)
                            
                            st.success(f"✅ データの登録とQRコード生成が完了しました！\n登録先URL: {long_url}")
                            
                            st.markdown("---")
                            st.subheader("🏷️ コンセント・タグ用ラベルのダウンロード")
                            label_data = {"name": name, "power": power, "img_qr": img_qr}
                            
                            label_img = create_label_image(label_data)
                            add_label_to_history(name, label_img)
                            
                            buf = io.BytesIO()
                            label_img.save(buf, format="PNG")
                            st.image(label_img, caption="印刷用ラベル（Excelへ自動追記されました）", width=300)
                            
                            label_dl_name = f"{safe_id}_{safe_filename(name)}_label.png" if include_equip_name else f"{safe_id}_label.png"
                            st.download_button(label="📥 画像のみ(PNG)をダウンロード", data=buf.getvalue(), file_name=label_dl_name, mime="image/png")
                            
                        except Exception as e:
                            st.error(f"データベース通信エラー: {str(e)}\n※接続キーが間違っているか、権限が不足している可能性があります。")
                else:
                    st.error("管理番号、機器名称、使用電源は全て必須です。")

        # --- 【新規追加】Step 5: 連続入力用のリセットボタン ---
        st.markdown("---")
        st.header("5. 次の作業")
        st.info("💡 続けて別の機器を登録する場合は、以下のボタンを押すと入力内容がリセットされ、一番上に戻ります。")
        
        # エラー回避：ボタンが押された瞬間に実行する「コールバック関数」を定義
        def reset_form_callback():
            st.session_state.input_did = ""
            st.session_state.input_name = ""
            st.session_state.input_power = None
            if "db_select" in st.session_state:
                del st.session_state["db_select"]
            for k in ["img_exterior", "img_outlet", "img_label", "img_loto1", "img_loto2"]:
                if k in st.session_state:
                    del st.session_state[k]
            # 【新規追加】一番上へスクロールさせるためのフラグをONにする
            st.session_state["scroll_to_top"] = True

        # on_click を使って、画面を描き直す「前」にリセット処理を走らせる
        st.button("🔄 次の機器を入力する (クリアして上へ戻る)", type="primary", use_container_width=True, on_click=reset_form_callback)
        # ==========================================
        # --- 🖨️ 印刷用Excel台帳UI ---
        # ==========================================
        st.sidebar.markdown("---")
        st.sidebar.subheader("🖨️ 印刷用Excel台帳")
        
        history = []
        if LABEL_HISTORY_FILE.exists():
            try:
                with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except:
                pass
                
        current_count = len(history)
        
        if current_count == 0:
            st.sidebar.info("🈳 現在、台帳は白紙です。")
        else:
            st.sidebar.success(f"✅ 現在 **{current_count}枚** のラベルが配置されています！")
            
            rows_per_col = 5 
            label_col_multiplier = 2
            total_labels = len(history)
            actual_excel_cols = ((total_labels - 1) // rows_per_col) + 1
            display_cols = actual_excel_cols * label_col_multiplier
            
            grid_html = "<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; font-size:16px; line-height:1.2; text-align:center;'>"
            for r in range(rows_per_col):
                row_str = ""
                for c_set in range(actual_excel_cols):
                    idx = c_set * rows_per_col + r
                    if idx < total_labels:
                        num_char = chr(9311 + idx + 1) if idx < 20 else f"({idx+1})"
                        row_str += f"<span style='display:inline-block; width:25px; font-weight:bold; color:#d4af37;'>{num_char}</span>"
                    else:
                        row_str += "<span style='display:inline-block; width:25px; color:#ccc;'>⬜</span>"
                    
                    row_str += "<span style='display:inline-block; width:25px; color:#ddd;'>⬜</span>"

                grid_html += f"{row_str}<br>"
            grid_html += "</div>"
            
            st.sidebar.markdown("**【現在の配置マップ】**")
            st.sidebar.markdown(grid_html, unsafe_allow_html=True)
            
            st.sidebar.markdown("**【配置済みラベル一覧】**")
            for i, item in enumerate(history):
                col1, col2 = st.sidebar.columns([4, 1])
                num_char = chr(9311 + i + 1) if i < 20 else f"({i+1})"
                col1.write(f"**{num_char}** {item['name']}")
                if col2.button("❌", key=f"del_btn_{i}", help="このラベルを削除して間を詰める"):
                    delete_label_from_history(i)
                    st.rerun()

        if EXCEL_LABEL_PATH.exists():
            with open(EXCEL_LABEL_PATH, "rb") as f:
                st.sidebar.download_button(
                    label="📥 蓄積された最新のExcel台帳をダウンロード",
                    data=f,
                    file_name="print_labels.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            if st.sidebar.button("🗑️ 台帳をリセット (白紙に戻す)"):
                clear_history()
                st.sidebar.success("Excel台帳を白紙にリセットしました！")
                st.rerun()

if __name__ == "__main__":
    main()




