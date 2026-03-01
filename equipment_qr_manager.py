import streamlit as st
import pandas as pd
import qrcode
import os
import urllib.request
from pathlib import Path
from datetime import datetime
import io
from PIL import Image, ImageDraw, ImageFont, ImageOps

# PDF生成用ライブラリ
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

# --- 初期設定 ---
DB_CSV = Path("devices.csv")
QR_DIR = Path("qr_codes")
PDF_DIR = Path("pdfs")
QR_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

# グローバルフォント設定
FONT_NAME = "Helvetica"
cloud_font_path = "BIZUDGothic-Regular.ttf"

# --- 日本語フォントの設定（クラウド対応）---
def setup_fonts():
    """フォントのセットアップを行う（重複登録を避ける）"""
    global FONT_NAME, cloud_font_path
    
    try:
        if not os.path.exists(cloud_font_path):
            font_url = "https://github.com/googlefonts/morisawa-biz-ud-gothic/raw/main/fonts/ttf/BIZUDGothic-Regular.ttf"
            urllib.request.urlretrieve(font_url, cloud_font_path)
        
        if "BIZUDGothic" not in pdfmetrics._fonts:
            pdfmetrics.registerFont(TTFont("BIZUDGothic", cloud_font_path))
        FONT_NAME = "BIZUDGothic"
    except Exception as e:
        try:
            win_font_path = "C:/Windows/Fonts/meiryo.ttc"
            if "Meiryo" not in pdfmetrics._fonts:
                pdfmetrics.registerFont(TTFont("Meiryo", win_font_path))
            FONT_NAME = "Meiryo"
        except Exception as e2:
            FONT_NAME = "Helvetica"

# フォント初期化
setup_fonts()

# --- ユーティリティ関数 ---
def safe_filename(name):
    """ファイル名に使えない文字をアンダースコアに置換"""
    keepcharacters = (' ', '.', '_', '-')
    return "".join(c for c in name if c.isalnum() or c in keepcharacters).rstrip()

# --- PDF生成関数 ---
def create_pdf(data, output_path):
    """PDFドキュメントを生成（新・最適化レイアウト搭載）"""
    c = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4
    
    # ==========================================
    # --- ヘッダー領域 ---
    # ==========================================
    bg_c = (1.0, 0.84, 0.0)  # #FFD700 (Gold/Yellow)
    txt_c = (0.2, 0.2, 0.2)
    c.setFillColorRGB(*bg_c)
    
    # ヘッダーの高さ
    c.rect(0, height - 60, width, 60, stroke=0, fill=1)
    
    # 右上の管理番号
    c.setFillColorRGB(*txt_c)
    c.setFont(FONT_NAME, 10)
    c.drawRightString(width - 20, height - 20, f"管理番号: {data['id']}")
    
    # 機器名（タイトル）
    c.setFont(FONT_NAME, 22)
    c.drawString(20, height - 40, data['name'])
    
    # 使用電源の帯（オレンジ）
    p_y = height - 85
    c.setFillColorRGB(0.95, 0.61, 0.13)
    c.rect(20, p_y, width - 40, 18, stroke=0, fill=1)
    
    c.setFillColorRGB(*txt_c)
    c.setFont(FONT_NAME, 12)
    power_text = data['power'] if data['power'] else "未設定"
    c.drawString(25, p_y + 4, f"■ 使用電源: AC {power_text}")

    # ==========================================
    # --- 画像レイアウトエンジン ---
    # ==========================================
    
    def draw_smart_image_box(c, img_file, title, x, y, w, h, none_title=None):
        """スマホの回転バグだけを直し、本来の縦横比で描画する"""
        c.setFillColorRGB(0, 0, 0)
        c.setFont(FONT_NAME, 11)
        c.drawString(x, y + h + 4, title)  # タイトルを画像の上に配置
        
        display_none_title = none_title if none_title else title
        
        if img_file is not None:
            try:
                # 1. 画像の読み込み
                if hasattr(img_file, 'read'):
                    img_data = img_file.read()
                    img = Image.open(io.BytesIO(img_data))
                else:
                    img = Image.open(img_file)
                
                # 2. 【最重要】スマホ特有のEXIF回転バグのみ補正
                img = ImageOps.exif_transpose(img)
                
                # 3. ReportLab用にRGB変換
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=90)
                img_byte_arr.seek(0)
                
                # 4. 画像の描画
                img_reader = ImageReader(img_byte_arr)
                c.drawImage(img_reader, x, y, width=w, height=h, preserveAspectRatio=True, anchor='c')
                
                # 枠線を引く
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x, y, w, h)
                c.setStrokeColorRGB(0, 0, 0)
                
            except Exception as e:
                print(f"画像読み込みエラー({title}): {str(e)}")
                c.rect(x, y, w, h)  # エラー時は枠だけ表示
        else:
            c.setDash(3, 3)
            c.rect(x, y, w, h)
            c.setDash()
            c.setFont(FONT_NAME, 10)
            c.drawCentredString(x + w/2, y + h/2, f"None ({display_none_title}なし)")

    # ---------------------------------------------------------
    # 緻密に計算された新しいレイアウト座標（A4サイズに最適化）
    # ---------------------------------------------------------
    
    if data.get('is_related_loto'):
        loto_title1 = "LOTO手順書（関連機器）Page 1"
        loto_title2 = "LOTO手順書（関連機器）Page 2"
    else:
        loto_title1 = "LOTO手順書 Page 1"
        loto_title2 = "LOTO手順書 Page 2"
    
    # 下段：LOTO手順書（縦長ドキュメントに最適なボックス）
    draw_smart_image_box(c, data.get('img_loto1'), loto_title1, 30, 40, 260, 360, none_title="LOTO手順書 Page 1")
    draw_smart_image_box(c, data.get('img_loto2'), loto_title2, 305, 40, 260, 360, none_title="LOTO手順書 Page 2")

    # 上段左：機器外観（正方形に近く、どんな写真でも大きく表示）
    draw_smart_image_box(c, data.get('img_exterior'), "機器外観", 30, 440, 260, 280)

    # 上段右：コンセント＆ラベル（横長の写真が自然に収まる横長ボックス）
    draw_smart_image_box(c, data.get('img_label'), "資産管理ラベル", 305, 440, 260, 130)
    draw_smart_image_box(c, data.get('img_outlet'), "コンセント位置", 305, 590, 260, 130)

    c.save()

