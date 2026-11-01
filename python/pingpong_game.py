"""
BÓNG BÀN - ĐIỆN THOẠI LÀ VỢT
Chạy trên laptop (Windows). Điện thoại iPhone gắn trên vợt gửi cảm biến qua WiFi (UDP cổng 5005).
Không có điện thoại vẫn chơi được bằng chuột (click = đập mạnh).

Phím:  SPACE = căn chỉnh (giữ vợt tư thế sẵn sàng)   R = chơi lại
       [ / ] = giảm/tăng độ nhạy     I = đảo trái-phải    O = đảo lên-xuống
       T = đổi trục (nếu gắn máy xoay ngang)   1/2/3 = độ khó   ESC = thoát
"""
import math
import random
import socket
import sys
import threading
import time
from collections import deque

PORT = 5005
W, H = 1280, 720
G = 9.8
TL, TW = 2.74, 1.525          # chiều dài / rộng bàn (m)
NET_H = 0.1525
ZN = TL / 2
CAM_Z, CAM_H, FOCAL, HY = 1.9, 0.9, 760.0, 240
PADDLE_R = 95                 # bán kính vùng chạm vợt (pixel)
PADDLE_Y0 = 518               # vị trí y mặc định của vợt trên màn hình
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


# ---------------- Quaternion ----------------
def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def qconj(q):
    return (q[0], -q[1], -q[2], -q[3])


def qrot(q, v):
    r = qmul(qmul(q, (0.0,) + tuple(v)), qconj(q))
    return r[1], r[2], r[3]


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


