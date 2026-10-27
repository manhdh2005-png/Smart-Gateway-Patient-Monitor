const express = require("express");
const http = require("http");
const { Server } = require("socket.io");
const cors = require("cors");
const { createClient } = require("@supabase/supabase-js");

const app = express();
const server = http.createServer(app);

// ==================== 1. CẤU HÌNH SUPABASE ====================
const SUPABASE_URL = "https://lhiticvstojrfnealtuy.supabase.co";
const SUPABASE_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxoaXRpY3ZzdG9qcmZuZWFsdHV5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MzAxOTIzNywiZXhwIjoyMTA4NTk1MjM3fQ.zz3mdJ2AVQ28sCeV3aauOkUoh3OLwyO0K4gHfYWhgPc";

let supabase = null;
if (SUPABASE_URL && SUPABASE_KEY) {
  supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
  console.log("-> [SUPABASE] Đã khởi tạo kết nối Supabase thành công!");
}

// ==================== 2. CẤU HÌNH SOCKET.IO & EXPRESS ====================
const io = new Server(server, {
  cors: { origin: "*", methods: ["GET", "POST"] },
});

app.use(cors());
app.use(express.json({ limit: "20mb" }));

// Quản lý trạng thái sinh hiệu real-time của cả 4 Bệnh nhân
let activePatientsMap = {};

// ==================== 3. API NHẬN DỮ LIỆU FHIR TỪ PI 5 ====================
app.post("/api/v1/fhir/observations", async (req, res) => {
  try {
    const fhirBundle = req.body;

    if (
      fhirBundle &&
      fhirBundle.resourceType === "Bundle" &&
      Array.isArray(fhirBundle.entry)
    ) {
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
          // Bóc tách Patient ID
          if (itemRes.subject && itemRes.subject.reference) {
            patientId = itemRes.subject.reference.replace("Patient/", "");
          }

          // 🛡️ AN TOÀN CHUYỆN BÓC TÁCH INTERPRETATION (Tránh lỗi reading '0')
          if (
            Array.isArray(itemRes.interpretation) &&
            itemRes.interpretation.length > 0
          ) {
            const firstInterp = itemRes.interpretation[0];
            if (
              firstInterp &&
              Array.isArray(firstInterp.coding) &&
              firstInterp.coding.length > 0
            ) {
              alarmTag = firstInterp.coding[0].code || "STATUS_NORMAL";
              const displayStr = firstInterp.coding[0].display || "";
              priority = displayStr.includes("HIGH") ? "HIGH" : "INFO";
            }
          }

          // Bóc tách LOINC & Waveforms
          const codeObj =
            Array.isArray(itemRes.code?.coding) &&
            itemRes.code.coding.length > 0
              ? itemRes.code.coding[0]
              : null;

          const code = codeObj?.code || "";
          const codeText = itemRes.code?.text || "";

          if (code === "8867-4") hr = itemRes.valueQuantity?.value || 0;
          else if (code === "2708-6") spo2 = itemRes.valueQuantity?.value || 0;
          else if (code === "9279-1") resp = itemRes.valueQuantity?.value || 0;
          else if (codeText.includes("ECG")) {
            ecgWave = itemRes.valueSampledData?.data || [];
          } else if (codeText.includes("PPG") || codeText.includes("PLETH")) {
            ppgWave = itemRes.valueSampledData?.data || [];
          }
        }
      });

      // 1. Dữ liệu chuẩn bị ghi vào Supabase
      const supabaseData = {
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

      // 2. Cập nhật RAM cho Socket.IO
      activePatientsMap[patientId] = supabaseData;
      io.emit("patient_update", supabaseData);
      io.emit("all_patients_update", Object.values(activePatientsMap));

      // 3. Ghi trực tiếp vào Supabase và Bắt Log An Toàn
      if (supabase) {
        const { data, error } = await supabase
          .from("patient_logs")
          .insert([supabaseData])
          .select();

        if (error) {
          console.error(`❌ [SUPABASE ERROR] ${patientId}:`, error.message);
        } else if (Array.isArray(data) && data.length > 0) {
          console.log(
            `✅ [SUPABASE SAVED SUCCESS] ${patientId} (ID: ${data[0].id})`,
          );
        } else {
          console.log(`✅ [SUPABASE SAVED SUCCESS] ${patientId}`);
        }
      }

      console.log(
        `[${new Date().toLocaleTimeString()}] [BACKEND RECEIVED] ${patientId} | HR: ${hr} | SpO2: ${spo2}%`,
      );
      return res.status(200).json({ status: "success", message: "Processed" });
    } else {
      return res.status(400).json({ status: "error", message: "Invalid FHIR" });
    }
  } catch (err) {
    console.error("❌ Lỗi Server:", err.stack || err.message);
    return res.status(500).json({ status: "error", message: err.message });
  }
});

// ==================== 4. API CHO FRONTEND ====================
app.get("/api/v1/patient/all", (req, res) => {
  res.status(200).json(Object.values(activePatientsMap));
});

app.get("/api/v1/patient/history", async (req, res) => {
  if (!supabase) return res.status(500).json({ error: "No Supabase" });
  const { data, error } = await supabase
    .from("patient_logs")
    .select("*")
    .order("timestamp", { ascending: false })
    .limit(50);
  if (error) return res.status(500).json({ error: error.message });
  return res.status(200).json(data);
});

// ==================== 5. SOCKET.IO CONNECT ====================
io.on("connection", (socket) => {
  console.log(`-> [SOCKET.IO] Web Client kết nối: ${socket.id}`);
  socket.emit("all_patients_update", Object.values(activePatientsMap));
});

// ==================== 6. KÍCH HOẠT SERVER ====================
const PORT = 5000;
server.listen(PORT, () => {
  console.log(`====================================================`);
  console.log(`🚀 CLINICAL BACKEND RUNNING PORT: ${PORT}`);
  console.log(`====================================================`);
});
