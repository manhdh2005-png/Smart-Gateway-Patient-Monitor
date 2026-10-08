import time
import math
import random
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# ==================== MENU CHỌN 3 CHẾ ĐỘ ====================
def show_menu():
    print("\n==================================================")
    print("   PATIENT MONITOR - WAVEFORM VISUALIZER (DEMO)")
    print("==================================================")
    print(" Vui lòng chọn chế độ hiển thị sóng:")
    print("  [1] MODE 1: Sóng Bệnh Nhân BIDMC Gốc")
    print("  [2] MODE 2: Sóng Bệnh Nhân Bình Thường (Normal)")
    print("  [3] MODE 3: Sóng Bệnh Nhân Cấp Cứu / Bất Thường (Critical)")
    print("==================================================")
    
    while True:
        choice = input(" Nhập lựa chọn (1, 2 hoặc 3): ").strip()
        if choice in ['1', '2', '3']:
            return int(choice)
        print(" -> [Lỗi] Vui lòng chỉ chọn 1, 2 hoặc 3!")

MODE = show_menu()

# ==================== NẠP DỮ LIỆU TỆP GỐC BIDMC ====================
try:
    df_signals = pd.read_csv('bidmc_01_Signals.csv')
    df_signals.columns = df_signals.columns.str.strip()
    ecg_wave = df_signals['II'].dropna().values.tolist()
    pleth_wave = df_signals['PLETH'].dropna().values.tolist()
    resp_wave = df_signals['RESP'].dropna().values.tolist()
    print("-> [OK] Đã tải dữ liệu tín hiệu BIDMC thành công!")
except Exception as e:
    print(f"-> [LỖI] Không đọc được file BIDMC: {e}")
    exit()

# ==================== CẤU HÌNH GIAO DIỆN MONITOR ====================
plt.style.use('dark_background')
fig, axs = plt.subplots(5, 1, figsize=(11, 8), sharex=True)
fig.canvas.manager.set_window_title('PATIENT MONITOR - 5 WAVEFORMS DISPLAY')

mode_titles = {
    1: "MODE 1: DATA THẬT (BIDMC GỐC)",
    2: "MODE 2: GIẢ LẬP - BỆNH NHÂN BÌNH THƯỜNG",
    3: "MODE 3: GIẢ LẬP - BỆNH NHÂN CẤP CỨU / SỰ CỐ"
}
fig.suptitle(f'PATIENT MONITOR WAVEFORMS [{mode_titles[MODE]}]', fontsize=13, color='cyan', fontweight='bold')

BUFFER_SIZE = 500
x_data = list(range(BUFFER_SIZE))
waves_buffer = {
    'ecg': [0.0]*BUFFER_SIZE,
    'pleth': [0.0]*BUFFER_SIZE,
    'resp': [0.0]*BUFFER_SIZE,
    'abp': [100.0]*BUFFER_SIZE,
    'co2': [0.0]*BUFFER_SIZE
}

lines = {
    'ecg': axs[0].plot(x_data, waves_buffer['ecg'], color='#00FF00', lw=1.5, label='1. ECG Lead II (mV)')[0],
    'pleth': axs[1].plot(x_data, waves_buffer['pleth'], color='#00FFFF', lw=1.5, label='2. SpO2 PLETH (%)')[0],
    'resp': axs[2].plot(x_data, waves_buffer['resp'], color='#FFFF00', lw=1.5, label='3. RESP Wave')[0],
    'abp': axs[3].plot(x_data, waves_buffer['abp'], color='#FF0000', lw=1.5, label='4. ABP Blood Pressure (mmHg)')[0],
    'co2': axs[4].plot(x_data, waves_buffer['co2'], color='#FF00FF', lw=1.5, label='5. Capnography EtCO2 (mmHg)')[0]
}

ylims = [(-1.5, 2.0), (-0.2, 1.2), (-0.5, 1.5), (50, 180), (-5, 50)]
for i, ax in enumerate(axs):
    ax.set_ylim(ylims[i])
    ax.legend(loc='upper right', framealpha=0.3)
    ax.grid(True, color='#222222', linestyle='--')

# ==================== VÒNG LẶP CẬP NHẬT ĐỒ THỊ ====================
FS = 125
signal_ptr = 0
global_step = 0

def update_plot(frame):
    global signal_ptr, global_step
    
    # 1. Lấy mảng điểm sóng thật từ file BIDMC
    ecg_c = ecg_wave[signal_ptr : signal_ptr + FS]
    pleth_c = pleth_wave[signal_ptr : signal_ptr + FS]
    resp_c = resp_wave[signal_ptr : signal_ptr + FS]
    
    signal_ptr += FS
    if signal_ptr >= len(ecg_wave) - FS: 
        signal_ptr = 0

    # 2. Xử lý biên độ Sóng Huyết Áp (ABP) & CO2 theo trạng thái từng Mode
    abp_c, co2_c = [], []
    for i in range(FS):
        t = (i + global_step) / 125.0
        
        if MODE == 1 or MODE == 2:
            # Mode 1 & 2: Huyết áp bình thường (120/80 mmHg), CO2 chuẩn (38 mmHg)
            sys_bp, dia_bp = 120, 80
            etco2_val = 38.0
        else:
            # Mode 3: Huyết áp tăng cao cấp cứu (160/100 mmHg), CO2 giảm nhẹ (30 mmHg)
            sys_bp, dia_bp = 165, 105
            etco2_val = 30.0

        # Mô phỏng sóng ABP biến đổi dựa trên biến thiên mạch thật
        abp_val = dia_bp + (sys_bp - dia_bp) * (pleth_c[i] - 0.38) / 0.25
        abp_c.append(round(max(min(abp_val, 175), 40), 1))
        
        # Sóng CO2 đồng bộ nhịp thở
        val_co2 = etco2_val if math.sin(2 * math.pi * 0.2 * t) > 0 else 0.0
        co2_c.append(round(val_co2, 1))

    global_step += FS

    # Đẩy dữ liệu vào buffer để cuộn màn hình
    for key, chunk in zip(['ecg', 'pleth', 'resp', 'abp', 'co2'], [ecg_c, pleth_c, resp_c, abp_c, co2_c]):
        waves_buffer[key] = waves_buffer[key][FS:] + chunk
        lines[key].set_ydata(waves_buffer[key])

    print(f"[{time.strftime('%H:%M:%S')}] Updating waveforms [MODE {MODE}]...")
    return list(lines.values())

ani = FuncAnimation(fig, update_plot, interval=1000, cache_frame_data=False)

plt.tight_layout()
plt.show()