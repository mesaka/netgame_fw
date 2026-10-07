"""テスト・スクリーンショット用の、いちばん小さなアダプター(盤面は文字だけ)。"""
import pygame

from netgame.adapter import RealtimeAdapter


class DemoAdapter(RealtimeAdapter):
    game_id = "demo"

    def __init__(self, size=(480, 800)):
        self.size = size
        self.saved_name = ""
        self.frames = 0
        self.controls_log = []
        self.matches = []
        self.resets = 0
        self.keys = 0
        self.sounds = []
        self.bgms = []
        self.over = False
        self.global_hits = 0

    def settings(self):
        return {"diff": "normal"}

    def settings_label(self):
        return "むずかしさ: ふつう"

    def load_name(self):
        return self.saved_name

    def save_name(self, name):
        self.saved_name = name

    def start_match(self, sess):
        self.matches.append((sess.seed, sess.seat, [p["name"] for p in sess.players]))
        self.frames = 0
        self.over = False

    def reset_input(self):
        self.resets += 1

    def handle(self, ev):
        if ev.type == pygame.KEYDOWN:
            self.keys += 1

    def update(self, sess, controls):
        self.frames += 1
        self.controls_log.append(controls)

    def local_over(self):
        return self.over

    def draw(self, sess, screen, view, frame):
        screen.fill((20, 20, 40))
        f = pygame.font.Font(None, 40)
        screen.blit(f.render("frames %d" % self.frames, True, (255, 255, 255)), (40 + (screen.get_width() - 480) // 2, 60))
        if view.banner:
            big, color, small = view.banner
            screen.blit(f.render(big, True, color), (60 + (screen.get_width() - 480) // 2, 300))

    def handle_global(self, ev, phase):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_m:
            self.global_hits += 1
            return True
        return False

    def sound(self, name):
        self.sounds.append(name)

    def bgm(self, name):
        self.bgms.append(name)
