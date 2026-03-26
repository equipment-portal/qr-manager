import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import pickle
import os
import base64
from streamlit_autorefresh import st_autorefresh

# ページ設定
logo_path = "logo.png" 
icon_path = "icon.ico" 
st.set_page_config(page_title="MFR電源管理システム", page_icon=icon_path, layout="wide")

# 60秒ごとに自動更新
st_autorefresh(interval=60000, key="data_refresh")

# --- データの保存と読み込み ---
STATE_FILE = "mfr_state.pkl"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return None

def save_state():
    state_to_save = {
        'jobs': st.session_state.jobs,
        'last_inspection_date': st.session_state.last_inspection_date,
        'products': st.session_state.products,
        'shown_alerts': st.session_state.shown_alerts
    }
    with open(STATE_FILE, "wb") as f:
        pickle.dump(state_to_save, f)

def get_image_base64(path):
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode()

def get_measurement_text(num_targets, current_target_qty, targets):
    if num_targets == 2:
        if current_target_qty == targets[0]: return '始'
        if current_target_qty == targets[1]: return '終'
    elif num_targets == 3:
        if current_target_qty == targets[0]: return '始'
        if current_target_qty == targets[1]: return '中'
        if current_target_qty == targets[2]: return '終'
    return str(current_target_qty)

