# ============================================================
#  🤖 무잔 코인 디스코드 봇 (bot.py) — SQLite 완성본
#  만든이: 무잔 서버용
#  사용 라이브러리: discord.py
# ============================================================

import discord
from discord.ext import commands, tasks
import sqlite3
import os
import random
import re

# ──────────────────────────────────────────────
#  ✅ 1. 봇 토큰 설정
# ──────────────────────────────────────────────
access_token - os.environ["BOT_TOKEN"]
TOKEN = "access_token"

# ══════════════════════════════════════════════
#  🗄️ SQLite DB 설정
# ══════════════════════════════════════════════
DB_FILE = "data.db"

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """DB 테이블 초기화 (최초 1회만 실행)"""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                gamble_win_streak INTEGER DEFAULT 0,
                gamble_lose_streak INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_stocks (
                user_id TEXT,
                stock_id TEXT,
                qty INTEGER DEFAULT 0,
                avg_price INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, stock_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                stock_id TEXT PRIMARY KEY,
                name TEXT,
                start_price INTEGER,
                max_price INTEGER,
                current_price INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_history (
                stock_id TEXT,
                price INTEGER,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

# ══════════════════════════════════════════════
#  📁 SQLite 데이터 헬퍼 함수
# ══════════════════════════════════════════════

def get_user(user_id: str) -> dict:
    """유저 데이터 가져오기 (없으면 자동 생성)"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            return {"user_id": user_id, "balance": 0,
                    "gamble_win_streak": 0, "gamble_lose_streak": 0}
        return dict(row)

def save_user(user_id: str, balance: int, win_streak: int, lose_streak: int):
    """유저 데이터 저장"""
    with get_conn() as conn:
        conn.execute("""
            UPDATE users
            SET balance = ?, gamble_win_streak = ?, gamble_lose_streak = ?
            WHERE user_id = ?
        """, (balance, win_streak, lose_streak, user_id))
        conn.commit()

def get_user_stock(user_id: str, stock_id: str) -> dict:
    """유저의 특정 주식 보유량 가져오기"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_stocks WHERE user_id = ? AND stock_id = ?",
            (user_id, stock_id)
        ).fetchone()
        if row is None:
            return {"qty": 0, "avg_price": 0}
        return dict(row)

def save_user_stock(user_id: str, stock_id: str, qty: int, avg_price: int):
    """유저의 주식 보유량 저장 (없으면 생성, 있으면 업데이트)"""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_stocks (user_id, stock_id, qty, avg_price)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, stock_id)
            DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price
        """, (user_id, stock_id, qty, avg_price))
        conn.commit()

def get_all_stocks() -> list:
    """모든 주식 종목 가져오기"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM stocks").fetchall()
        return [dict(row) for row in rows]

def get_stock(stock_id: str):
    """특정 주식 종목 가져오기 (없으면 None)"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM stocks WHERE stock_id = ?", (stock_id,)
        ).fetchone()
        return dict(row) if row else None

def get_stock_history(stock_id: str, limit: int = 10) -> list:
    """주식 가격 히스토리 가져오기 (오래된 순)"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT price FROM stock_history
            WHERE stock_id = ?
            ORDER BY rowid DESC
            LIMIT ?
        """, (stock_id, limit)).fetchall()
        return [row["price"] for row in reversed(rows)]

def get_all_users() -> list:
    """모든 유저 데이터 가져오기"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
        return [dict(row) for row in rows]

# ──────────────────────────────────────────────
#  ✅ 2. 봇 인텐트(권한) 설정
# ──────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ══════════════════════════════════════════════
#  💰 숫자 포맷 함수 (한국식 단위 변환)
# ══════════════════════════════════════════════

def format_number(n: int) -> str:
    if n is None:
        return "0원"
    n = int(n)
    if n == 0:
        return "0원"
    negative = n < 0
    n = abs(n)
    parts = []
    if n >= 1_000_000_000_000:
        parts.append(f"{n // 1_000_000_000_000}조")
        n %= 1_000_000_000_000
    if n >= 100_000_000:
        parts.append(f"{n // 100_000_000}억")
        n %= 100_000_000
    if n >= 10_000:
        parts.append(f"{n // 10_000}만")
        n %= 10_000
    if n > 0:
        parts.append(str(n))
    result = " ".join(parts) + "원"
    return ("-" + result) if negative else result

