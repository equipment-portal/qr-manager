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
import textwrap

# --- Excel操作用 ---
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter

# --- 画像処理用 ---
from PIL import Image, ImageDraw, ImageFont, ImageOps

# --- 初期設定 ---
DB_CSV = Path("devices.csv")
QR_DIR = Path("qr_codes")
MANUAL_DIR = Path("manuals")
EXCEL_LABEL_PATH = Path("print_labels.xlsx")
LABEL_HISTORY_FILE = Path("label_history.json")
TEMP_LABEL_DIR = Path("temp_labels")

for p in [QR_DIR, MANUAL_DIR, TEMP_LABEL_DIR]:
    p.mkdir(exist_ok=True)

cloud_font_path = "BIZUDGothic-Regular.ttf"
def setup_fonts():
    if not os.path.exists(cloud_font_path):
        try:
            font_url = "https://github.com/googlefonts/morisawa-biz-ud-gothic/raw/main/fonts/ttf/BIZUDGothic-Regular.ttf"
            urllib.request.urlretrieve(font_url, cloud_font_path)
        except: pass
setup_fonts()

def safe_filename(name):
    keep = (' ', '.', '_', '-')
    return "".join(c for c in name if c.isalnum() or c in keep).rstrip()

# ==========================================
# --- 画像生成ロジック ---
# ==========================================
def create_manual_image(data, output_path):
    W = 1600; margin = 80; content_w = W - margin * 2
    try:
        font_title = ImageFont.truetype(cloud_font_path, 80)
        font_sub = ImageFont.truetype(cloud_font_path, 55)
        font_text = ImageFont.truetype(cloud_font_path, 45)
    except:
        font_title = font_sub = font_text = ImageFont.load_default()

    sections = []
    h_img = Image.new('RGB', (W, 380), 'white')
    draw = ImageDraw.Draw(h_img)
    draw.rectangle([0, 0, W, 100], fill=(255, 215, 0))
    draw.text((W - margin, 25), f"管理番号: {data['id']}", fill="black", font=font_text, anchor="ra")
    draw.text((margin, 150), data['name'], fill="black", font=font_title)
    draw.rectangle([margin, 280, W - margin, 340], fill=(242, 155, 33))
    draw.text((margin + 20, 285), f"■ 使用電源: AC {data['power']}", fill="white", font=font_text)
    sections.append(h_img)

    def process_img(img_file, title):
        if not img_file: return None
        try:
            pil = ImageOps.exif_transpose(Image.open(img_file)).convert('RGB')
            nh = int(content_w * (pil.height / pil.width))
            pil = pil.resize((content_w, nh), Image.Resampling.LANCZOS)
            si = Image.new('RGB', (W, 140 + nh), 'white')
            d = ImageDraw.Draw(si)
            d.text((margin, 20), title, fill="black", font=font_sub)
            si.paste(pil, (margin, 90))
            d.rectangle([margin, 90, margin + content_w, 90 + nh], outline="gray", width=3)
            return si
        except: return None

    titles = ["機器外観", "コンセント位置", "資産管理ラベル", "LOTO手順書 Page1", "LOTO手順書 Page2"]
    imgs = [data.get('img_exterior'), data.get('img_outlet'), data.get('img_label'), data.get('img_loto1'), data.get('img_loto2')]
    for i, f in enumerate(imgs):
        sec = process_img(f, titles[i])
        if sec: sections.append(sec)

    total_h = sum(s.height for s in sections)
    final = Image.new('RGB', (W, total_h), 'white')
    cy = 0
    for s in sections:
        final.paste(s, (0, cy)); cy += s.height
    final.save(output_path)

