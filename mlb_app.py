import streamlit as st
from pybaseball import statcast_batter, playerid_lookup
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime
import unicodedata

# 設定頁面配置
st.set_page_config(layout="wide", page_title="MLB 球員分析系統")

# --- 1. 核心函數：處理特殊字元 ---
def normalize_text(text):
    if not isinstance(text, str): return ""
    # 將重音符號拆解並移除，例如 Báez -> baez
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower().strip()

# --- 2. 核心函數：動態球場牆界計算 ---
def get_wall_radius(theta):
    base_wall = 355  
    depth_variation = 45  
    return base_wall + depth_variation * np.cos(2 * (theta - np.pi / 2))

# --- 3. 核心函數：座標轉換 ---
def transform_coords_refined(hc_x, hc_y, distance, events):
    if pd.isna(hc_x) or pd.isna(hc_y) or (hc_x == 0 and hc_y == 0):
        return None, None
    theta_offset = (hc_x - 125.42) * 0.0085
    theta = np.pi / 2 - theta_offset
    theta = np.clip(theta, np.pi / 4 + 0.01, 3 * np.pi / 4 - 0.01)
    r = float(distance) if not pd.isna(distance) else 15.0
    r = max(r, 18.0)
    tx = r * np.cos(theta)
    ty = r * np.sin(theta)
    return tx, ty

# --- 4. 繪圖函數 ---
def plot_spray_chart(df):
    fig = go.Figure()
    t_range = np.linspace(np.pi / 4, 3 * np.pi / 4, 100)
    wall_radii = [get_wall_radius(t) for t in t_range]
    wall_x = [r * np.cos(t) for r, t in zip(wall_radii, t_range)]
    wall_y = [r * np.sin(t) for r, t in zip(wall_radii, t_range)]
    
    fig.add_trace(go.Scatter(x=[0] + wall_x + [0], y=[0] + wall_y + [0], fill='toself', fillcolor='rgba(34, 139, 34, 0.2)', line_width=0, showlegend=False))
    fig.add_trace(go.Scatter(x=[0] + (145 * np.cos(t_range)).tolist() + [0], y=[0] + (145 * np.sin(t_range)).tolist() + [0], fill='toself', fillcolor='rgba(255, 165, 0, 0.3)', line_width=0, showlegend=False))
    fig.add_trace(go.Scatter(x=wall_x, y=wall_y, mode='lines', line=dict(color='red', dash='dash', width=3), name='全壘打牆'))
    
    s = 90 / np.sqrt(2)
    fig.add_trace(go.Scatter(x=[0, s, 0, -s, 0], y=[0, s, s * 2, s, 0], mode='lines+markers', line=dict(color='black', width=3), marker=dict(symbol='square', size=13, color='white', line=dict(width=1.5, color='black')), showlegend=False))
    
    for i, row in df.iterrows():
        tx, ty = transform_coords_refined(row['hc_x'], row['hc_y'], row['hit_distance_sc'], row['events'])
        if tx is not None:
            is_hr = 'home run' in str(row['events']).lower()
            marker_size = 28 if is_hr else 18
            line_color = 'gold' if is_hr else 'black'
            line_width = 3 if is_hr else 1.5
            fig.add_trace(go.Scatter(x=[tx], y=[ty], mode='markers', marker=dict(size=marker_size, color=row['color'], line=dict(width=line_width, color=line_color)), hovertemplate=f"打席: {i + 1}<br>結果: {row['events']}<br>距離: {row['hit_distance_sc']} ft", showlegend=False))
    
    fig.update_layout(xaxis=dict(visible=False, range=[-400, 400], scaleanchor="y", scaleratio=1), yaxis=dict(visible=False, range=[-30, 500]), width=700, height=700, plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0))
    return fig

# --- 5. 數據邏輯：窮舉搜尋機制 ---
if 'data_cache' not in st.session_state: st.session_state.data_cache = None
if 'p_name' not in st.session_state: st.session_state.p_name = ""

