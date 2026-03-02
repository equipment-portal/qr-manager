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
# --- 印刷用ラベル生成関数（実寸：3.8x2cm対応） ---
# ==========================================
def create_label_image(data):
    # 【究極Kaizen】印刷実寸 3.8cm × 2cm にピタリと合わせる設計

    # Pillow内での描画用スケール（高画質を保つために倍率をかけるが、
    # 最終的なピクセル数はエクセルに貼り付ける「縦横比」だけを重要視する）
    # 印刷実寸 38mm x 20mm の比率 (1.9 : 1) を保つ必要がある。
    scale = 8
    
    # フォントサイズを実寸に合わせて調整（非常に小さくなるため慎重に）
    font_path = cloud_font_path
    try:
        font_lg = ImageFont.truetype(font_path, 20 * scale) # ≡記号とタイトル
        font_md = ImageFont.truetype(font_path, 28 * scale) # 機器名称・電源AC200V（少し強調）
        font_sm = ImageFont.truetype(font_path, 13 * scale) # 「機器名称:」ラベル
        font_xs = ImageFont.truetype(font_path, 11 * scale) # [QR]詳細スキャン
    except Exception as e:
        font_lg = font_md = font_sm = font_xs = ImageFont.load_default()
        
    device_name = data.get('name', '不明')
    device_power = data.get('power', '不明')
    
    # --- 【サイズ設計】 ---
    # 38mm x 20mm のアスペクト比 (38:20 = 1.9:1) をピクセルに変換。
    # openpyxlでエクセルに貼る際、画像のピクセルサイズにセルの高さを合わせる手法を取る。
    
    # 最終的な画像のターゲットピクセルサイズ（エクセルに「そのまま」貼る）
    target_h_px = 200 # 20mmに相当
    target_w_px = 380 # 38mmに相当

    # 描画キャンバスのサイズ（高解像度で描き、最後に縮小する）
    h_px = target_h_px * scale
    w_px = target_w_px * scale
    
    label_img = Image.new('RGB', (w_px, h_px), 'white')
    draw = ImageDraw.Draw(label_img)
    
    # --- 【レイアウト調整】 ---
    # 実寸が小さいため、余白（マージン）を極限まで削る
    left_margin = 10 * scale
    top_margin = 10 * scale
    
    # 黄色の枠線（実寸が小さいため細く）
    border_color = (255, 255, 0)
    border_width = 12 * scale # 実寸で約1mm弱
    draw.rectangle([0, 0, w_px - 1, h_px - 1], outline=border_color, width=border_width)
    
    # 1段目：タイトル
    title_y = 10 * scale
    draw.text((20 * scale, title_y), "≡", fill="black", font=font_lg)
    draw.text((60 * scale, title_y), "機器情報・LOTO確認ラベル", fill="black", font=font_lg)
    
    # QRコード（実寸が小さいため、ラベルの左下を大きく占有させる）
    if 'img_qr' in data and data['img_qr'] is not None:
        try:
            qr_pil_img = data['img_qr']
            if hasattr(qr_pil_img, 'convert'):
                qr_pil_img = qr_pil_img.convert('RGB')
            # 実寸2cmの中に、約1.2cm四方のQRを配置
            qr_size_px = 120 * scale 
            qr_pil_img = qr_pil_img.resize((qr_size_px, qr_size_px))
            label_img.paste(qr_pil_img, (15 * scale, 55 * scale))
        except Exception as e:
            pass
    
    # テキストエリア（QRコードの右側）
    x_text = 150 * scale
    
    # 2段目：機器名称（フォントを少し大きく）
    draw.text((x_text, 60 * scale), "機器名称:", fill="black", font=font_sm)
    draw.text((x_text, 78 * scale), f"{device_name}", fill="black", font=font_md)
    
    # 3段目：使用電源（AC 200V を大きく表示）
    draw.text((x_text, 120 * scale), "使用電源:", fill="black", font=font_sm)
    draw.text((x_text, 138 * scale), f"AC {device_power}", fill="black", font=font_md)
    
    # 4段目：フッター（[QR]詳細スキャン）
    y_footer = 180 * scale
    draw.text((x_text, y_footer), "[QR] 詳細スキャン (LOTO･外観･ｺﾝｾﾝﾄ)", fill="black", font=font_xs)
    
    # --- 【実寸へのリサイズ】 ---
    # 高解像度で描いたものを、最終ターゲットピクセルサイズ (380x200) へ縮小。
    # これにより、文字のギザギザが消え、非常にクッキリとしたラベルになる。
    final_label_img = label_img.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)
    
    return final_label_img

