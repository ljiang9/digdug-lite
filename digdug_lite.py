#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
digdug-lite —— 极简《打空气》(Dig Dug)克隆。

玩法:
  在泥土里挖隧道, 用打气筒把敌人吹到爆,
  或者挖空石头下方的泥土, 让石头掉下来砸死敌人。
  消灭所有敌人即过关; 被敌人碰到或被石头砸到会丢一条命(共 3 条)。

纯 Python 标准库, 无第三方依赖。
"""

import argparse
import random
import sys

WIDTH, HEIGHT = 20, 12
DIRT, TUNNEL = "#", " "

UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)
DIRS = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT}

PUMP_RANGE = 4      # 打气筒射程(格)
PUMPS_TO_POP = 4    # 吹爆所需打气次数
POP_SCORE = 200     # 吹爆基础分(另有深度加成)
CRUSH_SCORE = 500   # 石头砸死敌人的得分
DEFLATE_TICKS = 8   # 停止打气后, 多少 tick 漏掉一格气
LIVES = 3


class Enemy:
    """敌人: 会在隧道里追玩家, 在泥土里缓慢"穿行"靠近玩家。"""

    def __init__(self, x, y, kind):
        self.x = x
        self.y = y
        self.kind = kind  # 'P' / 'F', 两种敌人仅显示不同
        self.inflation = 0  # 当前充气格数
        self.hooked = False  # 是否被打气筒勾住(勾住后无法移动)
        self.cool = 0  # 漏气计时

    def __repr__(self):
        return f"Enemy({self.x},{self.y},{self.kind},气={self.inflation})"


class Rock:
    """石头: 下方泥土被挖空后会下落, 砸死压到的玩家和敌人。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.falling = False


