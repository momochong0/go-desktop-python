"""
围棋小课堂 - Python版 (Tkinter版)
面向围棋初学者的桌面教学应用
"""
import tkinter as tk
from tkinter import font as tkfont
import threading
import queue
import random
import json
import os
import tempfile
import winsound
import subprocess

# ============================================================
# 语音系统（参考 HTML 版的 voiceQueue 设计，顺序播放无间断）
#
# 架构：
#   speak(text) --> 入队 voice_queue
#   process_queue() --> 取队首，后台生成 WAV，主线程 winsound.PlaySound() 播放
#   _play_wav() 播完 --> finish_current() --> 处理 callback + pending_ai_move --> 继续队列
#
# winsound.PlaySound(SND_FILENAME) 是同步的（阻塞直到播完），
# 因此自然形成顺序播放，消除间断。
# ============================================================
class VoiceSystem:

    def __init__(self, root=None):
        self.root = root
        self.muted = False
        self.speed = 150
        self._engine = None
        self._engine_ready = False   # 引擎是否已完成初始化
        self.temp_dir = tempfile.mkdtemp(prefix='go_voice_')
        self._wav_counter = 0

        self.voice_queue = []
        self.voice_playing = False
        self.pending_ai_move = None
        self._engine_lock = threading.Lock()

    def _get_engine(self):
        """在调用线程内懒初始化引擎（必须在同一线程调用 save_to_file）"""
        if self._engine is not None:
            return self._engine
        if not self._engine_ready:
            with self._engine_lock:
                # 双重检查
                if self._engine is None:
                    try:
                        import pyttsx3
                        eng = pyttsx3.init()
                        voices = eng.getProperty('voices')
                        for v in voices:
                            if 'chinese' in v.name.lower() or 'zh' in v.name.lower():
                                eng.setProperty('voice', v.id)
                                break
                        eng.setProperty('rate', self.speed)
                        self._engine = eng
                        self._engine_ready = True
                        print("[TTS] 引擎在后台线程内初始化成功", flush=True)
                    except Exception as e:
                        print(f"[TTS] 引擎初始化失败: {e}", flush=True)
                        self._engine_ready = True  # 防止重复尝试
        return self._engine

    def warmup(self):
        """预热引擎：在后台线程提前创建好，用户点击时引擎已就绪"""
        def _do_warmup():
            self._get_engine()
        threading.Thread(target=_do_warmup, daemon=True).start()

    def init_engine(self):
        """兼容旧调用：触发后台线程预热引擎"""
        self.warmup()

    def set_speed(self, rate):
        """设置语速 0.7-1.2 -> 100-200"""
        self.speed = int(100 + (rate - 0.7) * 500)

    def speak(self, text, priority=False, callback=None, turn='player'):
        """
        priority=True : 打断当前播放，清空队列，立即播这条（最高优先）
        priority=False: 排队，等当前播完再播（默认，参考 HTML 版的 speak）
        """
        print(f"[TTS] speak() 调用: {repr(text[:50]) if text else None}..., priority={priority}", flush=True)
        if not text or self.muted:
            if callback:
                try: callback()
                except: pass
            return
        clean = self._clean_text(text)
        if not clean:
            if callback:
                try: callback()
                except: pass
            return

        if priority and self.voice_playing:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
            self.voice_queue = []
            self.voice_playing = False
            print("[TTS] 打断当前播放，清空队列", flush=True)

        self.voice_queue.append({'text': clean, 'callback': callback, 'turn': turn})
        self.process_queue()

    def process_queue(self):
        """
        从队列取一条，后台线程生成 WAV，主线程播放。
        播完后自动触发 finish_current() 继续下一条。
        """
        if self.voice_playing or not self.voice_queue:
            return

        item = self.voice_queue.pop(0)
        self.voice_playing = True

        self._wav_counter += 1
        wav_path = os.path.join(self.temp_dir, f"speech_{self._wav_counter}.wav")
        print(f"[TTS] 开始处理队列项: {repr(item['text'][:30])}...", flush=True)

        def do_generate():
            """后台线程：生成 WAV 文件（引擎在本线程内懒创建）"""
            engine = self._get_engine()
            if not engine:
                print("[TTS] 引擎不可用，跳过本条", flush=True)
                self.finish_current(item, skip_play=True)
                return
            try:
                engine.save_to_file(item['text'], wav_path)
                engine.runAndWait()
                if not os.path.exists(wav_path):
                    print(f"[TTS] WAV 文件未生成: {wav_path}", flush=True)
                    self.finish_current(item, skip_play=True)
                    return
                size = os.path.getsize(wav_path)
                print(f"[TTS] WAV 生成完成: size={size}", flush=True)
                if self.root:
                    self.root.after(0, lambda: self._play_wav(wav_path, item))
                else:
                    self._play_wav(wav_path, item)
            except Exception as e:
                print(f"[TTS] WAV 生成失败: {e}", flush=True)
                self.finish_current(item, skip_play=True)

        threading.Thread(target=do_generate, daemon=True).start()

    def _play_wav(self, wav_path, item):
        """主线程：播放 WAV，失败后降级到 powershell TTS"""
        try:
            if not os.path.exists(wav_path):
                print(f"[TTS][WAV] 文件不存在，降级 TTS: {wav_path}", flush=True)
                self._fallback_speak(item['text'])
                return
            fsize = os.path.getsize(wav_path)
            print(f"[TTS][WAV] 播放 size={fsize}, path={wav_path}", flush=True)
            if fsize < 44:
                print("[TTS][WAV] 文件过小，降级 TTS", flush=True)
                self._fallback_speak(item['text'])
                return
            winsound.PlaySound(wav_path, winsound.SND_FILENAME)
            print(f"[TTS][WAV] 播放完成: {item['text'][:30]}", flush=True)
        except Exception as e:
            print(f"[TTS][WAV] 播放失败={e}，降级 TTS", flush=True)
            self._fallback_speak(item['text'])
        finally:
            try:
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception:
                pass
            self.finish_current(item, skip_play=True)

    def _fallback_speak(self, text):
        """降级：用 powershell 播报（不依赖 pyttsx3 WAV）"""
        try:
            safe = text.replace('"', "'").replace('\n', ' ')
            ps = f'Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate=1; $s.Speak("{safe}")'
            subprocess.run(['powershell', '-NonInteractive', '-Command', ps],
                          capture_output=True, timeout=10)
            print(f"[TTS][FALLBACK] powershell 播报完成: {text[:30]}", flush=True)
        except Exception as e:
            print(f"[TTS][FALLBACK] 也失败了: {e}", flush=True)

    def finish_current(self, item, skip_play=False):
        """
        播完一条语音后（参考 HTML 版的 finishCurrentSpeech）：
          1. 执行 item['callback']（如 AI 落子回调）
          2. 如果有 pending_ai_move → 执行它（AI 等玩家语音播完再落子）
          3. 否则继续 process_queue() 播放下一条
        """
        self.voice_playing = False
        if item['callback']:
            try:
                item['callback']()
            except Exception as e:
                print(f"[TTS] callback 执行失败: {e}", flush=True)

        # 参考 HTML 版的 finishCurrentSpeech：优先处理 pending_ai_move
        if self.pending_ai_move:
            cb = self.pending_ai_move
            self.pending_ai_move = None
            print("[TTS] 执行 pending_ai_move（AI等玩家语音播完）", flush=True)
            cb()
        else:
            print("[TTS] 继续队列下一条", flush=True)
            self.process_queue()

    def set_pending_ai_move(self, callback):
        """设置 AI 移动回调（AI 等待玩家语音播完后再落子）"""
        self.pending_ai_move = callback

    def stop(self):
        """停止当前播放，清空队列"""
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        self.voice_queue = []
        self.voice_playing = False
        self.pending_ai_move = None
        # 清理所有临时 WAV 文件
        try:
            for f in os.listdir(self.temp_dir):
                if f.endswith('.wav'):
                    os.remove(os.path.join(self.temp_dir, f))
        except Exception as e:
            print(f"[TTS] stop() 清理失败: {e}", flush=True)

    def toggle_mute(self):
        """切换静音"""
        self.muted = not self.muted
        return not self.muted

    def _clean_text(self, text):
        """清理文本：去除 HTML 标签和 emoji"""
        import re
        text = re.sub(r'<[^>]+>', '', text)
        emoji_pattern = re.compile(
            '['
            '\U0001F300-\U0001F5FF'
            '\U0001F600-\U0001F64F'
            '\U0001F680-\U0001F6FF'
            '\U0001F1E0-\U0001F1FF'
            '\U00002702-\U000027B0'
            '\U000024C2-\U000024FF'
            '\U0001F200-\U0001F251'
            ']+',
            flags=re.UNICODE
        )
        text = emoji_pattern.sub('', text)
        text = text.replace('\u26AB', '').replace('\u2B1B', '')
        text = text.replace('\u2B50', '').replace('\u274C', '')
        text = text.replace('\u2714', '').replace('\u26A1', '')
        text = text.replace('\u1F4A1', '').replace('\u1F3AF', '')
        text = text.replace('⚫', '黑').replace('⚪', '白')
        return text.strip()