# --- 印刷用ラベル生成関数 ---
def create_label_image(data):
    w_px, h_px = 472, 295
    label_img = Image.new('RGB', (w_px, h_px), 'white')
    draw = ImageDraw.Draw(label_img)
    
    font_path = cloud_font_path
    try:
        font_lg = ImageFont.truetype(font_path, 20)
        font_sm = ImageFont.truetype(font_path, 12)
        font_xs = ImageFont.truetype(font_path, 8)
    except Exception as e:
        font_lg = font_sm = font_xs = ImageFont.load_default()
    
    try:
        factory_icon_path = "factory_icon.png"
        if not os.path.exists(factory_icon_path):
            factory_icon_url = "https://raw.githubusercontent.com/googlefonts/morisawa-biz-ud-gothic/main/docs/biz_font_specimen/sample_ud_gothic.png"
            urllib.request.urlretrieve(factory_icon_url, factory_icon_path)
        
        icon_img = Image.open(factory_icon_path)
        icon_img = icon_img.resize((30, 30))
        label_img.paste(icon_img, (10, 10))
    except Exception as e:
        draw.text((10, 10), "🏭", fill="black", font=font_lg)
    
    draw.text((45, 10), "機器情報・LOTO確認ラベル", fill="black", font=font_lg)
    
    if 'img_qr' in data and data['img_qr'] is not None:
        try:
            qr_pil_img = data['img_qr']
            if hasattr(qr_pil_img, 'convert'):
                qr_pil_img = qr_pil_img.convert('RGB')
            qr_pil_img = qr_pil_img.resize((140, 140))
            label_img.paste(qr_pil_img, (10, 50))
        except Exception as e:
            print(f"QRコード埋め込みエラー: {str(e)}")
    
    x_text = 160
    y_text = 50
    line_height = 20
    device_name = data.get('name', '不明')
    device_power = data.get('power', '不明')
    
    draw.text((x_text, y_text), f"機器名称: {device_name}", fill="black", font=font_sm)
    draw.text((x_text, y_text + line_height), f"使用電源: AC {device_power}", fill="black", font=font_sm)
    
    y_line = y_text + line_height * 2 + 5
    draw.line((x_text, y_line, w_px - 10, y_line), fill="gray", width=1)
    
    draw.text((x_text, y_line + 10), "📱詳細スキャン (LOTO･外観･ｺﾝｾﾝﾄ)", fill="black", font=font_xs)
    
    return label_img

