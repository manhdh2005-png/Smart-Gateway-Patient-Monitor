const express = require("express");
const http = require("http");
const { Server } = require("socket.io");
const cors = require("cors");
const { createClient } = require("@supabase/supabase-js");

const app = express();
const server = http.createServer(app);

// ==================== 1. CẤU HÌNH SUPABASE ====================
// Điền thông tin URL và ANON_KEY từ Supabase Project của bạn khi có
const SUPABASE_URL = "https://lhiticvstojrfnealtuy.supabase.co";
const SUPABASE_KEY = "sb_publishable_yuSEO4NaJrhe1HLyYytqiA_TdcqrQ5c";

let supabase = null;
if (SUPABASE_URL && SUPABASE_KEY) {
  supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
  console.log("-> [SUPABASE] Đã khởi tạo kết nối Supabase thành công!");
} else {
  console.log(
    "-> [CẢNH BÁO SUPABASE] Chưa điền API Key thực tế. Đang chạy ở chế độ Bỏ qua lưu Database (chỉ phát Real-time).",
  );
}

// ==================== 2. CẤU HÌNH SOCKET.IO & EXPRESS ====================
const io = new Server(server, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"],
  },
});

app.use(cors());
app.use(express.json({ limit: "20mb" })); // Tăng limit để nhận mảng sóng ECG/PPG lớn

// Khung dữ liệu sinh hiệu mặc định chứa trọn vẹn 5 kênh tín hiệu
let latestPatientState = {
  patient_id: "NO_DATA",
  hr_bpm: 0,
  spo2_percent: 0,
  resp_rpm: 0, // Signal 3: Nhịp thở (Respiration Rate)
  ecg_signal: [], // Signal 4: Chuỗi mảng sóng ECG
  ppg_signal: [], // Signal 5: Chuỗi mảng sóng PPG/Pleth
  alarm_level1: "STATUS_NORMAL",
  priority: "INFO",
  timestamp: new Date().toISOString(),
};

// ==================== 3. API NHẬN DỮ LIỆU FHIR TỪ RASPBERRY PI 5 ====================
app.post("/api/v1/fhir/observations", async (req, res) => {
  try {
    const fhirBundle = req.body;

    if (fhirBundle.resourceType === "Bundle" && fhirBundle.entry) {
      let patientId = "UNKNOWN";
      let hr = 0;
      let spo2 = 0;
      let resp = 0;
      let ecgWave = [];
      let ppgWave = [];
      let alarmTag = "STATUS_NORMAL";
      let priority = "INFO";

      fhirBundle.entry.forEach((item) => {
        const itemRes = item.resource;
        if (itemRes && itemRes.resourceType === "Observation") {
          // Lấy Patient ID
          if (itemRes.subject && itemRes.subject.reference) {
            patientId = itemRes.subject.reference.replace("Patient/", "");
          }

          // Lấy thông tin Cảnh báo (Interpretation)
          if (itemRes.interpretation && itemRes.interpretation[0]?.coding[0]) {
            alarmTag = itemRes.interpretation[0].coding[0].code;
            const displayStr =
              itemRes.interpretation[0].coding[0].display || "";
            priority = displayStr.includes("HIGH") ? "HIGH" : "INFO";
          }

          // Bóc tách 5 kênh tín hiệu dựa trên mã LOINC / Text Code
          const code = itemRes.code?.coding[0]?.code;
          const codeText = itemRes.code?.text || "";

          if (code === "8867-4") {
            hr = itemRes.valueQuantity?.value || 0;
          } else if (code === "2708-6") {
            spo2 = itemRes.valueQuantity?.value || 0;
          } else if (code === "9279-1") {
            resp = itemRes.valueQuantity?.value || 0;
          } else if (code === "131329" || codeText.includes("ECG")) {
            ecgWave =
              itemRes.valueSampledData?.data || itemRes.valueArray || [];
          } else if (
            code === "150456" ||
            codeText.includes("PPG") ||
            codeText.includes("PLETH")
          ) {
            ppgWave =
              itemRes.valueSampledData?.data || itemRes.valueArray || [];
          }
        }
      });

      // Cập nhật Trạng thái mới nhất
      latestPatientState = {
        patient_id: patientId,
        hr_bpm: hr,
        spo2_percent: spo2,
        resp_rpm: resp,
        ecg_signal: ecgWave,
        ppg_signal: ppgWave,
        alarm_level1: alarmTag,
        priority: priority,
        timestamp: fhirBundle.timestamp || new Date().toISOString(),
      };

      // ⚡ LUỒNG 1: Bắn Real-time xuống Web Frontend qua Socket.IO (Truyền 5 tín hiệu tức thì)
      io.emit("patient_update", latestPatientState);

      // 💾 LUỒNG 2: Ghi bản ghi lịch sử vào Supabase (nếu đã cấu hình)
      if (supabase) {
        const { error } = await supabase
          .from("patient_logs")
          .insert([latestPatientState]);

        if (error) {
          console.error("Lỗi lưu Supabase:", error.message);
        } else {
          console.log(
            ` -> [SUPABASE SAVED] Đã lưu bản ghi Bệnh nhân ${patientId} (Gồm 5 kênh tín hiệu)`,
          );
        }
      }

      console.log(
        `[${new Date().toLocaleTimeString()}] [BACKEND RECEIVED] Patient: ${patientId} | HR: ${hr} | SpO2: ${spo2}% | RESP: ${resp}/p | ECG Points: ${ecgWave.length} | Alarm: ${alarmTag} (${priority})`,
      );

      return res.status(200).json({
        status: "success",
        message: "FHIR Bundle processed successfully",
      });
    } else {
      return res
        .status(400)
        .json({ status: "error", message: "Invalid FHIR Bundle structure" });
    }
  } catch (err) {
    console.error("Lỗi xử lý FHIR API:", err);
    return res.status(500).json({ status: "error", message: err.message });
  }
});

// ==================== 4. API CHO FRONTEND LẤY DỮ LIỆU ====================
app.get("/api/v1/patient/latest", (req, res) => {
  res.status(200).json(latestPatientState);
});

app.get("/api/v1/patient/history", async (req, res) => {
  if (!supabase) {
    return res
      .status(500)
      .json({ error: "Supabase chưa được cấu hình trên Server." });
  }

  const { data, error } = await supabase
    .from("patient_logs")
    .select("*")
    .order("timestamp", { ascending: false })
    .limit(50);

  if (error) return res.status(500).json({ error: error.message });
  return res.status(200).json(data);
});

// ==================== 5. SỰ KIỆN KẾT NỐI SOCKET.IO ====================
io.on("connection", (socket) => {
  console.log(`-> [SOCKET.IO] Client Web vừa kết nối! ID: ${socket.id}`);
  socket.emit("patient_update", latestPatientState);

  socket.on("disconnect", () => {
    console.log(`-> [SOCKET.IO] Client Web đã ngắt kết nối: ${socket.id}`);
  });
});

// ==================== 6. KÍCH HOẠT SERVER ====================
const PORT = 5000;
server.listen(PORT, () => {
  console.log(`====================================================`);
  console.log(`🚀 CLINICAL BACKEND SERVER ĐÃ CHẠY TẠI PORT: ${PORT}`);
  console.log(
    `👉 FHIR API Endpoint : http://localhost:${PORT}/api/v1/fhir/observations`,
  );
  console.log(`👉 Web Socket Server : ws://localhost:${PORT}`);
  console.log(`====================================================`);
});
