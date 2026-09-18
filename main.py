# ============================================================
# 4IR Mining Fleet | Driver Fatigue Telemetry
# Copyright (c) 2026 [Your Name]. All Rights Reserved.
# This code is shared publicly for portfolio/demonstration purposes only.
# Not licensed for reuse, modification, or redistribution without
# written permission. Contact: [your email / LinkedIn here]
# ============================================================

import os
import cv2
import csv
import time
import math
import winsound
import threading
import json
import urllib.request
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from datetime import datetime
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import paho.mqtt.client as mqtt

# ============================================================
# CONFIG
# ============================================================

MQTT_BROKER = "broker.hivemq.com"  # Replace with private broker / AWS IoT endpoint
MQTT_PORT = 1883

MODEL_PATH = "face_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

LOG_FILE = "fatigue_event_log.csv"

# Eyes
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
EAR_THRESHOLD = 0.21
EAR_CONSEC_FRAMES = 12

# Mouth (yawning)
MOUTH_TOP = 13
MOUTH_BOTTOM = 14
MOUTH_LEFT = 78
MOUTH_RIGHT = 308
MAR_THRESHOLD = 0.60
MAR_CONSEC_FRAMES = 20

# Head drop (nodding off)
NOSE_TIP = 1
CHIN = 152
HEAD_DROP_RATIO = 0.12
HEAD_DROP_CONSEC_FRAMES = 15
CALIBRATION_SECONDS = 3.0

# Fatigue score (0-100), replaces the old "3 strikes = critical" rule
SCORE_NORMAL_MAX = 29
SCORE_CAUTION_MAX = 59
SCORE_HIGH_MAX = 84
SCORE_INCREMENT = 3.0
SCORE_DECAY = 1.0


# ============================================================
# Model bootstrap -- keeps this runnable as a single file in Thonny
# ============================================================

def ensure_model():
    if os.path.exists(MODEL_PATH):
        return
    print("Downloading face_landmarker.task (one-time setup)...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Model downloaded.")
    except Exception as e:
        raise SystemExit(
            f"Could not download {MODEL_PATH} automatically ({e}).\n"
            f"Download it manually from:\n{MODEL_URL}\n"
            f"and place it next to this script."
        )


# ============================================================
# Geometry helpers
# ============================================================

def distance(p1, p2):
    return math.hypot(p1.x - p2.x, p1.y - p2.y)


def calculate_ear(landmarks, eye_indices):
    v1 = distance(landmarks[eye_indices[1]], landmarks[eye_indices[5]])
    v2 = distance(landmarks[eye_indices[2]], landmarks[eye_indices[4]])
    h = distance(landmarks[eye_indices[0]], landmarks[eye_indices[3]])
    return (v1 + v2) / (2.0 * h) if h else 0.0


def calculate_mar(landmarks):
    top = landmarks[MOUTH_TOP]
    bottom = landmarks[MOUTH_BOTTOM]
    left = landmarks[MOUTH_LEFT]
    right = landmarks[MOUTH_RIGHT]
    horiz = distance(left, right)
    return distance(top, bottom) / horiz if horiz else 0.0


def face_height(landmarks):
    return distance(landmarks[NOSE_TIP], landmarks[CHIN])


# ============================================================
# Local CSV event log
# ============================================================

def init_log():
    new_file = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "driver", "permit_id", "truck_id", "event", "level"])


def write_log_row(driver, permit, truck, message, level):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([ts, driver, permit, truck, message, level])