# ==========================================
# --- エクセル配置システム（サイズ・間隔Kaizen版） ---
# ==========================================
def rebuild_excel():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "印刷用ラベルシート"
    
    history = []
    if LABEL_HISTORY_FILE.exists():
        try:
            with open(LABEL_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass
            
    # 【究極Kaizen】セルのサイズを、ラベルの実寸に合わせる手法に変更。
    # openpyxlは画像をセルにぴったり収めるのが得意ではないため、
    # 1セル＝1ラベル画像とし、セルの高さ・幅を画像と同じに設定する。
    
    # PILで生成した画像のサイズ (create_label_image関数で target_h_px=200, target_w_px=380 と設定)
    pil_w = 380
    pil_h = 200
    
    # エクセルでの配置設定
    rows_per_col = 10 # 1列に10枚まで並べる
    # 【Kaizen】間隔を広げるため、隣り合うラベルの間に「空白セル」を2行/2列挟む
    col_multiplier = 3 # ラベル・空白・空白 で1セット
    row_multiplier = 3 # ラベル・空白・空白 で1セット

    for count, item in enumerate(history):
        img_path = TEMP_LABEL_DIR / item["img_filename"]
        if not img_path.exists():
            continue
            
        col_group = count // rows_per_col
        row_in_group = count % rows_per_col

        # セルの位置を計算（1, 1から始まり、3ずつ増える）
        cell_col = 1 + (col_group * col_multiplier)
        cell_row = 1 + (row_in_group * row_multiplier)
        
        col_letter = get_column_letter(cell_col)
        cell_ref = f"{col_letter}{cell_row}"

        # --- 【実寸合わせ魔法】セルの幅と高さを画像のピクセル数に合わせる ---
        # セルの幅 (ColumnWidth): PILのピクセル数 / 7.23 (非常に大雑把な変換式)
        # 実寸3.8cm (380px) に合わせるための数値
        ws.column_dimensions[col_letter].width = pil_w / 7.2
        
        # セルの高さ (RowHeight): PILのピクセル数 * 0.75 (ピクセル->ポイント変換)
        # 実寸2.0cm (200px) に合わせるための数値。
        # ExcelはRowHeightを最優先するため、これが実寸を決定づける。
        # 200px * 0.75 = 150ポイント。これをRowHeightに設定する。
        # PILのh=200, scale=8で描いているが、貼り付けるRowHeight=150ポイントが実寸(2cm)になる。
        ws.row_dimensions[cell_row].height = pil_h * 0.75

        # 画像をエクセル用に読み込む
        xl_img = XLImage(str(img_path))
        
        # アンカー（画像の左上基準点）を設定
        xl_img.anchor = cell_ref
        
        # シートに追加
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
    
    # create_label_image関数で既にリサイズされているため、ここではそのまま保存
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

# --- メインアプリ ---
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
        
        hide_streamlit_style = """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
        """
        st.markdown(hide_streamlit_style, unsafe_allow_html=True)
        
        st.sidebar.header("⚙️ システム詳細設定")
        
        st.sidebar.markdown("---")
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
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.header("1. 基本情報入力")
            did = st.text_input("管理番号 (例: 2699)")
            name = st.text_input("機器名称 (例: 5t金型反転機)")
            power = st.selectbox("使用電源", ["100V", "200V"], index=None, placeholder="選択してください")
            
        with col2:
            st.header("2. 画像の指定")
            img_exterior = st.file_uploader("機器外観", type=["png", "jpg", "jpeg"])
            img_outlet = st.file_uploader("コンセント位置", type=["png", "jpg", "jpeg"])
            img_label = st.file_uploader("資産管理ラベル", type=["png", "jpg", "jpeg"])
            
            is_related_loto = st.checkbox("関連機器・付帯設備のLOTO手順書として登録する")
            
            img_loto1 = st.file_uploader("LOTO手順書（1ページ目）", type=["png", "jpg", "jpeg"])
            img_loto2 = st.file_uploader("LOTO手順書（2ページ目）", type=["png", "jpg", "jpeg"])
            
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
                        
                        # --- 修正点：Kaizen後のラベル生成関数を呼び出す ---
                        label_img = create_label_image(label_data)
                        add_label_to_history(name, label_img)
                        
                        buf = io.BytesIO()
                        # 実寸ピクセルのPNGをプレビュー＆ダウンロード用にバッファに保存
                        label_img.save(buf, format="PNG")
                        # プレビューでは少し拡大して見せる（ width=200px ）
                        st.image(label_img, caption="印刷用ラベル（Excelへ自動追記されました）", width=200)
                        
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
                            
                            # --- 修正点：Kaizen後のラベル生成関数を呼び出す ---
                            label_img = create_label_image(label_data)
                            add_label_to_history(name, label_img)
                            
                            buf = io.BytesIO()
                            label_img.save(buf, format="PNG")
                            st.image(label_img, caption="印刷用ラベル（Excelへ自動追記されました）", width=200)
                            
                            label_dl_name = f"{safe_id}_{safe_filename(name)}_label.png" if include_equip_name else f"{safe_id}_label.png"
                            st.download_button(label="📥 画像のみ(PNG)をダウンロード", data=buf.getvalue(), file_name=label_dl_name, mime="image/png")
                            
                        except Exception as e:
                            st.error(f"データベース通信エラー: {str(e)}\n※接続キーが間違っているか、権限が不足している可能性があります。")
                else:
                    st.error("管理番号、機器名称、使用電源は全て必須です。")

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
            
            # 配置マップの表示 Kaizen
            rows_per_col = 10 # エクセル設計と同じ数にする
            # 3列に1セット配置されるため、display_colsの計算を合わせる
            label_col_ multiplier = 3
            last_idx = history[-1]['name']
            total_labels = len(history)
            actual_excel_cols = ((total_labels - 1) // rows_per_col) + 1
            display_cols = actual_excel_cols * label_col_multiplier
            
            grid_html = "<div style='background-color:#f0f2f6; padding:10px; border-radius:5px; font-size:16px; line-height:1.2; text-align:center;'>"
            for r in range(rows_per_col):
                row_str = ""
                for c_set in range(actual_excel_cols):
                    # 1セット（ラベル・空白・空白）を描画
                    idx = c_set * rows_per_col + r
                    if idx < total_labels:
                        num_char = chr(9311 + idx + 1) if idx < 20 else f"({idx+1})"
                        row_str += f"<span style='display:inline-block; width:25px; font-weight:bold; color:#d4af37;'>{num_char}</span>"
                    else:
                        row_str += "<span style='display:inline-block; width:25px; color:#ccc;'>⬜</span>"
                    
                    # 空白セルを2つ挟む（間隔Kaizenをマップに反映）
                    row_str += "<span style='display:inline-block; width:25px; color:#ddd;'>⬜</span>"
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