class Game:
    def __init__(self, seed=0, n_enemies=4, n_rocks=3):
        self.rng = random.Random(seed)
        self.w, self.h = WIDTH, HEIGHT
        self.grid = [[DIRT] * WIDTH for _ in range(HEIGHT)]
        self.px, self.py = 1, 1
        self.facing = RIGHT
        self.lives = LIVES
        self.score = 0
        self.tick_n = 0
        self.over = False
        self.won = False
        self.enemies = []
        self.rocks = []
        # 出生点挖一小段隧道
        for dx in range(3):
            self.grid[1][1 + dx] = TUNNEL
        # 随机放置敌人和石头(避开出生点)
        spots = [
            (x, y)
            for y in range(2, HEIGHT)
            for x in range(WIDTH)
        ]
        self.rng.shuffle(spots)
        for i in range(min(n_enemies, len(spots))):
            x, y = spots.pop()
            self.enemies.append(Enemy(x, y, "P" if i % 2 == 0 else "F"))
        for _ in range(min(n_rocks, len(spots))):
            x, y = spots.pop()
            self.rocks.append(Rock(x, y))

    # ---------- 查询辅助 ----------

    def _rock_at(self, x, y):
        for r in self.rocks:
            if (r.x, r.y) == (x, y):
                return r
        return None

    def _enemy_at(self, x, y):
        for e in self.enemies:
            if (e.x, e.y) == (x, y):
                return e
        return None

    def _in_bounds(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    # ---------- 玩家动作 ----------

    def step(self, action):
        """执行一个动作并推进一 tick 世界。action 取值:
        up/down/left/right 移动(挖土); aim_up/... 只转身;
        fire 发射打气筒; pump 打气; wait 等待。"""
        if self.over:
            return
        self.tick_n += 1
        if action in DIRS:
            self._move_player(*DIRS[action])
        elif action.startswith("aim_") and action[4:] in DIRS:
            self.facing = DIRS[action[4:]]
        elif action == "fire":
            self._fire()
        elif action == "pump":
            self._pump()
        # 'wait' 或未知动作: 什么都不做
        self._update_rocks()
        if not self.over:
            self._move_enemies()
        if not self.over:
            self._deflate()
        if not self.enemies and not self.over:
            self.won = True
            self.over = True

    def _move_player(self, dx, dy):
        self.facing = (dx, dy)
        # 移动会挣脱打气筒(气还留着, 会慢慢漏掉)
        for e in self.enemies:
            e.hooked = False
        nx, ny = self.px + dx, self.py + dy
        if not self._in_bounds(nx, ny):
            return
        if self._rock_at(nx, ny):
            return  # 石头挡路, 推不动
        self.px, self.py = nx, ny
        self.grid[ny][nx] = TUNNEL  # 挖土
        if self._enemy_at(nx, ny):
            self._kill_player()

    def _fire(self):
        """沿朝向发射打气筒: 只能穿过隧道, 泥土/石头挡住;
        射程内第一个敌人会被勾住。"""
        for e in self.enemies:
            e.hooked = False
        dx, dy = self.facing
        x, y = self.px, self.py
        for _ in range(PUMP_RANGE):
            x, y = x + dx, y + dy
            if not self._in_bounds(x, y):
                break
            if self.grid[y][x] != TUNNEL:
                break  # 泥土挡住打气筒
            if self._rock_at(x, y):
                break
            e = self._enemy_at(x, y)
            if e is not None:
                e.hooked = True
                e.cool = 0
                break

    def _pump(self):
        """给勾住的敌人打气; 充满 PUMPS_TO_POP 格则吹爆。"""
        for e in self.enemies:
            if e.hooked:
                e.inflation += 1
                e.cool = 0
                if e.inflation >= PUMPS_TO_POP:
                    self.enemies.remove(e)
                    self.score += POP_SCORE + e.y * 10  # 越深分越高
                break

    # ---------- 世界推进 ----------

    def _update_rocks(self):
        for r in self.rocks:
            below = r.y + 1
            if below >= self.h:
                r.falling = False
                continue
            below_open = (
                self.grid[below][r.x] == TUNNEL
                and self._rock_at(r.x, below) is None
            )
            if r.falling:
                if below_open:
                    r.y = below
                    if (r.x, r.y) == (self.px, self.py):
                        self._kill_player()
                        if self.over:
                            return
                    for e in list(self.enemies):
                        if (e.x, e.y) == (r.x, r.y):
                            self.enemies.remove(e)
                            self.score += CRUSH_SCORE
                else:
                    r.falling = False
            elif below_open:
                r.falling = True  # 下方被挖空, 开始下落

    def _move_enemies(self):
        for e in list(self.enemies):
            if e.hooked:
                continue
            in_tunnel = self.grid[e.y][e.x] == TUNNEL
            if in_tunnel:
                if self.tick_n % 2 != 0:
                    continue  # 隧道里速度是玩家的一半, 不然没法玩
            elif self.tick_n % 3 != 0:
                continue  # 在泥土里穿行更慢
            dx = (self.px > e.x) - (self.px < e.x)
            dy = (self.py > e.y) - (self.py < e.y)
            if abs(self.px - e.x) >= abs(self.py - e.y):
                tries = [(dx, 0), (0, dy)]
            else:
                tries = [(0, dy), (dx, 0)]
            for mx, my in tries:
                nx, ny = e.x + mx, e.y + my
                if self._in_bounds(nx, ny) and self._rock_at(nx, ny) is None:
                    e.x, e.y = nx, ny
                    break
            if (e.x, e.y) == (self.px, self.py):
                self._kill_player()
                if self.over:
                    return

    def _deflate(self):
        for e in self.enemies:
            if e.inflation > 0:
                e.cool += 1
                if e.cool >= DEFLATE_TICKS:
                    e.inflation -= 1
                    e.cool = 0
                    if e.inflation == 0:
                        e.hooked = False

    def _kill_player(self):
        self.lives -= 1
        for e in self.enemies:
            e.hooked = False
            e.inflation = 0
        if self.lives <= 0:
            self.over = True
        else:
            self.px, self.py = 1, 1
            self.facing = RIGHT
            self.grid[1][1] = TUNNEL
            self._scatter_enemies()

    def _scatter_enemies(self):
        """重生后把敌人散开, 避免重生点被守尸导致连续瞬死。"""
        for e in self.enemies:
            for _ in range(100):
                x = self.rng.randrange(self.w)
                y = self.rng.randrange(2, self.h)
                if (abs(x - self.px) + abs(y - self.py) >= 6
                        and self._rock_at(x, y) is None):
                    e.x, e.y = x, y
                    break

    # ---------- 渲染 ----------

    def render(self):
        rows = []
        for y in range(self.h):
            row = []
            for x in range(self.w):
                ch = self.grid[y][x]
                r = self._rock_at(x, y)
                if r is not None:
                    ch = "o" if r.falling else "O"
                e = self._enemy_at(x, y)
                if e is not None:
                    ch = str(e.inflation) if e.inflation > 0 else e.kind
                if (x, y) == (self.px, self.py):
                    ch = "@"
                row.append(ch)
            rows.append("".join(row))
        return "\n".join(rows)


# ---------- 自动演示 AI ----------

def _firing_dir(g, px, py):
    """从 (px,py) 沿四个朝向看, 返回能打中敌人的朝向名, 没有则返回 None。
    要求整条线都是已挖通的隧道(泥土/石头挡住打气筒)。"""
    for name, (dx, dy) in DIRS.items():
        x, y = px, py
        for _ in range(PUMP_RANGE):
            x, y = x + dx, y + dy
            if not g._in_bounds(x, y):
                break
            if g.grid[y][x] != TUNNEL:
                break
            if g._rock_at(x, y) is not None:
                break
            if g._enemy_at(x, y) is not None:
                return name
    return None


def ai_decide(g):
    """贪心+走位 AI: 有勾住的敌人就打气; 有射击角度就开火;
    否则走位——优先走到能狙击的位置, 危险时拉开距离, 平时靠近敌人。"""
    for e in g.enemies:
        if e.hooked:
            return "pump"
    px, py = g.px, g.py
    d = _firing_dir(g, px, py)
    if d is not None:
        return "fire" if g.facing == DIRS[d] else "aim_" + d
    if not g.enemies:
        return "wait"
    cands = []
    for name, (dx, dy) in DIRS.items():
        nx, ny = px + dx, py + dy
        if not g._in_bounds(nx, ny):
            continue
        if g._rock_at(nx, ny) is not None:
            continue
        if g._enemy_at(nx, ny) is not None:
            continue
        # 别挖石头正下方的土(石头会掉下来砸到自己)
        under_rock = g._rock_at(nx, ny - 1) is not None
        dmin = min(abs(e.x - nx) + abs(e.y - ny) for e in g.enemies)
        fire_after = _firing_dir(g, nx, ny) is not None
        cands.append({"name": name, "under_rock": under_rock,
                      "dmin": dmin, "fire_after": fire_after})
    if not cands:
        return "wait"
    # 1) 能走到狙击位且不贴脸 -> 去狙击
    snipes = [c for c in cands
              if c["fire_after"] and c["dmin"] >= 2 and not c["under_rock"]]
    if snipes:
        return sorted(snipes, key=lambda c: (-c["dmin"], c["name"]))[0]["name"]
    # 2) 敌人贴脸(距离<=2) -> 拉开距离
    dmin_now = min(abs(e.x - px) + abs(e.y - py) for e in g.enemies)
    if dmin_now <= 2:
        safe = [c for c in cands if not c["under_rock"]] or cands
        return sorted(safe, key=lambda c: (-c["dmin"], c["name"]))[0]["name"]
    # 3) 平时 -> 靠近最近的敌人, 但不贴脸
    ok = [c for c in cands if c["dmin"] >= 2 and not c["under_rock"]] or cands
    target = min(g.enemies, key=lambda e: abs(e.x - px) + abs(e.y - py))

    def approach(c):
        dx, dy = DIRS[c["name"]]
        return abs(target.x - (px + dx)) + abs(target.y - (py + dy))

    return sorted(ok, key=lambda c: (approach(c), c["name"]))[0]["name"]


def auto_play(game, max_moves):
    moves = 0
    while not game.over and moves < max_moves:
        game.step(ai_decide(game))
        moves += 1
    return moves


# ---------- 命令行 ----------

KEYMAP = {
    "w": "up", "s": "down", "a": "left", "d": "right",
    "i": "aim_up", "k": "aim_down", "j": "aim_left", "l": "aim_right",
    "f": "fire", "p": "pump", ".": "wait", " ": "wait",
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="digdug-lite —— 极简《打空气》克隆(纯标准库)")
    ap.add_argument("--seed", type=int, default=0, help="随机种子")
    ap.add_argument("--auto", action="store_true", help="无头自动演示")
    ap.add_argument("--moves", type=int, default=400, help="自动演示最大步数")
    ap.add_argument("--enemies", type=int, default=4, help="敌人数量")
    ap.add_argument("--rocks", type=int, default=3, help="石头数量")
    args = ap.parse_args(argv)

    game = Game(seed=args.seed, n_enemies=args.enemies, n_rocks=args.rocks)
    if args.auto:
        moves = auto_play(game, args.moves)
        if game.won:
            result = "胜利"
        elif game.over:
            result = "失败"
        else:
            result = "步数用完"
        print(f"自动演示结束: {result}, 得分 {game.score}, "
              f"剩余敌人 {len(game.enemies)}, 剩余生命 {game.lives}, 步数 {moves}")
        return 0

    if not sys.stdin.isatty():
        print("交互模式需要终端, 请用 --auto 运行无头演示", file=sys.stderr)
        return 2
    print("操作: w/a/s/d 移动挖土 | i/k/j/l 瞄准上下左右 | "
          "f 发射打气筒 | p 打气 | . 等待 | q 退出")
    print("图例: @你 PF敌人 数字=充气格 O石头 #泥土")
    while not game.over:
        print(game.render())
        print(f"得分 {game.score}  生命 {game.lives}  敌人 {len(game.enemies)}")
        try:
            line = input("> ").strip().lower()
        except EOFError:
            break
        if line in ("q", "quit", "exit"):
            break
        action = KEYMAP.get(line, "wait")
        game.step(action)
    print(game.render())
    print("过关! " if game.won else "游戏结束! ", f"最终得分 {game.score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