# --- メインアプリ ---
def main():
    query_params = st.query_params
    is_redirect_mode = "id" in query_params
    
    if is_redirect_mode:
        st.set_page_config(page_title="PDFを開く", layout="centered")
        target_id = query_params["id"]
        
        if DB_CSV.exists():
            try:
                df = pd.read_csv(DB_CSV)
                match = df[df["ID"].astype(str) == str(target_id)]
                
                if not match.empty:
                    target_url = match.iloc[-1]["URL"]
                    
                    link_html = f"""
                    <div style="text-align: center; margin-top: 60px;">
                        <p style="font-size: 20px; font-weight: bold; color: #333;">✅ 資料の準備ができました</p>
                        <a href="{target_url}" target="_blank" style="
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
                            📄 ここをタップしてPDFを開く
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
        st.set_page_config(page_title="設備QR＆PDF管理システム", layout="wide", initial_sidebar_state="expanded")
        
        # ==========================================
        # --- ⚙️ システム設定（サイドバー） ---
        # ==========================================
        st.sidebar.header("⚙️ システム詳細設定")
        st.sidebar.info("💡 ダウンロード先のフォルダを指定したい場合は、お使いのブラウザ（ChromeやEdge）の設定で「ダウンロード前に保存先を確認する」をオンにしてください。")
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("📄 ファイル名出力設定")
        include_equip_name = st.sidebar.checkbox("ダウンロードファイル名に「設備名称」を含める", value=True)
        st.sidebar.caption("例: チェックなし → 2699.pdf")
        st.sidebar.caption("例: チェックあり → 2699_5t金型反転機.pdf")
        
        st.title("🏭 設備QR＆PDF管理システム")
        st.info("※ この画面はPCでのPDF作成・台帳登録用です。")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.header("1. 基本情報入力")
            did = st.text_input("管理番号 (例: 2699)")
            name = st.text_input("設備名称 (例: 5t金型反転機)")
            power = st.selectbox("使用電源", ["100V", "200V"], index=None, placeholder="選択してください")
            
        with col2:
            st.header("2. 画像アップロード")
            img_exterior = st.file_uploader("機器外観", type=["png", "jpg", "jpeg"])
            img_outlet = st.file_uploader("コンセント位置", type=["png", "jpg", "jpeg"])
            img_label = st.file_uploader("資産管理ラベル", type=["png", "jpg", "jpeg"])
            
            is_related_loto = st.checkbox("関連機器・付帯設備のLOTO手順書として登録する")
            
            img_loto1 = st.file_uploader("LOTO手順書（1ページ目）", type=["png", "jpg", "jpeg"])
            img_loto2 = st.file_uploader("LOTO手順書（2ページ目）", type=["png", "jpg", "jpeg"])
            
        st.markdown("---")
        st.header("3. PDF生成・保存")
        if st.button("PDFを生成してダウンロード", type="primary"):
            if did and name and power:
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
                    pdf_path = PDF_DIR / f"{safe_id}.pdf"
                    
                    create_pdf(data, pdf_path)
                    
                    if include_equip_name:
                        dl_file_name = f"{safe_id}_{safe_filename(name)}.pdf"
                    else:
                        dl_file_name = f"{safe_id}.pdf"
                    
                    if pdf_path.exists():
                        st.success(f"{dl_file_name} の生成が完了しました！")
                        with open(pdf_path, "rb") as pdf_file:
                            st.download_button(
                                label="📥 PDFをダウンロード",
                                data=pdf_file,
                                file_name=dl_file_name,
                                mime="application/pdf"
                            )
                    else:
                        st.error("エラー：PDFの保存に失敗しました。")
                except Exception as e:
                    st.error(f"PDF生成エラー: {str(e)}")
            else:
                st.error("管理番号、設備名称、使用電源は全て必須です。")

        st.markdown("---")
        st.header("4. 自動転送QRコード生成")
        long_url = st.text_input("パソコンでPDFを開いた時の【上部アドレスバーの長いURL】（GitHub等のURL）を貼り付け")
        if st.button("QRコードを生成して台帳更新", type="secondary"):
            if long_url and did and name and power:
                try:
                    safe_id = safe_filename(did)
                    qr_path = QR_DIR / f"{safe_id}_qr.png"
                    
                    clean_base_url = "https://equipment-qr-manager.streamlit.app"
                    dynamic_url = f"{clean_base_url}/?id={did}"
                    
                    img_qr = qrcode.make(dynamic_url)
                    img_qr.save(qr_path)
                    st.success("自動転送用のQRコードを生成しました！")
                    
                    if DB_CSV.exists():
                        df = pd.read_csv(DB_CSV)
                        df = df[df["ID"].astype(str) != str(did)]
                    else:
                        df = pd.DataFrame(columns=["ID", "Name", "Power", "URL", "Updated"])
                    
                    new_data = {
                        "ID": did,
                        "Name": name,
                        "Power": power,
                        "URL": long_url,
                        "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                    df.to_csv(DB_CSV, index=False)
                    st.info("台帳(devices.csv)に最終目的地を記録しました。")
                    
                    st.markdown("---")
                    st.subheader("🏷️ コンセント・タグ用ラベルのダウンロード")
                    
                    label_data = {
                        "name": name,
                        "power": power,
                        "img_qr": img_qr
                    }
                    label_img = create_label_image(label_data)
                    
                    buf = io.BytesIO()
                    label_img.save(buf, format="PNG")
                    buf.seek(0)
                    byte_im = buf.getvalue()
                    
                    st.image(label_img, caption="2.5cm × 4cm 印刷用ラベル", width=300)
                    
                    if include_equip_name:
                        label_dl_name = f"{safe_id}_{safe_filename(name)}_label.png"
                    else:
                        label_dl_name = f"{safe_id}_label.png"
                    
                    st.download_button(
                        label="📥 ラベル画像(PNG)をダウンロード",
                        data=byte_im,
                        file_name=label_dl_name,
                        mime="image/png"
                    )
                except Exception as e:
                    st.error(f"QRコード・ラベル生成エラー: {str(e)}")
            else:
                st.error("「管理番号」「設備名称」「使用電源」「URL」の全てを入力してください。")

if __name__ == "__main__":
    main()

