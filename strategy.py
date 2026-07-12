import pandas as pd
import numpy as np
import os
import time
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns
from datetime import datetime, timedelta
import warnings
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

warnings.filterwarnings('ignore')

# ==========================================
# --- 全局配置区 ---
# ==========================================

# 🌡️ 温度计阈值配置
T_LOW_MIN = 20      # 低温区下限
T_LOW_MAX = 50      # 低温区上限
T_HIGH_IN = 76      # 进主升浪高温区
T_HIGH_OUT = 66     # 跌出主升浪高温区

# 均线参数
MA_SHORT = 5
MA_LONG = 30

# 基础信息配置
DATA_DIR = './stock_data'
TICKERS = ['TSLA', 'AZO', 'ORLY']
START_DATE = '2010-01-01'

# 邮件配置
EMAIL_CONFIG = {
    'smtp_server': 'smtp.qq.com',
    'smtp_port': 465,
    'sender_email': os.environ.get('SENDER_EMAIL', '1300139854@qq.com'),
    'sender_password': os.environ.get('SENDER_PASSWORD', 'yurtncvsncqhfhbc'),
    'receiver_email': os.environ.get('RECEIVER_EMAIL', '982421018@qq.com'),
}

# 检查邮件配置是否完整
EMAIL_ENABLED = all([
    EMAIL_CONFIG['sender_email'],
    EMAIL_CONFIG['sender_password'],
    EMAIL_CONFIG['receiver_email']
])

if EMAIL_ENABLED:
    print("📧 邮件功能已启用")
else:
    print("⚠️ 邮件功能未启用")

# 代理配置（如需代理请取消注释）
# proxy = "http://127.0.0.1:6789"
# if proxy:
#     os.environ['HTTP_PROXY'] = proxy
#     os.environ['HTTPS_PROXY'] = proxy

# --- 1. 环境设置 ---
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

os.makedirs(DATA_DIR, exist_ok=True)


# ==========================================
# --- 邮件发送模块 ---
# ==========================================