def parse_number(s: str) -> int:
    s = s.strip().replace(",", "")
    if re.fullmatch(r"\d+", s):
        return int(s)
    result = 0
    jo_m  = re.search(r"(\d+)\s*조", s)
    eok_m = re.search(r"(\d+)\s*억", s)
    man_m = re.search(r"(\d+)\s*만", s)
    won_m = re.search(r"(\d+)\s*원", s)
    if jo_m:  result += int(jo_m.group(1))  * 1_000_000_000_000
    if eok_m: result += int(eok_m.group(1)) * 100_000_000
    if man_m: result += int(man_m.group(1)) * 10_000
    if won_m: result += int(won_m.group(1))
    return result

# ══════════════════════════════════════════════
#  🔠 초성 서브명령어 매핑
# ══════════════════════════════════════════════

STOCK_SUBCMD_MAP = {
    "차트": "차트", "ㅊㅌ": "차트",
    "구매": "구매", "ㄱㅁ": "구매", "ㄱㅂ": "구매",
    "판매": "판매", "ㅍㅁ": "판매",
}
DON_SUBCMD_MAP = {
    "순위": "순위", "ㅅㅇ": "순위", "ㅅㄴ": "순위",
    "지급": "지급", "ㅈㄱ": "지급",
}
JONGMOK_SUBCMD_MAP = {
    "추가": "추가", "ㅊㄱ": "추가",
}

# ══════════════════════════════════════════════
#  🔒 관리자 확인 / 🎲 도박 확률 계산
# ══════════════════════════════════════════════

def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator

def get_gamble_probs(win_streak: int, lose_streak: int):
    win_prob  = max(0.10 / (2 ** win_streak),  0.01)
    lose_prob = max(0.20 / (2 ** lose_streak), 0.02)
    return win_prob, lose_prob

# ══════════════════════════════════════════════
#  📈 주식 가격 자동 업데이트 (1분마다)
# ══════════════════════════════════════════════

@tasks.loop(minutes=1)
async def update_stock_prices():
    stocks = get_all_stocks()
    if not stocks:
        return
    with get_conn() as conn:
        for stock in stocks:
            stock_id  = stock["stock_id"]
            start     = stock["start_price"]
            max_price = stock["max_price"]
            current   = stock["current_price"]

            price_range = max_price - start
            max_change  = max(price_range * 0.02, 1)
            change      = random.uniform(-max_change, max_change)
            change      += random.uniform(-0.3, 0.3) * max_change * 0.5
            new_price   = int(max(start, min(max_price, current + change)))

            conn.execute(
                "UPDATE stocks SET current_price = ? WHERE stock_id = ?",
                (new_price, stock_id)
            )
            conn.execute(
                "INSERT INTO stock_history (stock_id, price) VALUES (?, ?)",
                (stock_id, new_price)
            )
        conn.commit()

# ══════════════════════════════════════════════
#  🟢 봇 시작 이벤트
# ══════════════════════════════════════════════

@bot.event
async def on_ready():
    print("=" * 45)
    print(f"  ✅ 봇 로그인 성공!")
    print(f"  🤖 봇 이름: {bot.user.name}")
    print(f"  🆔 봇 ID  : {bot.user.id}")
    print("=" * 45)
    print("  📈 주식 가격 자동 업데이트 시작 (1분 주기)")
    print("=" * 45)
    update_stock_prices.start()

# ══════════════════════════════════════════════
#  🎰 명령어 1: !도박 / !ㄷㅂ
# ══════════════════════════════════════════════

