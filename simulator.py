import time
import json
import serial
import pandas as pd

# 1. Khởi tạo kết nối tới cổng COM1 ảo
COM_PORT = 'COM1'  # Đảm bảo trùng với tên cổng thứ nhất bạn vừa tạo
BAUD_RATE = 115200

try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    print(f"-> [OK] Đã kết nối thành công tới cổng ảo {COM_PORT}!")
except Exception as e:
    print(f"-> [LỖI] Không thể mở cổng {COM_PORT}: {e}")
    exit()

# 2. Đọc dữ liệu từ BIDMC Dataset
print("-> Đang đọc dữ liệu từ BIDMC Dataset...")
try:
    df_signals = pd.read_csv('bidmc_01_Signals.csv')
    df_signals.columns = df_signals.columns.str.strip()
    ecg_wave = df_signals['II'].dropna().values.tolist()
    pleth_wave = df_signals['PLETH'].dropna().values.tolist()

    df_numerics = pd.read_csv('bidmc_01_Numerics.csv')
    df_numerics.columns = df_numerics.columns.str.strip()
    hr_list = df_numerics['HR'].dropna().values.tolist()
    spo2_list = df_numerics['SpO2'].dropna().values.tolist()
    resp_rate_list = df_numerics['RESP'].dropna().values.tolist()
    print("-> [OK] Tải dữ liệu thành công.")
except Exception as e:
    print(f"-> [LỖI] Không đọc được file CSV: {e}")
    exit()

# 3. Vòng lặp phát dữ liệu ra Cổng Serial (COM1)
FS = 125
signal_ptr = 0
numeric_ptr = 0

print("\n=== BẮT ĐẦU PHÁT DỮ LIỆU SANG GATEWAY QUA CỔNG SERIAL ===")

try:
    while True:
        ecg_chunk = ecg_wave[signal_ptr : signal_ptr + FS]
        pleth_chunk = pleth_wave[signal_ptr : signal_ptr + FS]
        
        signal_ptr += FS
        if signal_ptr >= len(ecg_wave) - FS:
            signal_ptr = 0

        current_hr = int(hr_list[numeric_ptr]) if numeric_ptr < len(hr_list) else 75
        current_spo2 = int(spo2_list[numeric_ptr]) if numeric_ptr < len(spo2_list) else 98
        current_resp = int(resp_rate_list[numeric_ptr]) if numeric_ptr < len(resp_rate_list) else 16
        
        numeric_ptr += 1
        if numeric_ptr >= len(hr_list):
            numeric_ptr = 0

        monitor_packet = {
            "device_info": {"id": "MONITOR_BED_01", "patient_id": "PATIENT_BIDMC_01"},
            "timestamp": int(time.time()),
            "vitals": {
                "hr_bpm": current_hr,
                "spo2_percent": current_spo2,
                "resp_rate": current_resp,
                "nibp_mmHg": "120/80",
                "temp_C": 36.8
            },
            "waveforms": {
                "ecg_lead_ii": [round(val, 3) for val in ecg_chunk],
                "pleth_spo2": [round(val, 3) for val in pleth_chunk]
            }
        }

        # Đóng gói JSON và thêm ký tự xuống dòng '\n' để báo kết thúc gói tin
        payload = json.dumps(monitor_packet) + "\n"
        
        # Bắn dữ liệu ra cổng Serial (COM1)
        ser.write(payload.encode('utf-8'))
        
        print(f"[{time.strftime('%H:%M:%S')}] Đã phát gói dữ liệu sang {COM_PORT} -> HR: {current_hr} | SpO2: {current_spo2}%")

        time.sleep(1)

except KeyboardInterrupt:
    ser.close()
    print("\n-> Đã đóng cổng Serial và dừng Simulator.")