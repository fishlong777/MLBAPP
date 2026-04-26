import streamlit as st
from pybaseball import statcast_batter, playerid_lookup
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import unicodedata

# 設定頁面配置
st.set_page_config(layout="wide", page_title="MLB 球員分析系統")

# --- 1. 核心函數：處理特殊字元 ---
def normalize_text(text):
    if not isinstance(text, str): return ""
    # 徹底移除所有重音符號並轉小寫，用於精準比對
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower().strip()

# --- 2. 核心函數：座標轉換 ---
def transform_coords_refined(hc_x, hc_y, distance, events):
    if pd.isna(hc_x) or pd.isna(hc_y) or (hc_x == 0 and hc_y == 0): return None, None
    theta_offset = (hc_x - 125.42) * 0.0085
    theta = np.pi / 2 - theta_offset
    theta = np.clip(theta, np.pi / 4 + 0.01, 3 * np.pi / 4 - 0.01)
    r = float(distance) if not pd.isna(distance) else 15.0
    r = max(r, 18.0)
    return r * np.cos(theta), r * np.sin(theta)

# --- 3. 繪圖函數 ---
def plot_spray_chart(df):
    fig = go.Figure()
    t_range = np.linspace(np.pi / 4, 3 * np.pi / 4, 100)
    wall_radii = [355 + 45 * np.cos(2 * (t - np.pi / 2)) for t in t_range]
    wall_x, wall_y = [r * np.cos(t) for r, t in zip(wall_radii, t_range)], [r * np.sin(t) for r, t in zip(wall_radii, t_range)]
    
    # 繪製球場背景與牆
    fig.add_trace(go.Scatter(x=[0]+wall_x+[0], y=[0]+wall_y+[0], fill='toself', fillcolor='rgba(34, 139, 34, 0.2)', line_width=0, showlegend=False))
    fig.add_trace(go.Scatter(x=wall_x, y=wall_y, mode='lines', line=dict(color='red', dash='dash', width=3), name='全壘打牆'))
    
    # 繪製內野
    s = 90 / np.sqrt(2)
    fig.add_trace(go.Scatter(x=[0, s, 0, -s, 0], y=[0, s, s*2, s, 0], mode='lines+markers', line=dict(color='black', width=3), marker=dict(symbol='square', size=13, color='white', line=dict(width=1.5, color='black')), showlegend=False))
    
    # 繪製擊球點
    for i, row in df.iterrows():
        tx, ty = transform_coords_refined(row['hc_x'], row['hc_y'], row['hit_distance_sc'], row['events'])
        if tx is not None:
            is_hr = 'home run' in str(row['events']).lower()
            fig.add_trace(go.Scatter(x=[tx], y=[ty], mode='markers', marker=dict(size=28 if is_hr else 18, color=row['color'], line=dict(width=3 if is_hr else 1.5, color='gold' if is_hr else 'black')), hovertemplate=f"結果: {row['events']}<br>距離: {row['hit_distance_sc']} ft", showlegend=False))
    
    fig.update_layout(xaxis=dict(visible=False, range=[-400, 400], scaleanchor="y", scaleratio=1), yaxis=dict(visible=False, range=[-30, 500]), width=700, height=700, plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0))
    return fig

# --- 4. 數據邏輯：地毯式搜尋 ---
if 'data_cache' not in st.session_state: st.session_state.data_cache = None
if 'p_name' not in st.session_state: st.session_state.p_name = ""

st.sidebar.header("球員查詢")
p_query = st.sidebar.text_input("輸入球員姓名", placeholder="例如：Javier Baez").strip()

if st.sidebar.button("查詢資料"):
    try:
        names = p_query.lower().split()
        if len(names) >= 2:
            with st.spinner('連線 MLB 伺服器進行精準比對...'):
                last_in, first_in = names[-1], names[0]
                
                # 嘗試原始姓氏與常見重音補正
                seeds = [last_in]
                corrections = {"baez": "Báez", "alvarez": "Álvarez", "acuna": "Acuña"}
                if last_in in corrections: seeds.append(corrections[last_in])
                
                results = [playerid_lookup(s) for s in list(set(seeds))]
                candidates = pd.concat(results).drop_duplicates(subset=['key_mlbam']) if results else pd.DataFrame()

                if not candidates.empty:
                    # 本地端脫殼比對
                    candidates['f_norm'] = candidates['name_first'].apply(normalize_text)
                    candidates['l_norm'] = candidates['name_last'].apply(normalize_text)
                    target_f, target_l = normalize_text(first_in), normalize_text(last_in)
                    
                    match = candidates[(candidates['f_norm'] == target_f) & (candidates['l_norm'] == target_l)].sort_values('mlb_played_last', ascending=False).head(1)

                    if not match.empty:
                        res = match.iloc[0]
                        # 儲存原始名字（首字母大寫），避免顯示為小寫
                        st.session_state.p_name = f"{res['name_first']} {res['name_last']}".title()
                        raw = statcast_batter('2024-03-01', '2026-12-31', res['key_mlbam'])
                        st.session_state.data_cache = raw[raw['events'].notna()].copy()
                    else:
                        st.error(f"找不到球員：{p_query}")
                else:
                    st.error(f"查無姓氏：{last_in}")
    except Exception as e:
        st.error(f"連線異常: {e}")

# --- 5. 顯示端 (修正名字顯示) ---
if st.session_state.data_cache is not None and st.session_state.p_name != "":
    df = st.session_state.data_cache
    df['game_date'] = pd.to_datetime(df['game_date']).dt.date
    dates = sorted(df['game_date'].unique(), reverse=True)[:10]
    sel_date = st.sidebar.selectbox("選擇日期", dates)
    
    curr = df[df['game_date'] == sel_date].copy().sort_values('at_bat_number').reset_index(drop=True)
    clist = ['#AEC7E8', '#FFBB78', '#98DF8A', '#FF9896', '#C5B0D5', '#C49C94', '#F7B6D2', '#DBDB8D', '#9EDAE5', '#D62728']
    curr['color'] = [clist[i % len(clist)] for i in range(len(curr))]
    
    # 使用 Markdown 並強制取消 text-transform 限制，確保首字母大寫正確顯示
    st.markdown(f"<h1 style='text-transform: none;'>{st.session_state.p_name} - {sel_date}</h1><hr>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([1.2, 1])
    with c1: st.plotly_chart(plot_spray_chart(curr), use_container_width=True)
    with c2:
        st.subheader("📊 打席明細")
        t_df = curr[['events', 'launch_speed', 'launch_angle', 'hit_distance_sc']].copy()
        t_df.columns = ['結果', '初速(mph)', '仰角(°)', '距離(ft)']
        for col in t_df.columns[1:]: t_df[col] = pd.to_numeric(t_df[col]).fillna(0.0).map('{:.1f}'.format)
        st.table(t_df.style.apply(lambda r: [f'background-color: {curr.loc[r.name, "color"]}; color: black; font-weight: bold'] * len(r), axis=1))
