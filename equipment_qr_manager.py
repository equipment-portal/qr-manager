import streamlit as st
import pandas as pd
import qrcode
import os
import urllib.request
from pathlib import Path
from datetime import datetime
import io
import base64
import json
import streamlit.components.v1 as components  # ← PDFを別タブで開くために追加
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

setup_fonts()

# --- ユーティリティ関数 ---
def safe_filename(name):
    keepcharacters = (' ', '.', '_', '-')
    return "".join(c for c in name if c.isalnum() or c in keepcharacters).rstrip()

# --- 【変更】PDFプレビュー表示関数（別タブで開く） ---
def display_pdf(file_path):
    """生成したPDFを別タブ（新しいウィンドウ）で開くためのボタンを生成する"""
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    
    # JavaScriptを使用して、PDFデータを新しいタブで開くボタンを作成
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
    .btn {{
        display: inline-block;
        padding: 12px 24px;
        background-color: #17a2b8;
        color: white;
        text-decoration: none;
        border-radius: 5px;
        font-weight: bold;
        font-family: sans-serif;
        font-size: 16px;
        cursor: pointer;
        border: none;
    }}
    .btn:hover {{
        background-color: #138496;
    }}
    </style>
    </head>
    <body style="margin: 0; padding: 10px 0;">
        <button class="btn" onclick="openPdf()">🔍 新しいウィンドウでPDFプレビューを開く</button>
        <script>
        function openPdf() {{
            var pdfData = "{base64_pdf}";
            var byteCharacters = atob(pdfData);
            var byteNumbers = new Array(byteCharacters.length);
            for (var i = 0; i < byteCharacters.length; i++) {{
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }}
            var byteArray = new Uint8Array(byteNumbers);
            var file = new Blob([byteArray], {{ type: 'application/pdf' }});
            var fileURL = URL.createObjectURL(file);
            window.open(fileURL, '_blank');
        }}
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=70)

# --- PDF生成関数 ---
def create_pdf(data, output_path):
    c = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4
    
    bg_c = (1.0, 0.84, 0.0)
    txt_c = (0.2, 0.2, 0.2)
    c.setFillColorRGB(*bg_c)
    
    c.rect(0, height - 60, width, 60, stroke=0, fill=1)
    
    c.setFillColorRGB(*txt_c)
    c.setFont(FONT_NAME, 10)
    c.drawRightString(width - 20, height - 20, f"管理番号: {data['id']}")
    
    c.setFont(FONT_NAME, 22)
    c.drawString(20, height - 40, data['name'])
    
    p_y = height - 85
    c.setFillColorRGB(0.95, 0.61, 0.13)
    c.rect(20, p_y, width - 40, 18, stroke=0, fill=1)
    
    c.setFillColorRGB(*txt_c)
    c.setFont(FONT_NAME, 12)
    power_text = data['power'] if data['power'] else "未設定"
    c.drawString(25, p_y + 4, f"■ 使用電源: AC {power_text}")

    def draw_smart_image_box(c, img_file, title, x, y, w, h, none_title=None):
        c.setFillColorRGB(0, 0, 0)
        c.setFont(FONT_NAME, 11)
        c.drawString(x, y + h + 4, title)
        
        display_none_title = none_title if none_title else title
        
        if img_file is not None:
            try:
                if hasattr(img_file, 'read'):
                    img_data = img_file.read()
                    img = Image.open(io.BytesIO(img_data))
                else:
                    img = Image.open(img_file)
                
                img = ImageOps.exif_transpose(img)
                
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=90)
                img_byte_arr.seek(0)
                
                img_reader = ImageReader(img_byte_arr)
                c.drawImage(img_reader, x, y, width=w, height=h, preserveAspectRatio=True, anchor='c')
                
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x, y, w, h)
                c.setStrokeColorRGB(0, 0, 0)
                
            except Exception as e:
                print(f"画像読み込みエラー({title}): {str(e)}")
                c.rect(x, y, w, h)
        else:
            c.setDash(3, 3)
            c.rect(x, y, w, h)
            c.setDash()
            c.setFont(FONT_NAME, 10)
            c.drawCentredString(x + w/2, y + h/2, f"None ({display_none_title}なし)")

    if data.get('is_related_loto'):
        loto_title1 = "LOTO手順書（関連機器）Page 1"
        loto_title2 = "LOTO手順書（関連機器）Page 2"
    else:
        loto_title1 = "LOTO手順書 Page 1"
        loto_title2 = "LOTO手順書 Page 2"
    
    draw_smart_image_box(c, data.get('img_loto1'), loto_title1, 30, 40, 260, 360, none_title="LOTO手順書 Page 1")
    draw_smart_image_box(c, data.get('img_loto2'), loto_title2, 305, 40, 260, 360, none_title="LOTO手順書 Page 2")

    draw_smart_image_box(c, data.get('img_exterior'), "機器外観", 30, 440, 260, 280)
    draw_smart_image_box(c, data.get('img_label'), "資産管理ラベル", 305, 440, 260, 130)
    draw_smart_image_box(c, data.get('img_outlet'), "コンセント位置", 305, 590, 260, 130)

    c.save()