@bot.command(name="도박", aliases=["ㄷㅂ"])
async def cmd_gamble(ctx, amount_str: str = None):
    if amount_str is None:
        embed = discord.Embed(
            title="🎰 도박 사용법",
            description=(
                "`!도박 (금액)` 또는 `!ㄷㅂ (금액)`\n\n"
                "**예시**\n"
                "• `!도박 100만`\n• `!도박 1억`\n• `!ㄷㅂ 5000`"
            ),
            color=0xffa500
        )
        await ctx.send(embed=embed)
        return

    try:
        amount = parse_number(amount_str)
    except Exception:
        await ctx.send("❌ 금액을 올바르게 입력해주세요!\n예) `100만`, `1억`, `5000`")
        return

    if amount <= 0:
        await ctx.send("❌ 1원 이상 입력해주세요!")
        return

    user_id = str(ctx.author.id)
    user    = get_user(user_id)
    balance = user["balance"]

    if balance < amount:
        await ctx.send(
            f"❌ **잔액 부족!**\n"
            f"현재 잔액: **{format_number(balance)}**\n"
            f"필요 금액: **{format_number(amount)}**"
        )
        return

    win_streak  = user["gamble_win_streak"]
    lose_streak = user["gamble_lose_streak"]
    win_prob, lose_prob = get_gamble_probs(win_streak, lose_streak)
    rand = random.random()

    if rand < win_prob:
        # ✅ 성공
        new_balance    = balance + amount
        new_win_streak = win_streak + 1
        new_lose_streak = 0
        save_user(user_id, new_balance, new_win_streak, new_lose_streak)

        next_win_prob, _ = get_gamble_probs(new_win_streak, new_lose_streak)
        embed = discord.Embed(
            title="🎰 도박 결과 — 성공!",
            description=f"🎉 **{format_number(amount)}** 을(를) 획득했습니다!",
            color=0x00ff00
        )
        embed.add_field(name="💰 현재 잔액",     value=format_number(new_balance),          inline=True)
        embed.add_field(name="🔥 연속 성공",      value=f"{new_win_streak}번",               inline=True)
        embed.add_field(name="📊 다음 성공 확률", value=f"{next_win_prob * 100:.2f}%",       inline=True)

    elif rand < win_prob + lose_prob:
        # ❌ 실패
        new_balance     = balance - amount
        new_win_streak  = 0
        new_lose_streak = lose_streak + 1
        save_user(user_id, new_balance, new_win_streak, new_lose_streak)

        _, next_lose_prob = get_gamble_probs(new_win_streak, new_lose_streak)
        embed = discord.Embed(
            title="🎰 도박 결과 — 실패...",
            description=f"💸 **{format_number(amount)}** 을(를) 잃었습니다...",
            color=0xff0000
        )
        embed.add_field(name="💰 현재 잔액",     value=format_number(new_balance),          inline=True)
        embed.add_field(name="💀 연속 실패",      value=f"{new_lose_streak}번",              inline=True)
        embed.add_field(name="📊 다음 실패 확률", value=f"{next_lose_prob * 100:.2f}%",      inline=True)

    else:
        # 🟡 비김
        save_user(user_id, balance, 0, 0)
        embed = discord.Embed(
            title="🎰 도박 결과 — 비김!",
            description="😐 아무 일도 일어나지 않았습니다. 다음엔 행운이 있기를!",
            color=0xffff00
        )
        embed.add_field(name="💰 현재 잔액", value=format_number(balance),  inline=True)
        embed.add_field(name="📊 성공 확률", value="10.00% (초기화)",       inline=True)

    embed.set_footer(text=f"{ctx.author.display_name}의 도박 결과")
    await ctx.send(embed=embed)

# ══════════════════════════════════════════════
#  📊 명령어 2: !주식 / !ㅈㅅ
# ══════════════════════════════════════════════

