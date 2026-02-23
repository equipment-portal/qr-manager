import os
import io
import re
from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd
import qrcode
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import urllib.request

# --- 日本語フォントの設定（クラウド対応） ---
try:
    # 現場で圧倒的に読みやすい「BIZ UDゴシック」を自動ダウンロード
    cloud_font_path = "BIZUDGothic-Regular.ttf"
    if not os.path.exists(cloud_font_path):
        font_url = "https://github.com/googlefonts/morisawa-biz-ud-gothic/raw/main/fonts/ttf/BIZUDGothic-Regular.ttf"
        urllib.request.urlretrieve(font_url, cloud_font_path)
    
    pdfmetrics.registerFont(TTFont("BIZUDGothic", cloud_font_path))
    FONT_NAME = "BIZUDGothic"
except:
    try:
        # ローカル環境（パソコン）のフォールバック
        win_font_path = "C:/Windows/Fonts/meiryo.ttc"
        pdfmetrics.registerFont(TTFont("Meiryo", win_font_path))
        FONT_NAME = "Meiryo"
    except:
        FONT_NAME = "Helvetica"

# --- 設定 ---
APP_TITLE = "設備QR管理システム（高画質・レイアウト調整版）"
OUTPUT_DIR = Path("output")
PDF_DIR = OUTPUT_DIR / "pdf"
QR_DIR = OUTPUT_DIR / "qr"
DB_CSV = OUTPUT_DIR / "devices.csv"
A4_W, A4_H = A4

def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    QR_DIR.mkdir(parents=True, exist_ok=True)

def safe_filename(s):
    return re.sub(r"[\\/:*?\"<>|]", "_", str(s)).strip()

def fit_contain(img, target_w, target_h):
    """エラーを防ぎつつ、ズームしても文字が読める超高画質（約300dpi相当）に最適化する"""
    if img is None: return None, 0, 0
    
    # EXIFの回転情報を適用（スマホ写真が横を向くのを防ぐ）
    img = ImageOps.exif_transpose(img)
    
    # 透過PNGなどをJPEG保存できるようにRGBに変換（ここでエラーによるフリーズを防ぎます）
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
        
    # 画像の元のアスペクト比を計算
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h
    
    # 枠（target_w x target_h）に収まる最大の描画サイズを正確に計算
    if img_ratio > target_ratio:
        draw_w = target_w
        draw_h = target_w / img_ratio
    else:
        draw_w = target_h * img_ratio
        draw_h = target_h
        
    # ズームした際の画質を高く保つため、PDF上の描画サイズの4倍のピクセル数にリサイズ
    # （これ以上大きくしてもPDFのファイルサイズが跳ね上がるだけで見た目は変わりません）
    render_w = int(draw_w * 4)
    render_h = int(draw_h * 4)
    img.thumbnail((render_w, render_h), Image.Resampling.LANCZOS)
    
    return img, draw_w, draw_h