# --- 印刷用ラベル生成関数 ---
def create_label_image(data):
    """
    印刷用に高画質化（解像度4倍）し、黄色の枠線を付与したラベル画像を生成
    """
    scale = 4  # 画質を4倍に引き上げ（印刷品質）
    w_px, h_px = 472 * scale, 295 * scale
    
    # 背景を白で作成
    label_img = Image.new('RGB', (w_px, h_px), 'white')
    draw = ImageDraw.Draw(label_img)
    
    # 画像のフチに黄色の枠線（PDFのヘッダー色）を描画
    border_color = (255, 215, 0)
    border_width = 12 * scale
    draw.rectangle([0, 0, w_px - 1, h_px - 1], outline=border_color, width=border_width)
    
    # フォント設定（サイズも4倍に）
    font_path = cloud_font_path
    try:
        font_lg = ImageFont.truetype(font_path, 20 * scale)
        font_sm = ImageFont.truetype(font_path, 12 * scale)
        font_xs = ImageFont.truetype(font_path, 9 * scale) # 潰れ防止のため微増
    except Exception as e:
        font_lg = font_sm = font_xs = ImageFont.load_default()
    
    # 1. アイコン（文字化けする🏭の代わりに、安全なリスト記号「≡」を使用）
    draw.text((20 * scale, 12 * scale), "≡", fill="black", font=font_lg)
    
    # 2. タイトル
    draw.text((50 * scale, 12 * scale), "機器情報・LOTO確認ラベル", fill="black", font=font_lg)
    
    # 3. QRコードを配置（サイズも4倍に）
    if 'img_qr' in data and data['img_qr'] is not None:
        try:
            qr_pil_img = data['img_qr']
            if hasattr(qr_pil_img, 'convert'):
                qr_pil_img = qr_pil_img.convert('RGB')
            qr_pil_img = qr_pil_img.resize((140 * scale, 140 * scale))
            label_img.paste(qr_pil_img, (15 * scale, 50 * scale))
        except Exception as e:
            pass
    
    # 4. 詳細テキスト
    x_text = 165 * scale
    y_text = 60 * scale
    line_height = 25 * scale
    device_name = data.get('name', '不明')
    device_power = data.get('power', '不明')
    
    draw.text((x_text, y_text), f"機器名称: {device_name}", fill="black", font=font_sm)
    draw.text((x_text, y_text + line_height), f"使用電源: AC {device_power}", fill="black", font=font_sm)
    
    # 5. 区切り線
    y_line = y_text + line_height * 2 + 10 * scale
    draw.line((x_text, y_line, w_px - 20 * scale, y_line), fill="gray", width=1 * scale)
    
    # 6. 極短の案内文（文字化けする📱の代わりに、スキャンを連想させる「[QR]」を使用）
    draw.text((x_text, y_line + 10 * scale), "[QR] 詳細スキャン (LOTO･外観･ｺﾝｾﾝﾄ)", fill="black", font=font_xs)
    
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
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("💾 自動保存モード設定")
        save_mode = st.sidebar.radio(
            "PDFとQRコードの保存方式を選択:",
            ["1. 手動ダウンロードのみ (現在の方式)", "2. GitHubへ自動アップロード", "3. 社内共有フォルダへ自動保存"],
            index=1  # 変更：リストの2番目（インデックス1）をデフォルト選択にする
        )
        
        if save_mode == "2. GitHubへ自動アップロード":
            st.sidebar.info("💡 GitHubの合鍵（トークン）を設定すると全自動化されます。")
            github_repo = st.sidebar.text_input("リポジトリ名", value="equipment-portal/qr-manager")
            # --- 変更：value属性を追加し、デフォルトでトークンを入力済みにしておく ---
            github_token = st.sidebar.text_input("アクセス・トークン (ghp_...)", value="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", type="password")
            
        elif save_mode == "3. 社内共有フォルダへ自動保存":
            st.sidebar.warning("※機能実装準備中※\n会社のPCで直接アプリを動かす（オンプレミス稼働）環境への移行が必要です。")
            local_path = st.sidebar.text_input("共有フォルダのパス (例: Z:\\LOTO手順書)", value=r"C:\Equipment_PDF")

        st.sidebar.markdown("---")
        st.sidebar.subheader("📄 ファイル名出力設定")
        include_equip_name = st.sidebar.checkbox("ダウンロードファイル名に「設備名称」を含める", value=True)
        
        st.title("📄 設備QR＆PDF管理システム")
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
            
        # ==========================================
        # --- 3. PDFプレビュー確認（新機能） ---
        # ==========================================
        st.markdown("---")
        st.header("3. PDFプレビュー確認")
        st.info("💡 発行（クラウド保存）する前に、まずはここでPDFの出来栄えや画像の向きをチェックしてください。")
        
        if st.button("🔍 PDFを生成してプレビューを表示", type="secondary"):
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
                        pdf_path = PDF_DIR / f"{safe_id}.pdf"
                        
                        # PDF作成
                        create_pdf(data, pdf_path)
                        
                        if pdf_path.exists():
                            st.success("✨ プレビューの作成に成功しました！内容に問題がなければ、下の「4. 本番発行」に進んでください。")
                            # --- PDFを画面上に表示 ---
                            display_pdf(pdf_path)
                            
                            # 手動ダウンロード用ボタンも一応表示しておく
                            dl_file_name = f"{safe_id}_{safe_filename(name)}.pdf" if include_equip_name else f"{safe_id}.pdf"
                            with open(pdf_path, "rb") as pdf_file:
                                st.download_button(
                                    label="📥 (手動用) プレビューしたPDFをダウンロード",
                                    data=pdf_file,
                                    file_name=dl_file_name,
                                    mime="application/pdf"
                                )
                        else:
                            st.error("エラー：PDFの保存に失敗しました。")
                    except Exception as e:
                        st.error(f"PDFプレビュー生成エラー: {str(e)}")
            else:
                st.error("管理番号、設備名称、使用電源は全て必須です。")

        # ==========================================
        # --- 4. データ保存 ＆ 印刷用ラベル発行 ---
        # ==========================================
        st.markdown("---")
        st.header("4. データ保存 ＆ 印刷用ラベル発行")
        
        # ====== 手動モード ======
        if save_mode == "1. 手動ダウンロードのみ (現在の方式)":
            long_url = st.text_input("パソコンでPDFを開いた時の【上部アドレスバーの長いURL】（GitHub等のURL）を貼り付け")
            if st.button("🖨️ 手動設定で印刷用QRラベルを発行する", type="primary"):
                if long_url and did and name and power:
                    try:
                        safe_id = safe_filename(did)
                        qr_path = QR_DIR / f"{safe_id}_qr.png"
                        clean_base_url = "https://equipment-qr-manager.streamlit.app"
                        dynamic_url = f"{clean_base_url}/?id={did}"
                        img_qr = qrcode.make(dynamic_url)
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
                        buf = io.BytesIO()
                        label_img.save(buf, format="PNG")
                        st.image(label_img, caption="2.5cm × 4cm 印刷用ラベル", width=300)
                        
                        label_dl_name = f"{safe_id}_{safe_filename(name)}_label.png" if include_equip_name else f"{safe_id}_label.png"
                        st.download_button(label="📥 ラベル画像(PNG)をダウンロード", data=buf.getvalue(), file_name=label_dl_name, mime="image/png")
                    except Exception as e:
                        st.error(f"エラー: {str(e)}")
                else:
                    st.error("「管理番号」「設備名称」「使用電源」「URL」の全てを入力してください。")
                    
        # ====== GitHub全自動モード ======
        elif save_mode == "2. GitHubへ自動アップロード":
            st.info("💡 プレビューで問題がなければ、ボタン1つで【GitHub保存 ＋ QR発行】を全自動で行います。")
            if st.button("🖨️ 【全自動】PDFをGitHubへ保存し、印刷用QRラベルを発行する", type="primary"):
                if not github_repo or not github_token:
                    st.error("左の「⚙️ システム詳細設定」から、GitHubのリポジトリ名とアクセス・トークンを入力してください。")
                elif did and name and power:
                    with st.spinner("☁️ GitHubのクラウドへ自動アップロード中...（約5〜10秒かかります）"):
                        try:
                            # 1. PDFの再作成（最新の入力内容を確実に反映するため）
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
                            
                            # 2. GitHubへのAPI通信（アップロード）
                            with open(pdf_path, "rb") as f:
                                encoded_content = base64.b64encode(f.read()).decode("utf-8")
                            
                            file_name_for_github = f"{safe_id}_{safe_filename(name)}.pdf" if include_equip_name else f"{safe_id}.pdf"
                            
                            # --- 修正：日本語ファイル名をURL通信用に変換（エンコード） ---
                            import urllib.parse
                            encoded_file_name = urllib.parse.quote(file_name_for_github)
                            api_url = f"https://api.github.com/repos/{github_repo}/contents/pdfs/{encoded_file_name}"
                            
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
                                github_pdf_url = res_data["content"]["html_url"]
                            
                            # 3. QRコードの生成と台帳登録
                            long_url = github_pdf_url
                            qr_path = QR_DIR / f"{safe_id}_qr.png"
                            clean_base_url = "https://equipment-qr-manager.streamlit.app"
                            dynamic_url = f"{clean_base_url}/?id={did}"
                            img_qr = qrcode.make(dynamic_url)
                            img_qr.save(qr_path)
                            
                            if DB_CSV.exists():
                                df = pd.read_csv(DB_CSV)
                                df = df[df["ID"].astype(str) != str(did)]
                            else:
                                df = pd.DataFrame(columns=["ID", "Name", "Power", "URL", "Updated"])
                            
                            new_data = {"ID": did, "Name": name, "Power": power, "URL": long_url, "Updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                            df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                            df.to_csv(DB_CSV, index=False)
                            
                            st.success(f"✅ GitHubへの保存とQRコード生成が完了しました！\n保管先URL: {long_url}")
                            
                            # 4. ラベル画像の表示
                            st.markdown("---")
                            st.subheader("🏷️ コンセント・タグ用ラベルのダウンロード")
                            label_data = {"name": name, "power": power, "img_qr": img_qr}
                            label_img = create_label_image(label_data)
                            buf = io.BytesIO()
                            label_img.save(buf, format="PNG")
                            st.image(label_img, caption="2.5cm × 4cm 印刷用ラベル", width=300)
                            
                            label_dl_name = f"{safe_id}_{safe_filename(name)}_label.png" if include_equip_name else f"{safe_id}_label.png"
                            st.download_button(label="📥 ラベル画像(PNG)をダウンロード", data=buf.getvalue(), file_name=label_dl_name, mime="image/png")
                            
                        except Exception as e:
                            st.error(f"GitHub連携エラー: {str(e)}\n※トークンが間違っているか、権限(repo)が不足している可能性があります。")
                else:
                    st.error("管理番号、設備名称、使用電源は全て必須です。")

if __name__ == "__main__":
    main()






