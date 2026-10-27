import time
import json
import serial
import random
import pandas as pd

# ==================== CẤU HÌNH CỔNG COM ====================
COM_PORT = 'COM6'
BAUD_RATE = 115200

# ==================== MENU CHỌN 3 CHẾ ĐỘ ====================
def show_menu():
    print("\n==================================================")
    print("   PATIENT MONITOR SIMULATOR - BỆNH VIỆN BÁCH KHOA")
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

# ==================== KHỞI TẠO CỔNG SERIAL ====================
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    print(f"\n-> [OK] Đã mở cổng {COM_PORT} thành công!")
    print(f"-> [OK] Khởi chạy hệ thống ở [MODE {MODE}]")
except Exception as e:
    print(f"\n-> [LỖI] Không thể mở cổng {COM_PORT}: {e}")
    exit()

# ==================== NẠP DỮ LIỆU TỆP GỐC BIDMC ====================
print("-> Đang tải tập dữ liệu BIDMC gốc...")
try:
    df_signals = pd.read_csv('bidmc_01_Signals.csv')
    df_signals.columns = df_signals.columns.str.strip()
    ecg_wave = df_signals['II'].dropna().values.tolist()
    pleth_wave = df_signals['PLETH'].dropna().values.tolist()
    resp_wave = df_signals['RESP'].dropna().values.tolist()

    df_numerics = pd.read_csv('bidmc_01_Numerics.csv')
    df_numerics.columns = df_numerics.columns.str.strip()
    hr_list = df_numerics['HR'].dropna().values.tolist()
    spo2_list = df_numerics['SpO2'].dropna().values.tolist()
    resp_list = df_numerics['RESP'].dropna().values.tolist()
    print("-> [OK] Đã nạp thành công dữ liệu từ file CSV!")
except Exception as e:
    print(f"-> [LỖI] Không tìm thấy file CSV dữ liệu BIDMC: {e}")
    exit()

# ==================== VÒNG LẶP PHÁT DỮ LIỆU ====================
FS = 125
signal_ptr = 0
numeric_ptr = 0

print("\n==================================================")
print(f"  BẮT ĐẦU PHÁT DỮ LIỆU MODE {MODE} SANG GATEWAY (Ctrl+C để dừng)")
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
            # MODE 1: Dữ liệu chuẩn gốc từ BIDMC
            patient_id = "RS232_BED_01_REAL"
            current_hr = int(hr_list[numeric_ptr]) if numeric_ptr < len(hr_list) else 75
            current_spo2 = int(spo2_list[numeric_ptr]) if numeric_ptr < len(spo2_list) else 98
            current_resp = int(resp_list[numeric_ptr]) if numeric_ptr < len(resp_list) else 16
            nibp_str = "120/80"
            numeric_ptr = (numeric_ptr + 1) % len(hr_list)

        elif MODE == 2:
            # MODE 2: Giả lập bệnh nhân bình thường khác
            patient_id = "RS232_BED_01_NORMAL"
            current_hr = random.randint(65, 85)
            current_spo2 = random.randint(96, 99)
            current_resp = random.randint(12, 18)
            nibp_str = f"{random.randint(110, 122)}/{random.randint(70, 80)}"

        else:
            # MODE 3: Giả lập bệnh nhân bất thường / sự cố cấp cứu
            patient_id = "RS232_BED_01_CRITICAL"
            current_hr = random.choice([135, 150, 42, 48])     # Nhịp tim quá nhanh hoặc quá chậm
            current_spo2 = random.choice([82, 86, 89])          # Tụt SpO2 nghiêm trọng
            current_resp = random.choice([8, 32])               # Suy hô hấp
            nibp_str = random.choice(["165/105", "80/50"])      # Cao hoặc tụt huyết áp

        # Đóng gói JSON
        monitor_packet = {
            "device_info": {
                "id": "MONITOR_BED_01", 
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

        # Bắn dữ liệu ra cổng Serial (COM1)
        payload = json.dumps(monitor_packet) + "\n"
        ser.write(payload.encode('utf-8'))
        
        print(f"[{time.strftime('%H:%M:%S')}] [MODE {MODE}] [{patient_id}] -> HR: {current_hr} bpm | SpO2: {current_spo2}% | Resp: {current_resp}/phút | BP: {nibp_str}")
        time.sleep(1)

except KeyboardInterrupt:
    ser.close()
    print("\n-> Đã đóng kết nối Serial.")