def create_manual_image_extended(data, extra_images, output_path):
    W = 1600; margin = 80; content_w = W - margin * 2
    try:
        font_sub = ImageFont.truetype(cloud_font_path, 65)
        font_text = ImageFont.truetype(cloud_font_path, 55)
    except: font_sub = font_text = ImageFont.load_default()

    create_manual_image(data, output_path)
    base = Image.open(output_path)
    added = []

    for ex_f, ex_t in extra_images:
        try:
            pil = ImageOps.exif_transpose(Image.open(ex_f)).convert('RGB')
            nh = int(content_w * (pil.height / pil.width))
            pil = pil.resize((content_w, nh), Image.Resampling.LANCZOS)
            si = Image.new('RGB', (W, 160 + nh), 'white')
            dr = ImageDraw.Draw(si)
            dr.text((margin, 25), ex_t, fill="black", font=font_sub)
            si.paste(pil, (margin, 100))
            dr.rectangle([margin, 100, margin+content_w, 100+nh], outline="gray", width=3)
            added.append(si)
        except: continue

    lines = textwrap.wrap(data.get("memo", "なし"), width=32)
    lh = 80; mh = 180 + (len(lines) * lh)
    ms = Image.new('RGB', (W, mh), 'white')
    md = ImageDraw.Draw(ms)
    md.text((margin, 30), "■ メモ・備考", fill="black", font=font_sub)
    md.rectangle([margin, 110, W - margin, mh - 30], outline=(242, 155, 33), width=6)
    for i, line in enumerate(lines):
        md.text((margin + 40, 130 + (i * lh)), line, fill="black", font=font_text)
    added.append(ms)

    final = Image.new('RGB', (W, base.height + sum(s.height for s in added) + 50), 'white')
    final.paste(base, (0, 0))
    cy = base.height
    for s in added:
        final.paste(s, (0, cy)); cy += s.height
    final.save(output_path)

# ==========================================
# --- ラベル・Excel・履歴管理 ---
# ==========================================
def create_label_image(data):
    scale = 4; tw = 350 * scale; th = 200 * scale
    try:
        ft = ImageFont.truetype(cloud_font_path, 19 * scale)
        fm = ImageFont.truetype(cloud_font_path, 30 * scale)
        fs = ImageFont.truetype(cloud_font_path, 12 * scale)
        ff = ImageFont.truetype(cloud_font_path, 13 * scale)
    except: ft = fm = fs = ff = ImageFont.load_default()
    
    img = Image.new('RGB', (tw, th), 'white')
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,0,tw-1,th-1], outline=(255,255,0), width=12*scale)
    draw.text((18*scale, 16*scale), "■", fill="black", font=ft)
    draw.text((42*scale, 16*scale), "機器情報・LOTO確認ラベル", fill="black", font=ft)
    
    qs = 72 * scale
    if data.get('img_qr'):
        qr = data['img_qr'].convert('RGB').resize((qs, qs))
        img.paste(qr, (tw - qs - 22*scale, th - qs - 32*scale))
    
    xm = 18 * scale; mw = tw - 40*scale
    cur = 30 * scale; tf = fm; name = data.get('name','不明'); pwr = f"AC {data.get('power','不明')}"
    longest = name if len(name) > len(pwr) else pwr
    bbox = draw.textbbox((0,0), longest, font=tf)
    while (bbox[2]-bbox[0]) > mw and cur > 12*scale:
        cur -= 1*scale; tf = ImageFont.truetype(cloud_font_path, cur); bbox = draw.textbbox((0,0), longest, font=tf)
    
    draw.text((xm, 52*scale), "機器名称:", font=fs, fill="black")
    draw.text((xm, 66*scale), name, font=tf, fill="black")
    draw.text((xm, 108*scale), "使用電源:", font=fs, fill="black")
    draw.text((xm, 122*scale), pwr, font=tf, fill="black")
    draw.text((xm, 172*scale), "[QR] 詳細スキャン（外観・コンセント位置・LOTO手順）", font=ff, fill="black")
    return img.resize((350, 200), Image.Resampling.LANCZOS)

def rebuild_excel():
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Labels"
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = ws.page_margins.right = ws.page_margins.top = ws.page_margins.bottom = 0.1
    h = []
    if LABEL_HISTORY_FILE.exists():
        with open(LABEL_HISTORY_FILE, "r") as f: h = json.load(f)
    
    rows_per_col = 5; lw = 350; lh = 200
    for i, item in enumerate(h):
        ip = TEMP_LABEL_DIR / item["img_filename"]
        if not ip.exists(): continue
        c_idx = i // rows_per_col
        r_idx = i % rows_per_col
        cell_col = c_idx + 1
        cell_row = r_idx + 1
        
        cl = get_column_letter(cell_col)
        ws.column_dimensions[cl].width = (lw / 7) + 0.5
        ws.row_dimensions[cell_row].height = (lh * 0.75) + 2
        xi = XLImage(str(ip)); xi.width, xi.height = lw, lh; xi.anchor = f"{cl}{cell_row}"
        ws.add_image(xi)
    wb.save(EXCEL_LABEL_PATH)

