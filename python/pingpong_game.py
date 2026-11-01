"""
BÓNG BÀN - CAMERA THEO DÕI VỢT  (chỉ dùng camera, không cần cảm biến điện thoại)

CÁCH HOẠT ĐỘNG
  * Mở app trên iPhone -> bấm "BẬT MÀN HÌNH VỢT" -> màn hình điện thoại sáng màu hồng (magenta).
  * Dán điện thoại lên vợt, quay màn hình hồng về phía camera laptop.
  * Camera tìm vật màu hồng -> biết vợt ở đâu (trái/phải, cao/thấp, tiến/lùi theo kích thước vật),
    nghiêng đầu vợt bao nhiêu (theo hướng trục dài của điện thoại) và vung nhanh hay chậm (theo tốc độ).
  * Không có camera thì chơi bằng chuột.

PHÍM
  SPACE  căn chỉnh (cầm vợt tư thế sẵn sàng, màn hình hồng hướng về camera)   R  chơi lại
  Click vào khung camera (góc trên phải) để chọn đúng màu vợt nếu nó không bắt được
  C  đổi camera (0/1/2)    V  ẩn/hiện khung camera
  , .  độ nhạy di chuyển    H  hút bóng (0/30/60%)    1/2/3  độ khó
  M  chuyển qua lại giữa camera / chuột    ESC  thoát
"""
import math
import os
import random
import sys
import threading
import time

try:
    import cv2
    import numpy as np
except ImportError:      # chưa cài opencv -> vẫn chạy, chỉ không có camera
    cv2 = None
    np = None

W, H = 1280, 720
G = 9.8
TL, TW = 2.74, 1.525          # chiều dài / rộng bàn (m)
NET_H = 0.1525
ZN = TL / 2
CAM_Z, CAM_H, FOCAL, HY = 1.9, 0.9, 760.0, 240
PADDLE_Y0 = 518               # (chỉ dùng cho chuột) y mặc định trên màn hình
HIT_R = 0.17                  # bán kính vùng chạm của vợt (m)
PADDLE_R_WORLD = 0.13         # bán kính vẽ mặt vợt (m)
PAD_X0, PAD_Y0W, PAD_Z0 = 0.0, 0.30, -0.25   # vị trí vợt ban đầu trong không gian (m)
CAM_D0 = 0.7                  # khoảng cách ước lượng từ vợt tới camera (m)
CAM_VIEW_W, CAM_VIEW_H = 0.70, 0.52     # bề ngang/cao (m) camera nhìn thấy ở khoảng cách chơi -> đổi tốc độ vung ra m/s
CAM_GX, CAM_GY, CAM_GZ = 1.8, 1.4, 2.4   # hệ số đổi chuyển động trước camera -> chuyển động vợt trong game
WIN_SCORE = 11


def clamp(v, a, b):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def proj(x, y, z):
    """Chiếu điểm 3D (m) ra màn hình. Camera đứng sau người chơi."""
    d = max(z + CAM_Z, 0.25)
    s = FOCAL / d
    return W / 2 + x * s, HY + (CAM_H - y) * s, s


class OneEuro:
    """Lọc mượt khi tay đứng yên (hết rung), vẫn nhạy khi vung nhanh."""
    def __init__(self, mincut=1.5, beta=1.5, dcut=1.0):
        self.mincut, self.beta, self.dcut = mincut, beta, dcut
        self.x = None
        self.dx = 0.0

    @staticmethod
    def _alpha(cut, dt):
        tau = 1.0 / (2 * math.pi * cut)
        return 1.0 / (1.0 + tau / max(dt, 1e-4))

    def __call__(self, v, dt):
        if self.x is None:
            self.x = v
            return v
        dx = (v - self.x) / max(dt, 1e-4)
        self.dx += self._alpha(self.dcut, dt) * (dx - self.dx)
        cut = self.mincut + self.beta * abs(self.dx)
        self.x += self._alpha(cut, dt) * (v - self.x)
        return self.x

    def reset(self):
        self.x = None
        self.dx = 0.0


