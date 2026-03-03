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
# --- 印刷用ラベル生成関数（QR位置・最終微調整） ---
# ==========================================
def create_label_image(data):
    scale = 4  
    target_w_px = 350 * scale
    target_h_px = 200 * scale
    
    font_path = cloud_font_path
    try:
        font_title = ImageFont.truetype(font_path, 19 * scale) 
        font_main = ImageFont.truetype(font_path, 30 * scale)  
        font_sm = ImageFont.truetype(font_path, 12 * scale)    
        font_footer = ImageFont.truetype(font_path, 13 * scale) 
    except:
        font_title = font_main = font_sm = font_footer = ImageFont.load_default()
        
    device_name = data.get('name', '不明')
    device_power = data.get('power', '不明')
    
    label_img = Image.new('RGB', (target_w_px, target_h_px), 'white')
    draw = ImageDraw.Draw(label_img)
    
    # 黄色い外枠
    border_color = (255, 255, 0)
    border_width = 12 * scale
    draw.rectangle([0, 0, target_w_px - 1, target_h_px - 1], outline=border_color, width=border_width)
    
    # 1段目：タイトル（■記号）
    title_y = 16 * scale
    draw.text((18 * scale, title_y), "■", fill="black", font=font_title)
    draw.text((42 * scale, title_y), "機器情報・LOTO確認ラベル", fill="black", font=font_title)
    
    # --- 【QRコード】90%サイズ ＆ さらに1mm(4px*scale)左へ移動 ---
    qr_size = 72 * scale
    if 'img_qr' in data and data['img_qr'] is not None:
        try:
            qr_pil_img = data['img_qr']
            if hasattr(qr_pil_img, 'convert'): qr_pil_img = qr_pil_img.convert('RGB')
            qr_pil_img = qr_pil_img.resize((qr_size, qr_size))
            # x位置を 18*scale(約4.5mm) から 22*scale(約5.5mm) に増やして左へ寄せる
            label_img.paste(qr_pil_img, (target_w_px - qr_size - 22 * scale, target_h_px - qr_size - 30 * scale))
        except: pass
    
    # --- 【メイン情報エリア】 ---
    x_margin = 18 * scale
    max_text_w = target_w_px - (40 * scale) # 左寄せQRに合わせて微調整
    
    current_size = 30 * scale
    temp_font = font_main
    longest_text = device_name if len(device_name) > len(f"AC {device_power}") else f"AC {device_power}"
    bbox = draw.textbbox((0, 0), longest_text, font=temp_font)
    while (bbox[2] - bbox[0]) > max_text_w and current_size > 12 * scale:
        current_size -= 1 * scale
        temp_font = ImageFont.truetype(font_path, current_size)
        bbox = draw.textbbox((0, 0), longest_text, font=temp_font)

    draw.text((x_margin, 52 * scale), "機器名称:", fill="black", font=font_sm)
    draw.text((x_margin, 66 * scale), device_name, fill="black", font=temp_font)
    draw.text((x_margin, 108 * scale), "使用電源:", fill="black", font=font_sm)
    draw.text((x_margin, 122 * scale), f"AC {device_power}", fill="black", font=temp_font)
    
    # 4段目：フッター
    footer_text = "[QR] 詳細スキャン（外観・コンセント位置・LOTO手順）"
    y_footer = 172 * scale
    f_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
    f_font = font_footer
    f_size = 13 * scale
    while (f_bbox[2] - f_bbox[0]) > (target_w_px - 36 * scale):
        f_size -= 1 * scale
        f_font = ImageFont.truetype(font_path, f_size)
        f_bbox = draw.textbbox((0, 0), footer_text, font=f_font)

    draw.text((x_margin, y_footer), footer_text, fill="black", font=f_font)
    
    return label_img.resize((350, 200), Image.Resampling.LANCZOS)