# ============================================================
# 围棋引擎
# ============================================================
EMPTY, BLACK, WHITE = 0, 1, 2

RANK_TABLE = [
    ('业余10级', '级位', 0.99, '刚刚开始学棋的小朋友'),
    ('业余9级',  '级位', 0.97, '认识棋盘和基本规则'),
    ('业余8级',  '级位', 0.95, '能吃掉对方的子了'),
    ('业余7级',  '级位', 0.93, '会连接自己的棋子'),
    ('业余6级',  '级位', 0.90, '开始理解围地概念'),
    ('业余5级',  '级位', 0.87, '知道角和边的价值'),
    ('业余4级',  '级位', 0.84, '开始会做眼逃跑'),
    ('业余3级',  '级位', 0.81, '懂得棋形好坏'),
    ('业余2级',  '级位', 0.78, '会简单的进攻和防守'),
    ('业余1级',  '级位', 0.74, '级位最高！可以挑战段位了！'),
    ('业余1段',  '段位', 0.70, '正式段位，开始！'),
    ('业余2段',  '段位', 0.65, '段位选手，有点厉害了'),
    ('业余3段',  '段位', 0.60, '能进行简单布局'),
    ('业余4段',  '段位', 0.55, '攻防意识提升'),
    ('业余5段',  '段位', 0.50, '业余高手！'),
    ('业余6段',  '段位', 0.45, '非常强的业余棋手'),
    ('业余7段',  '段位', 0.40, '接近顶尖业余水平'),
    ('业余8段',  '段位', 0.35, '顶尖业余高手'),
    ('业余9段',  '段位', 0.30, '恭喜！达到最高业余水平！'),
]