# ---------------- Camera: theo dõi màn hình điện thoại (màu hồng) ----------------
# Trả về: vị trí tâm, kích thước, và độ nghiêng của trục dài (đầu vợt) so với phương thẳng đứng.
class CameraTracker:
    FW, FH = 320, 240

    def __init__(self, index=0):
        self.available = cv2 is not None
        self.index = index
        self.restart = False
        self.stop = False
        self.lock = threading.Lock()
        self.hue, self.tol, self.smin, self.vmin = 150, 14, 100, 100   # hồng/magenta (OpenCV hue 0..179)
        self.cx = self.cy = self.size = 0.0
        self.tilt = 0.0          # rad, dương = đầu vợt nghiêng sang phải (theo màn hình)
        self.opened = False      # camera đã mở được chưa
        self.last_seen = 0.0
        self.frame_bytes = None
        self.hsv = None
        self.status = "Chưa cài opencv-python" if not self.available else "Đang mở camera..."
        if self.available:
            threading.Thread(target=self._loop, daemon=True).start()

    def _open(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(self.index)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
        return cap

    def _mask(self, hsv):
        h, t = self.hue, self.tol
        lo_s, lo_v = self.smin, self.vmin
        if h - t < 0:
            m1 = cv2.inRange(hsv, (0, lo_s, lo_v), (h + t, 255, 255))
            m2 = cv2.inRange(hsv, (180 + h - t, lo_s, lo_v), (179, 255, 255))
            return cv2.bitwise_or(m1, m2)
        if h + t > 179:
            m1 = cv2.inRange(hsv, (h - t, lo_s, lo_v), (179, 255, 255))
            m2 = cv2.inRange(hsv, (0, lo_s, lo_v), (h + t - 180, 255, 255))
            return cv2.bitwise_or(m1, m2)
        return cv2.inRange(hsv, (h - t, lo_s, lo_v), (h + t, 255, 255))

    def _loop(self):
        cap = None
        kernel = np.ones((3, 3), np.uint8)
        while not self.stop:
            if cap is None or self.restart:
                if cap is not None:
                    cap.release()
                self.restart = False
                cap = self._open()
                self.opened = cap.isOpened()
                if not cap.isOpened():
                    self.status = f"Không mở được camera {self.index} (nhấn C để đổi)"
                    cap = None
                    time.sleep(1.0)
                    continue
                self.status = f"Camera {self.index}"
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.03)
                continue
            frame = cv2.flip(frame, 1)                         # lật gương: tay phải của bạn -> bên phải màn hình
            small = cv2.resize(frame, (self.FW, self.FH))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            mask = self._mask(hsv)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.dilate(mask, kernel, iterations=2)
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            found = None
            if cnts:
                c = max(cnts, key=cv2.contourArea)
                area = cv2.contourArea(c)
                if area >= 80:
                    m = cv2.moments(c)
                    if m["m00"] > 0:
                        tilt = None
                        mu20, mu02, mu11 = m["mu20"] / m["m00"], m["mu02"] / m["m00"], m["mu11"] / m["m00"]
                        common = math.sqrt(4 * mu11 * mu11 + (mu20 - mu02) ** 2)
                        l1, l2 = (mu20 + mu02 + common) / 2, (mu20 + mu02 - common) / 2
                        if l2 > 1e-6 and math.sqrt(l1 / l2) >= 1.3:      # đủ dài mới tin hướng
                            phi = 0.5 * math.atan2(2 * mu11, mu20 - mu02)  # góc trục dài (hệ ảnh, y xuống)
                            vx, vy = math.cos(phi), math.sin(phi)
                            if vy > 0:                                      # luôn lấy chiều hướng lên
                                vx, vy = -vx, -vy
                            tilt = math.atan2(vx, -vy)
                        found = (m["m10"] / m["m00"], m["m01"] / m["m00"], math.sqrt(area), c, tilt)
            vis = small.copy()
            if found:
                cv2.drawContours(vis, [found[3]], -1, (0, 255, 0), 2)
                cv2.circle(vis, (int(found[0]), int(found[1])), 5, (0, 255, 255), -1)
                if found[4] is not None:      # vẽ trục đầu vợt
                    L = found[2] * 0.9
                    p2 = (int(found[0] + math.sin(found[4]) * L), int(found[1] - math.cos(found[4]) * L))
                    cv2.line(vis, (int(found[0]), int(found[1])), p2, (255, 255, 0), 2)
            rgb = cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)
            with self.lock:
                self.hsv = hsv
                self.frame_bytes = rgb.tobytes()
                if found:
                    self.cx = found[0] / self.FW
                    self.cy = found[1] / self.FH
                    self.size = found[2] / self.FH
                    if found[4] is not None:
                        self.tilt = found[4]
                    self.last_seen = time.time()
        if cap is not None:
            cap.release()

    def get(self):
        with self.lock:
            vis = time.time() - self.last_seen < 0.35
            return vis, self.cx, self.cy, self.size, self.tilt

    def preview(self):
        with self.lock:
            return self.frame_bytes

    def pick_color(self, px, py):
        """Người chơi click vào khung camera -> lấy màu tại đó làm màu vợt."""
        with self.lock:
            hsv = self.hsv
            if hsv is None:
                return
            x, y = int(clamp(px, 3, self.FW - 4)), int(clamp(py, 3, self.FH - 4))
            patch = hsv[y - 2:y + 3, x - 2:x + 3].reshape(-1, 3)
            h, s, v = [int(np.median(patch[:, i])) for i in range(3)]
            if s < 50 or v < 50:
                self.status = "Màu quá nhạt/tối, chọn chỗ màu rực hơn"
                return
            self.hue = h
            self.smin = int(max(60, s * 0.55))
            self.vmin = int(max(60, v * 0.5))
            self.status = f"Đã chọn màu (hue {h})"