def send_email(subject, body, is_html=True):
    """发送邮件"""
    if not EMAIL_ENABLED:
        print("⏭️ 邮件未发送（邮件功能未启用）")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = EMAIL_CONFIG['receiver_email']
        msg['Subject'] = Header(subject, 'utf-8')

        if is_html:
            msg.attach(MIMEText(body, 'html', 'utf-8'))
        else:
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

        with smtplib.SMTP_SSL(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
            server.sendmail(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['receiver_email'], msg.as_string())

        print(f"✅ 邮件发送成功！收件人: {EMAIL_CONFIG['receiver_email']}")
        return True

    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False


def build_email_body(ma_df, thermo_df, data_dict):
    """构建HTML邮件正文"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ---- 均线策略最近10天 ----
    ma_rows = ""
    if ma_df is not None and not ma_df.empty:
        state_map = {'TSLA': '⚡️ TSLA', 'HEDGE': '🚗 避险'}
        last_10 = ma_df.tail(10)
        for date, row in last_10.iterrows():
            d_str = date.strftime('%Y-%m-%d')
            s_str = state_map.get(row['state'], row['state'])
            nv_str = f"${row['net_value']:,.0f}"
            ma_str = f"{row['ma5']:.1f}/{row['ma30']:.1f}"
            ma_rows += f"<tr><td>{d_str}</td><td>{s_str}</td><td>{nv_str}</td><td>{ma_str}</td></tr>"

    # ---- 温度计策略最近10天 ----
    thermo_rows = ""
    if thermo_df is not None and not thermo_df.empty:
        state_map = {
            'HEDGE': '🚗 避险',
            'TSLA_LOW': '⚡️ TSLA(低温)',
            'TSLA_HIGH': '🔥 TSLA(主升)'
        }
        last_10 = thermo_df.tail(10)
        for date, row in last_10.iterrows():
            d_str = date.strftime('%Y-%m-%d')
            s_str = state_map.get(row['state'], row['state'])
            nv_str = f"${row['net_value']:,.0f}"
            temp_str = f"{row['temp']:.1f}°C"
            thermo_rows += f"<tr><td>{d_str}</td><td>{s_str}</td><td>{nv_str}</td><td>{temp_str}</td></tr>"

    # ---- 最新价格 ----
    price_rows = ""
    for ticker, df in data_dict.items():
        latest = df.index[-1].date()
        last_close = df['Close'].iloc[-1]
        price_rows += f"<tr><td>{ticker}</td><td>{latest}</td><td>${last_close:.2f}</td></tr>"

    # ---- 操作建议 ----
    ma_action = ""
    if ma_df is not None and not ma_df.empty:
        last_row = ma_df.iloc[-1]
        prev_row = ma_df.iloc[-2]
        m5_now, m30_now = last_row['ma5'], last_row['ma30']
        m5_pre, m30_pre = prev_row['ma5'], prev_row['ma30']
        current_state = last_row['state']
        if m5_now > m30_now and m5_pre <= m30_pre and current_state != 'TSLA':
            ma_action = "🚨 金叉确认！明天开盘全仓买入 TSLA"
        elif m5_now < m30_now and m5_pre >= m30_pre and current_state == 'TSLA':
            ma_action = "🚨 死叉确认！明天开盘清仓 TSLA，买入 AZO+ORLY"
        else:
            ma_action = "🛡️ 维持现状，无需操作"

    thermo_action = ""
    if thermo_df is not None and not thermo_df.empty:
        last_row = thermo_df.iloc[-1]
        current_state = last_row['state']
        T = last_row['temp']
        target_state = current_state

        if current_state == 'HEDGE':
            if T_LOW_MIN < T <= T_LOW_MAX:
                target_state = 'TSLA_LOW'
            elif T > T_HIGH_IN:
                target_state = 'TSLA_HIGH'
        elif current_state == 'TSLA_LOW':
            if T > T_LOW_MAX or T < T_LOW_MIN:
                if T > T_HIGH_IN:
                    target_state = 'TSLA_HIGH'
                else:
                    target_state = 'HEDGE'
        elif current_state == 'TSLA_HIGH':
            if T < T_HIGH_OUT:
                if T_LOW_MIN < T <= T_LOW_MAX:
                    target_state = 'TSLA_LOW'
                else:
                    target_state = 'HEDGE'

        if current_state == 'HEDGE' and target_state != 'HEDGE':
            thermo_action = f"🚨 温度 {T:.1f}°C，进入攻击区间！买入 TSLA"
        elif current_state != 'HEDGE' and target_state == 'HEDGE':
            thermo_action = f"🚨 温度 {T:.1f}°C，跌破下限！清仓 TSLA，买入 AZO+ORLY"
        elif current_state == 'TSLA_LOW' and target_state == 'TSLA_HIGH':
            thermo_action = f"🔥 温度 {T:.1f}°C，升级为主升浪！继续持有 TSLA"
        elif current_state == 'TSLA_HIGH' and target_state == 'TSLA_LOW':
            thermo_action = f"📉 温度 {T:.1f}°C，降级！继续持有 TSLA"
        else:
            thermo_action = "🛡️ 维持现状，无需操作"

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; background: #f5f5f5; padding: 20px; }}
            .container {{ max-width: 750px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .header {{ background: linear-gradient(135deg, #1a1a2e, #16213e); color: white; padding: 20px; border-radius: 10px 10px 0 0; }}
            .content {{ padding: 20px; }}
            .section {{ margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
            th {{ background: #f8f9fa; padding: 8px; text-align: left; border-bottom: 2px solid #dee2e6; }}
            td {{ padding: 6px 8px; border-bottom: 1px solid #eee; }}
            .highlight-green {{ background: #d4edda; padding: 10px; border-radius: 6px; border-left: 4px solid #28a745; margin: 10px 0; }}
            .highlight-yellow {{ background: #fff3cd; padding: 10px; border-radius: 6px; border-left: 4px solid #ffc107; margin: 10px 0; }}
            .footer {{ color: #6c757d; font-size: 12px; text-align: center; padding: 15px; border-top: 1px solid #eee; }}
            .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
            .badge-green {{ background: #28a745; color: white; }}
            .badge-red {{ background: #dc3545; color: white; }}
            .badge-yellow {{ background: #ffc107; color: #333; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin:0;">📊 股票双策略日报</h2>
                <p style="margin:5px 0 0 0; opacity:0.8;">{now}</p>
            </div>
            <div class="content">

                <div class="section">
                    <h3>📈 均线策略 (MA5/MA30) - 最近10天</h3>
                    <table>
                        <tr><th>日期</th><th>持仓</th><th>净值</th><th>MA5/MA30</th></tr>
                        {ma_rows if ma_rows else '<tr><td colspan="4" style="text-align:center;color:#999;">暂无数据</td></tr>'}
                    </table>
                    <div class="highlight-green">
                        <strong>🔮 操作建议：</strong> {ma_action}
                    </div>
                </div>

                <div class="section">
                    <h3>🌡️ 温度计策略 - 最近10天</h3>
                    <table>
                        <tr><th>日期</th><th>持仓</th><th>净值</th><th>温度计</th></tr>
                        {thermo_rows if thermo_rows else '<tr><td colspan="4" style="text-align:center;color:#999;">暂无数据</td></tr>'}
                    </table>
                    <div class="highlight-yellow">
                        <strong>🔮 操作建议：</strong> {thermo_action}
                    </div>
                </div>

                <div class="section">
                    <h3>📊 各股票最新数据</h3>
                    <table>
                        <tr><th>股票</th><th>最新日期</th><th>收盘价</th></tr>
                        {price_rows}
                    </table>
                </div>

                <div class="section">
                    <h3>📋 配置参数</h3>
                    <table>
                        <tr><td><strong>温度计阈值</strong></td><td>低温: {T_LOW_MIN}-{T_LOW_MAX}°C | 高温入: {T_HIGH_IN}°C | 高温出: {T_HIGH_OUT}°C</td></tr>
                        <tr><td><strong>均线参数</strong></td><td>MA{MA_SHORT} / MA{MA_LONG}</td></tr>
                        <tr><td><strong>股票池</strong></td><td>{', '.join(TICKERS)}</td></tr>
                    </table>
                </div>

            </div>
            <div class="footer">
                <p>此邮件由 strategy_timer 自动生成 | 仅供参考，不构成投资建议</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


# ==========================================
# --- 数据下载模块 ---
# ==========================================

def get_data_by_ticker(ticker, start_str, max_retries=3):
    """带指数退避重试机制的数据下载函数"""
    for attempt in range(max_retries):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_str, auto_adjust=True)

            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.loc[:, ~df.columns.duplicated()]
                df.index = pd.to_datetime(df.index).tz_localize(None)
                return df
            else:
                print(f"⚠️ {ticker} 返回数据为空 (尝试 {attempt + 1}/{max_retries})...")
        except Exception as e:
            print(f"⚠️ 下载 {ticker} 失败: {e} (尝试 {attempt + 1}/{max_retries})...")

        if attempt < max_retries - 1:
            time.sleep(2 ** (attempt + 1))

    print(f"❌ {ticker} 数据拉取彻底失败。")
    return pd.DataFrame()


def fetch_and_update_all():
    """批量更新所有股票数据"""
    print(f"🕒 开始检查并更新数据 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n" + "-" * 40)

    for ticker in TICKERS:
        file_path = os.path.join(DATA_DIR, f"{ticker}.csv")
        df = pd.DataFrame()

        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, index_col=0)
                df.index = pd.to_datetime(df.index, errors='coerce')
                df = df[df.index.notnull()]
                if not df.empty:
                    df.index = df.index.tz_localize(None)
            except Exception as e:
                print(f"读取 {ticker} 本地文件异常，将重新下载: {e}")
                df = pd.DataFrame()

        if df.empty:
            print(f"📥 正在全量下载 {ticker} (从 {START_DATE} 起)...")
            df = get_data_by_ticker(ticker, START_DATE)
            if not df.empty:
                df.to_csv(file_path)
                print(f"✅ {ticker} 全量下载完成，最新数据至: {df.index[-1].date()}")
        else:
            last_date = df.index[-1]
            start_fetch = (last_date - pd.Timedelta(days=5)).strftime('%Y-%m-%d')
            print(f"🔄 正在增量更新 {ticker} (回退至 {start_fetch})...")

            new_data = get_data_by_ticker(ticker, start_fetch)
            if not new_data.empty:
                df = pd.concat([df, new_data])
                df = df[~df.index.duplicated(keep='last')]
                df = df.sort_index()
                df.to_csv(file_path)
                print(f"✅ {ticker} 更新完毕，最新数据至: {df.index[-1].date()}")
            else:
                print(f"⏭️ {ticker} 暂无新数据可更新。")
        print("-" * 40)

    print("🎉 所有数据更新任务结束！")


# ==========================================
# --- 温度计指标算法 ---
# ==========================================

def rma(series, n):
    return series.ewm(alpha=1 / n, adjust=False).mean()


def transform_value(s, low_thresh, high_thresh):
    res = s.copy()
    mask_low = (s < low_thresh) & s.notna()
    res.loc[mask_low] = (s.loc[mask_low] ** 2) / 100
    mask_high = (s > high_thresh) & s.notna()
    res.loc[mask_high] = np.sqrt(s.loc[mask_high].clip(lower=0)) * 10
    return res


def calc_thermometer(df, length=14):
    c = df['Close']
    h = df['High']
    l = df['Low']
    o = df['Open']

    delta = c.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    rs = rma(up, length) / (rma(down, length) + 1e-10)
    value_rsi = transform_value(100 - (100 / (1 + rs)), 30, 70)

    hh = h.rolling(length).max()
    ll = l.rolling(length).min()
    value_wr = transform_value(((c - hh) / (hh - ll + 1e-10)) * 100 + 100, 20, 80)

    sum_up = up.rolling(length).sum()
    sum_down = down.rolling(length).sum()
    value_cmo = transform_value(((((sum_up - sum_down) / (sum_up + sum_down + 1e-10)) * 100) + 100) / 2, 25, 75)

    value_kd = transform_value(((c - ll) / (hh - ll + 1e-10)) * 100, 20, 80)

    short_len = round(length / 2)
    m = c.diff()
    smooth1 = m.ewm(span=length, adjust=False).mean()
    smooth2 = smooth1.ewm(span=short_len, adjust=False).mean()
    abs_m = m.abs()
    abs_smooth1 = abs_m.ewm(span=length, adjust=False).mean()
    abs_smooth2 = abs_smooth1.ewm(span=short_len, adjust=False).mean()
    value_tsi = transform_value(((100 * (smooth2 / (abs_smooth2 + 1e-10))) + 100) / 2, 30, 70)

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up_move = h - h.shift()
    down_move = l.shift() - l
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=df.index)

    tr_rma = rma(tr, length)
    plus_di = 100 * rma(plus_dm, length) / (tr_rma + 1e-10)
    minus_di = 100 * rma(minus_dm, length) / (tr_rma + 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    value_adx = rma(dx, length + 4)

    adx_diff = value_adx.diff()
    adx_rs = rma(adx_diff.clip(lower=0), 14) / (rma(-1 * adx_diff.clip(upper=0), 14) + 1e-10)
    rsi_adx = 100 - (100 / (1 + adx_rs))
    adxrsi = (rsi_adx * np.sign(c - o) + 100) / 2

    index_raw = (value_rsi * 0.1 + value_wr * 0.2 + value_cmo * 0.1 +
                 value_kd * 0.3 + value_tsi * 0.2 + adxrsi * 0.1)

    return index_raw.ewm(span=3, adjust=False).mean()


# ==========================================
# --- 数据加载模块 ---
# ==========================================

def load_local_data():
    all_data = {}
    print(f"📂 开始读取本地数据 ({DATA_DIR}/)...")

    for ticker in TICKERS:
        file_path = os.path.join(DATA_DIR, f"{ticker}.csv")

        if not os.path.exists(file_path):
            print(f"❌ 找不到本地文件 {file_path}")
            continue

        try:
            df = pd.read_csv(file_path, index_col=0)
            df.index = pd.to_datetime(df.index, errors='coerce')
            df = df[df.index.notnull()]

            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            all_data[ticker] = df.sort_index()
            print(f"✅ 成功加载 {ticker}: 共 {len(df)} 个交易日，最新至 {df.index[-1].date()}")
        except Exception as e:
            print(f"❌ 读取 {ticker} 数据时发生错误: {e}")

    return all_data


# ==========================================
# --- 均线策略回测 ---
# ==========================================

def run_ma_backtest(data_dict):
    """MA5/MA30 金叉死叉策略"""
    if not all(t in data_dict for t in TICKERS):
        return None

    tsla = data_dict['TSLA'].copy()
    azo = data_dict['AZO']
    orly = data_dict['ORLY']

    tsla['ma5'] = tsla['Close'].rolling(MA_SHORT).mean()
    tsla['ma30'] = tsla['Close'].rolling(MA_LONG).mean()
    tsla = tsla.dropna(subset=['ma30'])

    common_dates = tsla.index.intersection(azo.index).intersection(orly.index)
    if len(common_dates) < 20:
        return None

    cash = 100000.0
    shares = {'TSLA': 0, 'AZO': 0, 'ORLY': 0}
    state = 'HEDGE'
    history = []

    d0 = common_dates[0]
    shares['AZO'] = (cash / 2) / azo.loc[d0, 'Open']
    shares['ORLY'] = (cash / 2) / orly.loc[d0, 'Open']
    cash = 0

    for i in range(len(common_dates)):
        t = common_dates[i]
        current_val = (shares['TSLA'] * tsla.loc[t, 'Close'] +
                       shares['AZO'] * azo.loc[t, 'Close'] +
                       shares['ORLY'] * orly.loc[t, 'Close'] + cash)

        history.append({
            'date': t,
            'net_value': current_val,
            'state': state,
            'ma5': tsla.loc[t, 'ma5'],
            'ma30': tsla.loc[t, 'ma30']
        })

        if i + 1 >= len(common_dates):
            break

        tomorrow = common_dates[i + 1]
        yesterday = common_dates[i - 1] if i > 0 else t

        m5_now, m30_now = tsla.loc[t, 'ma5'], tsla.loc[t, 'ma30']
        m5_pre, m30_pre = tsla.loc[yesterday, 'ma5'], tsla.loc[yesterday, 'ma30']

        if m5_now > m30_now and m5_pre <= m30_pre and state != 'TSLA':
            total_cash = shares['AZO'] * azo.loc[tomorrow, 'Open'] + shares['ORLY'] * orly.loc[tomorrow, 'Open']
            shares['AZO'] = shares['ORLY'] = 0
            shares['TSLA'] = total_cash / tsla.loc[tomorrow, 'Open']
            state = 'TSLA'

        elif m5_now < m30_now and m5_pre >= m30_pre and state == 'TSLA':
            total_cash = shares['TSLA'] * tsla.loc[tomorrow, 'Open']
            shares['TSLA'] = 0
            shares['AZO'] = (total_cash / 2) / azo.loc[tomorrow, 'Open']
            shares['ORLY'] = (total_cash / 2) / orly.loc[tomorrow, 'Open']
            state = 'HEDGE'

    return pd.DataFrame(history).set_index('date')


# ==========================================
# --- 温度计策略回测 ---
# ==========================================

def run_thermometer_backtest(data_dict):
    """温度计状态机策略"""
    if not all(t in data_dict for t in TICKERS):
        return None, None

    tsla = data_dict['TSLA'].copy()
    azo = data_dict['AZO']
    orly = data_dict['ORLY']

    tsla['Temp'] = calc_thermometer(tsla)
    tsla = tsla.dropna(subset=['Temp'])

    common_dates = tsla.index.intersection(azo.index).intersection(orly.index)
    if len(common_dates) < 20:
        return None, None

    cash = 100000.0
    shares = {'TSLA': 0, 'AZO': 0, 'ORLY': 0}
    current_state = 'HEDGE'
    history = []
    trades_history = []
    current_asset_type = 'HEDGE'
    trade_entry_date = common_dates[0]
    trade_entry_value = cash

    d0 = common_dates[0]
    shares['AZO'] = (cash / 2) / azo.loc[d0, 'Open']
    shares['ORLY'] = (cash / 2) / orly.loc[d0, 'Open']
    cash = 0

    for i in range(len(common_dates)):
        t = common_dates[i]
        T = tsla.loc[t, 'Temp']

        current_val = (shares['TSLA'] * tsla.loc[t, 'Close'] +
                       shares['AZO'] * azo.loc[t, 'Close'] +
                       shares['ORLY'] * orly.loc[t, 'Close'] + cash)

        history.append({
            'date': t,
            'net_value': current_val,
            'state': current_state,
            'temp': T
        })

        if i + 1 >= len(common_dates):
            trades_history.append({
                'asset': current_asset_type,
                'entry_date': trade_entry_date,
                'exit_date': t,
                'return': (current_val / trade_entry_value) - 1,
                'status': 'OPEN'
            })
            break

        tomorrow = common_dates[i + 1]
        target_state = current_state

        # 温度计状态机
        if current_state == 'HEDGE':
            if T_LOW_MIN < T <= T_LOW_MAX:
                target_state = 'TSLA_LOW'
            elif T > T_HIGH_IN:
                target_state = 'TSLA_HIGH'

        elif current_state == 'TSLA_LOW':
            if T > T_LOW_MAX or T < T_LOW_MIN:
                if T > T_HIGH_IN:
                    target_state = 'TSLA_HIGH'
                else:
                    target_state = 'HEDGE'

        elif current_state == 'TSLA_HIGH':
            if T < T_HIGH_OUT:
                if T_LOW_MIN < T <= T_LOW_MAX:
                    target_state = 'TSLA_LOW'
                else:
                    target_state = 'HEDGE'

        if target_state != current_state:
            target_asset_type = 'HEDGE' if target_state == 'HEDGE' else 'TSLA'
            if target_asset_type != current_asset_type:
                trades_history.append({
                    'asset': current_asset_type,
                    'entry_date': trade_entry_date,
                    'exit_date': t,
                    'return': (current_val / trade_entry_value) - 1,
                    'status': 'CLOSED'
                })
                trade_entry_date = tomorrow
                trade_entry_value = current_val
                current_asset_type = target_asset_type

            if current_state == 'HEDGE':
                total_cash = shares['AZO'] * azo.loc[tomorrow, 'Open'] + shares['ORLY'] * orly.loc[tomorrow, 'Open']
                shares['AZO'] = shares['ORLY'] = 0
            else:
                total_cash = shares['TSLA'] * tsla.loc[tomorrow, 'Open']
                shares['TSLA'] = 0

            if target_state == 'HEDGE':
                shares['AZO'] = (total_cash / 2) / azo.loc[tomorrow, 'Open']
                shares['ORLY'] = (total_cash / 2) / orly.loc[tomorrow, 'Open']
            else:
                shares['TSLA'] = total_cash / tsla.loc[tomorrow, 'Open']

            current_state = target_state

    return pd.DataFrame(history).set_index('date'), pd.DataFrame(trades_history)


# ==========================================
# --- 显示最近10天数据和操作建议 ---
# ==========================================

def show_recent_and_next_action_ma(df):
    """均线策略：显示最近10天 + 下一天建议"""
    if df is None or df.empty:
        return

    print("\n" + "=" * 65)
    print("📊 均线策略 (MA5/MA30) - 最近10个交易日")
    print("=" * 65)

    last_10 = df.tail(10)
    print(f"{'日期':<12} | {'持仓状态':<18} | {'总净值':<12} | MA5 / MA30")
    print("-" * 65)

    state_map = {'TSLA': '⚡️ TSLA', 'HEDGE': '🚗 避险'}

    for date, row in last_10.iterrows():
        d_str = date.strftime('%Y-%m-%d')
        s_str = state_map.get(row['state'], row['state'])
        nv_str = f"${row['net_value']:,.0f}"
        ma_str = f"{row['ma5']:.1f} / {row['ma30']:.1f}"
        print(f"{d_str:<12} | {s_str:<18} | {nv_str:<12} | {ma_str}")

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    m5_now, m30_now = last_row['ma5'], last_row['ma30']
    m5_pre, m30_pre = prev_row['ma5'], prev_row['ma30']
    current_state = last_row['state']

    print("\n" + "=" * 65)
    print("🔮 均线策略 - 下一个交易日操作建议")
    print("=" * 65)

    if m5_now > m30_now and m5_pre <= m30_pre and current_state != 'TSLA':
        print("🚨 【调仓指令】：金叉确认！明天开盘全仓买入 TSLA！")
    elif m5_now < m30_now and m5_pre >= m30_pre and current_state == 'TSLA':
        print("🚨 【调仓指令】：死叉确认！明天开盘清仓 TSLA，买入 AZO+ORLY 避险！")
    else:
        asset = "🚗 AZO+ORLY 避险" if current_state == 'HEDGE' else "⚡️ TSLA"
        print(f"🛡️ 【维持现状】：继续持有 {asset}，无需操作。")
    print("=" * 65 + "\n")


def show_recent_and_next_action_thermometer(df):
    """温度计策略：显示最近10天 + 下一天建议"""
    if df is None or df.empty:
        return

    print("\n" + "=" * 65)
    print("🌡️ 温度计策略 - 最近10个交易日")
    print("=" * 65)

    last_10 = df.tail(10)
    print(f"{'日期':<12} | {'持仓状态':<22} | {'总净值':<12} | 温度计")
    print("-" * 65)

    state_map = {
        'HEDGE': '🚗 AZO+ORLY (避险)',
        'TSLA_LOW': '⚡️ TSLA (低温)',
        'TSLA_HIGH': '🔥 TSLA (主升浪)'
    }

    for date, row in last_10.iterrows():
        d_str = date.strftime('%Y-%m-%d')
        s_str = state_map.get(row['state'], row['state'])
        nv_str = f"${row['net_value']:,.0f}"
        temp_str = f"{row['temp']:.2f}°C"
        print(f"{d_str:<12} | {s_str:<20} | {nv_str:<12} | {temp_str}")

    last_row = df.iloc[-1]
    current_state = last_row['state']
    T = last_row['temp']
    target_state = current_state

    if current_state == 'HEDGE':
        if T_LOW_MIN < T <= T_LOW_MAX:
            target_state = 'TSLA_LOW'
        elif T > T_HIGH_IN:
            target_state = 'TSLA_HIGH'
    elif current_state == 'TSLA_LOW':
        if T > T_LOW_MAX or T < T_LOW_MIN:
            target_state = 'TSLA_HIGH' if T > T_HIGH_IN else 'HEDGE'
    elif current_state == 'TSLA_HIGH':
        if T < T_HIGH_OUT:
            target_state = 'TSLA_LOW' if T_LOW_MIN < T <= T_LOW_MAX else 'HEDGE'

    print("\n" + "=" * 65)
    print("🌡️ 温度计策略 - 下一个交易日操作建议")
    print("=" * 65)

    if current_state == 'HEDGE' and target_state != 'HEDGE':
        print(f"🚨 【调仓指令】：温度 {T:.2f}°C，进入攻击区间！👉 明早全仓买入 TSLA！")
    elif current_state != 'HEDGE' and target_state == 'HEDGE':
        print(f"🚨 【调仓指令】：温度 {T:.2f}°C，跌破下限！👉 明早清仓 TSLA，买入 AZO+ORLY 避险！")
    elif current_state == 'TSLA_LOW' and target_state == 'TSLA_HIGH':
        print(f"🔥 【状态升级】：温度 {T:.2f}°C，进入主升浪！继续持有 TSLA。")
    elif current_state == 'TSLA_HIGH' and target_state == 'TSLA_LOW':
        print(f"📉 【状态降级】：温度 {T:.2f}°C，退回低温区！继续持有 TSLA。")
    else:
        asset = "🚗 AZO+ORLY 避险" if current_state == 'HEDGE' else "⚡️ TSLA"
        print(f"🛡️ 【维持现状】：温度 {T:.2f}°C。继续持有 {asset}，无需操作。")
    print("=" * 65 + "\n")


# ==========================================
# --- 主函数 ---
# ==========================================

def main():
    """主执行函数：先更新数据，再运行两种策略"""
    print("=" * 70)
    print("🚀 股票策略定时任务启动")
    print(f"⏰ 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 更新数据
    fetch_and_update_all()

    # 2. 加载数据
    data_dict = load_local_data()

    if not all(t in data_dict for t in TICKERS):
        print("❌ 数据加载失败，退出。")
        return

    # 3. 运行均线策略
    print("\n" + "=" * 70)
    print("📈 均线策略回测结果")
    print("=" * 70)
    ma_df = run_ma_backtest(data_dict)
    show_recent_and_next_action_ma(ma_df)

    # 4. 运行温度计策略
    print("\n" + "=" * 70)
    print("🌡️ 温度计策略回测结果")
    print("=" * 70)
    thermo_df, trades_df = run_thermometer_backtest(data_dict)
    show_recent_and_next_action_thermometer(thermo_df)

    # 5. 打印最新数据日期
    print("\n" + "=" * 70)
    print("📊 各股票最新数据日期")
    print("=" * 70)
    for ticker, df in data_dict.items():
        latest = df.index[-1].date()
        last_close = df['Close'].iloc[-1]
        print(f"{ticker}: {latest} 收盘价: ${last_close:.2f}")

    # ==================== 6. 发送邮件 ====================
    if EMAIL_ENABLED:
        print("\n" + "=" * 70)
        print("📧 准备发送邮件...")
        print("=" * 70)

        subject = f"📊 股票双策略日报 {datetime.now().strftime('%Y-%m-%d')}"

        # 避免 matplotlib 在无头环境下报错
        try:
            import matplotlib
            matplotlib.use('Agg')
        except:
            pass

        email_body = build_email_body(ma_df, thermo_df, data_dict)
        send_email(subject, email_body, is_html=True)

    print("\n" + "=" * 70)
    print("✅ 定时任务执行完成")
    print("=" * 70)


if __name__ == "__main__":
    main()