class MiningFatigueApp:
    def __init__(self, window):
        self.window = window
        self.window.title("4IR MINING FLEET | DRIVER FATIGUE TELEMETRY")
        self.window.geometry("1080x780")
        self.window.configure(bg="#121212")

        self.driver_name = ""
        self.driver_id = ""
        self.truck_id = ""
        self.is_monitoring = False
        self.cap = None

        # Fatigue cue frame counters
        self.eyes_closed_frames = 0
        self.yawn_frames = 0
        self.head_drop_frames = 0

        # Fatigue score engine (replaces fatigue_count >= 3)
        self.score = 0.0
        self.warnings = 0
        self.criticals = 0
        self.last_status = "NORMAL"
        self.session_start = None

        # Head-drop calibration
        self.calibrated = False
        self.calib_start = None
        self.baseline_nose_y = None

        self._clock_job = None
        self._feed_job = None
        self.is_beeping = False
        self.critical_alarm_running = False

        self.mqtt_client = mqtt.Client(client_id="", protocol=mqtt.MQTTv311)
        self.mqtt_connected = False
        self.last_telemetry_time = 0

        ensure_model()
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
            num_faces=1,
        )
        self.detector = vision.FaceLandmarker.create_from_options(options)

        init_log()

        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.build_registration_ui()

    # -------------------- MQTT --------------------

    def setup_mqtt(self):
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self.mqtt_connected = True
                init_payload = {
                    "event": "DRIVER_SESSION_START",
                    "driver_name": self.driver_name,
                    "driver_id": self.driver_id,
                    "truck_id": self.truck_id,
                    "timestamp": time.time(),
                }
                self.mqtt_client.publish(
                    f"mining/fleet/{self.truck_id}/session", json.dumps(init_payload), qos=1
                )

        self.mqtt_client.on_connect = on_connect
        try:
            self.mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[MQTT ERROR] Connection failed: {e}")

    def publish_telemetry(self, ear, mar, head_down, status_str):
        if not self.mqtt_connected:
            return
        now = time.time()
        if now - self.last_telemetry_time >= 1.0:
            self.last_telemetry_time = now
            payload = {
                "driver_id": self.driver_id,
                "truck_id": self.truck_id,
                "ear": round(ear, 3),
                "mar": round(mar, 3),
                "head_down": head_down,
                "fatigue_score": round(self.score, 1),
                "status": status_str,
                "timestamp": now,
            }
            self.mqtt_client.publish(
                f"mining/fleet/{self.truck_id}/telemetry", json.dumps(payload), qos=0
            )

    def publish_alert(self, level, message, ear):
        if not self.mqtt_connected:
            return
        payload = {
            "event": f"{level}_FATIGUE_ALERT",
            "driver_name": self.driver_name,
            "driver_id": self.driver_id,
            "truck_id": self.truck_id,
            "message": message,
            "fatigue_score": round(self.score, 1),
            "ear": round(ear, 3),
            "timestamp": time.time(),
        }
        self.mqtt_client.publish(
            f"mining/fleet/{self.truck_id}/alerts", json.dumps(payload), qos=1
        )

    # -------------------- UI 1: Registration --------------------

    def build_registration_ui(self):
        self.clear_ui()
        card = tk.Frame(self.window, bg="#1E1E1E", bd=1, relief="solid", padx=30, pady=30)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(card, text="MINING FLEET DISPATCH", font=("Consolas", 18, "bold"),
                 fg="#00E676", bg="#1E1E1E").pack(pady=(0, 5))
        tk.Label(card, text="Driver Identity Verification", font=("Helvetica", 10),
                 fg="#A0A0A0", bg="#1E1E1E").pack(pady=(0, 20))

        fields = [("Full Name:", "entry_name"), ("Driver Permit ID:", "entry_id"),
                  ("Mining Truck ID:", "entry_truck")]
        for label_text, attr_name in fields:
            tk.Label(card, text=label_text, font=("Helvetica", 10, "bold"), fg="#E0E0E0",
                     bg="#1E1E1E", anchor="w").pack(fill="x", pady=(5, 2))
            entry = tk.Entry(card, font=("Consolas", 11), bg="#2A2A2A", fg="#FFFFFF",
                              insertbackground="white", bd=0, highlightthickness=1,
                              highlightbackground="#3A3A3A")
            entry.pack(fill="x", ipady=6, pady=(0, 10))
            setattr(self, attr_name, entry)

        btn = tk.Button(card, text="INITIALIZE TELEMETRY FEED (P)", font=("Helvetica", 11, "bold"),
                         bg="#00E676", fg="#000000", activebackground="#00B359",
                         activeforeground="#000000", bd=0, cursor="hand2",
                         command=self.register_and_start)
        btn.pack(fill="x", ipady=8, pady=(15, 0))

        self.window.bind('<p>', lambda event: self.register_and_start())

    def register_and_start(self):
        name = self.entry_name.get().strip()
        d_id = self.entry_id.get().strip()
        truck = self.entry_truck.get().strip()
        if not name or not d_id or not truck:
            messagebox.showwarning("Input Validation", "All telemetry identification fields are required.")
            return
        self.driver_name = name
        self.driver_id = d_id
        self.truck_id = truck
        self.window.unbind('<p>')
        self.build_dashboard_ui()

    # -------------------- UI 2: Dashboard --------------------

    def build_dashboard_ui(self):
        self.clear_ui()

        header = tk.Frame(self.window, bg="#1E1E1E", height=60)
        header.pack(fill="x", side="top")
        info_str = f"DRIVER: {self.driver_name.upper()}  |  PERMIT: {self.driver_id}  |  VEHICLE: {self.truck_id}"
        tk.Label(header, text=info_str, font=("Consolas", 11, "bold"), fg="#00E676",
                 bg="#1E1E1E").pack(side="left", padx=20)
        self.clock_label = tk.Label(header, font=("Consolas", 10), fg="#808080", bg="#1E1E1E")
        self.clock_label.pack(side="right", padx=20)

        main_container = tk.Frame(self.window, bg="#121212")
        main_container.pack(fill="both", expand=True, padx=20, pady=(15, 5))

        video_box = tk.Frame(main_container, bg="#1E1E1E", bd=1, relief="solid")
        video_box.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.cam_label = tk.Label(video_box, bg="#000000")
        self.cam_label.pack(fill="both", expand=True, padx=5, pady=5)

        panel = tk.Frame(main_container, bg="#1E1E1E", width=300, bd=1, relief="solid",
                          padx=15, pady=15)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        tk.Label(panel, text="SAFETY TELEMETRY", font=("Consolas", 12, "bold"), fg="#FFFFFF",
                 bg="#1E1E1E").pack(anchor="w", pady=(0, 12))

        self.ear_val_label = self._make_metric_card(panel, "EYE ASPECT RATIO (EAR)")
        self.mar_val_label = self._make_metric_card(panel, "MOUTH ASPECT RATIO (MAR)")
        self.head_val_label = self._make_metric_card(panel, "HEAD POSITION")
        self.score_val_label = self._make_metric_card(panel, "FATIGUE SCORE")

        self.status_card = tk.Frame(panel, bg="#1B3A2B", padx=10, pady=12)
        self.status_card.pack(fill="x", pady=(15, 0))
        self.status_title = tk.Label(self.status_card, text="SYSTEM ACTIVE", font=("Consolas", 10, "bold"),
                                      fg="#00E676", bg="#1B3A2B")
        self.status_title.pack(anchor="w")
        self.status_sub = tk.Label(self.status_card, text="Calibrating...", font=("Helvetica", 8),
                                    fg="#A0A0A0", bg="#1B3A2B")
        self.status_sub.pack(anchor="w")

        # Logo panel -- fills remaining vertical space in the sidebar.
        # Drop a "logo.png" / "logo.jpg" / "logo.jpeg" next to this script
        # and it will be picked up automatically.
        self.logo_frame = tk.Frame(panel, bg="#1E1E1E")
        self.logo_frame.pack(fill="both", expand=True, pady=(15, 0))
        self.load_logo()

        # Event log panel (bottom strip)
        log_frame = tk.Frame(self.window, bg="#1E1E1E", bd=1, relief="solid")
        log_frame.pack(fill="x", side="bottom", padx=20, pady=(0, 15))
        tk.Label(log_frame, text="EVENT LOG", font=("Consolas", 9, "bold"), fg="#A0A0A0",
                 bg="#1E1E1E").pack(anchor="w", padx=10, pady=(6, 0))
        self.event_text = tk.Text(log_frame, height=6, bg="#0A0A0A", fg="#E0E0E0",
                                   font=("Consolas", 9), bd=0, state="disabled")
        self.event_text.pack(fill="x", padx=10, pady=(2, 10))
        self.event_text.tag_config("CRITICAL", foreground="#FF5252")
        self.event_text.tag_config("WARNING", foreground="#FFD700")
        self.event_text.tag_config("CLEAR", foreground="#00E676")

        self.session_start = time.time()
        self.calib_start = time.time()
        self.update_clock()
        self.setup_mqtt()

        self.cap = cv2.VideoCapture(0)
        self.is_monitoring = True
        self.update_feed()

    def load_logo(self):
        candidates = ["logo.png", "logo.jpg", "logo.jpeg"]
        path = next((p for p in candidates if os.path.exists(p)), None)
        if not path:
            tk.Label(self.logo_frame, text="LOGO", font=("Consolas", 10), fg="#3A3A3A",
                     bg="#1E1E1E").pack(expand=True)
            return
        try:
            img = Image.open(path)
            img.thumbnail((260, 260))
            self.logo_imgtk = ImageTk.PhotoImage(img)
            tk.Label(self.logo_frame, image=self.logo_imgtk, bg="#1E1E1E").pack(expand=True)
        except Exception:
            tk.Label(self.logo_frame, text="LOGO", font=("Consolas", 10), fg="#3A3A3A",
                     bg="#1E1E1E").pack(expand=True)

    def _make_metric_card(self, parent, title):
        card = tk.Frame(parent, bg="#2A2A2A", padx=10, pady=10)
        card.pack(fill="x", pady=5)
        tk.Label(card, text=title, font=("Helvetica", 8, "bold"), fg="#A0A0A0",
                 bg="#2A2A2A").pack(anchor="w")
        val = tk.Label(card, text="--", font=("Consolas", 16, "bold"), fg="#00E676", bg="#2A2A2A")
        val.pack(anchor="w")
        return val

    def update_clock(self):
        if hasattr(self, 'clock_label') and self.is_monitoring:
            self.clock_label.config(text=time.strftime("%Y-%m-%d %H:%M:%S"))
            self._clock_job = self.window.after(1000, self.update_clock)

    # -------------------- Event log helper --------------------

    def log_event(self, message, level="WARNING"):
        ts = datetime.now().strftime("%H:%M:%S")
        write_log_row(self.driver_name, self.driver_id, self.truck_id, message, level)
        self.event_text.config(state="normal")
        self.event_text.insert("end", f"{ts}   {message}\n", level)
        self.event_text.see("end")
        # keep only the last ~40 lines on screen
        lines = int(self.event_text.index('end-1c').split('.')[0])
        if lines > 40:
            self.event_text.delete("1.0", "2.0")
        self.event_text.config(state="disabled")

    # -------------------- Fatigue status --------------------

    def status_from_score(self):
        if self.score <= SCORE_NORMAL_MAX:
            return "NORMAL"
        elif self.score <= SCORE_CAUTION_MAX:
            return "CAUTION"
        elif self.score <= SCORE_HIGH_MAX:
            return "HIGH"
        return "CRITICAL"

    def apply_status_ui(self, status):
        colors = {
            "NORMAL": ("#1B3A2B", "#00E676", "Monitoring facial metrics"),
            "CAUTION": ("#3A2E1B", "#FFD700", "Early fatigue cues detected"),
            "HIGH": ("#3A2E1B", "#FFA500", "Fatigue risk rising -- stay alert"),
            "CRITICAL": ("#3A1B1B", "#FF5252", "Driver rest required immediately"),
        }
        bg, fg, sub = colors[status]
        self.status_card.config(bg=bg)
        self.status_title.config(text=f"STATUS: {status}", fg=fg, bg=bg)
        self.status_sub.config(text=sub, fg="#E0E0E0", bg=bg)
        self.score_val_label.config(text=f"{self.score:.0f} / 100", fg=fg)

    # -------------------- Main camera loop --------------------

    def update_feed(self):
        if not self.is_monitoring or not self.cap or not self.cap.isOpened():
            return

        ret, frame = self.cap.read()
        if ret:
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            detection_result = self.detector.detect(mp_image)

            ear, mar = 0.0, 0.0
            head_down = False
            cues_active = False

            if detection_result.face_landmarks:
                landmarks = detection_result.face_landmarks[0]

                for eye_indices in [LEFT_EYE, RIGHT_EYE]:
                    pts = [(int(landmarks[idx].x * w), int(landmarks[idx].y * h)) for idx in eye_indices]
                    for i in range(len(pts)):
                        cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], (0, 230, 118), 1)

                left_ear = calculate_ear(landmarks, LEFT_EYE)
                right_ear = calculate_ear(landmarks, RIGHT_EYE)
                ear = (left_ear + right_ear) / 2.0
                mar = calculate_mar(landmarks)
                nose_y = landmarks[NOSE_TIP].y
                f_height = face_height(landmarks)

                self.ear_val_label.config(text=f"{ear:.2f}")
                self.mar_val_label.config(text=f"{mar:.2f}")

                if not self.calibrated:
                    self.head_val_label.config(text="CALIBRATING")
                    if time.time() - self.calib_start > CALIBRATION_SECONDS:
                        self.baseline_nose_y = nose_y
                        self.calibrated = True
                        self.log_event("Calibration complete -- monitoring started", "CLEAR")
                else:
                    # Eyes
                    if ear < EAR_THRESHOLD:
                        self.eyes_closed_frames += 1
                    else:
                        if self.eyes_closed_frames >= EAR_CONSEC_FRAMES:
                            self.log_event("Prolonged eye closure detected")
                        self.eyes_closed_frames = 0
                    if self.eyes_closed_frames >= EAR_CONSEC_FRAMES:
                        cues_active = True

                    # Mouth / yawning
                    if mar > MAR_THRESHOLD:
                        self.yawn_frames += 1
                    else:
                        if self.yawn_frames >= MAR_CONSEC_FRAMES:
                            self.log_event("Yawn detected")
                        self.yawn_frames = 0
                    if self.yawn_frames >= MAR_CONSEC_FRAMES:
                        cues_active = True

                    # Head drop
                    drop = (nose_y - self.baseline_nose_y) / f_height if f_height else 0
                    head_down = drop > HEAD_DROP_RATIO
                    if head_down:
                        self.head_drop_frames += 1
                    else:
                        if self.head_drop_frames >= HEAD_DROP_CONSEC_FRAMES:
                            self.log_event("Head drop / microsleep detected")
                        self.head_drop_frames = 0
                    if self.head_drop_frames >= HEAD_DROP_CONSEC_FRAMES:
                        cues_active = True

                    self.head_val_label.config(text="DROPPED" if head_down else "NORMAL")

                    # Update decaying fatigue score
                    if cues_active:
                        self.score = min(100.0, self.score + SCORE_INCREMENT)
                    else:
                        self.score = max(0.0, self.score - SCORE_DECAY)

                    status = self.status_from_score()
                    if status != self.last_status:
                        if status == "CRITICAL":
                            self.criticals += 1
                            self.log_event("FATIGUE ESCALATION -> CRITICAL", "CRITICAL")
                            self.publish_alert("CRITICAL", "Fatigue escalation to CRITICAL", ear)
                            self.start_critical_alarm()
                        elif status == "HIGH":
                            self.warnings += 1
                            self.log_event("Fatigue escalation -> HIGH", "WARNING")
                            self.async_beep(1200, 400)
                    self.last_status = status
                    self.apply_status_ui(status)

            rgb_display = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb_display)
            imgtk = ImageTk.PhotoImage(image=img)
            self.cam_label.imgtk = imgtk
            self.cam_label.configure(image=imgtk)

            if self.calibrated:
                self.publish_telemetry(ear, mar, head_down, self.last_status)

        if self.is_monitoring:
            self._feed_job = self.window.after(15, self.update_feed)

    def async_beep(self, freq, duration):
        if not self.is_beeping:
            def play():
                self.is_beeping = True
                try:
                    winsound.Beep(freq, duration)
                except Exception:
                    pass
                self.is_beeping = False
            threading.Thread(target=play, daemon=True).start()

    def start_critical_alarm(self):
        """Loud, repeating alarm -- keeps ringing while the driver stays in
        CRITICAL, rather than a single easy-to-miss beep. Stops itself as
        soon as the status improves."""
        if self.critical_alarm_running:
            return
        self.critical_alarm_running = True

        def loop():
            while self.critical_alarm_running and self.is_monitoring and self.last_status == "CRITICAL":
                try:
                    winsound.Beep(2500, 700)
                except Exception:
                    pass
                time.sleep(0.3)
            self.critical_alarm_running = False

        threading.Thread(target=loop, daemon=True).start()

    def clear_ui(self):
        for widget in self.window.winfo_children():
            widget.destroy()

    def on_closing(self):
        self.is_monitoring = False
        self.critical_alarm_running = False
        if self._clock_job is not None:
            try:
                self.window.after_cancel(self._clock_job)
            except Exception:
                pass
        if self._feed_job is not None:
            try:
                self.window.after_cancel(self._feed_job)
            except Exception:
                pass
        if self.mqtt_connected:
            try:
                end_payload = {
                    "event": "DRIVER_SESSION_END",
                    "truck_id": self.truck_id,
                    "warnings": self.warnings,
                    "criticals": self.criticals,
                    "timestamp": time.time(),
                }
                self.mqtt_client.publish(f"mining/fleet/{self.truck_id}/session",
                                          json.dumps(end_payload), qos=1)
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MiningFatigueApp(root)
    root.mainloop()