def generate_pdf(pdf_path, data, imgs):
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    
    # テキスト未入力処理
    name = data['name'] if data['name'] else "ー"
    model = data['model'] if data['model'] else "ー"
    did = data['did'] if data['did'] else "ー"

    # 背景
    c.setFillColorRGB(1.00, 0.98, 0.90)
    c.rect(0, 0, A4_W, A4_H, stroke=0, fill=1)

    # タイトル帯（安全イエロー）
    c.setFillColorRGB(1.00, 0.84, 0.00)
    c.rect(0, A4_H - 80, A4_W, 80, stroke=0, fill=1)
    
    c.setFillColorRGB(0, 0, 0)
    c.setFont(FONT_NAME, 24)
    c.drawString(30, A4_H - 50, name)
    c.setFont(FONT_NAME, 12)
    c.drawRightString(A4_W - 30, A4_H - 30, f"管理番号: {did}")

    # 電源表示帯
    p_y = A4_H - 110
    color = (0.96, 0.62, 0.04) if data['power'] == "200V" else (0.00, 0.47, 0.83)
    txt_c = (0,0,0) if data['power'] == "200V" else (1,1,1)
    c.setFillColorRGB(*color)
    c.rect(30, p_y, A4_W - 60, 25, stroke=0, fill=1)
    c.setFillColorRGB(*txt_c)
    c.setFont(FONT_NAME, 14)
    c.drawString(40, p_y + 7, f"⚡ 使用電源: AC {data['power']}")

    # 型番表示
    c.setFillColorRGB(0, 0, 0)
    c.setFont(FONT_NAME, 12)
    c.drawString(30, p_y - 25, f"型番: {model}")

    # 画像描画サブ関数
    def draw_img(img, x, y, w, h, label, is_loto=False):
        c.setFillColorRGB(0, 0, 0)
        c.setFont(FONT_NAME, 11)
        # ラベルは指定された枠の上端(y+h)の少し上に描画
        c.drawString(x, y + h + 5, label)
        
        if img:
            processed, draw_w, draw_h = fit_contain(img.copy(), w, h)
            buf = io.BytesIO()
            # エラー防止のためqualityは95に設定（ファイルサイズを抑えつつ十分に高画質です）
            processed.save(buf, format="JPEG", quality=95)
            
            # 画像のX座標（枠内で中央揃え）
            draw_x = x + (w - draw_w) / 2
            # 画像のY座標（枠内で上端揃え: 枠の上端から画像の高さを引く）
            draw_y = (y + h) - draw_h
            
            if is_loto:
                c.setLineWidth(2); c.setStrokeColorRGB(1, 0, 0)
                # LOTOの赤枠は実際の画像の大きさに合わせて描画する
                c.rect(draw_x, draw_y, draw_w, draw_h, stroke=1, fill=0)
            
            # 高解像度データを指定の描画枠（draw_w, draw_h）に表示
            c.drawImage(ImageReader(buf), draw_x, draw_y, draw_w, draw_h, mask='auto')
        else:
            c.setDash(3, 3)
            c.rect(x, y, w, h, stroke=1)
            c.drawCentredString(x + w/2, y + h/2, "None (なし)")
            c.setDash(1, 0)

    # --- レイアウト座標計算（2x2均等グリッド配置） ---
    # 1ページのA4サイズ（縦841.89）の余白を最大限に活かす
    row1_top_y = p_y - 50 # 上段の上端（型番ラベルの下）
    
    # 4枚の画像を同じサイズにするための計算
    # 横幅：左右の余白30ずつ(計60)と、中央の余白20を引いて2等分
    box_w = (A4_W - 80) / 2 
    # 高さ：A4の残りの高さを最大限活用（上下の余白とラベル分を考慮し300に設定）
    box_h = 300 
    
    # X座標（左列と右列）
    x_left = 30
    x_right = x_left + box_w + 20
    
    # 1. 上段（機器外観 ＆ コンセント位置）
    y1 = row1_top_y - box_h # 上段の下端Y座標
    draw_img(imgs.get('overview'), x_left, y1, box_w, box_h, "機器外観")
    draw_img(imgs.get('outlet'), x_right, y1, box_w, box_h, "コンセント位置")

    # 2. 下段（資産管理ラベル ＆ LOTO手順書）
    # 上段の下端から余白（ラベル文字など）を40pt空ける
    row2_top_y = y1 - 40
    y2 = row2_top_y - box_h # 下段の下端Y座標
    
    draw_img(imgs.get('asset'), x_left, y2, box_w, box_h, "資産管理ラベル")
    
    loto_label = "LOTO手順書（関連機器）" if data['is_related'] else "LOTO手順書"
    draw_img(imgs.get('loto'), x_right, y2, box_w, box_h, loto_label, is_loto=True)

    c.showPage()
    c.save()