# ---------------- Luật + vật lý ----------------
class Game:
    def __init__(self, difficulty=2):
        self.difficulty = difficulty
        self.reset()

    def reset(self):
        self.score = {"P": 0, "A": 0}
        self.server = "P"
        self.over = False
        self.new_serve()

    def new_serve(self):
        self.state = "serve"            # serve: chờ người/AI giao bóng
        self.timer = 0.0
        self.msg = ""
        self.hitter = None
        self.recv = 0
        self.ai_done = False
        self.hit_cd = 0.0
        self.vx = self.vy = self.vz = 0.0
        if self.server == "P":
            self.x, self.y, self.z = 0.0, 0.35, -0.05
        else:
            self.x, self.y, self.z = 0.0, 0.30, TL + 0.1
            self.timer = 1.3
        self.ai_x = 0.0

    # --- tính vận tốc để bóng rơi đúng điểm (tx, tz) và qua lưới ---
    def launch(self, tx, tz, t_pref):
        T = t_pref
        vx = vy = vz = 0.0
        while T <= 1.5:
            vx = (tx - self.x) / T
            vz = (tz - self.z) / T
            vy = (0.0 - self.y) / T + 0.5 * G * T
            if abs(vz) < 1e-6:
                break
            tn = (ZN - self.z) / vz
            yn = self.y + vy * tn - 0.5 * G * tn * tn
            if yn > NET_H + 0.05:
                break
            T += 0.05
        self.vx, self.vy, self.vz = vx, vy, vz
        self.state = "rally"
        self.recv = 0
        self.ai_done = False
        self.hit_cd = 0.25

    def player_hit(self, xn, power):
        self.hitter = "P"
        err = random.gauss(0, 0.03 + 0.14 * power * power)
        tx = clamp(xn * 0.6 + err, -0.85, 0.85)
        tz = clamp(1.78 + 0.62 * power + random.gauss(0, 0.05 + 0.12 * power * power), 1.55, 2.62)
        self.launch(tx, tz, lerp(1.05, 0.55, power))

    def ai_return(self):
        self.hitter = "A"
        self.y = max(self.y, 0.12)
        tx = random.uniform(-0.62, 0.62)
        tz = random.uniform(0.22, 1.05)
        speed = {1: 1.0, 2: 0.85, 3: 0.68}[self.difficulty]
        self.launch(tx, tz, random.uniform(0.62, 0.95) * speed + 0.1)

    def ai_serve(self):
        self.hitter = "A"
        self.launch(random.uniform(-0.5, 0.5), random.uniform(0.3, 0.9), 0.9)

    def ai_miss_prob(self):
        base = {1: 0.28, 2: 0.14, 3: 0.05}[self.difficulty]
        return clamp(base * (0.6 + abs(self.vz) / 7.0), 0.0, 0.8)

    def win(self, who):
        self.score[who] += 1
        self.state = "pause"
        self.timer = 1.6
        self.msg = "Bạn ghi điểm!" if who == "P" else "Đối thủ ghi điểm"
        if max(self.score.values()) >= WIN_SCORE and abs(self.score["P"] - self.score["A"]) >= 2:
            self.over = True
            self.msg = "BẠN THẮNG! (R để chơi lại)" if self.score["P"] > self.score["A"] \
                else "BẠN THUA (R để chơi lại)"

    def fault(self, who, why=""):
        other = "A" if who == "P" else "P"
        self.win(other)
        if why:
            self.msg += " - " + why

    def paddle_touch(self, paddle, r, dz_max):
        dx, dy, dz = self.x - paddle[0], self.y - paddle[1], self.z - paddle[2]
        return math.hypot(dx, dy) < r and abs(dz) < dz_max

    def screen_pos(self):
        sx, sy, s = proj(self.x, self.y, self.z)
        return sx, sy, s

    def update(self, dt, paddle, xn, power, on_hit):
        """paddle = (x, y, z) vị trí vợt trong không gian (m)."""
        self.hit_cd -= dt
        if self.state == "pause":
            self.timer -= dt
            if self.timer <= 0 and not self.over:
                self.server = "P" if (self.score["P"] + self.score["A"]) % 2 == 0 else "A"
                self.new_serve()
            return

        if self.state == "serve":
            if self.server == "A":
                self.timer -= dt
                if self.timer <= 0:
                    self.ai_serve()
            else:
                if self.paddle_touch(paddle, 0.22, 0.45) and power > 0.3:
                    self.player_hit(xn, max(power, 0.35))
                    on_hit()
            return

        # ---- rally ----
        old_z = self.z
        self.vy -= G * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        # lưới
        if (old_z - ZN) * (self.z - ZN) < 0 and 0 < self.y < NET_H and abs(self.x) < TW / 2 + 0.15:
            self.fault(self.hitter, "chạm lưới")
            return

        # chạm bàn / sàn
        if self.y <= 0 and self.vy < 0:
            on_table = abs(self.x) <= TW / 2 and 0 <= self.z <= TL
            if on_table:
                side = "P" if self.z < ZN else "A"
                self.y = 0.0
                self.vy = -self.vy * 0.88
                if side == self.hitter:
                    self.fault(self.hitter, "bóng nảy bên mình")
                else:
                    self.recv += 1
                    if self.recv >= 2:
                        self.win(self.hitter)
            else:
                if self.recv >= 1:
                    self.win(self.hitter)
                else:
                    self.fault(self.hitter, "bóng ra ngoài")
            return

        if self.z < -1.7 or self.z > TL + 2.5 or abs(self.x) > 3:
            if self.recv >= 1:
                self.win(self.hitter)
            else:
                self.fault(self.hitter, "bóng ra ngoài")
            return

        # AI đỡ bóng
        if self.hitter == "P" and not self.ai_done and self.recv >= 1 and self.vz > 0 and self.z >= TL + 0.1:
            self.ai_done = True
            if random.random() > self.ai_miss_prob():
                self.ai_return()
                on_hit(ai=True)
            return

        # Người chơi đỡ bóng
        if self.hitter == "A" and self.recv >= 1 and self.vz < 0 and self.hit_cd <= 0:
            if self.paddle_touch(paddle, HIT_R, 0.24):
                self.player_hit(xn, max(power, 0.15))
                on_hit()