class GoEngine:
    def __init__(self):
        self.N = 9
        self.board = []
        self.current_player = BLACK
        self.player_captures = 0
        self.ai_captures = 0
        self.move_count = 0
        self.game_over = False
        self.consecutive_passes = 0
        self.ko_point = None
        self.history = []
        self.board_history = []
        self.ai_thinking = False
        self.rank_idx = 0
        self.rank_unlocked = [True] + [False] * 18
        self._load_progress()

    def _load_progress(self):
        """加载存档"""
        try:
            data_dir = os.path.dirname(os.path.abspath(__file__))
            rank_file = os.path.join(data_dir, 'rank_progress.json')
            if os.path.exists(rank_file):
                with open(rank_file, 'r') as f:
                    data = json.load(f)
                    self.rank_idx = data.get('rank_idx', 0)
                    self.rank_unlocked = data.get('rank_unlocked', self.rank_unlocked)
        except:
            pass

    def _save_progress(self):
        """保存存档"""
        try:
            data_dir = os.path.dirname(os.path.abspath(__file__))
            rank_file = os.path.join(data_dir, 'rank_progress.json')
            with open(rank_file, 'w') as f:
                json.dump({
                    'rank_idx': self.rank_idx,
                    'rank_unlocked': self.rank_unlocked
                }, f)
        except:
            pass

    def new_game(self, board_size=9):
        """开始新游戏"""
        self.N = board_size
        self.board = [[EMPTY] * self.N for _ in range(self.N)]
        self.current_player = BLACK
        self.player_captures = 0
        self.ai_captures = 0
        self.move_count = 0
        self.game_over = False
        self.consecutive_passes = 0
        self.ko_point = None
        self.history = []
        self.board_history = []
        self.ai_thinking = False

    def get_neighbors(self, r, c):
        nb = []
        if r > 0: nb.append((r-1, c))
        if r < self.N-1: nb.append((r+1, c))
        if c > 0: nb.append((r, c-1))
        if c < self.N-1: nb.append((r, c+1))
        return nb

    def get_group(self, r, c, bd):
        color = bd[r][c]
        if color == EMPTY:
            return {'stones': [], 'liberties': set()}
        visited = set()
        stones = []
        liberties = set()
        queue = [(r, c)]
        visited.add(r * self.N + c)
        while queue:
            cr, cc = queue.pop(0)
            stones.append((cr, cc))
            for nr, nc in self.get_neighbors(cr, cc):
                key = nr * self.N + nc
                if bd[nr][nc] == EMPTY:
                    liberties.add(key)
                elif bd[nr][nc] == color and key not in visited:
                    visited.add(key)
                    queue.append((nr, nc))
        return {'stones': stones, 'liberties': liberties}

    def try_place(self, r, c, color):
        """尝试落子，返回新棋盘和提掉的棋子"""
        if self.board[r][c] != EMPTY:
            return None
        new_board = [row[:] for row in self.board]
        new_board[r][c] = color
        opp = WHITE if color == BLACK else BLACK
        captured = []
        for nr, nc in self.get_neighbors(r, c):
            if new_board[nr][nc] == opp:
                group = self.get_group(nr, nc, new_board)
                if len(group['liberties']) == 0:
                    for sr, sc in group['stones']:
                        new_board[sr][sc] = EMPTY
                        captured.append((sr, sc))
        group = self.get_group(r, c, new_board)
        if len(group['liberties']) == 0:
            return None
        return {'board': new_board, 'captured': captured}

    def place_stone(self, r, c, player):
        """落子"""
        if self.board[r][c] != EMPTY:
            return False, "这里已经有棋子了，换个地方吧！"
        if self.ko_point and self.ko_point == (r, c):
            return False, "这里现在不能下！这叫做劫争，你要先去别的地方下一步！"
        result = self.try_place(r, c, player)
        if not result:
            return False, "这里不能下！下了之后你的棋子就没有气了！"

        self.board_history.append({
            'board': [row[:] for row in self.board],
            'player_captures': self.player_captures,
            'ai_captures': self.ai_captures,
            'move_count': self.move_count,
            'ko_point': self.ko_point,
            'consecutive_passes': self.consecutive_passes,
            'current_player': self.current_player
        })

        self.board = result['board']
        captured_count = len(result['captured'])

        if player == BLACK:
            self.player_captures += captured_count
        else:
            self.ai_captures += captured_count

        # 检查劫
        new_ko = None
        if captured_count == 1:
            kr, kc = result['captured'][0]
            test = self.try_place(kr, kc, WHITE if player == BLACK else BLACK)
            if test and len(test['captured']) == 1:
                new_ko = (kr, kc)
        self.ko_point = new_ko

        self.move_count += 1
        self.consecutive_passes = 0

        cols = 'ABCDEFGHJKLMNOPQRST'
        pos_label = f"{cols[c]}{self.N - r}"
        self.history.append({
            'player': player,
            'row': r,
            'col': c,
            'captured': captured_count,
            'pos': pos_label
        })

        return True, f"落子 {pos_label}"

    def pass_move(self):
        """跳过"""
        self.board_history.append({
            'board': [row[:] for row in self.board],
            'player_captures': self.player_captures,
            'ai_captures': self.ai_captures,
            'move_count': self.move_count,
            'ko_point': self.ko_point,
            'consecutive_passes': self.consecutive_passes,
            'current_player': self.current_player
        })
        self.consecutive_passes += 1
        self.ko_point = None
        self.history.append({'player': BLACK, 'row': -1, 'col': -1, 'captured': 0, 'pos': 'Pass'})
        self.move_count += 1
        return self.consecutive_passes >= 2

    def undo(self):
        """悔棋"""
        if len(self.board_history) < 2:
            return False
        for _ in range(min(2, len(self.board_history))):
            snap = self.board_history.pop()
            self.board = snap['board']
            self.player_captures = snap['player_captures']
            self.ai_captures = snap['ai_captures']
            self.move_count = snap['move_count']
            self.ko_point = snap['ko_point']
            self.consecutive_passes = snap['consecutive_passes']
            self.current_player = snap['current_player']
            if self.history:
                self.history.pop()
        self.ai_thinking = False
        self.game_over = False
        return True

    def get_all_legal_moves(self, player):
        moves = []
        for r in range(self.N):
            for c in range(self.N):
                if self.board[r][c] != EMPTY:
                    continue
                if self.ko_point and self.ko_point == (r, c):
                    continue
                if self.try_place(r, c, player):
                    moves.append((r, c))
        return moves

    def score_move(self, r, c, player):
        """评估落子分数"""
        result = self.try_place(r, c, player)
        if not result:
            return -9999
        score = 0
        score += len(result['captured']) * 15
        opp = WHITE if player == BLACK else BLACK

        group = self.get_group(r, c, result['board'])
        score += len(group['liberties']) * 2

        for nr, nc in self.get_neighbors(r, c):
            if self.board[nr][nc] == opp:
                lib = self.get_group(nr, nc, self.board)
                if len(lib['liberties']) == 1:
                    score += 20
                elif len(lib['liberties']) == 2:
                    score += 8
            if self.board[nr][nc] == player:
                lib = self.get_group(nr, nc, self.board)
                if len(lib['liberties']) == 1:
                    score += 12

        center = (self.N - 1) / 2
        score += max(0, (self.N - abs(r - center) - abs(c - center)) * 0.5)

        # 星位加分
        star_points = self._get_star_points()
        if (r, c) in star_points:
            score += 8

        return score + random.random() * 3

    def _get_star_points(self):
        """获取星位"""
        if self.N == 9:
            return [(2, 2), (2, 6), (4, 4), (6, 2), (6, 6)]
        elif self.N == 13:
            return [(3, 3), (3, 9), (6, 6), (9, 3), (9, 9)]
        else:
            return [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)]

    def ai_move(self):
        """AI落子"""
        moves = self.get_all_legal_moves(WHITE)
        if not moves:
            return None, None
        scored = [(r, c, self.score_move(r, c, WHITE)) for r, c in moves]
        scored.sort(key=lambda x: x[2], reverse=True)
        rank = RANK_TABLE[self.rank_idx]
        ratio = rank[2]
        pool = scored[:max(1, int(len(scored) * ratio))]
        r, c, _ = random.choice(pool)
        return r, c

    def end_game(self):
        """结束游戏"""
        self.game_over = True
        komi = 6.5
        black_stones = sum(row.count(BLACK) for row in self.board)
        white_stones = sum(row.count(WHITE) for row in self.board)
        player_score = black_stones + self.player_captures
        ai_score = white_stones + self.ai_captures + komi

        if player_score > ai_score:
            # 赢了
            if self.rank_idx < len(RANK_TABLE) - 1:
                old_rank = RANK_TABLE[self.rank_idx]
                self.rank_unlocked[self.rank_idx + 1] = True
                self.rank_idx += 1
                self._save_progress()
                return 'win', f"你赢了！({player_score:.1f} vs {ai_score:.1f})\n恭喜升级到{RANK_TABLE[self.rank_idx][0]}！"
            return 'win', f"你赢了！({player_score:.1f} vs {ai_score:.1f})\n你已经是最高级别！"
        elif abs(player_score - ai_score) < 0.1:
            return 'draw', f"平局！({player_score:.1f} vs {ai_score:.1f})"
        else:
            return 'lose', f"电脑赢了。({player_score:.1f} vs {ai_score:.1f})\n别灰心，继续加油！"