# --- メイン画面 ---
def main():
    # 1. URLパラメータを確認して「転送モード」か「通常の管理モード」かを判定
    query_params = st.query_params
    is_redirect_mode = "id" in query_params

    if is_redirect_mode:
        st.set_page_config(page_title="資料を開いています...", layout="centered")
        target_id = query_params["id"]
        st.title("🔄 該当する資料を開いています...")
        
        if DB_CSV.exists():
            df = pd.read_csv(DB_CSV)
            # 台帳の中から、アクセスされた管理番号と同じ行を探す
            match = df[df["ID"] == target_id]
            if not match.empty:
                # 複数回登録されていた場合は最新のもの（一番下）を取得
                target_url = match.iloc[-1]["URL"]
                st.info(f"管理番号: {target_id} のファイルへ転送します。")
                
                # 自動転送（リダイレクト）の処理（HTMLとJavaScriptを埋め込む）
                redirect_html = f"""
                <meta http-equiv="refresh" content="0; url={target_url}">
                <script>window.location.href = "{target_url}";</script>
                """
                st.markdown(redirect_html, unsafe_allow_html=True)
                st.markdown(f"**[自動的に画面が切り替わらない場合はこちらをクリックしてください]({target_url})**")
            else:
                st.error(f"エラー: 管理番号 '{target_id}' は見つかりませんでした。")
        else:
            st.error("エラー: 転送先を記録した台帳（devices.csv）がまだありません。")
        return  # 転送モードの時はここで処理を終了し、下の管理画面は表示させない

    # 2. ここから下は通常の「管理画面」
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(f"🛠 {APP_TITLE}")
    ensure_dirs()
    
    with st.sidebar:
        st.header("⚙️ システム設定")
        st.caption("※クラウド公開後、発行されたアプリのURLに変更してください")
        base_url = st.text_input("このアプリのURL", "http://localhost:8501")
        st.markdown("---")
        st.header("1. 基本情報入力")
        did = st.text_input("管理番号", "")
        name = st.text_input("機器名称", "")
        model = st.text_input("型番", "")
        power = st.selectbox("使用電源", ["100V", "200V"])
        st.markdown("---")
        is_related = st.checkbox("LOTO手順書は関連機器のもの", value=False)

    col1, col2 = st.columns(2)
    with col1:
        st.header("2. 画像アップロード")
        f1 = st.file_uploader("機器外観（縦長推奨）", type=['jpg','png','jpeg'])
        f2 = st.file_uploader("コンセント位置", type=['jpg','png','jpeg'])
        f3 = st.file_uploader("LOTO手順書", type=['jpg','png','jpeg'])
        f4 = st.file_uploader("資産ラベル（縦長推奨）", type=['jpg','png','jpeg'])

    with col2:
        st.header("3. PDF生成・保存")
        if st.button("PDFを生成してダウンロード", type="primary"):
            imgs = {
                'overview': Image.open(f1) if f1 else None,
                'outlet': Image.open(f2) if f2 else None,
                'loto': Image.open(f3) if f3 else None,
                'asset': Image.open(f4) if f4 else None
            }
            pdf_path = PDF_DIR / f"{safe_filename(did if did else '未設定')}.pdf"
            
            data = {'did': did, 'name': name, 'model': model, 'power': power, 'is_related': is_related}
            generate_pdf(pdf_path, data, imgs)
            
            with open(pdf_path, "rb") as f:
                st.download_button("✅ PDFをダウンロード", f, file_name=pdf_path.name, mime="application/pdf")
            st.success("高画質PDFの生成・レイアウト調整が完了しました。")

        st.markdown("---")
        st.header("4. 自動転送QRコード生成")
        long_url = st.text_input("OneDrive等の共有リンクを貼り付け")
        if st.button("QRコードを生成して台帳更新", type="secondary"):
            if long_url and did:
                safe_id = safe_filename(did)
                qr_path = QR_DIR / f"{safe_id}_qr.png"
                
                # 【重要】OneDriveのURLではなく、自作アプリのURLをQRコードにする
                clean_base_url = base_url.rstrip("/")
                dynamic_url = f"{clean_base_url}/?id={did}"
                
                img_qr = qrcode.make(dynamic_url)
                img_qr.save(qr_path)
                st.success("自動転送用のQRコードを生成しました！")
                st.image(str(qr_path), caption=f"QRの中身: {dynamic_url}", width=200)
                
                # 台帳更新（ここに本当の目的地＝OneDriveのURLを記録しておく）
                df = pd.read_csv(DB_CSV) if DB_CSV.exists() else pd.DataFrame(columns=["ID", "Name", "Power", "URL", "Updated"])
                new_data = {"ID": did, "Name": name, "Power": power, "URL": long_url, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                df.to_csv(DB_CSV, index=False)
                st.info("台帳(devices.csv)に最終目的地（OneDrive）を記録しました。")
            else:
                st.error("「管理番号」と「URL」の両方を入力してください。")

if __name__ == "__main__":

    main()