def add_label_to_history(n, img):
    h = []
    if LABEL_HISTORY_FILE.exists():
        with open(LABEL_HISTORY_FILE, "r") as f: h = json.load(f)
    fn = f"l_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.png"
    img.save(TEMP_LABEL_DIR / fn)
    h.append({"name":n, "img_filename":fn})
    with open(LABEL_HISTORY_FILE, "w") as f: json.dump(h, f)
    rebuild_excel()

def delete_label_from_history(idx):
    with open(LABEL_HISTORY_FILE, "r") as f: h = json.load(f)
    p = TEMP_LABEL_DIR / h[idx]["img_filename"]
    if p.exists(): p.unlink()
    h.pop(idx)
    with open(LABEL_HISTORY_FILE, "w") as f: json.dump(h, f)
    rebuild_excel()

def clear_history():
    for f in [EXCEL_LABEL_PATH, LABEL_HISTORY_FILE]: 
        if f.exists(): f.unlink()
    for f in TEMP_LABEL_DIR.glob("*.png"): f.unlink()

# ==========================================
# --- メインアプリ ---
# ==========================================
def main():
    qp = st.query_params
    if "id" in qp:
        st.set_page_config(page_title="機器情報閲覧", layout="centered")
        st.markdown("<style>#MainMenu,footer,header{visibility:hidden;}</style>", unsafe_allow_html=True)
        if DB_CSV.exists():
            df = pd.read_csv(DB_CSV)
            m = df[df["ID"].astype(str) == str(qp["id"])]
            if not m.empty:
                u = m.iloc[-1]["URL"].replace("github.com", "cdn.jsdelivr.net/gh").replace("/blob/", "@")
                st.markdown(f'<div style="text-align:center;margin-top:60px;"><a href="{u}" style="padding:20px 40px;background:#28a745;color:white;font-size:22px;text-decoration:none;border-radius:8px;font-weight:bold;">📱 機器情報ページを開く</a></div>', unsafe_allow_html=True)
    else:
        st.set_page_config(page_title="機器情報ページ＆QR管理", layout="wide", initial_sidebar_state="expanded")
        
        st.markdown("""
        <style>
        .stButton button { width: 100%; border-radius: 5px; }
        .stTextArea textarea { font-size: 16px; }
        [data-testid="stSidebar"] { min-width: 320px; }
        </style>
        """, unsafe_allow_html=True)

        if "form_reset_key" not in st.session_state: st.session_state["form_reset_key"] = 0
        if "extra_images_count" not in st.session_state: st.session_state["extra_images_count"] = 0
        rk = st.session_state["form_reset_key"]

        # サイドバー
        st.sidebar.header("🗄️ 登録済みデータベース")
        if DB_CSV.exists():
            df = pd.read_csv(DB_CSV)
            if not df.empty:
                opts = ["✨ 新規登録 (クリア)"] + (df["ID"].astype(str) + " : " + df["Name"]).tolist()
                def ld():
                    s = st.session_state.db_select
                    if s == "✨ 新規登録 (クリア)":
                        st.session_state[f"d_{rk}"] = ""; st.session_state[f"n_{rk}"] = ""; st.session_state[f"p_{rk}"] = None
                    else:
                        match_row = df[df["ID"].astype(str) == s.split(" : ")[0]]
                        if not match_row.empty:
                            r = match_row.iloc[-1]
                            st.session_state[f"d_{rk}"] = str(r["ID"])
                            st.session_state[f"n_{rk}"] = str(r["Name"])
                            st.session_state[f"p_{rk}"] = str(r["Power"])
                st.sidebar.selectbox("編集する機器を選択:", opts, key="db_select", on_change=ld)
                if st.sidebar.button("🗑️ 選択中の機器を削除"):
                    df[df["ID"].astype(str) != st.session_state.db_select.split(" : ")[0]].to_csv(DB_CSV, index=False)
                    st.session_state["form_reset_key"] += 1; st.rerun()
        
        st.sidebar.markdown("---")
        sm = st.sidebar.radio("保存モード:", ["1. 手動（テスト用）", "2. 全自動（GitHub保存）"], index=1)
        repo = st.sidebar.text_input("リポジトリ名", value="equipment-portal/qr-manager") if sm=="2. 全自動（GitHub保存）" else ""
        tok = st.sidebar.text_input("トークン", value=st.secrets.get("github_token",""), type="password") if sm=="2. 全自動（GitHub保存）" else ""

        # メイン
        st.markdown("<div id='top_anchor'></div>", unsafe_allow_html=True)
        st.title("📱 機器情報ページ ＆ QRラベル管理")
        
        if st.session_state.get("scroll_to_top"):
            st.components.v1.html("<script>var t=window.parent.document.getElementById('top_anchor');if(t)t.scrollIntoView(true);</script>", height=0)
            st.session_state["scroll_to_top"] = False

        c1, c2 = st.columns([1, 1])
        with c1:
            st.header("1. 基本情報入力")
            did = st.text_input("管理番号", key=f"d_{rk}", placeholder="例: 2699")
            nm = st.text_input("機器名称", key=f"n_{rk}", placeholder="例: 100tジェットローダー")
            pw = st.selectbox("使用電源", ["100V", "200V"], index=None, key=f"p_{rk}")
            
            st.markdown("---")
            st.header("📝 メモ・備考欄")
            memo = st.text_area("現場へ伝える補足情報", key=f"m_{rk}", height=150, placeholder="例: 設定温度は25℃を維持すること。")

        with c2:
            st.header("2. 画像・マニュアル指定")
            f_ext = st.file_uploader("機器外観", key=f"fe_{rk}")
            f_out = st.file_uploader("コンセント位置", key=f"fo_{rk}")
            f_lab = st.file_uploader("資産管理ラベル", key=f"fl_{rk}")
            is_loto = st.checkbox("関連機器のLOTOとして登録する", key=f"lo_{rk}")
            f_l1 = st.file_uploader("LOTO手順書 1ページ目", key=f"l1_{rk}")
            f_l2 = st.file_uploader("LOTO手順書 2ページ目", key=f"l2_{rk}")
            
            st.markdown("---")
            st.subheader("➕ 追加情報の画像（点検表など）")
            ex_imgs = []
            for i in range(st.session_state["extra_images_count"]):
                et = st.text_input(f"タイトルの入力 {i+1}", key=f"et_{rk}_{i}")
                ef = st.file_uploader(f"画像の選択 {i+1}", key=f"ef_{rk}_{i}")
                if ef: ex_imgs.append((ef, et if et else f"追加画像 {i+1}"))
            
            if st.button("➕ 項目を追加する"):
                st.session_state["extra_images_count"] += 1
                st.rerun()

        st.markdown("---")
        st.header("3. ページ生成 ＆ プレビュー")
        if st.button("🔍 機器情報ページをプレビュー", type="secondary"):
            if did and nm and pw:
                dt = {"id":did,"name":nm,"power":pw,"img_exterior":f_ext,"img_outlet":f_out,"img_label":f_lab,"img_loto1":f_l1,"img_loto2":f_l2,"memo":memo if memo.strip() else "なし"}
                pt = MANUAL_DIR / f"{safe_filename(did)}.png"
                create_manual_image_extended(dt, ex_imgs, pt)
                with open(pt, "rb") as f: b = base64.b64encode(f.read()).decode()
                st.components.v1.html(f'<div style="max-height:600px;overflow-y:scroll;border:2px solid #ddd;padding:10px;"><img src="data:image/png;base64,{b}" style="width:100%;"></div>', height=620)
            else: st.warning("管理番号、名称、電源を先に入力してください。")

        st.header("4. 最終登録 ＆ QRラベル発行")
        if st.button("🖨️ サーバーへ保存してQRラベルを発行", type="primary"):
            if did and nm and pw:
                with st.spinner("サーバー通信中..."):
                    try:
                        fn = f"{safe_filename(did)}_{safe_filename(nm)}.png"
                        pt = MANUAL_DIR / f"{safe_filename(did)}.png"
                        dt_gen = {"id":did,"name":nm,"power":pw,"img_exterior":f_ext,"img_outlet":f_out,"img_label":f_lab,"img_loto1":f_l1,"img_loto2":f_l2,"memo":memo if memo.strip() else "なし"}
                        create_manual_image_extended(dt_gen, ex_imgs, pt)
                        
                        if sm == "2. 全自動（GitHub保存）":
                            with open(pt, "rb") as f: b64_data = base64.b64encode(f.read()).decode()
                            url_api = f"https://api.github.com/repos/{repo}/contents/manuals/{urllib.parse.quote(fn)}"
                            sha_val = None
                            try:
                                rq_check = urllib.request.Request(url_api); rq_check.add_header("Authorization", f"token {tok}")
                                with urllib.request.urlopen(rq_check) as r_res: sha_val = json.loads(r_res.read())["sha"]
                            except: pass
                            
                            payload_data = {"message":"Update","content":b64_data,"branch":"main"}
                            if sha_val: payload_data["sha"] = sha_val
                            
                            # ここで変数名を統一 (rq -> rq_final)
                            rq_final = urllib.request.Request(url_api, data=json.dumps(payload_data).encode(), method="PUT")
                            rq_final.add_header("Authorization", f"token {tok}")
                            with urllib.request.urlopen(rq_final) as r_final:
                                gurl_raw = json.loads(r_final.read())["content"]["html_url"]
                            
                            furl = gurl_raw.replace("github.com", "cdn.jsdelivr.net/gh").replace("/blob/", "@")
                        else: furl = f"http://dummy-url.com/{did}"

                        df_save = pd.read_csv(DB_CSV) if DB_CSV.exists() else pd.DataFrame(columns=["ID","Name","Power","URL","Updated"])
                        df_save = df_save[df_save["ID"].astype(str) != str(did)]
                        new_data_row = pd.DataFrame([{"ID":did,"Name":nm,"Power":pw,"URL":furl,"Updated":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}])
                        pd.concat([df_save, new_data_row], ignore_index=True).to_csv(DB_CSV, index=False)
                        
                        limg_final = create_label_image({"name":nm,"power":pw,"img_qr":qrcode.make(furl)})
                        add_label_to_history(nm, limg_final)
                        
                        st.success(f"✅ 登録に成功しました！ URL: {furl}")
                        st.image(limg_final, caption="発行されたラベル", width=300)
                    except Exception as e: st.error(f"エラーが発生しました: {e}")

        st.markdown("---")
        def rst_action():
            st.session_state["form_reset_key"] += 1
            st.session_state["extra_images_count"] = 0
            st.session_state["scroll_to_top"] = True
        st.button("🔄 次の機器を登録する（入力をクリア）", type="primary", on_click=rst_action)

        # サイドバー：Excel台帳
        st.sidebar.markdown("---")
        st.sidebar.subheader("🖨️ 印刷用Excel台帳の状況")
        h_list = []
        if LABEL_HISTORY_FILE.exists():
            with open(LABEL_HISTORY_FILE, "r") as f: h_list = json.load(f)
        if len(h_list) > 0:
            st.sidebar.success(f"✅ 合計 {len(h_list)} 枚のラベルを配置済み")
            rows_p_col = 5; total_cnt = len(h_list)
            n_cols = ((total_cnt - 1) // rows_p_col) + 1
            grid_html_view = "<div style='background:#f0f2f6;padding:10px;border-radius:5px;font-size:14px;line-height:1.2;text-align:left;'>"
            for r in range(rows_p_col):
                row_str_line = ""
                for c in range(n_cols):
                    idx_val = c * rows_p_col + r
                    if idx_val < total_cnt:
                        num_icon = chr(9311 + idx_val + 1) if idx_val < 20 else f"({idx_val+1})"
                        row_str_line += f"<span style='display:inline-block;width:28px;font-weight:bold;color:#d4af37;'>{num_icon}</span>"
                    else:
                        row_str_line += "<span style='display:inline-block;width:28px;color:#ccc;'>⬜</span>"
                grid_html_view += row_str_line + "<br>"
            st.sidebar.markdown(grid_html_view + "</div>", unsafe_allow_html=True)
            for i_idx, itm_obj in enumerate(h_list):
                cb1, cb2 = st.sidebar.columns([5, 1])
                cb1.write(f"**{i_idx+1}** {itm_obj['name']}")
                if cb2.button("❌", key=f"d_itm_{i_idx}"): delete_label_from_history(i_idx); st.rerun()
        
        if EXCEL_LABEL_PATH.exists():
            with open(EXCEL_LABEL_PATH, "rb") as f_excel: st.sidebar.download_button("📥 最新のExcelをダウンロード", f_excel, "labels.xlsx")
            if st.sidebar.button("🗑️ 台帳をリセット"): clear_history(); st.rerun()

if __name__ == "__main__":
    main()