# ============================================================
# 桌面应用
# ============================================================
class GoApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("围棋小课堂")
        self.root.configure(bg='#ffecd2')

        self.engine = GoEngine()
        self.voice = VoiceSystem(root=self.root)
        self.speech_queue = queue.Queue()
        self.is_speaking = False
        self.last_speech = ""

        # 加载设置
        self._load_settings()

        # UI
        self._create_ui()

        # 读取棋盘大小，初始化引擎
        size = self.settings.get('board_size', 9)
        self.engine.new_game(size)

        # 先绘制棋盘（这会确定 canvas 的实际大小）
        self.new_game_no_speak()

        # ★ 在画板绘制完成之后再设置窗口大小，防止被覆盖
        self._update_window_size()

        # 窗口显示后延迟播报（延迟足够长确保TTS完全就绪）
        self.root.after(500, self._delayed_intro)

        # 启动主循环
        self.root.mainloop()

    def _delayed_intro(self):
        """延迟播报开场白（引擎改为懒初始化，无需手动调用 init_engine）"""
        rank = RANK_TABLE[self.engine.rank_idx]
        size = self.settings.get('board_size', 9)
        msg = f"新游戏！棋盘是{size}路。你下黑棋先走，对手是{rank[0]}水平。"
        print(f"[MAIN] _delayed_intro: {msg}", flush=True)
        self._update_speech(msg)
        self.voice.speak(msg)
        # 开场白播完后（延迟3秒）预热引擎，用户点击时已就绪
        self.root.after(3000, self.voice.warmup)

    def _load_settings(self):
        """加载设置"""
        try:
            data_dir = os.path.dirname(os.path.abspath(__file__))
            settings_file = os.path.join(data_dir, 'settings.json')
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    saved_settings = json.load(f)
                    # 处理旧版本设置（没有中文显示值的情况）
                    if 'board_size_display' not in saved_settings:
                        size = saved_settings.get('board_size', 9)
                        saved_settings['board_size_display'] = f"{size}路"
                    if 'speed_display' not in saved_settings:
                        speed_map = {0.7: '慢速🐢', 0.9: '正常🐸', 1.2: '较快🐇'}
                        saved_settings['speed_display'] = speed_map.get(saved_settings.get('speed', 0.9), '正常🐸')
                    # 处理旧的英文/旧中文值
                    commentary_map = {'simple': '精简', 'detail': '详细', '简单': '精简', '详细': '详细'}
                    saved_settings['commentary'] = commentary_map.get(saved_settings.get('commentary'), '精简')
                    tips_map = {'all': '全开', 'warn': '开黄红警告', 'danger': '仅红色警告', 'off': '全关',
                               '全部提示': '全开', '危险提示': '开黄红警告', '关闭提示': '全关', '关闭': '全关'}
                    saved_settings['tips'] = tips_map.get(saved_settings.get('tips'), '全开')
                    self.settings = saved_settings
            else:
                self.settings = {'board_size': 9, 'board_size_display': '9路', 'speed': 0.9, 'speed_display': '正常🐸', 'commentary': '精简', 'tips': '全开'}
        except:
            self.settings = {'board_size': 9, 'board_size_display': '9路', 'speed': 0.9, 'speed_display': '正常🐸', 'commentary': '精简', 'tips': '全开'}

        self.voice.set_speed(self.settings.get('speed', 0.9))

    def _save_settings(self):
        """保存设置"""
        try:
            data_dir = os.path.dirname(os.path.abspath(__file__))
            settings_file = os.path.join(data_dir, 'settings.json')
            with open(settings_file, 'w') as f:
                json.dump(self.settings, f)
        except:
            pass

    def _create_ui(self):
        """创建UI"""
        # 标题栏
        title_frame = tk.Frame(self.root, bg='white', padx=20, pady=10)
        title_frame.pack(fill='x', padx=20, pady=(10, 5))

        tk.Label(title_frame, text="🏯 围棋小课堂", font=('Microsoft YaHei', 24, 'bold'),
                fg='#e05c00', bg='white').pack(side='left')

        self.rank_label = tk.Label(title_frame, text="业余10级", font=('Microsoft YaHei', 14),
                                   bg='#e05c00', fg='white', padx=12, pady=4)
        self.rank_label.pack(side='left', padx=10)

        # 控制面板
        control_frame = tk.Frame(title_frame, bg='white')
        control_frame.pack(side='right')

        tk.Label(control_frame, text="解说:", bg='white', fg='#555').pack(side='left', padx=5)
        self.commentary_var = tk.StringVar(value=self.settings.get('commentary', '精简'))
        commentary_menu = tk.OptionMenu(control_frame, self.commentary_var, '精简', '详细',
                                       command=lambda x: self._update_setting('commentary', self.commentary_var.get()))
        commentary_menu.config(bg='#f0f8ff', bd=2)
        commentary_menu.pack(side='left', padx=5)

        tk.Label(control_frame, text="提示:", bg='white', fg='#555').pack(side='left', padx=5)
        self.tips_var = tk.StringVar(value=self.settings.get('tips', '全开'))
        tips_menu = tk.OptionMenu(control_frame, self.tips_var, '全开', '开黄红警告', '仅红色警告', '全关',
                                  command=lambda x: self._update_setting('tips', self.tips_var.get()))
        tips_menu.config(bg='#fff0f0', bd=2)
        tips_menu.pack(side='left', padx=5)

        tk.Label(control_frame, text="语速:", bg='white', fg='#555').pack(side='left', padx=5)
        self.speed_var = tk.StringVar(value=self.settings.get('speed_display', '正常🐸'))
        speed_menu = tk.OptionMenu(control_frame, self.speed_var, '慢速🐢', '正常🐸', '较快🐇',
                                   command=self._on_speed_change)
        speed_menu.config(bg='#fff9f0', bd=2)
        speed_menu.pack(side='left', padx=5)

        self.mute_btn = tk.Button(control_frame, text="🔊", font=('Arial', 18),
                                  command=self._toggle_mute, width=3, height=1)
        self.mute_btn.pack(side='left', padx=5)

        replay_btn = tk.Button(control_frame, text="🔁", font=('Arial', 18),
                               command=self._replay_speech, width=3, height=1)
        replay_btn.pack(side='left', padx=5)

        # 主区域
        main_frame = tk.Frame(self.root, bg='#ffecd2')
        main_frame.pack(fill='both', expand=True, padx=20, pady=10)

        # 左侧：棋盘
        left_frame = tk.Frame(main_frame, bg='#ffecd2')
        left_frame.pack(side='left', padx=(0, 20))

        self.status_label = tk.Label(left_frame, text="⚫ 轮到你啦！",
                                      font=('Microsoft YaHei', 18, 'bold'),
                                      bg='white', padx=20, pady=8)
        self.status_label.pack(pady=(0, 10))

        # 棋盘容器
        self.board_frame = tk.Frame(left_frame, bg='#e8b96a', padx=32, pady=32)
        self.board_frame.pack()

        self.canvas = tk.Canvas(self.board_frame, bg='#e8b96a', highlightthickness=0)
        self.canvas.pack()

        # 右侧面板
        right_frame = tk.Frame(main_frame, bg='#ffecd2', width=320)
        right_frame.pack(side='right', fill='y')
        right_frame.pack_propagate(False)

        # 级位卡片
        rank_card = tk.Frame(right_frame, bg='white', padx=18, pady=15)
        rank_card.pack(fill='x', pady=(0, 10))

        tk.Label(rank_card, text="⭐ 我的级位", font=('Microsoft YaHei', 16, 'bold'),
                fg='#e05c00', bg='white').pack(anchor='w')

        self.rank_badge = tk.Label(rank_card, text="业余10级", font=('Microsoft YaHei', 14, 'bold'),
                                   bg='#e05c00', fg='white', padx=15, pady=5)
        self.rank_badge.pack(pady=10)

        self.progress_canvas = tk.Canvas(rank_card, height=14, bg='#e9ecef', highlightthickness=0)
        self.progress_canvas.pack(fill='x', pady=5)
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 14, fill='#74c0fc')

        tk.Label(rank_card, text="业余10级                    业余9段",
                font=('Arial', 10), fg='#888', bg='white').pack(fill='x')

        self.next_rank_label = tk.Label(rank_card, text="🔒 再赢一局 → 业余9级",
                                        font=('Microsoft YaHei', 12), fg='#e67700', bg='white')
        self.next_rank_label.pack(pady=5)

        # 讲解卡片
        speech_card = tk.Frame(right_frame, bg='white', padx=18, pady=15)
        speech_card.pack(fill='x', pady=(0, 10))

        tk.Label(speech_card, text="🎓 老师说", font=('Microsoft YaHei', 16, 'bold'),
                fg='#e05c00', bg='white').pack(anchor='w')

        self.speech_label = tk.Label(speech_card, text="欢迎来玩围棋！你下黑棋，电脑下白棋，黑棋先走。",
                                     font=('Microsoft YaHei', 14), bg='#fffbe6',
                                     fg='#222', wraplength=280, justify='left', anchor='w')
        self.speech_label.pack(fill='x', pady=(10, 0))

        # 比分卡片
        score_card = tk.Frame(right_frame, bg='white', padx=18, pady=15)
        score_card.pack(fill='x', pady=(0, 10))

        tk.Label(score_card, text="📊 比分", font=('Microsoft YaHei', 16, 'bold'),
                fg='#e05c00', bg='white').pack(anchor='w')

        score_frame = tk.Frame(score_card, bg='white')
        score_frame.pack(pady=10)

        self.black_cap_label = tk.Label(score_frame, text="0", font=('Arial', 32, 'bold'),
                                        fg='#333', bg='white')
        self.black_cap_label.pack(side='left', padx=30)
        tk.Label(score_frame, text="手数\n0", font=('Arial', 12), fg='#4a90d9', bg='white').pack(side='left', padx=30)
        self.white_cap_label = tk.Label(score_frame, text="0", font=('Arial', 32, 'bold'),
                                        fg='#e08a00', bg='white')
        self.white_cap_label.pack(side='left', padx=30)

        tk.Label(score_card, text="⚫ 你                    ⚪ 电脑", font=('Arial', 10), fg='#888', bg='white').pack()

        # 按钮卡片
        btn_card = tk.Frame(right_frame, bg='white', padx=18, pady=15)
        btn_card.pack(fill='x', pady=(0, 10))

        new_btn = tk.Button(btn_card, text="🎮 新游戏", font=('Microsoft YaHei', 14, 'bold'),
                            bg='#74c0fc', fg='white', command=self.new_game)
        new_btn.pack(fill='x', pady=3)

        btn_frame = tk.Frame(btn_card, bg='white')
        btn_frame.pack(fill='x', pady=3)

        pass_btn = tk.Button(btn_frame, text="⏭ 跳过", font=('Microsoft YaHei', 12, 'bold'),
                             bg='#b2f2bb', fg='#1a5c2a', command=self.pass_move)
        pass_btn.pack(side='left', fill='x', expand=True, padx=(0, 5))

        undo_btn = tk.Button(btn_frame, text="↩ 悔棋", font=('Microsoft YaHei', 12, 'bold'),
                            bg='#ffd8a8', fg='#5c2d00', command=self.undo)
        undo_btn.pack(side='right', fill='x', expand=True, padx=(5, 0))

        # 设置卡片
        settings_card = tk.Frame(right_frame, bg='white', padx=18, pady=15)
        settings_card.pack(fill='x', pady=(0, 10))

        tk.Label(settings_card, text="⚙️ 设置", font=('Microsoft YaHei', 16, 'bold'),
                fg='#e05c00', bg='white').pack(anchor='w')

        tk.Label(settings_card, text="棋盘:", font=('Microsoft YaHei', 14), bg='white').pack(anchor='w', pady=5)
        self.board_size_var = tk.StringVar(value=self.settings.get('board_size_display', '9路'))
        board_menu = tk.OptionMenu(settings_card, self.board_size_var, '9路', '13路', '19路',
                                   command=self._on_board_size_change)
        board_menu.config(font=('Microsoft YaHei', 12), bg='#fff9f0', bd=2, width=20)
        board_menu.pack(fill='x')

        # 棋谱卡片
        history_card = tk.Frame(right_frame, bg='white', padx=18, pady=15)
        history_card.pack(fill='both', expand=True, pady=(0, 10))

        tk.Label(history_card, text="📋 棋谱", font=('Microsoft YaHei', 16, 'bold'),
                fg='#e05c00', bg='white').pack(anchor='w')

        scroll_frame = tk.Frame(history_card, bg='white')
        scroll_frame.pack(fill='both', expand=True, pady=(10, 0))

        self.history_text = tk.Text(scroll_frame, font=('Microsoft YaHei', 12), bg='#fafafa',
                                    fg='#555', wrap='none', height=8, highlightthickness=0)
        self.history_text.pack(fill='both', expand=True)

        scroll_y = tk.Scrollbar(scroll_frame, command=self.history_text.yview)
        scroll_y.pack(side='right', fill='y')
        self.history_text.config(yscrollcommand=scroll_y.set)

    def _update_setting(self, key, value):
        self.settings[key] = value
        self._save_settings()

    def _on_speed_change(self, value):
        speed_map = {'慢速🐢': 0.7, '正常🐸': 0.9, '较快🐇': 1.2}
        speed = speed_map.get(value, 0.9)
        self.settings['speed'] = speed
        self.settings['speed_display'] = value
        self.voice.set_speed(speed)
        self._save_settings()

    def _on_board_size_change(self, value):
        size_map = {'9路': 9, '13路': 13, '19路': 19}
        self.settings['board_size'] = size_map.get(value, 9)
        self.settings['board_size_display'] = value
        self._save_settings()
        self._update_window_size()
        self.new_game_no_speak()
        # 切换棋盘后延迟播报
        rank = RANK_TABLE[self.engine.rank_idx]
        msg = f"棋盘已切换到{value}，对手是{rank[0]}水平。"
        self._update_speech(msg)
        self.root.after(500, lambda: self.voice.speak(msg))

    def _toggle_mute(self):
        muted = self.voice.toggle_mute()
        self.mute_btn.config(text="🔇" if muted else "🔊")

    def _replay_speech(self):
        """重播上一句语音"""
        if self.last_speech:
            self.voice.speak(self.last_speech)

    def _get_cell_size(self, N=None):
        """根据窗口可用空间动态计算格子大小"""
        if N is None:
            N = self.engine.N
        # 棋盘最大尺寸限制
        max_board_size = 700
        return max(35, max_board_size // N)

    def _update_window_size(self):
        """根据棋盘大小更新窗口大小"""
        N = self.engine.N
        cell = self._get_cell_size()
        # canvas 大小：棋盘线 + 坐标标签
        canvas_size = cell * (N - 1) + cell + 60
        # board_frame padx=32 两侧共 64
        board_area = canvas_size + 64
        # 左侧 padx(0,20) + 右侧面板 320 + main_frame padx=20 两侧 40
        total_width = board_area + 20 + 320 + 40
        # 高度：title(~60) + board_area + status(~50) + 边距
        total_height = max(board_area + 160, 660)

        self.root.geometry(f"{total_width}x{total_height}")
        self.root.update_idletasks()
        self.root.minsize(900, 600)

    def _draw_board(self):
        """绘制棋盘"""
        self.canvas.delete('all')
        N = self.engine.N
        cell = self._get_cell_size()
        offset = cell * 0.4
        size = cell * (N - 1) + cell

        self.canvas.config(width=size + 60, height=size + 60)

        # 绘制棋盘背景（木纹渐变）
        for i in range(int(size)):
            ratio = i / size
            r = int(240 - ratio * 80)
            g = int(204 - ratio * 70)
            b = int(114 - ratio * 50)
            self.canvas.create_line(30, 30 + i, 30 + size, 30 + i, fill=f'#{r:02x}{g:02x}{b:02x}')

        # 绘制网格线
        for i in range(N):
            x = 30 + offset + i * cell
            y = 30 + offset + i * cell
            self.canvas.create_line(x, 30 + offset, x, 30 + offset + (N-1) * cell, fill='#7a5000', width=1)
            self.canvas.create_line(30 + offset, y, 30 + offset + (N-1) * cell, y, fill='#7a5000', width=1)

        # 绘制坐标标签
        # 围棋坐标规则：列用字母 A-T (跳过 I)，行用数字
        # 9路: A-H J (9个), 13路: A-H J-M (13个), 19路: A-T (19个)
        # 生成字母序列: A B C D E F G H J K L M N O P Q R S T (跳过 I)
        letters = []
        letter_idx = 0
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        for _ in range(N):
            letter = alphabet[letter_idx]
            if letter != 'I':  # 跳过 I
                letters.append(letter)
            else:
                letter_idx += 1
                letters.append(alphabet[letter_idx])
            letter_idx += 1
        for i in range(N):
            x = 30 + offset + i * cell
            # 列字母 (顶部和底部) - 增大字体和间距
            col_letter = letters[i]
            self.canvas.create_text(x, 15, text=col_letter, font=('Arial', 11, 'bold'), fill='#5a4000')
            self.canvas.create_text(x, size + 48, text=col_letter, font=('Arial', 11, 'bold'), fill='#5a4000')
            # 行数字 (左侧和右侧) - 增大字体和间距
            row_num = i + 1
            self.canvas.create_text(15, 30 + offset + i * cell, text=str(row_num), font=('Arial', 11, 'bold'), fill='#5a4000')
            self.canvas.create_text(size + 48, 30 + offset + i * cell, text=str(row_num), font=('Arial', 11, 'bold'), fill='#5a4000')

        # 绘制星位
        star_points = self.engine._get_star_points()
        for r, c in star_points:
            x = 30 + offset + c * cell
            y = 30 + offset + r * cell
            self.canvas.create_oval(x-3, y-3, x+3, y+3, fill='#7a5000', outline='#7a5000')

        # 绘制棋子
        for r in range(N):
            for c in range(N):
                if self.engine.board[r][c] != EMPTY:
                    x = 30 + offset + c * cell
                    y = 30 + offset + r * cell
                    self._draw_stone(x, y, self.engine.board[r][c])

        # 绘制最后一手标记
        if self.engine.history:
            last = self.engine.history[-1]
            if last['row'] >= 0:
                x = 30 + offset + last['col'] * cell
                y = 30 + offset + last['row'] * cell
                color = 'white' if last['player'] == BLACK else '#333'
                self.canvas.create_oval(x-6, y-6, x+6, y+6, fill=color, outline=color)

        # 劫标记
        if self.engine.ko_point:
            x = 30 + offset + self.engine.ko_point[1] * cell
            y = 30 + offset + self.engine.ko_point[0] * cell
            self.canvas.create_oval(x-15, y-15, x+15, y+15, outline='red', width=2)

        # 绑定点击事件
        self.canvas.unbind('<Button-1>')
        self.canvas.bind('<Button-1>', self._on_board_click)

    def _draw_stone(self, x, y, color):
        """绘制棋子"""
        cell = self._get_cell_size()
        radius = cell * 0.4

        # 渐变效果
        if color == BLACK:
            self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                                   fill='#333', outline='#111', width=1)
        else:
            self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                                   fill='#fff', outline='#999', width=1)

    def _on_board_click(self, event):
        """棋盘点击"""
        if self.engine.game_over or self.engine.current_player != BLACK or self.engine.ai_thinking:
            return

        N = self.engine.N
        cell = self._get_cell_size()
        offset = cell * 0.4
        board_offset = 30

        col = int(round((event.x - board_offset - offset) / cell))
        row = int(round((event.y - board_offset - offset) / cell))

        if row < 0 or row >= N or col < 0 or col >= N:
            return

        x = board_offset + offset + col * cell
        y = board_offset + offset + row * cell
        if abs(event.x - x) > cell * 0.46 or abs(event.y - y) > cell * 0.46:
            return

        self._player_move(row, col)

    def _player_move(self, row, col):
        """玩家落子"""
        success, msg = self.engine.place_stone(row, col, BLACK)
        if not success:
            self._update_speech(msg)
            self.voice.speak(msg, priority=True)
            return

        self._update_history()
        self._update_scores()
        self._draw_board()
        self._update_status()

        # 生成解说
        commentary = self._generate_commentary(row, col, BLACK)
        self._update_speech(commentary)

        # 切换到AI回合（立即切走，防止重复点击）
        self.engine.current_player = WHITE
        self._update_status()

        # 玩家语音播完后 → 执行 pending_ai_move（AI落子）
        self.voice.set_pending_ai_move(self._do_ai)
        # 入队玩家解说语音，callback 会在播完后触发 pending_ai_move
        self.voice.speak(commentary, priority=False, callback=None, turn='player')

    def _do_ai(self):
        """
        AI 实际落子（在 pending_ai_move 回调里执行）。
        参考 HTML 版 aiMove() 逻辑，同步计算+落子，不阻塞（计算很快）。
        """
        if self.engine.game_over:
            self.voice.pending_ai_move = None
            return

        self.engine.ai_thinking = True
        self._update_status()

        r, c = self.engine.ai_move()
        if r is None:
            # AI跳过
            self.engine.consecutive_passes += 1
            self.engine.ko_point = None
            self.engine.history.append({'player': WHITE, 'row': -1, 'col': -1, 'captured': 0, 'pos': 'Pass'})
            self.engine.move_count += 1

            if self.engine.consecutive_passes >= 2:
                self.voice.pending_ai_move = None
                self._end_game()
            else:
                self.engine.current_player = BLACK
                self.engine.ai_thinking = False
                self._update_status()
                self._update_history()
                self._update_scores()
                self._draw_board()
                # AI 跳过：解说入队，播完后切回玩家
                self.voice.set_pending_ai_move(self._resume_player_turn)
                self.voice.speak("电脑跳过了这一手", turn='ai')
        else:
            self.engine.place_stone(r, c, WHITE)
            self._update_history()
            self._update_scores()
            self._draw_board()

            commentary = self._generate_commentary(r, c, WHITE)
            self._update_speech(commentary)

            self.engine.current_player = BLACK
            self.engine.ai_thinking = False
            self._update_status()

            # AI 解说入队，播完后 → 切回玩家回合（_resume_player_turn）
            self.voice.set_pending_ai_move(self._resume_player_turn)
            self.voice.speak(commentary, turn='ai')

    def _resume_player_turn(self):
        """AI语音播完后：切回玩家回合，清除 pending"""
        self.engine.current_player = BLACK
        self.engine.ai_thinking = False
        self.voice.pending_ai_move = None
        self._update_status()

    def _generate_commentary(self, row, col, player):
        """生成解说"""
        N = self.engine.N
        cols = 'ABCDEFGHJKLMNOPQRST'
        pos = f"{cols[col]}{N-row}"
        is_black = player == BLACK

        parts = []
        if is_black:
            parts.append(f"你在{pos}落子")
        else:
            parts.append(f"电脑在{pos}落子")

        # 检查提子
        last = self.engine.history[-1]
        if last['captured'] > 0:
            parts.append(f"提掉{last['captured']}颗棋子！")

        # 检查气
        group = self.engine.get_group(row, col, self.engine.board)
        gas = len(group['liberties'])
        if gas == 1:
            parts.append("危险！只剩一口气！")
        elif gas == 2:
            parts.append("只有两口气，注意防守！")

        # 检查劫
        if self.engine.ko_point:
            parts.append("形成劫争！不能马上提回")

        # 位置评价
        margin = min(row, col, N-1-row, N-1-col)
        if margin == 0:
            parts.append("落在边线上，气比较少")
        elif margin == 1 and (row <= 1 or row >= N-2) and (col <= 1 or col >= N-2):
            parts.append("落在角落，好位置！")
        elif margin <= 2 and (row <= 2 or row >= N-3) and (col <= 2 or col >= N-3):
            parts.append("角部位置，开局好点！")
        else:
            center = (N-1) / 2
            if abs(row - center) <= 1 and abs(col - center) <= 1:
                parts.append("中央位置，影响力大")

        return "，".join(parts)

    def new_game_no_speak(self):
        """开始新游戏（不播报）"""
        size = self.settings.get('board_size', 9)
        size_display = f"{size}路"
        self.engine.new_game(size)
        self._update_history()
        self._update_scores()
        self._draw_board()
        self._update_rank_ui()
        self._update_status()

    def new_game(self):
        """开始新游戏"""
        size = self.settings.get('board_size', 9)
        size_display = f"{size}路"
        self.engine.new_game(size)
        self._update_history()
        self._update_scores()
        self._draw_board()
        self._update_rank_ui()
        self._update_status()

        rank = RANK_TABLE[self.engine.rank_idx]
        msg = f"新游戏！棋盘是{size_display}。你下黑棋先走，对手是{rank[0]}水平。"
        self._update_speech(msg)
        self.voice.speak(msg)

    def pass_move(self):
        """跳过"""
        if self.engine.game_over or self.engine.current_player != BLACK:
            return

        self.engine.pass_move()
        self._update_history()
        self._update_status()

        self._update_speech("你跳过了这一手")
        self.voice.speak("你跳过了这一手")

        if self.engine.consecutive_passes >= 2:
            self._end_game()
        else:
            self.root.after(500, self._ai_move)

    def undo(self):
        """悔棋"""
        if self.engine.undo():
            self.voice.stop()
            self._update_history()
            self._update_scores()
            self._draw_board()
            self._update_status()
            self._update_speech("悔棋成功！")
            self.voice.speak("悔棋成功！")
        else:
            self._update_speech("没有可以悔的棋了")
            self.voice.speak("没有可以悔的棋了")

    def _end_game(self):
        """结束游戏"""
        result, msg = self.engine.end_game()
        self._update_speech(msg)
        self.voice.speak(msg)
        self._update_rank_ui()
        self._update_status()

    def _update_speech(self, text):
        """更新解说"""
        self.speech_label.config(text=text)
        # 保存最后一句用于重播
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        clean = clean.replace('⚫', '黑').replace('⚪', '白')
        self.last_speech = clean

    def _update_scores(self):
        """更新比分"""
        self.black_cap_label.config(text=str(self.engine.player_captures))
        self.white_cap_label.config(text=str(self.engine.ai_captures))

    def _update_history(self):
        """更新棋谱"""
        self.history_text.delete('1.0', 'end')
        for i, h in enumerate(self.engine.history):
            stone = '⚫' if h['player'] == BLACK else '⚪'
            cap = f" 提{h['captured']}" if h['captured'] > 0 else ""
            self.history_text.insert('end', f"{i+1}. {stone} {h['pos']}{cap}\n")

    def _update_status(self):
        """更新状态"""
        if self.engine.game_over:
            self.status_label.config(text="🏁 游戏结束！", fg='#e03131')
        elif self.engine.ai_thinking:
            self.status_label.config(text="⏳ 电脑在想...", fg='#888')
        elif self.engine.current_player == BLACK:
            self.status_label.config(text="⚫ 轮到你啦！", fg='#333')
        else:
            self.status_label.config(text="⚪ 电脑下棋中...", fg='#888')

    def _update_rank_ui(self):
        """更新级位UI"""
        rank = RANK_TABLE[self.engine.rank_idx]
        color = '#e05c00' if rank[1] == '级位' else '#4a90d9'

        self.rank_label.config(text=rank[0], bg=color)
        self.rank_badge.config(text=rank[0], bg=color)

        total = len(RANK_TABLE)
        percent = self.engine.rank_idx / (total - 1)
        self.progress_canvas.coords(self.progress_bar, 0, 0, int(200 * percent), 14)

        if self.engine.rank_idx >= total - 1:
            self.next_rank_label.config(text="🏆 已达最高级别！")
        else:
            next_rank = RANK_TABLE[self.engine.rank_idx + 1]
            if self.engine.rank_unlocked[self.engine.rank_idx + 1]:
                self.next_rank_label.config(text=f"✅ 已解锁 {next_rank[0]}", fg='#51cf66')
            else:
                self.next_rank_label.config(text=f"🔒 再赢一局 → {next_rank[0]}", fg='#e67700')

    def run(self):
        """运行应用"""
        self.root.mainloop()


# ============================================================
# 入口
# ============================================================
if __name__ == '__main__':
    app = GoApp()
    app.run()
