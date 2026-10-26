import time
import json
import socket
import random
import pandas as pd

# ==================== CẤU HÌNH ĐỊA CHỈ PI 5 & SOCKET ====================
# 1. Điền địa chỉ IP mạng Wi-Fi của Raspberry Pi 5 tại đây (Ví dụ: 192.168.1.50)
RPI_IP = "192.168.1.50" 

# 2. Cấu hình Cổng và ID cho Monitor này
# Máy 2: Port 8081 | Máy 3: Port 8082 | Máy 4: Port 8083
PORT = 8081                     
MONITOR_ID = "MONITOR_BED_02"   

# ==================== MENU CHỌN 3 CHẾ ĐỘ ====================
def show_menu():
    print("\n==================================================")
    print(f"   PATIENT MONITOR WI-FI SIMULATOR - [{MONITOR_ID}]")
    print("==================================================")
    print(" Vui lòng chọn chế độ phát dữ liệu:")
    print("  [1] MODE 1: Data Thật (Chạy chuẩn theo bệnh nhân BIDMC gốc)")
    print("  [2] MODE 2: Data Giả Lập - BỆNH NHÂN BÌNH THƯỜNG (Data BIDMC + Vitals chuẩn)")
    print("  [3] MODE 3: Data Giả Lập - BỆNH NHÂN CẤP CỨU / SỰ CỐ (Data BIDMC + Vitals nguy cấp)")
    print("==================================================")
    
    while True:
        choice = input(" Nhập lựa chọn của bạn (1, 2 hoặc 3): ").strip()
        if choice in ['1', '2', '3']:
            return int(choice)
        print(" -> [Lỗi] Vui lòng chỉ chọn 1, 2 hoặc 3!")

MODE = show_menu()

# ==================== NẠP DỮ LIỆU TỆP GỐC BIDMC ====================
print("\n-> Đang tải tập dữ liệu BIDMC gốc...")
try:
    df_signals = pd.read_csv('bidmc_02_Signals.csv')
    df_signals.columns = df_signals.columns.str.strip()
    ecg_wave = df_signals['II'].dropna().values.tolist()
    pleth_wave = df_signals['PLETH'].dropna().values.tolist()
    resp_wave = df_signals['RESP'].dropna().values.tolist()

    df_numerics = pd.read_csv('bidmc_02_Numerics.csv')
    df_numerics.columns = df_numerics.columns.str.strip()
    hr_list = df_numerics['HR'].dropna().values.tolist()
    spo2_list = df_numerics['SpO2'].dropna().values.tolist()
    resp_list = df_numerics['RESP'].dropna().values.tolist()
    print("-> [OK] Đã nạp thành công dữ liệu từ file CSV!")
except Exception as e:
    print(f"-> [LỖI] Không tìm thấy file CSV dữ liệu BIDMC: {e}")
    exit()

# ==================== VÒNG LẶP PHÁT DỮ LIỆU QUA WI-FI ====================
FS = 125
signal_ptr = 0
numeric_ptr = 0

print("\n==================================================")
print(f"  BẮT ĐẦU PHÁT DỮ LIỆU WI-FI MODE {MODE} SANG PI 5 ({RPI_IP}:{PORT})")
print("==================================================\n")

try:
    while True:
        # Lấy mảng điểm sóng thật từ file BIDMC
        ecg_chunk = ecg_wave[signal_ptr : signal_ptr + FS]
        pleth_chunk = pleth_wave[signal_ptr : signal_ptr + FS]
        resp_chunk = resp_wave[signal_ptr : signal_ptr + FS]
        
        signal_ptr += FS
        if signal_ptr >= len(ecg_wave) - FS: 
            signal_ptr = 0  # Hết file lặp lại từ đầu

        # Cấu hình Vitals theo từng Mode
        if MODE == 1:
            patient_id = f"{MONITOR_ID}_BIDMC_REAL"
            current_hr = int(hr_list[numeric_ptr]) if numeric_ptr < len(hr_list) else 75
            current_spo2 = int(spo2_list[numeric_ptr]) if numeric_ptr < len(spo2_list) else 98
            current_resp = int(resp_list[numeric_ptr]) if numeric_ptr < len(resp_list) else 16
            nibp_str = "120/80"
            numeric_ptr = (numeric_ptr + 1) % len(hr_list)

        elif MODE == 2:
            patient_id = f"{MONITOR_ID}_SIM_NORMAL"
            current_hr = random.randint(65, 85)
            current_spo2 = random.randint(96, 99)
            current_resp = random.randint(12, 18)
            nibp_str = f"{random.randint(110, 122)}/{random.randint(70, 80)}"

        else:
            patient_id = f"{MONITOR_ID}_SIM_CRITICAL"
            current_hr = random.choice([135, 150, 42, 48])     # Nhịp tim bất thường
            current_spo2 = random.choice([82, 86, 89])          # Tụt SpO2 nghiêm trọng
            current_resp = random.choice([8, 32])               # Suy hô hấp
            nibp_str = random.choice(["165/105", "80/50"])

        # Đóng gói JSON chuẩn cấu hình của nhóm em
        monitor_packet = {
            "device_info": {
                "id": MONITOR_ID, 
                "patient_id": patient_id,
                "mode": f"MODE_{MODE}"
            },
            "timestamp": int(time.time()),
            "vitals": {
                "hr_bpm": current_hr,
                "spo2_percent": current_spo2,
                "resp_rate": current_resp,
                "nibp_mmHg": nibp_str,
                "temp_C": 36.8
            },
            "waveforms": {
                "ecg_lead_ii": ecg_chunk,
                "pleth_spo2": pleth_chunk,
                "resp_wave": resp_chunk
            }
        }

        # ⚡ PHÁT DỮ LIỆU SANG RASPBERRY PI 5 QUA WI-FI SOCKET
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(2)
            client_socket.connect((RPI_IP, PORT))
            
            payload = json.dumps(monitor_packet) + "\n"
            client_socket.sendall(payload.encode('utf-8'))
            client_socket.close()

            print(f"[{time.strftime('%H:%M:%S')}] [MODE {MODE}] [{patient_id}] -> HR: {current_hr} bpm | SpO2: {current_spo2}% | Resp: {current_resp}/phút | BP: {nibp_str}")

        except Exception as e:
            print(f"⚠️ [{MONITOR_ID}] Không thể kết nối tới Pi 5 ({RPI_IP}:{PORT}): {e}")

        time.sleep(1)

except KeyboardInterrupt:
    print("\n-> Đã dừng chương trình phát Wi-Fi.")