@bot.command(name="주식", aliases=["ㅈㅅ"])
async def cmd_stock(ctx, subcmd: str = None, *args):
    if subcmd is None:
        embed = discord.Embed(
            title="📊 주식 명령어 안내",
            description=(
                "`!주식 차트` — 주식 목록 & 현재 가격 확인\n"
                "`!주식 구매 (종목ID) (수량)` — 주식 구매\n"
                "`!주식 판매 (종목ID) (수량)` — 주식 판매\n\n"
                "**초성도 가능해요!**\n"
                "`!ㅈㅅ ㅊㅌ` / `!ㅈㅅ ㄱㅂ MUJN 10` / `!ㅈㅅ ㅍㅁ MUJN 5`"
            ),
            color=0x0099ff
        )
        await ctx.send(embed=embed)
        return

    subcmd  = STOCK_SUBCMD_MAP.get(subcmd, subcmd)
    user_id = str(ctx.author.id)
    get_user(user_id)  # 유저 없으면 자동 생성

    # ── 📋 차트 ──
    if subcmd == "차트":
        stocks = get_all_stocks()
        if not stocks:
            await ctx.send(
                "📊 아직 등록된 주식 종목이 없습니다!\n"
                "관리자에게 `!종목 추가` 명령어를 요청해보세요."
            )
            return

        embed = discord.Embed(title="📊 무잔 주식 차트", color=0x0099ff)
        for i, stock in enumerate(stocks, 1):
            sid     = stock["stock_id"]
            current = stock["current_price"]
            start   = stock["start_price"]
            max_p   = stock["max_price"]
            history = get_stock_history(sid, 10)

            if len(history) >= 2:
                diff = current - history[-2]
                if diff > 0:
                    arrow, diff_txt = "📈", f"+{format_number(diff)}"
                elif diff < 0:
                    arrow, diff_txt = "📉", f"-{format_number(abs(diff))}"
                else:
                    arrow, diff_txt = "➡️", "변동 없음"
            else:
                arrow, diff_txt = "🆕", "신규 상장"

            embed.add_field(
                name  = f"{i}. {stock['name']}  `[{sid}]`",
                value = (
                    f"{arrow} **현재가: {format_number(current)}**  ({diff_txt})\n"
                    f"시작가: {format_number(start)} ｜ 최고가(상한): {format_number(max_p)}"
                ),
                inline=False
            )
        embed.set_footer(text="⏱ 1분마다 가격이 자동 업데이트됩니다!")
        await ctx.send(embed=embed)

    # ── 🛒 구매 ──
    elif subcmd == "구매":
        if len(args) < 2:
            await ctx.send(
                "❌ 사용법: `!주식 구매 (종목ID) (수량)`\n"
                "예) `!주식 구매 MUJN 10`\n"
                "종목 ID는 `!주식 차트`에서 확인하세요!"
            )
            return

        stock_id = args[0].upper()
        try:
            qty = int(args[1])
        except ValueError:
            await ctx.send("❌ 수량은 **숫자**로 입력해주세요! 예) `!주식 구매 MUJN 10`")
            return

        if qty <= 0:
            await ctx.send("❌ 1주 이상 입력해주세요!")
            return

        stock = get_stock(stock_id)
        if stock is None:
            await ctx.send(
                f"❌ 종목 `{stock_id}` 를 찾을 수 없어요!\n"
                "`!주식 차트` 명령어로 종목 목록을 확인해주세요."
            )
            return

        unit_price = stock["current_price"]
        total_cost = unit_price * qty
        user       = get_user(user_id)
        balance    = user["balance"]

        if balance < total_cost:
            await ctx.send(
                f"❌ **잔액 부족!**\n"
                f"필요 금액: **{format_number(total_cost)}**\n"
                f"현재 잔액: **{format_number(balance)}**"
            )
            return

        user_stock = get_user_stock(user_id, stock_id)
        old_qty    = user_stock["qty"]
        old_avg    = user_stock["avg_price"]
        new_qty    = old_qty + qty
        new_avg    = int(((old_qty * old_avg) + total_cost) / new_qty)
        new_balance = balance - total_cost

        save_user(user_id, new_balance, user["gamble_win_streak"], user["gamble_lose_streak"])
        save_user_stock(user_id, stock_id, new_qty, new_avg)

        embed = discord.Embed(title="🛒 주식 구매 완료!", color=0x00cc44)
        embed.add_field(name="📌 종목",        value=f"{stock['name']} ({stock_id})", inline=True)
        embed.add_field(name="📦 구매 수량",   value=f"{qty}주",                      inline=True)
        embed.add_field(name="💵 구매 단가",   value=format_number(unit_price),       inline=True)
        embed.add_field(name="💳 총 결제금액", value=format_number(total_cost),       inline=True)
        embed.add_field(name="📊 평균 단가",   value=format_number(new_avg),          inline=True)
        embed.add_field(name="💰 잔여 코인",   value=format_number(new_balance),      inline=True)
        embed.set_footer(text=f"{ctx.author.display_name}님의 주식 구매")
        await ctx.send(embed=embed)

    # ── 💰 판매 ──
    elif subcmd == "판매":
        if len(args) < 2:
            await ctx.send(
                "❌ 사용법: `!주식 판매 (종목ID) (수량)`\n"
                "예) `!주식 판매 MUJN 10`\n"
                "전량 판매하려면 수량 자리에 `전부` 입력!"
            )
            return

        stock_id  = args[0].upper()
        qty_input = args[1]

        stock = get_stock(stock_id)
        if stock is None:
            await ctx.send(f"❌ 종목 `{stock_id}` 를 찾을 수 없어요!")
            return

        user_stock = get_user_stock(user_id, stock_id)
        if user_stock["qty"] <= 0:
            await ctx.send(f"❌ 보유한 `{stock_id}` 주식이 없습니다!")
            return

        if qty_input in ["전부", "전", "all", "ALL"]:
            qty = user_stock["qty"]
        else:
            try:
                qty = int(qty_input)
            except ValueError:
                await ctx.send("❌ 수량은 숫자 또는 `전부`로 입력해주세요!")
                return

        if qty <= 0:
            await ctx.send("❌ 1주 이상 입력해주세요!")
            return

        if qty > user_stock["qty"]:
            await ctx.send(
                f"❌ 보유 수량 초과!\n"
                f"현재 보유: **{user_stock['qty']}주**"
            )
            return

        unit_price  = stock["current_price"]
        total_gain  = unit_price * qty
        avg_price   = user_stock["avg_price"]
        profit      = (unit_price - avg_price) * qty

        user        = get_user(user_id)
        new_balance = user["balance"] + total_gain
        new_qty     = user_stock["qty"] - qty

        save_user(user_id, new_balance, user["gamble_win_streak"], user["gamble_lose_streak"])
        save_user_stock(user_id, stock_id, new_qty, avg_price)

        profit_icon = "🟢 +" if profit >= 0 else "🔴 -"
        embed = discord.Embed(title="💸 주식 판매 완료!", color=0xff6600)
        embed.add_field(name="📌 종목",        value=f"{stock['name']} ({stock_id})",          inline=True)
        embed.add_field(name="📦 판매 수량",   value=f"{qty}주",                               inline=True)
        embed.add_field(name="💵 판매 단가",   value=format_number(unit_price),                inline=True)
        embed.add_field(name="💳 총 판매금액", value=format_number(total_gain),                inline=True)
        embed.add_field(name="📈 손익",        value=f"{profit_icon}{format_number(abs(profit))}", inline=True)
        embed.add_field(name="💰 잔여 코인",   value=format_number(new_balance),               inline=True)
        embed.set_footer(text=f"{ctx.author.display_name}님의 주식 판매")
        await ctx.send(embed=embed)

    else:
        await ctx.send(
            "❌ 올바른 서브명령어를 입력하세요!\n"
            "`!주식 차트` / `!주식 구매` / `!주식 판매`"
        )