# --- CSS設定 ---
st.markdown(
    """
    <style>
    .mfr-status-header {
        font-size: 1.25rem !important; 
        font-weight: bold !important; 
        margin-top: 10px !important;
        margin-bottom: 5px !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- 初期設定・状態管理 ---
if 'initialized' not in st.session_state:
    saved_state = load_state()
    if saved_state:
        st.session_state.jobs = saved_state['jobs']
        st.session_state.last_inspection_date = saved_state['last_inspection_date']
        st.session_state.products = saved_state.get('products', {})
        st.session_state.shown_alerts = saved_state.get('shown_alerts', [])
    else:
        st.session_state.jobs = {'100t': None, '450t': None, '550t': None}
        st.session_state.last_inspection_date = None
        st.session_state.products = {
            'サンプル製品A': {'qty': 500, 'cycle': 60.0, 'measurements': 2},
            'サンプル製品B': {'qty': 1000, 'cycle': 30.0, 'measurements': 3}
        }
        st.session_state.shown_alerts = []
    st.session_state.initialized = True
    st.session_state.inspection_dialog_shown = False 

# --- UI：サイドバー ---
with st.sidebar:
    st.header("⚙️ システム管理")
        
    st.subheader("📦 製品マスター管理")
    with st.expander("製品の登録・編集・削除", expanded=False):
        with st.form("product_form"):
            p_name = st.text_input("製品名（新規登録または上書き）")
            p_qty = st.number_input("生産数", min_value=1, value=100)
            p_cycle = st.number_input("サイクルタイム(秒)", min_value=0.1, value=30.0, step=0.1)
            p_meas = st.radio("MFR測定回数", options=[2, 3], format_func=lambda x: "2回 (初め・終わり)" if x==2 else "3回 (初め・中・終わり)")
            submit_btn = st.form_submit_button("💾 登録・更新")
            if submit_btn and p_name:
                st.session_state.products[p_name] = {'qty': p_qty, 'cycle': p_cycle, 'measurements': p_meas}
                save_state(); st.success(f"「{p_name}」を登録しました。"); st.rerun()
        
        st.markdown("---")
        if st.session_state.products:
            del_name = st.selectbox("削除する製品を選択", list(st.session_state.products.keys()))
            if st.button("🗑️ 選択した製品を削除"):
                del st.session_state.products[del_name]; save_state(); st.success(f"「{del_name}」を削除しました。"); st.rerun()

    st.markdown("---")
    st.subheader("🔧 リセット・テスト用ツール")
    if st.button("🔄 すべての成型機の状態をリセット"):
        st.session_state.jobs = {'100t': None, '450t': None, '550t': None}
        save_state(); st.rerun()
        
    if st.button("🔄 今日の点検状態を未実施に戻す"):
        st.session_state.last_inspection_date = None; st.session_state.inspection_dialog_shown = False
        save_state(); st.rerun()

# --- 事前計算ロジック ---
now = (datetime.utcnow() + timedelta(hours=9))
today_date = now.date()

def calculate_upcoming_measurements():
    upcoming = []
    max_date = today_date 
    
    for machine, job in st.session_state.jobs.items():
        if job is None or job['status'] == 'Completed': continue
        for target in job['targets']:
            if target not in job['completed']:
                if job['status'] == 'Running':
                    remaining_qty = target - job['current_qty']
                    if remaining_qty <= 0: est_time = now
                    else: est_time = job['last_update'] + timedelta(seconds=remaining_qty * job['cycle_time'])
                elif job['status'] == 'Paused':
                    est_time = None 
                
                upcoming.append({
                    'machine': machine, 'target_qty': target, 'est_time': est_time,
                    'status': job['status'], 'Targets': job['targets']
                })
                if est_time and est_time.date() > max_date:
                    max_date = est_time.date()
    
    # 日常点検の予定を自動追加
    for i in range((max_date - today_date).days + 1):
        d = today_date + timedelta(days=i)
        if d == today_date and st.session_state.last_inspection_date == today_date:
            continue
        is_monday_d = (d.weekday() == 0)
        insp_time = datetime(d.year, d.month, d.day, 8 if is_monday_d else 7, 0, 0)
        est_time_insp = now if d == today_date and now >= insp_time else insp_time
        upcoming.append({
            'machine': '日常点検(A勤)', 'target_qty': '日常点検',
            'est_time': est_time_insp, 'status': 'Planned', 'Targets': ['日常点検']
        })

    valid_upcoming = [x for x in upcoming if x['est_time'] is not None]
    valid_upcoming.sort(key=lambda x: x['est_time'])
    return valid_upcoming, upcoming

valid_upcoming, all_upcoming = calculate_upcoming_measurements()

on_blocks = []
if valid_upcoming:
    current_start = valid_upcoming[0]['est_time'] - timedelta(minutes=60)
    current_end = valid_upcoming[0]['est_time']
    for i in range(1, len(valid_upcoming)):
        next_measure = valid_upcoming[i]['est_time']
        gap_minutes = (next_measure - current_end).total_seconds() / 60
        if gap_minutes >= 90:
            on_blocks.append((current_start, current_end))
            current_start = next_measure - timedelta(minutes=60)
            current_end = next_measure
        else:
            current_end = next_measure
    on_blocks.append((current_start, current_end))

# --- アラーム・ダイアログ通知 ---

# 1. 始業時点検確認
inspection_start_time = datetime.combine(today_date, dt_time(7, 0, 0))
inspection_end_time = datetime.combine(today_date, dt_time(10, 0, 0))

if st.session_state.last_inspection_date != today_date:
    if now >= inspection_end_time:
        st.session_state.last_inspection_date = today_date
        save_state()
        st.rerun()
    elif inspection_start_time <= now < inspection_end_time:
        if not st.session_state.get('inspection_dialog_shown', False):
            st.session_state.inspection_dialog_shown = True
            st.toast("📋 本日の日常点検（MFR測定）は既に完了していますか？下部のボタンから記録してください。", icon="⚠️")

# 2. 測定実行のアラーム
for pt in valid_upcoming:
    m_time = pt['est_time']
    if m_time <= now < m_time + timedelta(minutes=15):
        if pt['machine'] == '日常点検(A勤)':
            alert_id_meas = f"MEAS_INSP_{m_time.strftime('%Y%m%d_%H%M')}"
            msg_meas = "📋 日常点検の時間です！点検を実施してください。"
        else:
            meas_text = get_measurement_text(len(pt['Targets']), pt['target_qty'], pt['Targets'])
            alert_id_meas = f"MEAS_{pt['machine']}_{meas_text}_{m_time.strftime('%Y%m%d_%H%M')}"
            msg_meas = f"🎯 {pt['machine']} 成型機（{meas_text}）のMFR測定を実施してください！"

        if alert_id_meas not in st.session_state.shown_alerts:
            st.session_state.shown_alerts.append(alert_id_meas); save_state()
            st.toast(msg_meas, icon="🚨") 

# 3. 電源ON・OFFアラーム
for b_start, b_end in on_blocks:
    if b_start <= now < b_end:
        alert_id_on = f"ON_{b_start.strftime('%Y%m%d_%H%M')}"
        if alert_id_on not in st.session_state.shown_alerts:
            st.session_state.shown_alerts.append(alert_id_on); save_state()
            target_tasks = [x['machine'] for x in valid_upcoming if b_start <= x['est_time'] <= b_end]
            target_machine = target_tasks[0] if target_tasks else "成型機"
            scheduled_time_str = (b_start + timedelta(minutes=60)).strftime('%H:%M')
            st.toast(f"🔥 MFR測定器 電源ON！（{target_machine} {scheduled_time_str} 予定）", icon="🔥")

    if b_end + timedelta(minutes=3) <= now < b_end + timedelta(minutes=18):
        alert_id_off = f"OFF_{b_end.strftime('%Y%m%d_%H%M')}"
        if alert_id_off not in st.session_state.shown_alerts:
            st.session_state.shown_alerts.append(alert_id_off); save_state()
            st.toast("💤 MFR測定器 電源OFF！（測定完了・冷却開始）", icon="💤")

# --- UI：ヘッダー ---
try:
    logo_base64 = get_image_base64(logo_path)
    logo_html = f"""<div style="display: flex; align-items: flex-end; gap: 15px; margin-bottom: 10px;"><img src="data:image/png;base64,{logo_base64}" width="100px"><h1 style="margin: 0; color: #1f2937; line-height: 0.9; position: relative; top: 8px;">MFRスマート電源管理システム</h1></div>"""
    st.markdown(logo_html, unsafe_allow_html=True)
except:
    st.title("MFRスマート電源管理システム")

st.write(f"現在時刻: **{now.strftime('%Y/%m/%d %H:%M:%S')}** (60秒ごとに自動更新中 🔄)")
st.markdown("---")

# --- MFR電源ステータス ---
st.subheader("💡 MFR測定器 電源ステータス")
is_monday = (today_date.weekday() == 0)

inspection_start_time = datetime.combine(today_date, dt_time(7, 0, 0))
inspection_end_time = datetime.combine(today_date, dt_time(10, 0, 0))

if st.session_state.last_inspection_date == today_date:
    st.success("✅ 本日の日常点検は完了しています。")
else:
    if inspection_start_time <= now < inspection_end_time:
        if is_monday: st.error("⚠️ 【至急】本日の日常点検が未完了です！ MFR電源をONにして点検を実施してください。（月曜は朝8:00）")
        else: st.error("⚠️ 【至急】本日の日常点検が未完了です！ MFR電源をONにして点検を実施してください。（火〜金は朝7:00）")
        if st.button("📝 点検が終わったので完了を記録する"):
            st.session_state.last_inspection_date = today_date; save_state(); st.rerun()
    elif now < inspection_start_time:
        if is_monday: st.warning("📋 本日の日常点検が未完了です。（月曜は朝8:00開始）")
        else: st.warning("📋 本日の日常点検が未完了です。（火〜金は朝7:00開始）")
st.markdown("---")

if not valid_upcoming:
    st.success("💤 **電源OFF推奨** (現在、稼働中で測定予定のジョブはありません)")
else:
    next_measure = valid_upcoming[0]
    time_diff = next_measure['est_time'] - now
    minutes_until = time_diff.total_seconds() / 60
    
    if next_measure['target_qty'] == '日常点検': meas_text = '日常点検'
    else: meas_text = f"{get_measurement_text(len(next_measure['Targets']), next_measure['target_qty'], next_measure['Targets'])}の測定"

    if minutes_until <= 60: st.error(f"🔥 **電源ON（加熱開始・維持）** \n\n次回の測定まで約 {max(0, int(minutes_until))} 分です。 ({next_measure['machine']}の{meas_text})")
    elif minutes_until >= 90: st.success(f"💤 **電源OFF推奨（待機）** \n\n次回の測定まで約 {int(minutes_until)} 分あります。ゆっくり冷まして設備負担を軽減してください。")
    else: st.warning(f"⚠️ **まもなくON（待機）** \n\n次回の測定まで約 {int(minutes_until)} 分です。現在はOFFのままで問題ありません。")
st.markdown("---")

# --- UI：成型機コントロールパネル ---
cols_top = st.columns(3)
machine_data = {}

for idx, machine in enumerate(['100t', '450t', '550t']):
    with cols_top[idx]:
        st.header(f"⚙️ {machine} 成型機")
        job = st.session_state.jobs[machine]
        est_current = 0
        
        if job is None:
            if not st.session_state.products:
                st.warning("⚠️ サイドバーから製品マスターを登録してください。")
            else:
                product_name = st.selectbox("製品名を選択", list(st.session_state.products.keys()), key=f"prod_sel_{machine}")
                prod_info = st.session_state.products[product_name]
                total_qty, cycle_time, meas_count = prod_info['qty'], prod_info['cycle'], prod_info['measurements']
                
                st.info(f"📊 **設定呼び出し:** 生産数 {total_qty}個 / サイクル {cycle_time}秒 / 測定 {meas_count}回")
                
                if meas_count == 2: targets = [1, total_qty]
                else: targets = [1, total_qty] if total_qty <= 2 else [1, total_qty // 2, total_qty]
                
                st.markdown("💡 **途中開始の場合の設定**")
                current_qty = st.number_input("現在の生産数 (0からなら0のまま)", min_value=0, max_value=int(total_qty), value=0, step=1, key=f"cur_{machine}")
                default_completed = [t for t in targets if t <= current_qty]
                completed = st.multiselect("既に測定済みのポイント", options=targets, default=default_completed, format_func=lambda x: f"{x}個目", key=f"comp_sel_{machine}")

                if st.button("▶️ 生産スタート", key=f"start_btn_{machine}"):
                    st.session_state.jobs[machine] = {
                        'product_name': product_name, 'total_qty': total_qty, 'cycle_time': cycle_time,
                        'current_qty': current_qty, 'last_update': (datetime.utcnow() + timedelta(hours=9)),
                        'targets': targets, 'completed': completed, 'status': 'Running'
                    }
                    save_state(); st.rerun()
        else:
            status_color = "🟢" if job['status'] == 'Running' else ("🟡" if job['status'] == 'Paused' else "✅")
            st.write(f"状態: {status_color} **{job['status']}**")
            p_name = job.get('product_name', '設定なし')
            st.write(f"製品: **{p_name}** ({job['total_qty']}個 / サイクル: {job['cycle_time']}秒)")

            if job['status'] == 'Running':
                elapsed_sec = ((datetime.utcnow() + timedelta(hours=9)) - job['last_update']).total_seconds()
                est_current = min(int(job['current_qty'] + (elapsed_sec / job['cycle_time'])), job['total_qty'])
            else:
                est_current = job['current_qty']
                
            st.metric("現在生産数 (推測)", f"{est_current} / {job['total_qty']}")
            
            if job['status'] != 'Completed':
                col_ctrl1, col_ctrl2 = st.columns(2)
                with col_ctrl1:
                    if job['status'] == 'Running':
                        if st.button("⏸️ 一時停止", key=f"pause_main_{machine}"):
                            job['current_qty'] = est_current; job['status'] = 'Paused'; save_state(); st.rerun()
                    elif job['status'] == 'Paused':
                        if st.button("▶️ 再開", key=f"resume_main_{machine}"):
                            job['last_update'] = (datetime.utcnow() + timedelta(hours=9)); job['status'] = 'Running'; save_state(); st.rerun()
                with col_ctrl2:
                    if st.button("⏹️ 生産終了", key=f"stop_main_{machine}"):
                        st.session_state.jobs[machine] = None; save_state(); st.rerun()

            if job['status'] == 'Completed':
                if st.button("🔄 次の製品の生産をセット", key=f"next_ok_{machine}"):
                    st.session_state.jobs[machine] = None; save_state(); st.rerun()

            st.divider()
            st.markdown('<div class="mfr-status-header">📋 MFR測定状況：</div>', unsafe_allow_html=True)
            num_targets = len(job['targets'])
            for t in job['targets']:
                meas_text = get_measurement_text(num_targets, t, job['targets'])
                if t in job['completed']: st.write(f"✅ {meas_text} ー 測定完了")
                else:
                    if st.button(f"🎯 {meas_text} ー 測定完了を記録", key=f"comp_{machine}_{t}"):
                        if job['status'] == 'Running':
                            elapsed_sec = ((datetime.utcnow() + timedelta(hours=9)) - job['last_update']).total_seconds()
                            job['current_qty'] = min(int(job['current_qty'] + (elapsed_sec / job['cycle_time'])), job['total_qty'])
                            job['last_update'] = (datetime.utcnow() + timedelta(hours=9))
                            
                        job['completed'].append(t)
                        if len(job['completed']) == len(job['targets']): 
                            job['status'] = 'Completed'
                            job['current_qty'] = job['total_qty']
                        save_state(); st.rerun()

        machine_data[machine] = {'job': job, 'est_current': est_current}

# 下段パネル
cols_bottom = st.columns(3)
for idx, machine in enumerate(['100t', '450t', '550t']):
    with cols_bottom[idx]:
        st.divider() 
        job = machine_data[machine]['job']
        est_current = machine_data[machine]['est_current']
        
        with st.expander("🔧 実績の補正・サイクル微調整", expanded=False):
            adjust_qty_value = est_current if job is not None else 0
            adjust_cycle_value = float(job['cycle_time']) if job is not None else 30.0
            
            st.markdown("💡 **① 個数のズレを修正**")
            new_qty = st.number_input("現在の実際の個数", min_value=0, max_value=job['total_qty'] if job is not None else 999999, value=adjust_qty_value, step=1, key=f"adj_qty_{machine}")
            if st.button("💾 個数を上書き更新", key=f"update_qty_{machine}"):
                if job is not None:
                    job['current_qty'] = new_qty
                    job['last_update'] = (datetime.utcnow() + timedelta(hours=9))
                    save_state(); st.rerun()
                else:
                    st.warning("稼働していません。")
            
            st.markdown("---")
            
            st.markdown("💡 **② サイクル(生産ペース)の変更**")
            new_cycle = st.number_input("サイクルタイム微調整(秒)", min_value=1.0, value=adjust_cycle_value, step=0.1, key=f"adj_cyc_{machine}")
            if st.button("💾 サイクルのみ変更", key=f"update_cyc_{machine}"):
                if job is not None:
                    job['current_qty'] = est_current 
                    job['cycle_time'] = new_cycle
                    job['last_update'] = (datetime.utcnow() + timedelta(hours=9))
                    save_state(); st.rerun()
                else:
                    st.warning("稼働していません。")
st.markdown("---")

# --- UI：シフト別スケジュール表 ---
def get_shift_name(dt):
    h = dt.hour
    if 7 <= h < 15: return "A勤"
    elif 15 <= h < 23: return "B勤"
    else: return "C勤"

st.subheader("🗓️ 各勤務の電源操作・作業フロー 一覧")
if on_blocks:
    html = "<table style='width:100%; border-collapse: collapse; font-size: 20px; text-align: center; margin-bottom: 20px;'>"
    html += "<tr style='background-color: #f3f4f6; color: #111; font-weight: bold; border-bottom: 3px solid #ccc;'><th style='padding: 15px; border: 1px solid #ddd; width: 10%;'>状態</th><th style='padding: 15px; border: 1px solid #ddd; width: 30%;'>電源ON担当・ON時刻</th><th style='padding: 15px; border: 1px solid #ddd;'>作業フロー</th></tr>"
    for b_start, b_end in on_blocks:
        status_text = "完了" if b_end < now else ("進行中" if b_start <= now <= b_end else "予定")
        bg_color = "#e6ffe6" if status_text == "完了" else ("#fffdeb" if status_text == "進行中" else "#ffffff")
        on_assignee = get_shift_name(b_start)
        on_time = b_start.strftime('%m/%d %H:%M')
        
        tasks_in_flow = []
        for pt in valid_upcoming:
            if b_start <= pt['est_time'] <= b_end:
                if pt['machine'] == '日常点検(A勤)': tasks_in_flow.append("日常点検")
                else: tasks_in_flow.append(f"{pt['machine']}MFR測定({get_measurement_text(len(pt['Targets']), pt['target_qty'], pt['Targets'])})")
        
        flow_full_text = " ➡ ".join(tasks_in_flow) + " ➡ OFF" if tasks_in_flow else "➡ OFF (測定なし)"
        flow_full_html = f"<span style='color: #000; font-size: 22px;'>➡</span> {flow_full_text}"
        
        html += f"<tr style='background-color: {bg_color}; border-bottom: 1px solid #ddd;'><td style='padding: 15px; font-weight: bold;'>{status_text}</td><td style='padding: 15px; font-weight: bold;'><span style='color: #d32f2f; font-size: 24px;'>🔥 ON: </span> {on_assignee} ({on_time})</td><td style='padding: 15px; font-weight: bold; text-align: left;'>{flow_full_html}</td></tr>"
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)
else:
    st.info("現在、予定されている電源操作はありません。")

# --- UI：全体可視化グラフ ---
st.subheader("📈 成型機稼働状況・MFR電源スケジュール")

timeline_data = []
measurement_points = []

for machine, job in st.session_state.jobs.items():
    if job is None: continue
    start_time = job['last_update']
    end_time = (datetime.utcnow() + timedelta(hours=9)) if job['status'] == 'Completed' else job['last_update'] + timedelta(seconds=(job['total_qty'] - job['current_qty']) * job['cycle_time'])
    timeline_data.append({'Task': machine, 'Start': start_time, 'End': end_time, 'Status': job['status'], 'Targets': job['targets']})

    for t in job['targets']:
        t_time = job['last_update'] if job['status'] != 'Running' or (t - job['current_qty']) <= 0 else job['last_update'] + timedelta(seconds=(t - job['current_qty']) * job['cycle_time'])
        measurement_points.append({'Task': machine, 'Time': t_time, 'Target_Qty': t, 'Targets': job['targets'], 'Status': 'Completed' if (t in job['completed']) else 'Planned'})

today_start = datetime.combine(now.date(), dt_time.min)

if st.session_state.last_inspection_date == today_date:
    inspection_time = datetime(now.year, now.month, now.day, 8 if is_monday else 7, 0, 0)
    measurement_points.append({'Task': 'MFR電源', 'Time': inspection_time, 'Target_Qty': '点検済', 'Targets': ['点検済'], 'Status': 'Completed'})

for pt in valid_upcoming:
    if pt['machine'] == '日常点検(A勤)':
        measurement_points.append({'Task': 'MFR電源', 'Time': pt['est_time'], 'Target_Qty': '日常点検', 'Targets': ['日常点検'], 'Status': 'Planned'})

for b_start, b_end in on_blocks:
    timeline_data.append({'Task': 'MFR電源', 'Start': max(b_start, now), 'End': max(b_end, now), 'Status': 'ON'})

DUMMY_DATE = datetime(2000, 1, 1)
def time_to_dummy(dt):
    return datetime.combine(DUMMY_DATE, dt.time()) if isinstance(dt, datetime) else datetime.combine(DUMMY_DATE, dt)

def get_date_str(dt):
    weekdays = ['月', '火', '水', '木', '金', '土', '日']
    return f"{dt.strftime('%m/%d')} ({weekdays[dt.weekday()]})"

new_timeline_data = []
overall_end_time = now + timedelta(hours=1) 

for d in timeline_data:
    if d['End'] < today_start: continue
    if d['End'] > overall_end_time: overall_end_time = d['End']
    curr_start = max(d['Start'], today_start)
    end_time = max(d['End'], curr_start)

    while curr_start.date() < end_time.date():
        eod = datetime.combine(curr_start.date(), datetime.max.time())
        new_timeline_data.append({'Task': d['Task'], 'StartDummy': time_to_dummy(curr_start), 'EndDummy': time_to_dummy(eod), 'Status': d['Status'], 'DateStr': get_date_str(curr_start)})
        curr_start = datetime.combine(curr_start.date() + timedelta(days=1), datetime.min.time())
        
    if curr_start <= end_time:
        new_timeline_data.append({'Task': d['Task'], 'StartDummy': time_to_dummy(curr_start), 'EndDummy': time_to_dummy(end_time), 'Status': d['Status'], 'DateStr': get_date_str(curr_start)})

new_measurement_points = []
for pt in measurement_points:
    if pt['Time'] < today_start: continue
    if pt['Time'] > overall_end_time: overall_end_time = pt['Time']
    new_measurement_points.append({'Task': pt['Task'], 'TimeDummy': time_to_dummy(pt['Time']), 'DateStr': get_date_str(pt['Time']), 'Target_Qty': pt['Target_Qty'], 'Targets': pt.get('Targets', []), 'Status': pt['Status']})

if new_timeline_data:
    df = pd.DataFrame(new_timeline_data)
    unique_dates = sorted(list(set(df['DateStr']))) 
    
    date_to_row = {date: len(unique_dates) - i for i, date in enumerate(unique_dates)}
    
    fig = px.timeline(
        df, x_start="StartDummy", x_end="EndDummy", y="Task", color="Status", facet_row="DateStr",
        color_discrete_map={'Running': '#00a82d', 'Paused': '#f5a623', 'Completed': '#88d8b0', 'ON': '#ff3333'},
        facet_row_spacing=0.15,
        category_orders={"DateStr": unique_dates, "Task": ["MFR電源", "550t", "450t", "100t"]} 
    )
    
    fig.update_yaxes(
        title_text="", tickfont=dict(size=16, color="black", weight="bold"), 
        autorange=False, range=[3.8, -0.8],
        showline=True, linewidth=1, linecolor='gray', mirror=True
    )
    
    fig.update_xaxes(
        title_text="", tickformat="%H:%M", dtick=3600000, 
        tickfont=dict(size=14, color="black", weight="bold"),
        range=[datetime(2000, 1, 1, 0, 0, 0), datetime(2000, 1, 2, 0, 0, 0)],
        showgrid=True, gridcolor='rgba(150, 150, 150, 0.5)', gridwidth=1, griddash='dot',
        showticklabels=True,
        showline=True, linewidth=1, linecolor='gray', mirror=True
    )
    fig.layout.xaxis.title.text = "時間（各シフトごとの担当帯）"

    fig.add_vrect(x0=time_to_dummy(dt_time(0,0)), x1=time_to_dummy(dt_time(7,0)), fillcolor="#e6f2ff", opacity=0.4, layer="below", line_width=1, line_color="gray")
    fig.add_vrect(x0=time_to_dummy(dt_time(7,0)), x1=time_to_dummy(dt_time(15,0)), fillcolor="#fff5cc", opacity=0.4, layer="below", line_width=1, line_color="gray")
    fig.add_vrect(x0=time_to_dummy(dt_time(15,0)), x1=time_to_dummy(dt_time(23,0)), fillcolor="#e6ffe6", opacity=0.4, layer="below", line_width=1, line_color="gray")
    fig.add_vrect(x0=time_to_dummy(dt_time(23,0)), x1=time_to_dummy(dt_time(23,59,59)), fillcolor="#e6f2ff", opacity=0.4, layer="below", line_width=1, line_color="gray")

    for facet_date in unique_dates:
        row_idx = date_to_row[facet_date]
        shifts_text = [
            ("C勤", time_to_dummy(dt_time(3, 30)), 'rgba(0,68,136,0.05)'),
            ("A勤", time_to_dummy(dt_time(11, 0)), 'rgba(136,102,0,0.05)'),
            ("B勤", time_to_dummy(dt_time(19, 0)), 'rgba(0,102,0,0.05)')
        ]
        for text, x_pos, color in shifts_text:
            fig.add_annotation(
                x=x_pos, y=1.5, text=text, font=dict(size=120, color=color, weight="bold"),
                showarrow=False, xanchor="center", yanchor="middle", row=row_idx, col=1
            )
            
    today_str = get_date_str(now)
    if today_str in date_to_row:
        today_row = date_to_row[today_str]
        now_dummy_time = time_to_dummy(now)
        fig.add_vline(x=now_dummy_time, line_width=3, line_dash="dash", line_color="#ff0000", layer="above", row=today_row, col=1)
        yref_name = f"y{today_row if today_row > 1 else ''} domain"
        fig.add_annotation(
            x=now_dummy_time, y=1.02, yref=yref_name, text="▼ 現在", font=dict(size=18, color="#ff0000", weight="bold"), 
            showarrow=False, xanchor="center", yanchor="bottom", bgcolor="white", bordercolor="#ff0000", borderwidth=1, row=today_row, col=1
        )

    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1], font=dict(size=22, weight="bold", color="black")) if "=" in a.text else None)

    if new_measurement_points:
        df_pts = pd.DataFrame(new_measurement_points)
        for facet_date in unique_dates:
            row_idx = date_to_row[facet_date]
            df_pts_in_facet = df_pts[df_pts['DateStr'] == facet_date]
            if df_pts_in_facet.empty: continue
            
            df_comp = df_pts_in_facet[df_pts_in_facet['Status'] == 'Completed']
            if not df_comp.empty:
                trace_completed_text = ['点検済' if pt.get('Targets', []) and pt['Targets'][0] == '点検済' else get_measurement_text(len(pt.get('Targets', [])), pt['Target_Qty'], pt.get('Targets', [])) for pt in df_comp.to_dict('records')]
                fig.add_trace(go.Scatter(
                    x=df_comp['TimeDummy'], y=df_comp['Task'], mode='markers+text',
                    marker=dict(color='#00e6e6', size=18, symbol='circle', line=dict(width=2, color='black')),
                    text=trace_completed_text, textposition='top center', textfont=dict(size=18, color='black', weight='bold'),
                    cliponaxis=False, hoverinfo='skip', showlegend=False 
                ), row=row_idx, col=1)

            df_plan = df_pts_in_facet[df_pts_in_facet['Status'] == 'Planned']
            if not df_plan.empty:
                trace_planned_text = ['日常点検' if pt.get('Targets', []) and pt['Targets'][0] == '日常点検' else get_measurement_text(len(pt.get('Targets', [])), pt['Target_Qty'], pt.get('Targets', [])) for pt in df_plan.to_dict('records')]
                fig.add_trace(go.Scatter(
                    x=df_plan['TimeDummy'], y=df_plan['Task'], mode='markers+text',
                    marker=dict(color='#ffff00', size=20, symbol='diamond', line=dict(width=2, color='black')),
                    text=trace_planned_text, textposition='top center', textfont=dict(size=20, color='black', weight='bold'),
                    cliponaxis=False, hoverinfo='skip', showlegend=False 
                ), row=row_idx, col=1)

    fig.update_layout(
        height=max(700, len(unique_dates) * 350), margin=dict(t=120, b=50, l=100, r=50), showlegend=True,
        uirevision='constant'
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("📊 グラフを表示するための稼働中のジョブはありません。")

# --- UI：🌱EcoNavi ---
st.markdown("---")
st.header("🌱 EcoNavi")
st.write("日々のこまめな電源OFF運用によって節約できた「電気代」と、「ヒーター等の設備寿命延長に伴う修繕費の削減額」を自動計算するシミュレーターです。")

with st.expander("📊 現在のスケジュールにおける削減効果金額を計算", expanded=True):
    col_k, col_e, col_h, col_l = st.columns(4)
    with col_k: power_kw = st.number_input("MFR消費電力 (kW)", value=0.80, step=0.10, format="%.2f", help="最大値 0.80 kW")
    with col_e: elec_price = st.number_input("電気代単価 (円/kWh)", value=20.00, step=1.00, format="%.2f", help="20～25円目安")
    with col_h: heater_cost = st.number_input("修繕・メンテナンス費用 (円)", value=150000, step=10000, help="部品交換や修理にかかる1回あたりの概算費用")
    with col_l: heater_life_hours = st.number_input("メンテナンス周期 (時間)", value=10000, step=1000, help="上記の修繕が必要になるまでの想定稼働時間（過去の記録から設定）")

    if timeline_data and on_blocks:
        schedule_start = min([d['Start'] for d in timeline_data])
        schedule_end = max([d['End'] for d in timeline_data])
        total_hours = (schedule_end - schedule_start).total_seconds() / 3600
        new_on_hours = sum([(b_end - b_start).total_seconds() for b_start, b_end in on_blocks]) / 3600
        saved_hours = total_hours - new_on_hours
        
        if saved_hours > 0:
            saved_cost = saved_hours * power_kw * elec_price
            saved_heater_value = saved_hours * (heater_cost / heater_life_hours)

            st.success(f"✨ **現在のスケジュール期間中（約 {total_hours:.1f} 時間）の改善効果**")
            res_col1, res_col2, res_col3 = st.columns(3)
            
            help_time = "【計算式】\n従来OFFにしていなかった全期間の時間 － 今回のスケジュールでONになっている時間"
            help_elec = "【計算式】\n削減できた待機時間 × MFR消費電力(kW) × 電気代単価"
            help_maint = "【計算式】\n削減できた待機時間 × (修繕・メンテナンス費用 ÷ メンテナンス周期)\n\n※稼働時間が減ることで、将来発生するメンテナンス費用をどれだけ先送り（節約）できたかを金額換算しています。"
            
            res_col1.metric("無駄な待機時間の削減", f"{saved_hours:.1f} 時間", f"従来: {total_hours:.1f}h → 今回: {new_on_hours:.1f}h", delta_color="inverse", help=help_time)
            res_col2.metric("電気代の削減", f"{int(saved_cost):,} 円", f"▲ {int(saved_cost)}円", delta_color="inverse", help=help_elec)
            res_col3.metric("設備寿命(修繕費)の節約換算", f"{int(saved_heater_value):,} 円", "部品の長寿命化による効果", help=help_maint)
            st.caption("※この計算は現在画面に表示されているジョブ（未来の予測を含む）を対象とした概算シミュレーションです。")

            # --- 可視化グラフの追加と調整 ---
            st.markdown("<br>", unsafe_allow_html=True)
            
            old_elec = total_hours * power_kw * elec_price
            old_maint = total_hours * (heater_cost / heater_life_hours)
            new_elec = new_on_hours * power_kw * elec_price
            new_maint = new_on_hours * (heater_cost / heater_life_hours)
            total_old = old_elec + old_maint
            total_new = new_elec + new_maint
            saved_total = total_old - total_new

            df_eco = pd.DataFrame([
                {"運用方法": "❌ 従来の運用 (ずっとON)", "コスト内訳": "電気代", "金額": old_elec},
                {"運用方法": "❌ 従来の運用 (ずっとON)", "コスト内訳": "修繕費 (寿命換算)", "金額": old_maint},
                {"運用方法": "✨ EcoNavi スマート運用", "コスト内訳": "電気代", "金額": new_elec},
                {"運用方法": "✨ EcoNavi スマート運用", "コスト内訳": "修繕費 (寿命換算)", "金額": new_maint}
            ])

            # 配色は暖色系（オレンジ・赤系）を維持
            fig_eco = px.bar(
                df_eco, x="運用方法", y="金額", color="コスト内訳",
                text="金額",
                color_discrete_map={"電気代": "#f4a261", "修繕費 (寿命換算)": "#e76f51"} 
            )
            fig_eco.update_traces(texttemplate='<b>%{text:,.0f} 円</b>', textposition='inside', insidetextfont=dict(size=18, color="white"))
            
            fig_eco.update_layout(
                barmode='stack',
                height=550, 
                title=dict(text="<b>📊 スマート運用によるコスト削減効果</b>", font=dict(size=22)), 
                xaxis_title="",
                yaxis_title="発生コスト（円）",
                yaxis=dict(range=[0, total_old * 1.5], tickfont=dict(size=14, weight="bold")),
                xaxis=dict(tickfont=dict(size=18, weight="bold")),
                legend=dict(
                    title="<b>コスト内訳</b>",
                    orientation="h",
                    yanchor="bottom", y=1.02,
                    xanchor="right", x=1,
                    font=dict(size=14, weight="bold")
                ),
                margin=dict(t=80, b=50, l=50, r=50),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(250, 250, 250, 1)",
                yaxis_showgrid=True, yaxis_gridcolor="rgba(200,200,200,0.5)"
            )

            # トータル金額を棒の上に配置
            fig_eco.add_annotation(x="❌ 従来の運用 (ずっとON)", y=total_old, yshift=15, yanchor="bottom", text=f"<b>計 {int(total_old):,} 円</b>", showarrow=False, font=dict(size=22))
            fig_eco.add_annotation(x="✨ EcoNavi スマート運用", y=total_new, yshift=15, yanchor="bottom", text=f"<b>計 {int(total_new):,} 円</b>", showarrow=False, font=dict(size=22, color="#00a82d"))

            import math
            # --- デザインの良い矢印への変更（動的アングル計算） ---
            approx_dx_px = 500  
            approx_dy_px = ((total_old - total_new) / (total_old * 1.5)) * 400 
            
            angle_deg = int(math.degrees(math.atan2(approx_dy_px, approx_dx_px)))

            fig_eco.add_annotation(
                x=0.5, y=(total_old + total_new) / 2, xref="paper", yref="y",
                text="<span style='font-size: 80px; color: #e63946; text-shadow: 2px 2px 3px rgba(0,0,0,0.2);'>➡</span>",
                showarrow=False,
                textangle=angle_deg 
            )
            
            fig_eco.add_annotation(
                x=0.5, y=total_old * 1.15, xref="paper", yref="y", yanchor="bottom", 
                text=f"<b>✨ 削減効果</b><br><br><b><span style='font-size:42px; color:#d00000;'>▲ {int(saved_total):,} 円</span></b>",
                showarrow=False,
                font=dict(size=22, color="#111"),
                bgcolor="#fffdeb", bordercolor="#e63946", borderwidth=3, borderpad=15
            )

            st.plotly_chart(fig_eco, use_container_width=True)

        else:
            st.info("現在のスケジュールでは、測定が連続しているためOFFにする空き時間がありません。")
    else:
        st.write("稼働中のジョブを登録すると、ここに削減効果金額が表示されます。")
