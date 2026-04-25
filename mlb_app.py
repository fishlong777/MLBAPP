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
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower()


# --- 2. 核心函數：動態球場牆界計算 ---
def get_wall_radius(theta):
    """
    根據角度計算球場全壘打牆的物理距離 (簡化版球場模型)
    中外野 (pi/2) 約 400ft, 左右邊線 (pi/4, 3pi/4) 約 325ft
    """
    # 使用餘弦函數模擬中外野突出的形狀
    # 當 theta = pi/2 (90度), cos(2*(theta-pi/2)) = 1 -> 半徑最大
    # 當 theta = pi/4 或 3pi/4, cos 為負 -> 半徑最小
    base_wall = 355  # 平均半徑
    depth_variation = 45  # 深度變化量
    return base_wall + depth_variation * np.cos(2 * (theta - np.pi / 2))


# --- 3. 核心函數：座標轉換 (包含牆界限制) ---
def transform_coords_refined(hc_x, hc_y, distance, events):
    if pd.isna(hc_x) or pd.isna(hc_y) or (hc_x == 0 and hc_y == 0):
        return None, None

    # 1. 計算角度 theta
    theta_offset = (hc_x - 125.42) * 0.0085
    theta = np.pi / 2 - theta_offset
    theta = np.clip(theta, np.pi / 4 + 0.01, 3 * np.pi / 4 - 0.01)

    # 2. 取得該方向的牆界半徑
    wall_at_angle = get_wall_radius(theta)

    # 3. 決定視覺半徑 r
    r = float(distance) if not pd.isna(distance) else 15.0
    r = max(r, 18.0)

    # 邏輯核心：如果是出局球 (Sac Fly/Field Out)，距離絕對不能超過該處的牆界
    is_hr = 'home run' in str(events).lower()
    if not is_hr and r >= (wall_at_angle - 5):
        r = wall_at_angle - 8  # 強制縮回到牆內 8 英尺處，模擬牆前接殺

    tx = r * np.cos(theta)
    ty = r * np.sin(theta)
    return tx, ty


# --- 4. 繪圖函數 ---
def plot_spray_chart(df):
    fig = go.Figure()
    t_range = np.linspace(np.pi / 4, 3 * np.pi / 4, 100)

    # 繪製動態全壘打牆 (符合現實: 中外野深、邊線淺)
    wall_radii = [get_wall_radius(t) for t in t_range]
    wall_x = [r * np.cos(t) for r, t in zip(wall_radii, t_range)]
    wall_y = [r * np.sin(t) for r, t in zip(wall_radii, t_range)]

    # 草皮與紅土
    fig.add_trace(
        go.Scatter(x=[0] + wall_x + [0], y=[0] + wall_y + [0], fill='toself', fillcolor='rgba(34, 139, 34, 0.2)',
                   line_width=0, showlegend=False))
    fig.add_trace(
        go.Scatter(x=[0] + (145 * np.cos(t_range)).tolist() + [0], y=[0] + (145 * np.sin(t_range)).tolist() + [0],
                   fill='toself', fillcolor='rgba(255, 165, 0, 0.3)', line_width=0, showlegend=False))

    # 紅色動態牆線
    fig.add_trace(
        go.Scatter(x=wall_x, y=wall_y, mode='lines', line=dict(color='red', dash='dash', width=3), name='全壘打牆'))

    # 壘包
    s = 90 / np.sqrt(2)
    fig.add_trace(
        go.Scatter(x=[0, s, 0, -s, 0], y=[0, s, s * 2, s, 0], mode='lines+markers', line=dict(color='black', width=3),
                   marker=dict(symbol='square', size=13, color='white', line=dict(width=1.5, color='black')),
                   showlegend=False))

    for i, row in df.iterrows():
        tx, ty = transform_coords_refined(row['hc_x'], row['hc_y'], row['hit_distance_sc'], row['events'])
        if tx is not None:
            fig.add_trace(go.Scatter(x=[tx], y=[ty], mode='markers',
                                     marker=dict(size=18, color=row['color'], line=dict(width=1.5, color='black')),
                                     hovertemplate=f"打席: {i + 1}<br>結果: {row['events']}<br>距離: {row['hit_distance_sc']} ft",
                                     showlegend=False))

    fig.update_layout(xaxis=dict(visible=False, range=[-400, 400], scaleanchor="y", scaleratio=1),
                      yaxis=dict(visible=False, range=[-30, 500]), width=700, height=700, plot_bgcolor='rgba(0,0,0,0)',
                      margin=dict(l=0, r=0, t=30, b=0))
    return fig


# --- 5. 數據邏輯 (與先前一致) ---
if 'data_cache' not in st.session_state: st.session_state.data_cache = None
if 'p_name' not in st.session_state: st.session_state.p_name = ""

st.sidebar.header("球員查詢")
p_query = st.sidebar.text_input("輸入球員姓名", placeholder="例如：Ronald Acuna").strip()

if st.sidebar.button("查詢資料"):
    try:
        names = p_query.split()
        if len(names) >= 2:
            f_in, l_in = names[0], names[-1]
            with st.spinner('讀取數據中...'):
                common_map = {"acuna": "Acuña", "alvarez": "Álvarez"}
                s_last = common_map.get(l_in.lower(), l_in)
                l = playerid_lookup(s_last, f_in)
                if l.empty:
                    all_l = playerid_lookup(l_in)
                    if not all_l.empty:
                        all_l['f_norm'] = all_l['name_first'].apply(normalize_text)
                        l = all_l[all_l['f_norm'] == normalize_text(f_in)].head(1)
                if not l.empty:
                    res = l.iloc[0]
                    st.session_state.p_name = f"{res['name_first']} {res['name_last']}"
                    pid = res['key_mlbam']
                    raw = statcast_batter('2024-03-01', '2026-12-31', pid)
                    st.session_state.data_cache = raw[raw['events'].notna()].copy()
                else:
                    st.error("找不到球員")
    except Exception as e:
        st.error(f"錯誤: {e}")

if st.session_state.data_cache is not None:
    df = st.session_state.data_cache
    df['game_date'] = pd.to_datetime(df['game_date']).dt.date
    sel_date = st.sidebar.selectbox("選擇日期", sorted(df['game_date'].unique(), reverse=True)[:10])
    curr = df[df['game_date'] == sel_date].copy().sort_values('at_bat_number').reset_index(drop=True)
    curr['events'] = curr['events'].str.replace('_', ' ').str.replace('intent walk', 'intentional walk', case=False)

    clist = ['#AEC7E8', '#FFBB78', '#98DF8A', '#FF9896', '#C5B0D5', '#C49C94', '#F7B6D2', '#DBDB8D', '#9EDAE5',
             '#D62728']
    curr['color'] = [clist[i % len(clist)] for i in range(len(curr))]

    st.title(f"{st.session_state.p_name} - {sel_date}")
    c1, c2 = st.columns([1.2, 1])
    with c1:
        st.plotly_chart(plot_spray_chart(curr), use_container_width=True)
    with c2:
        t_df = curr[['events', 'launch_speed', 'launch_angle', 'hit_distance_sc']].copy()
        t_df.columns = ['結果', '初速(mph)', '仰角(°)', '距離(ft)']
        for col in t_df.columns[1:]: t_df[col] = pd.to_numeric(t_df[col]).fillna(0.0).map('{:.1f}'.format)
        t_df.insert(0, '打席', range(1, len(t_df) + 1))
        st.table(t_df.style.apply(
            lambda r: [f'background-color: {curr.loc[r.name, "color"]}; color: black; font-weight: bold'] * len(r),
            axis=1))