import serial
import json
from datetime import datetime

COM_PORT = 'COM2'
BAUD_RATE = 115200

def convert_to_hl7_v2(data):
    """
    Hàm chuyển đổi dữ liệu JSON thô sang Bản tin chuẩn Y tế HL7 v2.3.1 (ORU^R01)
    Sử dụng các mã chuẩn hóa quốc tế:
      - 8867-4 : Nhịp tim (Heart Rate)
      - 2708-6 : SpO2 (Oxygen Saturation)
      - 9279-1 : Nhịp thở (Respiration Rate)
    """
    vitals = data['vitals']
    patient_id = data['device_info']['patient_id']
    device_id = data['device_info']['id']
    
    # Tạo Timestamp theo định dạng HL7 (YYYYMMDDHHMMSS)
    hl7_time = datetime.now().strftime("%Y%m%d%H%M%S")
    msg_control_id = f"MSG_{int(datetime.now().timestamp())}"
    
    # 1. MSH Segment - Message Header (Thông tin đầu bản tin)
    msh = f"MSH|^~\\&|{device_id}|ICU_ROOM101|CENTRAL_MONITOR|HOSPITAL|{hl7_time}||ORU^R01|{msg_control_id}|P|2.3.1"
    
    # 2. PID Segment - Patient Identification (Thông tin bệnh nhân)
    pid = f"PID|1||{patient_id}||PATIENT_NAME||19800101|M"
    
    # 3. OBR Segment - Observation Request (Thông tin phiên đo)
    obr = f"OBR|1||{msg_control_id}|VITAL_SIGNS_PANEL|||{hl7_time}"
    
    # 4. OBX Segments - Observation Result (Kết quả từng chỉ số sinh hiệu đo được)
    # OBX|ID|ValueType|Code^Name^CodingSys||Value|Unit|||||Status
    obx_hr   = f"OBX|1|NM|8867-4^Heart rate^LN||{vitals['hr_bpm']}|bpm|60-100|N|||F"
    obx_spo2 = f"OBX|2|NM|2708-6^Oxygen saturation^LN||{vitals['spo2_percent']}|%|95-100|N|||F"
    obx_resp = f"OBX|3|NM|9279-1^Respiratory rate^LN||{vitals['resp_rate']}|/min|12-20|N|||F"
    
    # Ghép các Segment lại thành bản tin HL7 hoàn chỉnh (phân tách bằng dấu xuống dòng)
    hl7_message = f"{msh}\n{pid}\n{obr}\n{obx_hr}\n{obx_spo2}\n{obx_resp}"
    return hl7_message

# Khởi tạo lắng nghe Cổng Serial COM2
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    print(f"=== SMART GATEWAY: ĐANG LẮNG NGHE VÀ CHUẨN HÓA DỮ LIỆU SANG HL7 (CỔNG {COM_PORT}) ===")
except Exception as e:
    print(f"Lỗi mở cổng {COM_PORT}: {e}")
    exit()

while True:
    try:
        line = ser.readline().decode('utf-8').strip()
        if line:
            # Parse chuỗi JSON thô nhận từ Serial
            raw_data = json.loads(line)
            
            # Chuyển đổi sang Chuẩn Y tế HL7 v2
            hl7_output = convert_to_hl7_v2(raw_data)
            
            print("\n" + "="*70)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] -> NHẬN CẢM BIẾN & XUẤT BẢN TIN HL7 v2.x SUCCESS:")
            print("="*70)
            print(hl7_output)
            print("="*70)
            
    except Exception as e:
        print(f"Lỗi giải mã/chuyển đổi: {e}")