# ---------------- Nhận dữ liệu từ điện thoại ----------------
class Sensor:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", PORT))
        self.sock.settimeout(0.5)
        self.lock = threading.Lock()
        self.q = (1.0, 0.0, 0.0, 0.0)
        self.q0 = (1.0, 0.0, 0.0, 0.0)
        self.acc = deque()
        self.last = 0.0
        self.addr = None
        self.packets = 0
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                x, y, z, w, ax, ay, az = map(float, data.decode().strip().split(","))
            except ValueError:
                continue
            n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
            now = time.time()
            with self.lock:
                self.q = (w / n, x / n, y / n, z / n)
                self.addr = addr
                self.last = now
                self.packets += 1
                self.acc.append((now, math.sqrt(ax * ax + ay * ay + az * az)))
                while self.acc and now - self.acc[0][0] > 0.2:
                    self.acc.popleft()

    @property
    def connected(self):
        return time.time() - self.last < 1.0

    def calibrate(self):
        with self.lock:
            self.q0 = self.q

    def aim(self):
        """Hướng 'đỉnh điện thoại' (trục Y máy) so với lúc căn chỉnh, tính trong hệ máy lúc đó."""
        with self.lock:
            d = qmul(qconj(self.q0), self.q)
        return qrot(d, (0.0, 1.0, 0.0))

    def peak(self, window=0.12):
        now = time.time()
        with self.lock:
            vals = [m for t, m in self.acc if now - t <= window]
        return max(vals) if vals else 0.0

    def haptic(self):
        with self.lock:
            addr = self.addr
        if addr:
            try:
                self.sock.sendto(b"H", addr)
            except OSError:
                pass


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
            self.x, self.y, self.z = 0.0, 0.35, 0.15
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

    def screen_pos(self):
        sx, sy, s = proj(self.x, self.y, self.z)
        return sx, sy, s

    def update(self, dt, paddle_xy, xn, power, swing_click, on_hit):
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
                sx, sy, _ = self.screen_pos()
                if math.hypot(sx - paddle_xy[0], sy - paddle_xy[1]) < PADDLE_R and power > 0.3:
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
        if self.hitter == "A" and self.recv >= 1 and self.vz < 0 and -1.3 < self.z < 0.5 and self.hit_cd <= 0:
            sx, sy, _ = self.screen_pos()
            if math.hypot(sx - paddle_xy[0], sy - paddle_xy[1]) < PADDLE_R:
                p = max(power, 0.15)
                self.player_hit(xn, p)
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
    pygame.display.set_caption("Bóng bàn - điện thoại là vợt")
    clock = pygame.time.Clock()
    fn = lambda sz, b=False: pygame.font.SysFont("segoeui,arial,dejavusans", sz, bold=b)
    f_big, f_mid, f_small = fn(64, True), fn(30, True), fn(20)

    sensor = Sensor()
    ip = local_ip()
    game = Game(2)

    gain, inv_x, inv_y, swap = 3.0, 1.0, 1.0, False
    px = py = None
    mouse_prev = pygame.mouse.get_pos()
    mouse_power = 0.0
    click_power = 0.0
    flash = 0.0
    prev_bounce_recv = 0

    def on_hit(ai=False):
        nonlocal flash
        if ai:
            if beep_ai:
                beep_ai.play()
        else:
            flash = 0.2
            if beep_hit:
                beep_hit.play()
            sensor.haptic()

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

    def draw_paddle(x, y):
        pygame.draw.rect(screen, (150, 100, 50), (x - 8, y + 40, 16, 90), border_radius=4)
        col = (255, 255, 255) if flash > 0 else (210, 35, 35)
        pygame.draw.circle(screen, col, (int(x), int(y)), 70)
        pygame.draw.circle(screen, (15, 15, 15), (int(x), int(y)), 70, 4)
        pygame.draw.circle(screen, (255, 255, 255), (int(x), int(y)), PADDLE_R, 1)

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
                    sensor.calibrate()
                elif k == pygame.K_r:
                    game.reset()
                elif k == pygame.K_i:
                    inv_x = -inv_x
                elif k == pygame.K_o:
                    inv_y = -inv_y
                elif k == pygame.K_t:
                    swap = not swap
                elif k == pygame.K_LEFTBRACKET:
                    gain = max(0.8, gain - 0.3)
                elif k == pygame.K_RIGHTBRACKET:
                    gain = min(8.0, gain + 0.3)
                elif k in (pygame.K_1, pygame.K_2, pygame.K_3):
                    game.difficulty = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3}[k]
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                click_power = 1.0

        # ---- đọc vợt ----
        use_sensor = sensor.connected
        if use_sensor:
            ax, ay, az = sensor.aim()
            a, b = (az, ax) if swap else (ax, az)
            xn = clamp(a * gain * inv_x, -1.3, 1.3)
            yn = clamp(-b * gain * inv_y, -1.3, 1.3)
            tx, ty = W / 2 + xn * W * 0.35, PADDLE_Y0 - yn * 180
            peak = sensor.peak()
            power = clamp((peak - 0.6) / 2.5, 0.0, 1.0)
        else:
            mx, my = pygame.mouse.get_pos()
            speed = math.hypot(mx - mouse_prev[0], my - mouse_prev[1]) / max(dt, 1e-3)
            mouse_prev = (mx, my)
            mouse_power = max(mouse_power * (1 - dt * 6), clamp(speed / 2500.0, 0, 1))
            power = max(mouse_power, click_power)
            tx, ty = mx, clamp(my, 330, 700)
            xn = clamp((mx - W / 2) / (W * 0.35), -1.3, 1.3)
        if px is None:
            px, py = tx, ty
        px += (tx - px) * 0.45
        py += (ty - py) * 0.45

        flash = max(0.0, flash - dt)
        if not game.over or game.state != "pause":
            game.update(dt, (px, py), xn, power, click_power > 0, on_hit)
        # tiếng nảy
        total_recv = game.recv
        if total_recv != prev_bounce_recv and beep_bounce:
            beep_bounce.play()
        prev_bounce_recv = total_recv

        # ---- vẽ ----
        screen.fill((24, 26, 34))
        pygame.draw.rect(screen, (40, 44, 56), (0, HY, W, H - HY))
        draw_table()
        draw_ai()
        if game.z < ZN:
            draw_net()
            draw_ball()
        else:
            draw_ball()
            draw_net()
        draw_paddle(px, py)

        t = f_big.render(f"{game.score['P']} : {game.score['A']}", True, (255, 255, 255))
        screen.blit(t, (W // 2 - t.get_width() // 2, 14))
        screen.blit(f_small.render("BẠN", True, (160, 200, 255)), (W // 2 - 120, 36))
        screen.blit(f_small.render("MÁY", True, (255, 170, 170)), (W // 2 + 82, 36))
        if use_sensor:
            st = f"Điện thoại: ĐÃ KẾT NỐI  ({sensor.packets} gói)"
            col = (120, 255, 140)
        else:
            st = f"Chưa có điện thoại - chơi bằng chuột.   Nhập IP này vào app:  {ip}"
            col = (255, 210, 100)
        screen.blit(f_small.render(st, True, col), (16, 12))
        screen.blit(f_small.render(f"Độ khó {game.difficulty}  |  độ nhạy {gain:.1f}  |  Lực: {int(power*100)}%", True, (170, 170, 180)), (16, 40))
        hint = "Giao bóng: đưa vợt vào bóng rồi vung mạnh" if game.state == "serve" and game.server == "P" else ""
        if hint:
            h = f_mid.render(hint, True, (255, 255, 255))
            screen.blit(h, (W // 2 - h.get_width() // 2, 110))
        if game.msg:
            m = f_mid.render(game.msg, True, (255, 240, 120))
            screen.blit(m, (W // 2 - m.get_width() // 2, 150))
        screen.blit(f_small.render("SPACE căn chỉnh | R chơi lại | [ ] độ nhạy | I/O đảo trục | T đổi trục | 1-3 độ khó",
                                   True, (130, 130, 145)), (16, H - 28))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