# ---------------- Giao diện pygame ----------------
def main():
    import pygame

    pygame.init()
    try:
        pygame.mixer.init(44100, -16, 1, 512)
        mixer_ok = True
    except pygame.error:
        mixer_ok = False

    def make_beep(freq, ms=70):
        if not mixer_ok:
            return None
        n = int(44100 * ms / 1000)
        buf = bytearray()
        for i in range(n):
            v = int(9000 * math.sin(2 * math.pi * freq * i / 44100) * (1 - i / n))
            buf += v.to_bytes(2, "little", signed=True)
        return pygame.mixer.Sound(buffer=bytes(buf))

    beep_hit, beep_ai, beep_bounce = make_beep(900), make_beep(600), make_beep(300, 40)

    screen = pygame.display.set_mode((W, H), pygame.RESIZABLE | pygame.SCALED)
    pygame.display.set_caption("Bóng bàn - camera theo dõi vợt")
    clock = pygame.time.Clock()
    fn = lambda sz, b=False: pygame.font.SysFont("segoeui,arial,dejavusans", sz, bold=b)
    f_big, f_mid, f_small = fn(64, True), fn(30, True), fn(20)

    cam = CameraTracker(0)
    game = Game(2)

    filt = {'ang': OneEuro(mincut=1.0, beta=0.5)}
    filt.update({k: OneEuro(mincut=2.0, beta=2.0) for k in ('cx', 'cy', 'cs')})
    cam_ref = None
    want_cal = False
    prev_cam = None      # (cx, cy, fwd) của khung hình trước -> tính tốc độ vung
    swing = 0.0          # lực vung 0..1 (giữ đỉnh ngắn để kịp tính khi chạm bóng)
    mouse_mode = False
    show_prev = True
    PREV = pygame.Rect(W - 336, 8, 320, 240)
    pw = [PAD_X0, PAD_Y0W, PAD_Z0]   # vị trí vợt trong không gian 3D (m)
    mouse_prev = pygame.mouse.get_pos()
    mouse_power = 0.0
    click_power = 0.0
    flash = 0.0
    prev_bounce_recv = 0
    ang_s = 0.0
    move_scale = 1.0
    assist = 0.3         # hút nhẹ vợt về phía bóng khi bóng tới (0 = tắt)
    mouse_depth = 0.0

    def on_hit(ai=False):
        nonlocal flash
        if ai:
            if beep_ai:
                beep_ai.play()
        else:
            flash = 0.2
            if beep_hit:
                beep_hit.play()

    def draw_table():
        pts = [proj(-TW / 2, 0, 0), proj(TW / 2, 0, 0), proj(TW / 2, 0, TL), proj(-TW / 2, 0, TL)]
        poly = [(p[0], p[1]) for p in pts]
        # chân bàn
        for (x, z) in [(-TW / 2 + 0.05, 0.05), (TW / 2 - 0.05, 0.05), (-TW / 2 + 0.05, TL - 0.05), (TW / 2 - 0.05, TL - 0.05)]:
            a = proj(x, 0, z)
            b = proj(x, -0.76, z)
            pygame.draw.line(screen, (30, 30, 36), (a[0], a[1]), (b[0], b[1]), max(3, int(a[2] * 0.04)))
        pygame.draw.polygon(screen, (24, 90, 170), poly)
        pygame.draw.polygon(screen, (235, 235, 235), poly, 4)
        a, b = proj(0, 0, 0), proj(0, 0, TL)
        pygame.draw.line(screen, (235, 235, 235), (a[0], a[1]), (b[0], b[1]), 2)
        # dày bàn
        l0, r0 = proj(-TW / 2, 0, 0), proj(TW / 2, 0, 0)
        l1, r1 = proj(-TW / 2, -0.04, 0), proj(TW / 2, -0.04, 0)
        pygame.draw.polygon(screen, (14, 55, 110), [(l0[0], l0[1]), (r0[0], r0[1]), (r1[0], r1[1]), (l1[0], l1[1])])

    def draw_net():
        l0, r0 = proj(-TW / 2 - 0.15, 0, ZN), proj(TW / 2 + 0.15, 0, ZN)
        l1, r1 = proj(-TW / 2 - 0.15, NET_H, ZN), proj(TW / 2 + 0.15, NET_H, ZN)
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.polygon(surf, (230, 230, 230, 150), [(l0[0], l0[1]), (r0[0], r0[1]), (r1[0], r1[1]), (l1[0], l1[1])])
        screen.blit(surf, (0, 0))
        pygame.draw.line(screen, (255, 255, 255), (l1[0], l1[1]), (r1[0], r1[1]), 3)

    def draw_ball():
        if game.z + CAM_Z < 0.4:
            return
        sx, sy, s = proj(game.x, game.y, game.z)
        shx, shy, _ = proj(game.x, 0, game.z)
        r = max(4, int(0.045 * s))
        if game.y > 0.01:
            pygame.draw.ellipse(screen, (10, 40, 90), (shx - r, shy - r // 3, 2 * r, max(2, 2 * r // 3)))
        pygame.draw.circle(screen, (255, 140, 20), (int(sx), int(sy)), r)
        pygame.draw.circle(screen, (255, 210, 150), (int(sx - r * 0.3), int(sy - r * 0.3)), max(1, r // 4))

    def draw_ai():
        target = game.x if game.hitter == "P" and game.state == "rally" else 0.0
        game.ai_x += (clamp(target, -0.7, 0.7) - game.ai_x) * 0.08
        sx, sy, s = proj(game.ai_x, 0.22, TL + 0.2)
        r = int(0.085 * s)
        pygame.draw.rect(screen, (120, 80, 40), (sx - 3, sy, 6, int(0.1 * s)))
        pygame.draw.circle(screen, (200, 40, 40), (int(sx), int(sy)), r)
        pygame.draw.circle(screen, (20, 20, 20), (int(sx), int(sy)), r, 2)

    def draw_paddle(x, y, ang, roll, scale=1.0):
        """Vẽ vợt thật: xoay theo cổ tay (ang) và lật mặt đỏ/đen theo roll."""
        S = 380
        c = S // 2
        surf = pygame.Surface((S, S), pygame.SRCALPHA)
        k = math.cos(roll)
        front = k >= 0
        w = max(abs(k), 0.10) * 70
        h = 78
        # tay cầm
        pygame.draw.rect(surf, (175, 125, 65), (c - 11, c + h - 14, 22, 112), border_radius=8)
        pygame.draw.rect(surf, (110, 72, 36), (c - 11, c + h - 14, 22, 112), 2, border_radius=8)
        # viền gỗ + mặt vợt
        pygame.draw.ellipse(surf, (205, 165, 105), (c - w - 6, c - h - 6, 2 * w + 12, 2 * h + 12))
        if flash > 0:
            face = (255, 255, 255)
        elif abs(k) < 0.18:
            face = (205, 165, 105)
        else:
            face = (205, 35, 35) if front else (25, 25, 25)
        pygame.draw.ellipse(surf, face, (c - w, c - h, 2 * w, 2 * h))
        pygame.draw.ellipse(surf, (240, 240, 240), (c - w, c - h, 2 * w, 2 * h), 2)
        if abs(k) > 0.4:
            pygame.draw.circle(surf, (245, 245, 245) if front else (200, 200, 200), (c, c), int(14 * abs(k)), 2)
        if abs(scale - 1.0) > 0.02:
            surf = pygame.transform.smoothscale(surf, (int(S * scale), int(S * scale)))
        rot = pygame.transform.rotate(surf, -math.degrees(ang))
        screen.blit(rot, rot.get_rect(center=(int(x), int(y))))
        
    def draw_paddle_shadow(wx, wy, wz):
        sx, sy, s = proj(wx, wy, wz)
        gx, gy, _ = proj(wx, 0.0, wz)
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.line(surf, (255, 255, 255, 70), (sx, sy), (gx, gy), 1)
        rw, rh = int(0.16 * s), max(3, int(0.05 * s))
        pygame.draw.ellipse(surf, (0, 0, 0, 110), (gx - rw, gy - rh, 2 * rw, 2 * rh))
        screen.blit(surf, (0, 0))

    running = True
    last = time.time()
    while running:
        now = time.time()
        dt = min(now - last, 0.05)
        last = now
        click_power = max(0.0, click_power - dt * 4)

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                k = e.key
                if k == pygame.K_ESCAPE:
                    running = False
                elif k == pygame.K_SPACE:
                    for f in filt.values():
                        f.reset()
                    want_cal = True
                elif k == pygame.K_r:
                    game.reset()
                elif k == pygame.K_m:
                    mouse_mode = not mouse_mode
                elif k == pygame.K_h:
                    assist = {0.0: 0.3, 0.3: 0.6, 0.6: 0.0}.get(assist, 0.3)
                elif k == pygame.K_v:
                    show_prev = not show_prev
                elif k == pygame.K_c:
                    cam.index = (cam.index + 1) % 3
                    cam.restart = True
                elif k == pygame.K_COMMA:
                    move_scale = max(0.4, move_scale - 0.15)
                elif k == pygame.K_PERIOD:
                    move_scale = min(3.0, move_scale + 0.15)
                elif k in (pygame.K_1, pygame.K_2, pygame.K_3):
                    game.difficulty = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3}[k]
            elif e.type == pygame.MOUSEWHEEL:
                mouse_depth = clamp(mouse_depth + 0.06 * e.y, -0.1, 0.45)
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if show_prev and cam.available and not mouse_mode and PREV.collidepoint(e.pos):
                    cam.pick_color(e.pos[0] - PREV.x, e.pos[1] - PREV.y)
                else:
                    click_power = 1.0

        # ================= ĐỌC VỢT (chỉ camera) =================
        cam_vis, ccx, ccy, csz, ctilt = cam.get() if cam.available else (False, 0.0, 0.0, 0.0, 0.0)
        cam_ok = cam.available and cam.opened and not mouse_mode
        ang = 0.0
        power = 0.0
        twx, twy, twz = pw

        if cam_ok and cam_vis:
            pos_src = "camera"
            fcx, fcy, fcs = filt['cx'](ccx, dt), filt['cy'](ccy, dt), filt['cs'](csz, dt)
            ang = clamp(filt['ang'](ctilt, dt), -1.2, 1.2)
            if cam_ref is None or want_cal:
                cam_ref = (fcx, fcy, fcs)
                want_cal = False
                prev_cam = None
            fwd = clamp(CAM_D0 * (1.0 - cam_ref[2] / max(fcs, 1e-3)), -0.35, 0.6)
            twx = PAD_X0 + (fcx - cam_ref[0]) * CAM_GX * move_scale
            twy = PAD_Y0W + (cam_ref[1] - fcy) * CAM_GY * move_scale
            twz = PAD_Z0 + fwd * CAM_GZ * move_scale
            # lực vung = tốc độ tay (m/s ước lượng) theo mọi hướng
            if prev_cam is not None:
                vx = (fcx - prev_cam[0]) * CAM_VIEW_W / max(dt, 1e-3)
                vy = (fcy - prev_cam[1]) * CAM_VIEW_H / max(dt, 1e-3)
                vz = (fwd - prev_cam[2]) / max(dt, 1e-3)
                level = clamp((math.hypot(vx, vy, vz) - 0.35) / 1.5, 0.0, 1.0)
                swing = max(level, swing - dt * 4.0)
            prev_cam = (fcx, fcy, fwd)
            power = swing
        elif cam_ok:
            # camera đang mở nhưng không thấy vợt (mờ do vung nhanh / quay lưng): giữ nguyên vị trí
            pos_src = "camera (mất dấu - giữ vị trí)"
            prev_cam = None
            ang = ang_s
            swing = max(0.0, swing - dt * 4.0)
            power = swing
        else:
            pos_src = "chuột"
            prev_cam = None
            mx, my = pygame.mouse.get_pos()
            speed = math.hypot(mx - mouse_prev[0], my - mouse_prev[1]) / max(dt, 1e-3)
            mouse_prev = (mx, my)
            mouse_power = max(mouse_power * (1 - dt * 6), clamp(speed / 2500.0, 0, 1))
            power = max(mouse_power, click_power)
            twx = (mx - W / 2) / (W * 0.35) * 0.75
            twy = 0.30 + (PADDLE_Y0 - clamp(my, 330, 700)) / 180.0 * 0.3
            twz = PAD_Z0 + mouse_depth * 3.2
            ang = clamp(twx * 0.5, -0.8, 0.8)
        twx, twy, twz = clamp(twx, -1.0, 1.0), clamp(twy, 0.05, 0.9), clamp(twz, -0.7, 1.4)

        k_s = 1.0 - math.exp(-dt * 25.0)
        pw[0] += (twx - pw[0]) * k_s
        pw[1] += (twy - pw[1]) * k_s
        pw[2] += (twz - pw[2]) * k_s
        ang_s += (ang - ang_s) * 0.5

        # hút nhẹ vợt về phía bóng đang tới
        if assist > 0 and game.state == "rally" and game.hitter == "A" and game.recv >= 1 and game.vz < 0 and game.z < 1.3:
            pull = clamp(assist * dt * 6.0 * clamp((1.3 - game.z) / 1.3, 0.0, 1.0), 0.0, 0.5)
            pw[0] += (game.x - pw[0]) * pull
            pw[1] += (clamp(game.y, 0.05, 0.9) - pw[1]) * pull
            pw[2] += (game.z - pw[2]) * pull * 0.6
        elif assist > 0 and game.state == "serve" and game.server == "P":
            pull = clamp(assist * dt * 2.0, 0.0, 0.3)
            pw[0] += (game.x - pw[0]) * pull
            pw[1] += (game.y - pw[1]) * pull

        xn_shot = clamp(pw[0] / 0.6, -1.4, 1.4)

        flash = max(0.0, flash - dt)
        if not game.over or game.state != "pause":
            game.update(dt, tuple(pw), xn_shot, power, on_hit)
        total_recv = game.recv
        if total_recv != prev_bounce_recv and beep_bounce:
            beep_bounce.play()
        prev_bounce_recv = total_recv

        # ================= VẼ =================
        screen.fill((24, 26, 34))
        pygame.draw.rect(screen, (40, 44, 56), (0, HY, W, H - HY))
        draw_table()
        draw_ai()
        draw_paddle_shadow(*pw)
        psx, psy, ps = proj(*pw)
        items = [("net", ZN), ("ball", game.z), ("paddle", pw[2])]
        items.sort(key=lambda t: -t[1])
        for name, _z in items:
            if name == "net":
                draw_net()
            elif name == "ball":
                draw_ball()
            else:
                draw_paddle(psx, psy, ang_s, 0.0, PADDLE_R_WORLD * ps / 70.0)

        t = f_big.render(f"{game.score['P']} : {game.score['A']}", True, (255, 255, 255))
        screen.blit(t, (W // 2 - t.get_width() // 2, 14))
        screen.blit(f_small.render("BẠN", True, (160, 200, 255)), (W // 2 - 120, 36))
        screen.blit(f_small.render("MÁY", True, (255, 170, 170)), (W // 2 + 82, 36))
        if not cam.available:
            ct, cc = "Camera: chưa cài opencv-python (pip install opencv-python) - đang chơi bằng chuột", (255, 150, 120)
        elif mouse_mode:
            ct, cc = "Đang chơi bằng CHUỘT (nhấn M để quay lại camera)", (255, 210, 100)
        elif not cam.opened:
            ct, cc = f"Camera: {cam.status}", (255, 150, 120)
        elif cam_vis:
            ct, cc = f"Camera: THẤY VỢT ({cam.status})", (120, 255, 140)
        else:
            ct, cc = f"Camera: không thấy vợt - bật màn hình hồng trong app rồi hướng về camera, hoặc click chọn màu ({cam.status})", (255, 210, 100)
        screen.blit(f_small.render(ct, True, cc), (16, 12))
        info = (f"Vị trí: {pos_src} | độ khó {game.difficulty} | di chuyển x{move_scale:.2f} | "
                f"lực {int(power*100)}% | hút bóng {int(assist*100)}% | tiến {int((pw[2]-PAD_Z0)*100):+d}cm")
        screen.blit(f_small.render(info, True, (170, 170, 180)), (16, 38))
        if game.state == "serve" and game.server == "P":
            h = f_mid.render("Giao bóng: đưa vợt tới quả bóng rồi vung mạnh", True, (255, 255, 255))
            screen.blit(h, (W // 2 - h.get_width() // 2, 110))
        if game.msg:
            m = f_mid.render(game.msg, True, (255, 240, 120))
            screen.blit(m, (W // 2 - m.get_width() // 2, 150))
        if show_prev and cam.available and not mouse_mode:
            pb = cam.preview()
            if pb:
                screen.blit(pygame.image.frombuffer(pb, (cam.FW, cam.FH), "RGB"), PREV.topleft)
            pygame.draw.rect(screen, (255, 255, 255), PREV, 2)
            screen.blit(f_small.render("click vào vợt để chọn màu", True, (255, 255, 255)), (PREV.x + 6, PREV.bottom - 24))
        screen.blit(f_small.render("SPACE căn chỉnh | R chơi lại | C đổi camera | V khung camera | , . di chuyển | H hút bóng | M chuột/camera | 1-3 độ khó",
                                   True, (130, 130, 145)), (16, H - 28))
        pygame.display.flip()
        clock.tick(60)

    cam.stop = True
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