st.sidebar.header("球員查詢")
p_query = st.sidebar.text_input("輸入球員姓名", placeholder="例如：Javier Baez").strip()

if st.sidebar.button("查詢資料"):
    try:
        names = p_query.split()
        if len(names) >= 1:
            with st.spinner('正在分析全球員數據庫...'):
                first_in = names[0]
                last_in = names[-1]
                
                # 同時嘗試多種搜尋路徑
                search_list = []
                search_list.append(playerid_lookup(last_in, first_in)) # 標準搜尋
                search_list.append(playerid_lookup(last_in))           # 廣域姓氏搜尋
                
                # 處理重音路徑
                norm_last = normalize_text(last_in)
                if norm_last != last_in.lower():
                    search_list.append(playerid_lookup(norm_last))
                
                # 合併所有候選人並移除重複項
                candidates = pd.concat(search_list).drop_duplicates(subset=['key_mlbam']) if search_list else pd.DataFrame()
                
                if not candidates.empty:
                    # 在本地端進行全量「脫重音」比對
                    candidates['f_norm'] = candidates['name_first'].apply(normalize_text)
                    candidates['l_norm'] = candidates['name_last'].apply(normalize_text)
                    
                    target_f = normalize_text(first_in)
                    target_l = normalize_text(last_in)
                    
                    # 篩選最匹配的在役球員
                    match = candidates[
                        (candidates['f_norm'] == target_f) & 
                        (candidates['l_norm'] == target_l)
                    ].sort_values('mlb_played_last', ascending=False).head(1)

                    if not match.empty:
                        res = match.iloc[0]
                        st.session_state.p_name = f"{res['name_first']} {res['name_last']}"
                        pid = res['key_mlbam']
                        raw = statcast_batter('2024-03-01', '2026-12-31', pid)
                        st.session_state.data_cache = raw[raw['events'].notna()].copy()
                    else:
                        st.session_state.p_name = ""
                        st.session_state.data_cache = None
                        st.error("比對失敗，請確認名字拼寫")
                else:
                    st.session_state.p_name = ""
                    st.session_state.data_cache = None
                    st.error("找不到該姓氏的球員")
    except Exception as e:
        st.error(f"連線異常: {e}")

# --- 6. 顯示端 ---
if st.session_state.data_cache is not None and st.session_state.p_name != "":
    df = st.session_state.data_cache
    df['game_date'] = pd.to_datetime(df['game_date']).dt.date
    dates = sorted(df['game_date'].unique(), reverse=True)[:10]
    sel_date = st.sidebar.selectbox("選擇日期", dates)
    curr = df[df['game_date'] == sel_date].copy().sort_values('at_bat_number').reset_index(drop=True)
    curr['events'] = curr['events'].str.replace('_', ' ').str.replace('intent walk', 'intentional walk', case=False)
    
    clist = ['#AEC7E8', '#FFBB78', '#98DF8A', '#FF9896', '#C5B0D5', '#C49C94', '#F7B6D2', '#DBDB8D', '#9EDAE5', '#D62728']
    curr['color'] = [clist[i % len(clist)] for i in range(len(curr))]
    
    display_name = " ".join([word.capitalize() for word in str(st.session_state.p_name).split()])
    st.markdown(f"<h1 style='text-transform: none !important;'>{display_name} - {sel_date}</h1><hr>", unsafe_allow_html=True)

    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.plotly_chart(plot_spray_chart(curr), use_container_width=True)
    with c2:
        st.subheader("📊 打席明細")
        t_df = curr[['events', 'launch_speed', 'launch_angle', 'hit_distance_sc']].copy()
        t_df.columns = ['結果', '初速(mph)', '仰角(°)', '距離(ft)']
        for col in t_df.columns[1:]: 
            t_df[col] = pd.to_numeric(t_df[col]).fillna(0.0).map('{:.1f}'.format)
        t_df.insert(0, '打席', range(1, len(t_df) + 1))
        st.table(t_df.style.apply(lambda r: [f'background-color: {curr.loc[r.name, "color"]}; color: black; font-weight: bold'] * len(r), axis=1))
