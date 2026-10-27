import time
import json
import serial
import socket
import threading
import requests

# ==================== CẤU HÌNH BACKEND & CỔNG RS232 ====================
# Điền IP máy tính chạy Backend Node.js (xem bằng ipconfig)
BACKEND_URL = "http://192.168.1.15:5000/api/v1/fhir/observations"

SERIAL_PORT = "/dev/ttyUSB0"  # Hoặc /dev/ttyAMA0
BAUD_RATE = 115200

# ==================== HÀM ĐÓNG GÓI FHIR BUNDLE ====================
def build_fhir_bundle(patient_id, hr, spo2, resp, ecg_wave=[], ppg_wave=[], mode="MODE_1"):
    alarm_tag = "STATUS_CRITICAL" if "CRITICAL" in patient_id or hr > 130 or spo2 < 90 else "STATUS_NORMAL"
    priority = "HIGH" if alarm_tag == "STATUS_CRITICAL" else "INFO"
    
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
                    "valueQuantity": {"value": hr, "unit": "bpm"},
                    "interpretation": [{"coding": [{"code": alarm_tag, "display": f"Priority: {priority}"}]}]
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"coding": [{"system": "http://loinc.org", "code": "2708-6", "display": "Oxygen saturation"}]},
                    "valueQuantity": {"value": spo2, "unit": "%"}
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"coding": [{"system": "http://loinc.org", "code": "9279-1", "display": "Respiration rate"}]},
                    "valueQuantity": {"value": resp, "unit": "rpm"}
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"text": "ECG_LEAD_II"},
                    "valueSampledData": {"data": ecg_wave}
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"text": "PPG_PLETH"},
                    "valueSampledData": {"data": ppg_wave}
                }
            }
        ]
    }

def send_to_backend(fhir_bundle):
    """Bắn dữ liệu FHIR lên Backend Server"""
    try:
        headers = {'Content-Type': 'application/json'}
        res = requests.post(BACKEND_URL, json=fhir_bundle, headers=headers, timeout=2)
        if res.status_code == 200:
            patient_id = fhir_bundle["entry"][0]["resource"]["subject"]["reference"]
            print(f" -> [GATEWAY OK] Đẩy luồng {patient_id} lên Backend thành công!")
    except Exception as e:
        print(f" -> [GATEWAY ERROR] Lỗi kết nối Backend: {e}")

# ==================== HÀM BÓC TÁCH GÓI TIN SIMULATOR ====================
def process_incoming_packet(raw_json_str):
    try:
        packet = json.loads(raw_json_str)
        dev_info = packet.get("device_info", {})
        vitals = packet.get("vitals", {})
        waveforms = packet.get("waveforms", {})

        patient_id = dev_info.get("patient_id", dev_info.get("id", "UNKNOWN_PATIENT"))
        hr = vitals.get("hr_bpm", 0)
        spo2 = vitals.get("spo2_percent", 0)
        resp = vitals.get("resp_rate", 0)
        ecg = waveforms.get("ecg_lead_ii", [])
        ppg = waveforms.get("pleth_spo2", [])
        mode = dev_info.get("mode", "MODE_1")

        fhir = build_fhir_bundle(patient_id, hr, spo2, resp, ecg, ppg, mode)
        send_to_backend(fhir)
    except Exception as e:
        print(f"⚠️ Lỗi giải mã gói JSON: {e}")

# ==================== LUỒNG 1: ĐỌC CỔNG RS232 ====================
def thread_rs232_collector():
    print("🚀 [THREAD 1] Đang lắng nghe cổng RS232 (/dev/ttyUSB0)...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        buffer = ""
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    process_incoming_packet(line)
            time.sleep(0.05)
    except Exception as e:
        print(f"⚠️ Chưa mở được cổng RS232: {e}")

# ==================== LUỒNG 2, 3, 4: LẮNG NGHE WI-FI SOCKET ====================
def start_wifi_socket_server(port, monitor_name):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', port))
    server_socket.listen(5)
    print(f"🚀 [THREAD WI-FI] Đang lắng nghe {monitor_name} tại Port {port}...")

    while True:
        client, addr = server_socket.accept()
        try:
            data = client.recv(65536).decode('utf-8')
            if data:
                process_incoming_packet(data.strip())
        except Exception as e:
            pass
        finally:
            client.close()

# ==================== KHỞI CHẠY ĐA LUỒNG TẠI PI 5 ====================
if __name__ == "__main__":
    print("==========================================================")
    print("   SMART GATEWAY MULTI-THREADING (1 RS232 + 3 WI-FI)     ")
    print("==========================================================")

    # 1. Luồng 1 RS232 (Monitor 1)
    t1 = threading.Thread(target=thread_rs232_collector, daemon=True)
    
    # 2. Luồng 2 Wi-Fi (Monitor 2 - Port 8081)
    t2 = threading.Thread(target=start_wifi_socket_server, args=(8081, "MONITOR_BED_02"), daemon=True)
    
    # 3. Luồng 3 Wi-Fi (Monitor 3 - Port 8082)
    t3 = threading.Thread(target=start_wifi_socket_server, args=(8082, "MONITOR_BED_03"), daemon=True)

    # 4. Luồng 4 Wi-Fi (Monitor 4 - Port 8083)
    t4 = threading.Thread(target=start_wifi_socket_server, args=(8083, "MONITOR_BED_04"), daemon=True)

    t1.start()
    t2.start()
    t3.start()
    t4.start()

    while True:
        time.sleep(1)