# ==========================================
# --- エクセル配置システム（ギチギチ密着配置版） ---
# ==========================================
def rebuild_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "印刷用ラベルシート"
    
    # ページ設定
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = 0.2
    ws.page_margins.right = 0.2
    ws.page_margins.top = 0.2
    ws.page_margins.bottom = 0.2
    
    history = []
    if LABEL_HISTORY_FILE.exists():
        try:
            with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f: history = json.load(f)
        except: pass
            
    rows_per_page = 5
    label_w = 350
    label_h = 200

    for count, item in enumerate(history):
        img_path = TEMP_LABEL_DIR / item["img_filename"]
        if not img_path.exists(): continue
            
        col_idx = count // rows_per_page
        row_idx = count % rows_per_page

        # 列と行を 1, 2, 3... と隙間なく指定
        cell_col = col_idx + 1
        cell_row = row_idx + 1
        
        col_letter = get_column_letter(cell_col)
        cell_ref = f"{col_letter}{cell_row}"

        # 0.5mm程度の隙間を作るための微調整（Excelの幅単位 1=約7.5px / 高さ単位 1=約1.3px）
        ws.column_dimensions[col_letter].width = (label_w / 7) + 0.5
        ws.row_dimensions[cell_row].height = (label_h * 0.75) + 2

        xl_img = XLImage(str(img_path))
        xl_img.width = label_w
        xl_img.height = label_h
        xl_img.anchor = cell_ref
        ws.add_image(xl_img)

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
    
    label_img.save(img_path, format='PNG')
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
        
        if "form_reset_key" not in st.session_state:
            st.session_state["form_reset_key"] = 0
        if "extra_images_count" not in st.session_state:
            st.session_state["extra_images_count"] = 0
            
        rk = st.session_state["form_reset_key"]

        # --- サイドバー：データベース管理 ---
        st.sidebar.header("🗄️ 登録済み機器データベース")
        if DB_CSV.exists():
            df = pd.read_csv(DB_CSV)
            if not df.empty:
                options = ["✨ 新規登録 (クリア)"] + (df["ID"].astype(str) + " : " + df["Name"]).tolist()
                
                def load_data_callback():
                    selected = st.session_state.db_select
                    if selected == "✨ 新規登録 (クリア)":
                        st.session_state[f"input_did_{rk}"] = ""
                        st.session_state[f"input_name_{rk}"] = ""
                        st.session_state[f"input_power_{rk}"] = None
                    else:
                        did_str = selected.split(" : ")[0]
                        df_db = pd.read_csv(DB_CSV)
                        match = df_db[df_db["ID"].astype(str) == did_str]
                        if not match.empty:
                            row = match.iloc[-1]
                            st.session_state[f"input_did_{rk}"] = str(row["ID"])
                            st.session_state[f"input_name_{rk}"] = str(row["Name"])
                            st.session_state[f"input_power_{rk}"] = str(row["Power"]) if pd.notna(row["Power"]) else None

                st.sidebar.selectbox("編集・確認する機器を選択:", options, key="db_select", on_change=load_data_callback)
                
                if st.session_state.db_select != "✨ 新規登録 (クリア)":
                    st.sidebar.warning("⚠️ 過去の写真は保存されていないため、再セットが必要です。")
                    if st.sidebar.button("🗑️ この機器をデータベースから削除"):
                        did_to_del = st.session_state.db_select.split(" : ")[0]
                        df = df[df["ID"].astype(str) != did_to_del]
                        df.to_csv(DB_CSV, index=False)
                        st.sidebar.success("削除しました！")
                        st.session_state["form_reset_key"] += 1
                        st.rerun()
        
        st.sidebar.markdown("---")
        st.sidebar.header("⚙️ システム詳細設定")
        save_mode = st.sidebar.radio("保存方式を選択:", ["1. 手動ダウンロードのみ", "2. システム専用データベースへ自動保存"], index=1)
        
        if save_mode == "2. システム専用データベースへ自動保存":
            github_repo = st.sidebar.text_input("データベース領域名", value="equipment-portal/qr-manager")
            github_token = st.sidebar.text_input("接続キー(トークン)", value=st.secrets.get("github_token", ""), type="password")

        st.sidebar.subheader("📄 ファイル名出力設定")
        include_equip_name = st.sidebar.checkbox("ダウンロード名に「機器名称」を含める", value=True)
        
        # --- メイン画面 ---
        st.markdown("<div id='top_anchor'></div>", unsafe_allow_html=True)
        st.title("📱 機器情報ページ＆QR管理システム")

        if st.session_state.get("scroll_to_top"):
            import streamlit.components.v1 as components
            js = f"""<script>var target = window.parent.document.getElementById('top_anchor') || window.parent.document.querySelector('h1');
            if (target) {{ target.scrollIntoView(true); }} else {{ window.parent.scrollTo(0, 0); }}</script>"""
            components.html(js, height=0)
            st.session_state["scroll_to_top"] = False

        col1, col2 = st.columns(2)
        
        with col1:
            st.header("1. 基本情報入力")
            did = st.text_input("管理番号 (例: 2699)", key=f"input_did_{rk}")
            name = st.text_input("機器名称 (例: 5t金型反転機)", key=f"input_name_{rk}")
            power = st.selectbox("使用電源", ["100V", "200V"], index=None, placeholder="選択してください", key=f"input_power_{rk}")
            
        with col2:
            st.header("2. 画像の指定")
            img_exterior = st.file_uploader("機器外観", type=["png", "jpg", "jpeg"], key=f"img_ext_{rk}")
            img_outlet = st.file_uploader("コンセント位置", type=["png", "jpg", "jpeg"], key=f"img_out_{rk}")
            img_label = st.file_uploader("資産管理ラベル", type=["png", "jpg", "jpeg"], key=f"img_lab_{rk}")
            is_related_loto = st.checkbox("関連機器・付帯設備のLOTO手順書として登録する", key=f"is_loto_{rk}")
            img_loto1 = st.file_uploader("LOTO手順書（1ページ目）", type=["png", "jpg", "jpeg"], key=f"img_l1_{rk}")
            img_loto2 = st.file_uploader("LOTO手順書（2ページ目）", type=["png", "jpg", "jpeg"], key=f"img_l2_{rk}")
            
            st.markdown("---")
            st.subheader("➕ 追加画像の登録")
            extra_images = []
            for i in range(st.session_state["extra_images_count"]):
                st.markdown(f"**追加項目 {i+1}**")
                ex_title = st.text_input(f"タイトル", key=f"ex_title_{rk}_{i}")
                ex_img = st.file_uploader(f"画像", type=["png", "jpg", "jpeg"], key=f"ex_img_{rk}_{i}")
                if ex_img:
                    extra_images.append((ex_img, ex_title if ex_title else f"追加画像 {i+1}"))
            
            if st.button("➕ 画像を追加する"):
                st.session_state["extra_images_count"] += 1
                st.rerun()

            st.markdown("---")
            st.subheader("📝 その他情報の入力")
            memo_text = st.text_area("メモ・備考", placeholder="補足情報を入力...", key=f"memo_{rk}")

        st.markdown("---")
        st.header("3. プレビュー確認")
        if st.button("🔍 機器情報ページを生成してプレビュー", type="secondary"):
            if did and name and power:
                with st.spinner("生成中..."):
                    data = {
                        "id": did, "name": name, "power": power, 
                        "img_exterior": img_exterior, "img_outlet": img_outlet, "img_label": img_label,
                        "img_loto1": img_loto1, "img_loto2": img_loto2, "is_related_loto": is_related_loto,
                        "memo": memo_text if memo_text.strip() else "なし"
                    }
                    safe_id = safe_filename(did)
                    manual_path = MANUAL_DIR / f"{safe_id}.png"
                    create_manual_image_extended(data, extra_images, manual_path)
                    if manual_path.exists():
                        st.success("✨ プレビュー完成！")
                        import streamlit.components.v1 as components
                        with open(manual_path, "rb") as f:
                            img_base64 = base64.b64encode(f.read()).decode("utf-8")
                        components.html(f'<div style="max-height: 500px; overflow-y: scroll;"><img src="data:image/png;base64,{img_base64}" style="width: 100%;"></div>', height=520)

        st.markdown("---")
        st.header("4. データ登録 ＆ ラベル発行")
        if st.button("🖨️ 【全自動】登録してQRラベルを発行する", type="primary"):
            if did and name and power:
                with st.spinner("通信中..."):
                    try:
                        safe_id = safe_filename(did)
                        manual_path = MANUAL_DIR / f"{safe_id}.png"
                        data = {
                            "id": did, "name": name, "power": power, 
                            "img_exterior": img_exterior, "img_outlet": img_outlet, "img_label": img_label,
                            "img_loto1": img_loto1, "img_loto2": img_loto2, "is_related_loto": is_related_loto,
                            "memo": memo_text if memo_text.strip() else "なし"
                        }
                        create_manual_image_extended(data, extra_images, manual_path)
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
                                sha = json.loads(response.read().decode("utf-8"))["sha"]
                        except: pass
                        payload = {"message": f"Upload {file_name_for_github}", "content": encoded_content, "branch": "main"}
                        if sha: payload["sha"] = sha
                        req = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), method="PUT")
                        req.add_header("Authorization", f"token {github_token}")
                        with urllib.request.urlopen(req) as response:
                            github_img_url = json.loads(response.read().decode("utf-8"))["content"]["html_url"]
                        img_cdn_url = github_img_url.replace("https://github.com/", "https://cdn.jsdelivr.net/gh/").replace("/blob/", "@")
                        img_qr = qrcode.make(img_cdn_url)
                        if DB_CSV.exists():
                            df = pd.read_csv(DB_CSV)
                            df = df[df["ID"].astype(str) != str(did)]
                        else:
                            df = pd.DataFrame(columns=["ID", "Name", "Power", "URL", "Updated"])
                        new_row = {"ID": did, "Name": name, "Power": power, "URL": img_cdn_url, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                        pd.concat([df, pd.DataFrame([new_row])], ignore_index=True).to_csv(DB_CSV, index=False)
                        label_img = create_label_image({"name": name, "power": power, "img_qr": img_qr})
                        add_label_to_history(name, label_img)
                        st.success(f"✅ 登録完了！ URL: {img_cdn_url}")
                        st.image(label_img, caption="発行されたラベル", width=300)
                    except Exception as e:
                        st.error(f"エラー: {str(e)}")

        st.markdown("---")
        st.header("5. 次の作業")
        def reset_callback():
            st.session_state["form_reset_key"] += 1
            st.session_state["extra_images_count"] = 0
            st.session_state["scroll_to_top"] = True
        st.button("🔄 次の機器を入力する (クリアして上へ戻る)", type="primary", use_container_width=True, on_click=reset_callback)

        # --- サイドバー：Excel台帳（修正版：配置マップ復旧） ---
        st.sidebar.markdown("---")
        st.sidebar.subheader("🖨️ 印刷用Excel台帳")
        history = []
        if LABEL_HISTORY_FILE.exists():
            try:
                with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f: history = json.load(f)
            except: pass
        current_count = len(history)
        if current_count == 0:
            st.sidebar.info("🈳 現在、台帳は白紙です。")
        else:
            st.sidebar.success(f"✅ 現在 **{current_count}枚** 配置中！")
            
            # --- 配置マップ表示ロジック ---
            rows_per_page = 5 
            actual_cols = ((current_count - 1) // rows_per_page) + 1
            grid_html = "<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; font-size:16px; line-height:1.2; text-align:center;'>"
            for r in range(rows_per_page):
                row_str = ""
                for c in range(actual_cols):
                    idx = c * rows_per_page + r
                    if idx < current_count:
                        num_char = chr(9311 + idx + 1) if idx < 20 else f"({idx+1})"
                        row_str += f"<span style='display:inline-block; width:28px; font-weight:bold; color:#d4af37;'>{num_char}</span>"
                    else:
                        row_str += "<span style='display:inline-block; width:28px; color:#ccc;'>⬜</span>"
                grid_html += f"{row_str}<br>"
            grid_html += "</div>"
            st.sidebar.markdown(grid_html, unsafe_allow_html=True)
            
            for i, item in enumerate(history):
                col1, col2 = st.sidebar.columns([4, 1])
                col1.write(f"**{i+1}** {item['name']}")
                if col2.button("❌", key=f"del_label_{i}"):
                    delete_label_from_history(i)
                    st.rerun()
                    
        if EXCEL_LABEL_PATH.exists():
            with open(EXCEL_LABEL_PATH, "rb") as f:
                st.sidebar.download_button("📥 Excel台帳をダウンロード", data=f, file_name="print_labels.xlsx")
            if st.sidebar.button("🗑️ 台帳をリセット"):
                clear_history()
                st.rerun()

# --- 【修正版】メモ拡大と追加画像に対応した拡張画像生成関数 ---
def create_manual_image_extended(data, extra_images, output_path):
    W = 1600  
    margin = 80
    content_w = W - margin * 2
    try:
        font_sub = ImageFont.truetype(cloud_font_path, 65) # セクションタイトル拡大
        font_text = ImageFont.truetype(cloud_font_path, 55) # メモ本文拡大
    except:
        font_sub = font_text = ImageFont.load_default()

    create_manual_image(data, output_path)
    base_img = Image.open(output_path)
    added_sections = []

    for ex_img_file, ex_title in extra_images:
        try:
            pil_img = Image.open(ex_img_file)
            pil_img = ImageOps.exif_transpose(pil_img).convert('RGB')
            new_h = int(content_w * (pil_img.height / pil_img.width))
            pil_img = pil_img.resize((content_w, new_h), Image.Resampling.LANCZOS)
            sec_h = 100 + new_h + 60
            sec_img = Image.new('RGB', (W, sec_h), 'white')
            draw = ImageDraw.Draw(sec_img)
            draw.text((margin, 25), ex_title, fill="black", font=font_sub)
            sec_img.paste(pil_img, (margin, 100))
            draw.rectangle([margin, 100, margin + content_w, 100 + new_h], outline="gray", width=3)
            added_sections.append(sec_img)
        except: continue

    memo_val = data.get("memo", "なし")
    import textwrap
    lines = textwrap.wrap(memo_val, width=32) # 文字を大きくしたので折り返し幅を短く
    line_h = 80 # 行間を広く
    memo_box_h = 120 + (len(lines) * line_h) + 60
    
    memo_sec = Image.new('RGB', (W, memo_box_h), 'white')
    m_draw = ImageDraw.Draw(memo_sec)
    m_draw.text((margin, 30), "■ メモ・備考", fill="black", font=font_sub)
    m_draw.rectangle([margin, 110, W - margin, memo_box_h - 30], outline=(242, 155, 33), width=6)
    for i, line in enumerate(lines):
        m_draw.text((margin + 40, 130 + (i * line_h)), line, fill="black", font=font_text)
    added_sections.append(memo_sec)

    total_h = base_img.height + sum(s.height for s in added_sections) + 50
    final_img = Image.new('RGB', (W, total_h), 'white')
    final_img.paste(base_img, (0, 0))
    curr_y = base_img.height
    for s in added_sections:
        final_img.paste(s, (0, curr_y))
        curr_y += s.height
    final_img.save(output_path)

if __name__ == "__main__":
    main()