# ══════════════════════════════════════════════
#  💵 명령어 3: !돈 / !ㄷ
# ══════════════════════════════════════════════

@bot.command(name="돈", aliases=["ㄷ"])
async def cmd_don(ctx, subcmd: str = None, *args):
    if subcmd is None:
        embed = discord.Embed(
            title="💵 돈 명령어 안내",
            description=(
                "`!돈 순위` — 서버 내 무잔 코인 부자 순위 확인\n"
                "`!돈 지급 @유저 금액` — (관리자) 유저에게 코인 지급\n\n"
                "**초성도 가능!**\n"
                "`!ㄷ ㅅㅇ` / `!ㄷ ㅈㄱ @유저 100만`"
            ),
            color=0xffd700
        )
        await ctx.send(embed=embed)
        return

    subcmd = DON_SUBCMD_MAP.get(subcmd, subcmd)

    # ── 🏆 순위 ──
    if subcmd == "순위":
        all_users = get_all_users()
        guild     = ctx.guild
        user_list = []

        for udata in all_users:
            member = guild.get_member(int(udata["user_id"]))
            if member:
                user_list.append((member.display_name, udata["balance"]))

        if not user_list:
            await ctx.send(
                "📊 아직 등록된 유저가 없습니다!\n"
                "먼저 `!도박` 또는 `!돈 지급`을 통해 코인을 획득하세요."
            )
            return

        user_list.sort(key=lambda x: x[1], reverse=True)
        embed  = discord.Embed(title="🏆 무잔 코인 부자 순위 TOP 20", color=0xffd700)
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        lines  = []
        for i, (name, bal) in enumerate(user_list[:20]):
            medal = medals.get(i, f"**{i+1}위**")
            lines.append(f"{medal} **{name}** ─ {format_number(bal)}")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"총 {len(user_list)}명의 유저가 참가 중!")
        await ctx.send(embed=embed)

    # ── 💸 지급 (관리자 전용) ──
    elif subcmd == "지급":
        if not is_admin(ctx.author):
            await ctx.send("❌ **이 명령어는 관리자만 사용 가능합니다!**")
            return

        if len(args) < 2:
            await ctx.send(
                "❌ 사용법: `!돈 지급 @유저 금액`\n"
                "예) `!돈 지급 @홍길동 100만`"
            )
            return

        try:
            if ctx.message.mentions:
                target = ctx.message.mentions[0]
            else:
                target = await commands.MemberConverter().convert(ctx, args[0])
        except Exception:
            await ctx.send("❌ 유저를 찾을 수 없습니다. `@멘션` 형식으로 입력해주세요!")
            return

        try:
            amount = parse_number(args[1])
        except Exception:
            await ctx.send("❌ 금액을 올바르게 입력하세요! 예) `100만`, `1억`")
            return

        if amount <= 0:
            await ctx.send("❌ 1원 이상 입력해주세요!")
            return

        uid_str  = str(target.id)
        user     = get_user(uid_str)
        new_bal  = user["balance"] + amount
        save_user(uid_str, new_bal, user["gamble_win_streak"], user["gamble_lose_streak"])

        embed = discord.Embed(title="💸 코인 지급 완료!", color=0x00ff88)
        embed.add_field(name="👤 받는 유저", value=target.mention,          inline=True)
        embed.add_field(name="💰 지급 금액", value=format_number(amount),   inline=True)
        embed.add_field(name="🏦 현재 잔액", value=format_number(new_bal),  inline=True)
        embed.set_footer(text=f"지급한 관리자: {ctx.author.display_name}")
        await ctx.send(embed=embed)

    else:
        await ctx.send(
            "❌ 올바른 서브명령어를 입력하세요!\n"
            "`!돈 순위` / `!돈 지급 @유저 금액`"
        )

