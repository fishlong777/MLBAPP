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
    # 去除重音符號並轉小寫，例如 Báez -> baez
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower()

# --- 2. 核心函數：動態球場牆界計算 ---
def get_wall_radius(theta):
    base_wall = 355  
    depth_variation = 45  
    return base_wall + depth_variation * np.cos(2 * (theta - np.pi / 2))

# --- 3. 核心函數：座標轉換 (100% 準確版) ---
def transform_coords_refined(hc_x, hc_y, distance, events):
    if pd.isna(hc_x) or pd.isna(hc_y) or (hc_x == 0 and hc_y == 0):
        return None, None

    theta_offset = (hc_x - 125.42) * 0.0085
    theta = np.pi / 2 - theta_offset
    theta = np.clip(theta, np.pi / 4 + 0.01, 3 * np.pi / 4 - 0.01)

    # 這裡我們完全尊重原始距離數據，不做視覺位移
    r = float(distance) if not pd.isna(distance) else 15.0
    r = max(r, 18.0)

    tx = r * np.cos(theta)
    ty = r * np.sin(theta)
    return tx, ty

# --- 4. 繪圖函數：強化全壘打視覺特徵 ---
def plot_spray_chart(df):
    fig = go.Figure()
    t_range = np.linspace(np.pi / 4, 3 * np.pi / 4, 100)
    wall_radii = [get_wall_radius(t) for t in t_range]
    wall_x = [r * np.cos(t) for r, t in zip(wall_radii, t_range)]
    wall_y = [r * np.sin(t) for r, t in zip(wall_radii, t_range)]

    # 繪製球場背景
    fig.add_trace(go.Scatter(x=[0] + wall_x + [0], y=[0] + wall_y + [0], fill='toself', fillcolor='rgba(34, 139, 34, 0.2)', line_width=0, showlegend=False))
    fig.add_trace(go.Scatter(x=[0] + (145 * np.cos(t_range)).tolist() + [0], y=[0] + (145 * np.sin(t_range)).tolist() + [0], fill='toself', fillcolor='rgba(255, 165, 0, 0.3)', line_width=0, showlegend=False))
    fig.add_trace(go.Scatter(x=wall_x, y=wall_y, mode='lines', line=dict(color='red', dash='dash', width=3), name='全壘打牆'))

    # 繪製壘包
    s = 90 / np.sqrt(2)
    fig.add_trace(go.Scatter(x=[0, s, 0, -s, 0], y=[0, s, s * 2, s, 0], mode='lines+markers', line=dict(color='black', width=3), marker=dict(symbol='square', size=13, color='white', line=dict(width=1.5, color='black')), showlegend=False))

    # 繪製打擊落點
    for i, row in df.iterrows():
        tx, ty = transform_coords_refined(row['hc_x'], row['hc_y'], row['hit_distance_sc'], row['events'])
        if tx is not None:
            is_hr = 'home run' in str(row['events']).lower()
            
            # --- 視覺強化邏輯 ---
            # 如果是全壘打：加大尺寸 (25) 並使用金色外框
            # 如果是一般球：維持尺寸 (18) 並使用黑色外框
            marker_size = 28 if is_hr else 18
            line_color = 'gold' if is_hr else 'black'
            line_width = 3 if is_hr else 1.5
            
            fig.add_trace(go.Scatter(
                x=[tx], y=[ty], 
                mode='markers',
                marker=dict(
                    size=marker_size, 
                    color=row['color'], 
                    line=dict(width=line_width, color=line_color)
                ),
                hovertemplate=f"打席: {i + 1}<br>結果: {row['events']}<br>距離: {row['hit_distance_sc']} ft",
                showlegend=False
            ))

    fig.update_layout(xaxis=dict(visible=False, range=[-400, 400], scaleanchor="y", scaleratio=1), yaxis=dict(visible=False, range=[-30, 500]), width=700, height=700, plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0))
    return fig

# --- 5. 數據邏輯 ---
if 'data_cache' not in st.session_state: st.session_state.data_cache = None
if 'p_name' not in st.session_state: st.session_state.p_name = ""

st.sidebar.header("球員查詢")
p_query = st.sidebar.text_input("輸入球員姓名", placeholder="例如：Javier Baez").strip()

if st.sidebar.button("查詢資料"):
    try:
        names = p_query.split()
        if len(names) >= 2:
            f_in, l_in = names[0], names[-1]
            with st.spinner('搜尋球員中...'):
                # 模糊搜尋：比對資料庫時自動忽略重音符號
                l = playerid_lookup(l_in, f_in)
                if l.empty:
                    all_l = playerid_lookup(l_in)
                    if not all_l.empty:
                        all_l['f_norm'] = all_l['name_first'].apply(normalize_text)
                        all_l['l_norm'] = all_l['name_last'].apply(normalize_text)
                        l = all_l[(all_l['f_norm'] == normalize_text(f_in)) & (all_l['l_norm'] == normalize_text(l_in))].head(1)
                
                if not l.empty:
                    res = l.iloc[0]
                    st.session_state.p_name = f"{res['name_first']} {res['name_last']}"
                    pid = res['key_mlbam']
                    raw = statcast_batter('2024-03-01', '2026-12-31', pid)
                    st.session_state.data_cache = raw[raw['events'].notna()].copy()
                else:
                    st.session_state.p_name = ""
                    st.session_state.data_cache = None
                    st.error("找不到該球員，請檢查拼字")
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

    # 暴力大寫顯示
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