# ══════════════════════════════════════════════
#  📌 명령어 4: !종목 / !ㅈㅁ (관리자 전용)
# ══════════════════════════════════════════════

@bot.command(name="종목", aliases=["ㅈㅁ"])
async def cmd_jongmok(ctx, subcmd: str = None, *args):
    if subcmd is None:
        embed = discord.Embed(
            title="📌 종목 명령어 안내",
            description=(
                "`!종목 추가 (종목ID) (종목이름) (시작가격) (최고가격)`\n"
                "**예시:** `!종목 추가 MUJN 무잔전자 1만 500만`\n\n"
                "⚠️ **관리자만 사용 가능합니다!**"
            ),
            color=0x5865f2
        )
        await ctx.send(embed=embed)
        return

    subcmd = JONGMOK_SUBCMD_MAP.get(subcmd, subcmd)

    if subcmd == "추가":
        if not is_admin(ctx.author):
            await ctx.send("❌ **이 명령어는 관리자만 사용 가능합니다!**")
            return

        if len(args) < 4:
            await ctx.send(
                "❌ 사용법: `!종목 추가 (종목ID) (종목이름) (시작가격) (최고가격)`\n"
                "예) `!종목 추가 MUJN 무잔전자 1만 500만`"
            )
            return

        stock_id      = args[0].upper()
        stock_name    = args[1]
        start_price_s = args[2]
        max_price_s   = args[3]

        try:
            start_price = parse_number(start_price_s)
            max_price   = parse_number(max_price_s)
        except Exception:
            await ctx.send("❌ 가격 형식이 올바르지 않아요!\n예) `1만`, `100억`, `500`")
            return

        if start_price <= 0 or max_price <= 0:
            await ctx.send("❌ 가격은 1원 이상이어야 합니다!")
            return

        if start_price >= max_price:
            await ctx.send(
                f"❌ **시작가격({format_number(start_price)})** 은 "
                f"**최고가격({format_number(max_price)})** 보다 낮아야 합니다!"
            )
            return

        if get_stock(stock_id) is not None:
            await ctx.send(
                f"❌ 이미 등록된 종목 ID입니다: `{stock_id}`\n"
                "`!주식 차트`로 기존 종목을 확인해주세요."
            )
            return

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO stocks (stock_id, name, start_price, max_price, current_price)
                VALUES (?, ?, ?, ?, ?)
            """, (stock_id, stock_name, start_price, max_price, start_price))
            conn.execute(
                "INSERT INTO stock_history (stock_id, price) VALUES (?, ?)",
                (stock_id, start_price)
            )
            conn.commit()

        embed = discord.Embed(title="✅ 새 주식 종목이 추가되었습니다!", color=0x5865f2)
        embed.add_field(name="📌 종목 ID",    value=f"`{stock_id}`",             inline=True)
        embed.add_field(name="🏷️ 종목 이름", value=stock_name,                  inline=True)
        embed.add_field(name="🟢 시작 가격",  value=format_number(start_price),  inline=True)
        embed.add_field(name="🔴 최고 가격",  value=format_number(max_price),    inline=True)
        embed.set_footer(text=f"등록한 관리자: {ctx.author.display_name}")
        await ctx.send(embed=embed)

    else:
        await ctx.send(
            "❌ 올바른 서브명령어를 입력하세요!\n"
            "`!종목 추가 (종목ID) (종목이름) (시작가격) (최고가격)`"
        )

# ══════════════════════════════════════════════
#  ❓ 도움말: !도움말 / !ㄷㅇㅁ
# ══════════════════════════════════════════════

@bot.command(name="도움말", aliases=["ㄷㅇㅁ", "help", "도움", "ㄷㅇ"])
async def cmd_help(ctx):
    embed = discord.Embed(
        title="📖 무잔 코인 봇 — 전체 명령어 안내",
        description="모든 명령어는 `!` 로 시작합니다. 초성으로도 사용 가능해요!",
        color=0x5865f2
    )
    embed.add_field(
        name="🎰 도박",
        value=(
            "`!도박 (금액)` / `!ㄷㅂ (금액)`\n"
            "예) `!도박 100만` / `!ㄷㅂ 1억`\n"
            "성공 10% | 실패 20% | 비김 70%\n"
            "연속 성공/실패 시 해당 확률이 절반으로 감소"
        ),
        inline=False
    )
    embed.add_field(
        name="📊 주식",
        value=(
            "`!주식 차트` — 종목 목록 & 현재 가격 조회\n"
            "`!주식 구매 (종목ID) (수량)` — 주식 구매\n"
            "`!주식 판매 (종목ID) (수량)` — 주식 판매 (`전부` 입력 시 전량 판매)\n"
            "초성: `!ㅈㅅ ㅊㅌ` / `!ㅈㅅ ㄱㅂ` / `!ㅈㅅ ㅍㅁ`"
        ),
        inline=False
    )
    embed.add_field(
        name="🏆 돈 순위",
        value=("`!돈 순위` / `!ㄷ ㅅㅇ`\n서버 내 무잔 코인 보유량 순위"),
        inline=False
    )
    embed.add_field(
        name="👑 관리자 전용 명령어",
        value=(
            "`!돈 지급 @유저 금액` / `!ㄷ ㅈㄱ @유저 금액`\n"
            "→ 특정 유저에게 무잔 코인 지급\n\n"
            "`!종목 추가 (ID) (이름) (시작가) (최고가)` / `!ㅈㅁ ㅊㄱ ...`\n"
            "→ 주식 종목 등록"
        ),
        inline=False
    )
    embed.set_footer(text="💡 숫자는 '100만', '1억', '3조' 등 한국 단위로 입력 가능!")
    await ctx.send(embed=embed)

# ══════════════════════════════════════════════
#  🚀 봇 실행
# ══════════════════════════════════════════════
init_db()

bot.run(TOKEN)
