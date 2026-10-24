import os
import re
import json
import socket
import asyncio
import aiohttp
import discord
from discord.ext import commands
from datetime import datetime


# โหลด secret จากไฟล์ .env (ไม่ commit/แชร์) ถ้ามี — ทำให้ key ไม่ต้องอยู่ในโค้ด
def _load_env(path=".env"):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_env()

# ╔══════════════════════════════════════════════════════════════════╗
#  ตั้งค่าทั้งหมด — แก้แค่ตรงนี้ที่เดียว
# ╚══════════════════════════════════════════════════════════════════╝

# ── Discord IDs ──────────────────────────────────────────────────────
PANEL_CHANNEL_ID     = 1563381720122794125   # ช่องที่วางแผงหลัก (Buy / Redeem / etc.)
TICKET_CATEGORY_ID   = 1535559557034672168   # Category สำหรับ ticket
STAFF_ROLE_ID        = 1558202136104407100   # ยศ Staff (เห็น ticket + confirm)
PREMIUM_ROLE_ID      = 1563397158957223986   # ยศที่แจกหลัง redeem / ซื้อสำเร็จ
LOG_CHANNEL_ID       = 1563386508893880432   # ช่อง log การขาย
VERIFY_CHANNEL_ID    = 1559237018976919612   # ช่อง verify (เดิม)
RULE_CHANNEL_ID      = 1541028569004908574   # ช่องกฎ
VERIFY_ROLE_ID       = 1541028157379846184   # ยศ verify

# ── Luarmor ──────────────────────────────────────────────────────────
LUARMOR_API_KEY      = os.getenv("LUARMOR_API_KEY", "")   # ตั้งใน .env / env var
LUARMOR_PROJECT_ID   = "28d32f3b3363ebfb4a7627cfd4633c70"
LUARMOR_API          = "https://api.luarmor.net/v3"
SCRIPT_LOADSTRING    = 'loadstring(game:HttpGet("https://api.luarmor.net/files/v4/loaders/cb1894c647c18c274340bb3869e4d582.lua"))()'

# ── Payment ───────────────────────────────────────────────────────────
PRODUCT_PRICE        = 99.0     # ราคาสินค้า (บาท)
TRUEMONEY_NUMBER     = "083-862-8791"   # เบอร์ TrueMoney ผู้รับ
RECEIVER_NAME_TH     = "ศุภมงคล เควิ่น เรย์"
SLIP2GO_SECRET_KEY   = os.getenv("SLIP2GO_SECRET_KEY", "")   # ตั้งใน .env / env var

# ── รูปภาพ ────────────────────────────────────────────────────────────
HUB_LOGO_URL         = "https://media.discordapp.net/attachments/1535518847464120363/1563394773224529991/logohub.gif?ex=6add7858&is=6adc26d8&hm=5b2b040e208096a78d6607ec01bdd1bb8958b3904411a4f72a5080a561dcd1ce&="
HUB_BANNER_URL       = "https://media.discordapp.net/attachments/1535518847464120363/1563394772796702821/bannerhub.gif?ex=6add7858&is=6adc26d8&hm=d996f29726c0597198e3843f618e2f9a681ff190faa14779794f403f47a3aa47&="   # ใส่ลิงก์รูป banner ถ้ามี (ใส่ "" ถ้าไม่ใช้)

# ── Keys file ─────────────────────────────────────────────────────────
KEYS_FILE            = "keys.txt"
TICKET_COUNT_FILE    = "ticket_count.json"
RR_FILE              = "reaction_roles.json"
QR_IMAGE_FILE        = "qr.png"   # รูป QR พร้อมเพย์ ส่งตอนเปิด ticket
USED_SLIPS_FILE      = "used_slips.txt"   # กันสลิปซ้ำ (เก็บ transRef ที่ใช้ไปแล้ว)

# ── สี embed ─────────────────────────────────────────────────────────
COLOR_SUCCESS = 0x57F287   # เขียว
COLOR_ERROR   = 0xED4245   # แดง
COLOR_INFO    = 0x5865F2   # ม่วง Discord
COLOR_WARN    = 0xFEE75C   # เหลือง
COLOR_MAIN    = 0x2B2D31   # เทาดำ (main panel)

# ════════════════════════════════════════════════════════════════════
#  Bot Setup
# ════════════════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ════════════════════════════════════════════════════════════════════
#  Helper: Keys
# ════════════════════════════════════════════════════════════════════
_key_lock = asyncio.Lock()

def _is_valid_key_line(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith("---")

async def _pop_key() -> str | None:
    async with _key_lock:
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                keys = [k.strip() for k in f if _is_valid_key_line(k)]
            if not keys:
                return None
            key = keys.pop(0)
            with open(KEYS_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(keys) + ("\n" if keys else ""))
            return key
        except FileNotFoundError:
            return None

async def _remove_specific_key(key: str) -> bool:
    """Remove a specific key from keys.txt. Returns True if found and removed."""
    async with _key_lock:
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                keys = [k.strip() for k in f if _is_valid_key_line(k)]
            if key not in keys:
                return False
            keys.remove(key)
            with open(KEYS_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(keys) + ("\n" if keys else ""))
            return True
        except FileNotFoundError:
            return False

def _count_keys() -> int:
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return len([k for k in f if _is_valid_key_line(k)])
    except Exception:
        return 0

def _slip_used(ref: str) -> bool:
    """สลิป (transRef) นี้เคยถูกใช้ไปแล้วไหม — กันใช้สลิปซ้ำแลก key"""
    if not ref:
        return False
    try:
        with open(USED_SLIPS_FILE, "r", encoding="utf-8") as f:
            return any(line.strip() == ref for line in f)
    except FileNotFoundError:
        return False
    except Exception:
        return False

def _mark_slip_used(ref: str):
    if not ref:
        return
    with open(USED_SLIPS_FILE, "a", encoding="utf-8") as f:
        f.write(ref + "\n")

def _load_ticket_count() -> int:
    try:
        with open(TICKET_COUNT_FILE) as f:
            return json.load(f).get("count", 0)
    except Exception:
        return 0

def _save_ticket_count(n: int):
    with open(TICKET_COUNT_FILE, "w") as f:
        json.dump({"count": n}, f)

def _buyer_id_from_topic(topic: str | None) -> int | None:
    if not topic:
        return None
    m = re.search(r'\((\d+)\)', topic)
    return int(m.group(1)) if m else None

def _is_staff(member: discord.Member) -> bool:
    role = member.guild.get_role(STAFF_ROLE_ID)
    return member.guild_permissions.administrator or (role in member.roles if role else False)

# ════════════════════════════════════════════════════════════════════
#  Helper: Luarmor API
# ════════════════════════════════════════════════════════════════════
_LM_GET_HDR  = lambda: {"Authorization": LUARMOR_API_KEY, "Content-Type": "application/json"}
_LM_POST_HDR = lambda: {"Authorization": LUARMOR_API_KEY, "Content-Type": "application/json"}


def _session() -> aiohttp.ClientSession:
    """Session that forces IPv4. Luarmor's Cloudflare allows only whitelisted
    IPs; this host's IPv6 is a rotating privacy address that isn't whitelisted,
    so requests must go out over the (whitelisted) IPv4 address."""
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET))

async def lm_get_key(key: str) -> dict | None:
    url = f"{LUARMOR_API}/projects/{LUARMOR_PROJECT_ID}/users"
    async with _session() as s:
        async with s.get(url, headers=_LM_GET_HDR(), params={"user_key": key}) as r:
            text = await r.text()
            print(f"[LM lm_get_key] {r.status} {r.url}\n  → {text[:300]}")
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            users = data.get("users", [])
            return users[0] if users else None

async def lm_get_user_key(discord_id: str) -> str | None:
    url = f"{LUARMOR_API}/projects/{LUARMOR_PROJECT_ID}/users"
    async with _session() as s:
        async with s.get(url, headers=_LM_GET_HDR(), params={"discord_id": discord_id}) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
            users = data.get("users", [])
            return users[0].get("user_key") if users else None

async def lm_link_discord(key: str, discord_id: int) -> bool:
    url = f"{LUARMOR_API}/projects/{LUARMOR_PROJECT_ID}/users/linkdiscord"
    async with _session() as s:
        async with s.post(url, headers=_LM_POST_HDR(),
                          json={"user_key": key, "discord_id": str(discord_id), "force": True}) as r:
            text = await r.text()
            print(f"[LM link_discord] {r.status} → {text[:200]}")
            return r.status == 200

async def lm_reset_hwid(key: str) -> bool:
    url = f"{LUARMOR_API}/projects/{LUARMOR_PROJECT_ID}/users/resethwid"
    async with _session() as s:
        async with s.post(url, headers=_LM_POST_HDR(),
                          json={"user_key": key, "force": True}) as r:
            return r.status == 200

# ════════════════════════════════════════════════════════════════════
#  Helper: Slip2Go API (ตรวจสลิป)
# ════════════════════════════════════════════════════════════════════
_S2G_BASE = "https://connect.slip2go.com"

async def verify_slip(image_bytes: bytes, filename: str) -> dict | None:
    """ส่งรูปสลิปไปตรวจกับ Slip2Go"""
    if not SLIP2GO_SECRET_KEY or SLIP2GO_SECRET_KEY.startswith("ใส่"):
        return None

    url = f"{_S2G_BASE}/api/verify-slip/qr-image/info"
    headers = {"Authorization": f"Bearer {SLIP2GO_SECRET_KEY}"}   # Slip2Go ต้องมี Bearer

    import json as _json
    payload_json = _json.dumps({
        "checkDuplicate": True,          # กันสลิปซ้ำ
        "checkReceiver": [               # ตรวจบัญชีผู้รับ
            {"type": "PROMPTPAY", "account": TRUEMONEY_NUMBER}
        ]
    })

    # ใช้ content-type ให้ตรงชนิดรูปจริง (สลิป KPlus เป็น .png — เดิม hardcode jpeg)
    import mimetypes
    ctype = mimetypes.guess_type(filename)[0] or "image/png"

    form = aiohttp.FormData()
    form.add_field("file", image_bytes, filename=filename, content_type=ctype)
    form.add_field("payload", payload_json, content_type="application/json")

    async with _session() as s:
        async with s.post(url, headers=headers, data=form) as r:
            text = await r.text()
            print(f"[Slip2Go] HTTP {r.status} → {text[:600]}")   # debug: ดู response จริง
            if 200 <= r.status < 300:        # Slip2Go ตอบ 201 ตอนสำเร็จ
                try:
                    import json as _j2
                    return _j2.loads(text)
                except Exception:
                    return {"_fallback": True, "status": r.status, "body": text[:300]}
            return {"_fallback": True, "status": r.status, "body": text[:300]}

def _digits4(s) -> str:
    """4 ตัวท้ายของเลข (ใช้เทียบเลขพร้อมเพย์/บัญชีที่ถูก mask)"""
    d = re.sub(r"\D", "", str(s or ""))
    return d[-4:] if len(d) >= 4 else d


def slip_is_valid(slip_data: dict) -> tuple[bool, str]:
    """ตรวจสลิปจาก response ของ Slip2Go: คืน (valid, reason).

    รูปแบบจริง: { "code":"200200", "message":"Slip is valid.",
                 "data":{ "amount":99, "transRef":"...",
                          "receiver":{ "account":{"name":...},
                                       "proxy":{"account":"xxx-xxx-8791"} } } }
    """
    try:
        if slip_data.get("_fallback"):
            return False, f"ส่ง API ไม่สำเร็จ (status {slip_data.get('status')}) — รอ Staff confirm"

        code = str(slip_data.get("code", ""))
        msg  = str(slip_data.get("message", ""))
        data = slip_data.get("data") or {}

        # สำเร็จเมื่อ code 200200 หรือข้อความบอกว่า valid
        if not (code == "200200" or "valid" in msg.lower()):
            if "duplicate" in msg.lower() or "ซ้ำ" in msg:
                return False, "❌ สลิปนี้ใช้ไปแล้ว ห้ามใช้ซ้ำ"
            return False, msg or "สลิปไม่ถูกต้อง"

        amount = float(data.get("amount", 0) or 0)
        if amount < PRODUCT_PRICE:
            return False, f"ยอดเงิน **{amount:.2f} บาท** ไม่ถูกต้อง (ต้องการ {PRODUCT_PRICE:.2f} บาท)"

        # ยืนยันผู้รับ: เลขพร้อมเพย์ 4 ตัวท้าย (เชื่อถือได้กว่าชื่อที่ถูก mask)
        recv       = data.get("receiver", {}) or {}
        proxy_acct = ((recv.get("proxy") or {}).get("account") or "")
        recv_name  = ((recv.get("account") or {}).get("name") or recv.get("name") or "")
        p4, t4     = _digits4(proxy_acct), _digits4(TRUEMONEY_NUMBER)
        name_first = RECEIVER_NAME_TH.split()[0] if RECEIVER_NAME_TH else ""

        if p4 and t4:
            if p4 != t4:
                return False, f"โอนผิดบัญชี (ผู้รับลงท้าย {p4})"
        elif name_first and recv_name and name_first not in recv_name:
            return False, f"ชื่อผู้รับไม่ตรง: **{recv_name}**"

        return True, f"ยอด {amount:.2f} บาท → ผู้รับลงท้าย {p4 or '—'} ✓"
    except Exception as e:
        return False, f"อ่านข้อมูลสลิปไม่ได้ ({e})"

# ════════════════════════════════════════════════════════════════════
#  Helper: Log channel
# ════════════════════════════════════════════════════════════════════
async def send_log(guild: discord.Guild, title: str, desc: str,
                   color: int = COLOR_SUCCESS, buyer: discord.Member = None):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if not ch:
        return
    embed = discord.Embed(title=title, description=desc,
                          color=color, timestamp=datetime.now())
    if buyer:
        embed.set_thumbnail(url=buyer.display_avatar.url)
        embed.set_footer(text=f"{buyer} • {buyer.id}")
    await ch.send(embed=embed)

# ════════════════════════════════════════════════════════════════════
#  Reaction Roles (ระบบเดิม)
# ════════════════════════════════════════════════════════════════════
def load_rr():
    try:
        with open(RR_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_rr():
    with open(RR_FILE, "w", encoding="utf-8") as f:
        json.dump(reaction_roles, f, ensure_ascii=False, indent=2)

reaction_roles = load_rr()

def key_from_input(s):
    s = s.strip()
    m = re.fullmatch(r'<a?:\w+:(\d+)>', s)
    return m.group(1) if m else s

def emoji_key(e):
    if getattr(e, "id", None):
        return str(e.id)
    return str(getattr(e, "name", e))

async def handle_reaction(payload, add):
    mapping = reaction_roles.get(str(payload.message_id))
    if not mapping:
        return
    role_id = mapping.get(emoji_key(payload.emoji))
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(int(role_id))
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
            return
    if member.bot or not role:
        return
    try:
        if add:
            await member.add_roles(role, reason="reaction role")
        else:
            await member.remove_roles(role, reason="reaction role")
    except discord.Forbidden:
        pass

@bot.event
async def on_raw_reaction_add(payload):
    await handle_reaction(payload, add=True)

@bot.event
async def on_raw_reaction_remove(payload):
    await handle_reaction(payload, add=False)

# ════════════════════════════════════════════════════════════════════
#  Modals
# ════════════════════════════════════════════════════════════════════
class RedeemModal(discord.ui.Modal, title="🔑 กรอก Key ของคุณ"):
    key_input = discord.ui.TextInput(
        label="Key",
        placeholder="XXXX-XXXX-XXXX-XXXX",
        min_length=5, max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        key = self.key_input.value.strip()

        found = await _remove_specific_key(key)
        if not found:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ Key ไม่ถูกต้องหรือถูกใช้ไปแล้ว", color=COLOR_ERROR),
                ephemeral=True)
            return

        member = interaction.user
        guild  = interaction.guild
        role   = guild.get_role(PREMIUM_ROLE_ID)
        if role and role not in member.roles:
            await member.add_roles(role, reason=f"Redeem: {key}")

        # ส่ง script ใน ticket ที่มีอยู่ (ถ้ามี)
        script_msg = f'```\nscript_key = "{key}"\n{SCRIPT_LOADSTRING}\n```'
        for ch in guild.text_channels:
            if ch.topic and f"({member.id})" in ch.topic:
                await ch.send(f"🔑 **Key ของคุณ:**\n{script_msg}")
                break

        embed = discord.Embed(title="✅ Redeem สำเร็จ!", color=COLOR_SUCCESS)
        embed.set_thumbnail(url=HUB_LOGO_URL)
        embed.add_field(name="🔑 Key",  value=f"`{key}`",                           inline=False)
        embed.add_field(name="👤 ยศ",   value=role.mention if role else "ไม่ตั้งค่า", inline=True)
        embed.set_footer(text="Script ถูกส่งใน ticket แล้ว 📩")
        await interaction.followup.send(embed=embed, ephemeral=True)

        asyncio.ensure_future(lm_link_discord(key, member.id))
        asyncio.ensure_future(_refresh_panel(guild))

        await send_log(guild, "🔑 Key Redeemed",
                       f"{member.mention} redeem key สำเร็จ\n`{key}`",
                       COLOR_SUCCESS, member)

# ════════════════════════════════════════════════════════════════════
#  Main Panel View  (ปุ่มทั้งหมด)
# ════════════════════════════════════════════════════════════════════
class MainPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # ── Buy Key ──────────────────────────────────────────────────────
    @discord.ui.button(label="Buy Key", emoji="🛒",
                       style=discord.ButtonStyle.success, custom_id="mp:buy", row=0)
    async def buy_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild  = interaction.guild
        member = interaction.user

        # เช็ก ticket ซ้ำ
        for ch in guild.text_channels:
            if ch.topic and f"({member.id})" in ch.topic and ch.name.startswith("purchase-"):
                await interaction.response.send_message(
                    f"❌ คุณมี ticket เปิดอยู่แล้ว: {ch.mention}", ephemeral=True)
                return

        category = guild.get_channel(TICKET_CATEGORY_ID)
        staff    = guild.get_role(STAFF_ROLE_ID)
        count    = _load_ticket_count() + 1
        _save_ticket_count(count)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member:             discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        if staff:
            overwrites[staff] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"purchase-{count:04d}",
            category=category,
            overwrites=overwrites,
            topic=f"Ticket ของ {member} ({member.id})",
        )

        embed = discord.Embed(
            title="🛒 Purchase Ticket",
            description=(
                f"สวัสดี {member.mention}! 👋\n\n"
                "**ขั้นตอนการซื้อ:**\n"
                "1️⃣ โอนเงินตามช่องทางด้านล่าง\n"
                "2️⃣ **ส่งสลิป** ในช่องนี้\n"
                "3️⃣ บอทจะตรวจสลิปและส่ง key ให้อัตโนมัติ\n\n"
                "**ช่องทางชำระเงิน:**\n"
                f"💛 PromptPay: `{TRUEMONEY_NUMBER}`\n"
                f"💰 ราคา: **{PRODUCT_PRICE:.0f} บาท**\n\n"
                f"📦 Keys คงเหลือ: **{_count_keys()} keys**\n\n"
                "⚠️ **ส่งสลิปให้ตรงยอดและถูกเบอร์นะครับ**"
            ),
            color=COLOR_INFO,
        )
        if HUB_BANNER_URL:
            embed.set_image(url=HUB_BANNER_URL)
        embed.set_thumbnail(url=HUB_LOGO_URL)
        embed.set_footer(text=f"Ticket #{count:04d}  •  ส่งสลิปได้เลย")

        # ปิง buyer + staff role ตอนเปิด ticket
        mention = member.mention + (f" {staff.mention}" if staff else "")

        # แนบ QR พร้อมเพย์ (ไฟล์ในเครื่อง — ไม่หมดอายุเหมือนลิงก์ Discord)
        send_kwargs = dict(
            view=TicketControl(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        if os.path.exists(QR_IMAGE_FILE):
            qr_embed = discord.Embed(
                title="💳 สแกน QR เพื่อชำระเงิน",
                description=f"💰 ยอดชำระ: **{PRODUCT_PRICE:.0f} บาท**\nสแกนแล้วส่งสลิปในช่องนี้ได้เลย",
                color=COLOR_INFO,
            )
            qr_embed.set_image(url="attachment://qr.png")
            await channel.send(mention, embeds=[embed, qr_embed],
                               file=discord.File(QR_IMAGE_FILE, filename="qr.png"),
                               **send_kwargs)
        else:
            await channel.send(mention, embed=embed, **send_kwargs)

        await interaction.response.send_message(
            f"✅ สร้าง ticket แล้ว → {channel.mention}", ephemeral=True)

    # ── Redeem Key ───────────────────────────────────────────────────
    @discord.ui.button(label="Redeem Key", emoji="🔑",
                       style=discord.ButtonStyle.primary, custom_id="mp:redeem", row=0)
    async def redeem_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RedeemModal())

    # ── Get Script ───────────────────────────────────────────────────
    @discord.ui.button(label="Get Script", emoji="📜",
                       style=discord.ButtonStyle.primary, custom_id="mp:script", row=0)
    async def get_script(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(PREMIUM_ROLE_ID)
        if role and role not in interaction.user.roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ ต้องมียศ Premium ก่อน\nซื้อ key → Redeem Key → แล้วกลับมากด Get Script",
                    color=COLOR_ERROR),
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        # ดึง key ที่ผูกกับ discord ของผู้ใช้ เพื่อใส่ script_key ให้ถูกต้อง
        key = await lm_get_user_key(str(interaction.user.id))
        if not key:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ ไม่เจอ key ที่ผูกกับ account นี้\nRedeem key ก่อนนะครับ",
                    color=COLOR_ERROR),
                ephemeral=True)
            return
        # แสดง script พร้อม script_key — ephemeral เห็นแค่คนกด
        script_with_key = f'script_key = "{key}"\n{SCRIPT_LOADSTRING}'
        embed = discord.Embed(title="📜 Script ของคุณ", color=COLOR_INFO)
        embed.set_thumbnail(url=HUB_LOGO_URL)
        embed.add_field(name="Loadstring", value=f"```lua\n{script_with_key}\n```", inline=False)
        embed.set_footer(text="⚠️ ข้อความนี้เห็นแค่คุณคนเดียว — ห้ามแชร์")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Reset HWID ───────────────────────────────────────────────────
    @discord.ui.button(label="Reset HWID", emoji="⚙️",
                       style=discord.ButtonStyle.secondary, custom_id="mp:hwid", row=1)
    async def reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        key = await lm_get_user_key(str(interaction.user.id))
        if not key:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ ไม่เจอ key ที่ผูกกับ account นี้\nRedeem key ก่อนนะครับ",
                    color=COLOR_ERROR),
                ephemeral=True)
            return

        ok = await lm_reset_hwid(key)
        if ok:
            embed = discord.Embed(title="✅ Reset HWID สำเร็จ!", color=COLOR_SUCCESS)
            embed.add_field(name="Key", value=f"`{key}`", inline=False)
            embed.set_footer(text="เปิด script ใหม่ได้เลยครับ")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ Reset ไม่ได้\nอาจยังอยู่ใน cooldown หรือ key ไม่ถูกต้อง",
                    color=COLOR_ERROR),
                ephemeral=True)

    # ── Stats ────────────────────────────────────────────────────────
    @discord.ui.button(label="Stats", emoji="📊",
                       style=discord.ButtonStyle.secondary, custom_id="mp:stats", row=1)
    async def get_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        key = await lm_get_user_key(str(interaction.user.id))
        if not key:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="❌ ไม่เจอ key\nRedeem key ก่อนนะครับ",
                    color=COLOR_ERROR),
                ephemeral=True)
            return

        data = await lm_get_key(key)
        if not data:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ ดึงข้อมูลไม่ได้", color=COLOR_ERROR),
                ephemeral=True)
            return

        k = data.get("key") or data
        embed = discord.Embed(title="📊 ข้อมูล Key ของคุณ", color=COLOR_INFO)
        embed.set_thumbnail(url=HUB_LOGO_URL)
        embed.add_field(name="🔑 Key",         value=f"`{key}`",                               inline=False)
        embed.add_field(name="📅 หมดอายุ",     value=str(k.get("expires_at", "ไม่มีกำหนด")), inline=True)
        embed.add_field(name="💻 HWID",          value=str(k.get("hwid", "ยังไม่ผูก")),        inline=True)
        embed.add_field(name="🔄 HWID Resets",   value=str(k.get("hwid_reset", 0)),             inline=True)
        embed.set_footer(text=f"RayVinz Hub  •  Project: {LUARMOR_PROJECT_ID}")
        await interaction.followup.send(embed=embed, ephemeral=True)


# ════════════════════════════════════════════════════════════════════
#  Ticket Control View  (ในช่อง ticket)
# ════════════════════════════════════════════════════════════════════
class TicketControl(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Confirm (Manual)", style=discord.ButtonStyle.green,
                       custom_id="tc:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_staff(interaction.user):
            await interaction.response.send_message("❌ เฉพาะ Staff เท่านั้น", ephemeral=True)
            return

        buyer_id = _buyer_id_from_topic(interaction.channel.topic)
        if not buyer_id:
            await interaction.response.send_message("❌ หา buyer ID ไม่เจอ", ephemeral=True)
            return

        await _deliver_key(interaction.channel, interaction.guild, buyer_id,
                           confirmed_by=interaction.user)
        button.disabled = True
        button.label    = "✅ Confirmed"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.red,
                       custom_id="tc:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        buyer_id = _buyer_id_from_topic(interaction.channel.topic)
        if not _is_staff(interaction.user) and buyer_id != interaction.user.id:
            await interaction.response.send_message("❌ เฉพาะ Staff หรือเจ้าของ ticket", ephemeral=True)
            return
        await interaction.response.send_message("🔒 ปิด ticket ใน 5 วินาที...")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"ปิดโดย {interaction.user}")


# ════════════════════════════════════════════════════════════════════
#  ส่ง Key ให้ลูกค้า (ใช้ร่วมกัน)
# ════════════════════════════════════════════════════════════════════
async def _deliver_key(channel: discord.TextChannel, guild: discord.Guild,
                        buyer_id: int, confirmed_by=None):
    key = await _pop_key()
    buyer = guild.get_member(buyer_id)

    if not key:
        await channel.send(embed=discord.Embed(
            description="❌ **Keys หมดแล้ว!** Admin เติม key ด้วย `!addkeys`",
            color=COLOR_ERROR))
        await send_log(guild, "⚠️ Keys หมด",
                       f"ลูกค้า <@{buyer_id}> ซื้อแต่ key หมด กรุณาเติม!",
                       COLOR_WARN, buyer)
        return

    if buyer:
        asyncio.ensure_future(lm_link_discord(key, buyer.id))

    role = guild.get_role(PREMIUM_ROLE_ID)
    role_given = False
    if role and buyer and role not in buyer.roles:
        try:
            await buyer.add_roles(role, reason=f"ซื้อ key: {key}")
            role_given = True
        except Exception:
            pass

    embed = discord.Embed(title="🎉 ชำระเงินสำเร็จ!", color=COLOR_SUCCESS)
    embed.set_thumbnail(url=HUB_LOGO_URL)
    embed.add_field(name="🔑 Key ของคุณ", value=f"```\n{key}\n```", inline=False)
    embed.add_field(
        name="✅ ยศ Premium",
        value=f"{role.mention if role else 'Premium'} {'ได้รับแล้ว 🎉' if role_given else '(มีแล้ว)'}",
        inline=True,
    )
    embed.add_field(name="📦 Keys เหลือ", value=f"{_count_keys()} keys", inline=True)
    embed.add_field(
        name="📌 ขั้นตอนต่อไป",
        value="Script ถูกส่งให้ทาง **DM** แล้ว 📩\nเปิด Roblox → Execute ได้เลย 🚀",
        inline=False,
    )
    if confirmed_by:
        embed.set_footer(text=f"ยืนยันโดย {confirmed_by}")
    await channel.send(f"{'<@' + str(buyer_id) + '>' if buyer_id else ''}", embed=embed)

    # ส่ง script พร้อม key ใน ticket เลย
    script_with_key = f'script_key = "{key}" -- key\n{SCRIPT_LOADSTRING}'
    script_embed = discord.Embed(title="📜 Script ของคุณ", color=COLOR_INFO)
    script_embed.set_thumbnail(url=HUB_LOGO_URL)
    script_embed.add_field(name="Execute ใน Roblox Executor", value=f"```lua\n{script_with_key}\n```", inline=False)
    script_embed.set_footer(text="⚠️ ห้ามแชร์ key นี้กับใคร — ใช้ได้คนเดียว")
    await channel.send(embed=script_embed)

    by_text = f"\nยืนยันโดย {confirmed_by}" if confirmed_by else ""
    await send_log(guild, "✅ ขายสำเร็จ",
                   f"**ลูกค้า:** {buyer.mention if buyer else buyer_id}\n"
                   f"**Key:** `{key}`\n"
                   f"**ยศ:** {'✅ แจกแล้ว' if role_given else 'มีอยู่แล้ว'}{by_text}",
                   COLOR_SUCCESS, buyer)
    await _refresh_panel()


# ════════════════════════════════════════════════════════════════════
#  on_message — ตรวจสลิปอัตโนมัติ
# ════════════════════════════════════════════════════════════════════
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    # ตรวจเฉพาะช่อง purchase ticket
    if not message.channel.name.startswith("purchase-"):
        await bot.process_commands(message)
        return

    # ถ้ามีรูปแนบ → ตรวจสลิป
    if message.attachments:
        img = next((a for a in message.attachments
                    if a.content_type and "image" in a.content_type), None)
        if img:
            await message.add_reaction("⏳")
            img_bytes = await img.read()
            slip_data = await verify_slip(img_bytes, img.filename)

            await message.remove_reaction("⏳", bot.user)

            if slip_data is None:
                # Slip2Go ไม่ได้ตั้งค่า → รอ staff confirm manual
                await message.add_reaction("📋")
                await message.channel.send(
                    embed=discord.Embed(
                        description="📋 **รับสลิปแล้ว** — Staff กำลังตรวจสอบ...\n"
                                    "กด ✅ Confirm ด้านบนเพื่อยืนยัน",
                        color=COLOR_WARN))
            elif slip_data.get("_fallback"):
                # เรียก API ไม่สำเร็จ → ไม่ dead-end แล้ว, ส่งต่อให้ staff confirm
                await message.add_reaction("📋")
                await message.channel.send(
                    embed=discord.Embed(
                        description=f"📋 **รับสลิปแล้ว** — ตรวจอัตโนมัติไม่ได้ "
                                    f"(API status {slip_data.get('status')})\n"
                                    "รอ Staff กด ✅ Confirm เพื่อยืนยัน",
                        color=COLOR_WARN))
            else:
                valid, reason = slip_is_valid(slip_data)
                if valid:
                    transref = (slip_data.get("data") or {}).get("transRef") or ""
                    if _slip_used(transref):
                        await message.add_reaction("❌")
                        await message.channel.send(
                            embed=discord.Embed(
                                title="❌ สลิปซ้ำ",
                                description="สลิปนี้ถูกใช้ไปแล้ว — ห้ามใช้สลิปเดิมแลก key ซ้ำ",
                                color=COLOR_ERROR))
                    else:
                        _mark_slip_used(transref)
                        await message.add_reaction("✅")
                        buyer_id = _buyer_id_from_topic(message.channel.topic)
                        await _deliver_key(message.channel, message.guild, buyer_id)
                else:
                    await message.add_reaction("❌")
                    await message.channel.send(
                        embed=discord.Embed(
                            title="❌ สลิปไม่ถูกต้อง",
                            description=reason,
                            color=COLOR_ERROR))

    await bot.process_commands(message)


# ════════════════════════════════════════════════════════════════════
#  Commands
# ════════════════════════════════════════════════════════════════════
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    """วางแผงหลัก !setup"""
    ch = bot.get_channel(PANEL_CHANNEL_ID) or ctx.channel
    await ch.send(embed=_build_panel_embed(), view=MainPanel())
    await ctx.send(f"✅ วางแผงใน {ch.mention} แล้ว", delete_after=10)
    try:
        await ctx.message.delete()
    except Exception:
        pass


def _build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎮 RayVinz Hub",
        description=(
            "ยินดีต้อนรับสู่ **RayVinz Hub**!\n\n"
            "เลือกสิ่งที่ต้องการด้านล่างได้เลย 👇\n\n"
            f"🛒 **Buy Key** — ซื้อ key ({PRODUCT_PRICE:.0f} บาท)\n"
            f"🔑 **Redeem Key** — กรอก key เพื่อรับยศ\n"
            f"📜 **Get Script** — รับ script ทาง DM\n"
            f"⚙️ **Reset HWID** — รีเซ็ต Hardware ID\n"
            f"📊 **Stats** — ดูข้อมูล key ของคุณ\n\n"
            f"📦 Keys คงเหลือ: **{_count_keys()} keys**"
        ),
        color=COLOR_MAIN,
    )
    embed.set_thumbnail(url=HUB_LOGO_URL)
    if HUB_BANNER_URL:
        embed.set_image(url=HUB_BANNER_URL)
    embed.set_footer(text="RayVinz Hub  •  Powered by Luarmor")
    return embed

async def _refresh_panel():
    """อัพเดต embed ใน PANEL_CHANNEL แบบ live"""
    ch = bot.get_channel(PANEL_CHANNEL_ID)
    if not ch:
        return
    async for msg in ch.history(limit=20):
        if msg.author == bot.user and msg.embeds and msg.components:
            try:
                await msg.edit(embed=_build_panel_embed())
            except Exception:
                pass
            return

@bot.command()
@commands.has_permissions(administrator=True)
async def addkeys(ctx, *, text: str):
    """เพิ่ม key: !addkeys KEY1\nKEY2\nKEY3"""
    new_keys = [k.strip() for k in text.strip().split('\n') if _is_valid_key_line(k)]
    with open(KEYS_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(new_keys) + "\n")
    await ctx.send(f"✅ เพิ่ม **{len(new_keys)} keys** (รวมเหลือ {_count_keys()} keys)", delete_after=15)
    await _refresh_panel()
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command()
@commands.has_permissions(administrator=True)
async def importkeys(ctx):
    """แนบไฟล์ .txt แล้วพิมพ์ !importkeys — อ่าน key ทุกบรรทัดเลย"""
    if not ctx.message.attachments:
        await ctx.send("❌ แนบไฟล์ .txt มาด้วยนะ", delete_after=10)
        return
    att = ctx.message.attachments[0]
    if not att.filename.endswith(".txt"):
        await ctx.send("❌ รับแค่ไฟล์ .txt เท่านั้น", delete_after=10)
        return
    raw = await att.read()
    lines = raw.decode("utf-8", errors="ignore").splitlines()
    new_keys = [k.strip() for k in lines if _is_valid_key_line(k)]
    if not new_keys:
        await ctx.send("❌ ไม่พบ key ในไฟล์", delete_after=10)
        return
    with open(KEYS_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(new_keys) + "\n")
    await ctx.send(f"✅ Import **{len(new_keys)} keys** จากไฟล์ (รวมเหลือ {_count_keys()} keys)", delete_after=15)
    await _refresh_panel()
    try:
        await ctx.message.delete()
    except Exception:
        pass


@bot.command()
@commands.has_permissions(administrator=True)
async def keycount(ctx):
    await ctx.send(f"📦 Keys เหลือ: **{_count_keys()} keys**", delete_after=10)


@bot.command()
@commands.has_permissions(administrator=True)
async def closeticket(ctx):
    if not ctx.channel.name.startswith("purchase-"):
        await ctx.send("❌ ใช้ได้เฉพาะในช่อง purchase ticket", delete_after=10)
        return
    await ctx.send("🔒 ปิด ticket ใน 5 วินาที...")
    await asyncio.sleep(5)
    await ctx.channel.delete(reason=f"ปิดโดย {ctx.author}")


# ── Reaction Role commands (เดิม) ──────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def setupverify(ctx):
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if not channel:
        await ctx.send("❌ ตั้งค่า VERIFY_CHANNEL_ID ก่อน")
        return
    embed = discord.Embed(
        title="🔥 ยืนยันตัวตน • รับยศ",
        description=(f"📜 อ่านกฎที่ <#{RULE_CHANNEL_ID}> ก่อน\n\n"
                     f"กด ✅ ด้านล่างเพื่อรับยศเข้าเซิร์ฟเวอร์ 🎉"),
        color=0xff79c6)
    embed.set_image(url=HUB_LOGO_URL)
    embed.set_footer(text="กด ✅ = รับยศ  •  เอา ✅ ออก = ยศหาย")
    msg = await channel.send(embed=embed)
    await msg.add_reaction("✅")
    reaction_roles[str(msg.id)] = {key_from_input("✅"): VERIFY_ROLE_ID}
    save_rr()
    await ctx.send(f"✅ วางแผง verify ใน {channel.mention}", delete_after=20)


@bot.command()
@commands.has_permissions(administrator=True)
async def rrpanel(ctx, *, text):
    parts = text.split("|", 1)
    title = parts[0].strip() or "รับยศ"
    desc  = parts[1].strip() if len(parts) > 1 else "กดอิโมจิด้านล่างเพื่อรับยศ 👇"
    embed = discord.Embed(title=title, description=desc, color=0xff79c6)
    embed.set_footer(text="กดอิโมจิ = รับยศ  •  เอาออก = ยศหาย")
    msg = await ctx.send(embed=embed)
    reaction_roles[str(msg.id)] = {}
    save_rr()
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(f"✅ สร้างแผงแล้ว (id: `{msg.id}`) → reply แล้วพิมพ์ `!rradd <emoji> @ยศ`", delete_after=25)


@bot.command()
@commands.has_permissions(administrator=True)
async def rradd(ctx, emoji: str, role: discord.Role):
    ref = ctx.message.reference
    if not ref:
        await ctx.send("❌ ต้อง **reply** ข้อความแผงก่อน")
        return
    try:
        panel = await ctx.channel.fetch_message(ref.message_id)
        await panel.add_reaction(emoji)
    except Exception:
        await ctx.send("❌ อิโมจินี้ใช้ไม่ได้")
        return
    reaction_roles.setdefault(str(ref.message_id), {})[key_from_input(emoji)] = role.id
    save_rr()
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(f"✅ {emoji} → **{role.name}**", delete_after=10)


@bot.command()
@commands.has_permissions(administrator=True)
async def rrremove(ctx, emoji: str):
    ref = ctx.message.reference
    if not ref:
        await ctx.send("❌ reply แผงก่อน")
        return
    mapping = reaction_roles.get(str(ref.message_id))
    if mapping and mapping.pop(key_from_input(emoji), None):
        save_rr()
        await ctx.send(f"✅ ลบ {emoji} ออกแล้ว", delete_after=10)
    else:
        await ctx.send("❌ ไม่เจออิโมจินี้", delete_after=10)


@bot.command()
@commands.has_permissions(administrator=True)
async def giveall(ctx, role: discord.Role):
    status = await ctx.send(f"⏳ กำลังแจกยศ {role.name}...")
    given = 0
    for m in ctx.guild.members:
        if m.bot or role in m.roles:
            continue
        try:
            await m.add_roles(role, reason=f"giveall by {ctx.author}")
            given += 1
        except Exception:
            pass
    await status.edit(content=f"✅ แจกยศ {role.name} แล้ว {given} คน")


@bot.command()
@commands.has_permissions(administrator=True)
async def removeall(ctx, role: discord.Role):
    status = await ctx.send(f"⏳ กำลังเอายศ {role.name} ออก...")
    removed = 0
    for m in list(role.members):
        try:
            await m.remove_roles(role, reason=f"removeall by {ctx.author}")
            removed += 1
        except Exception:
            pass
    await status.edit(content=f"✅ เอายศ {role.name} ออกแล้ว {removed} คน")


@bot.command(name='type')
@commands.has_permissions(administrator=True)
async def type_cmd(ctx, channel: discord.TextChannel, *, message):
    await channel.send(message)
    await ctx.send(f"✅ ส่งไป {channel.mention} แล้ว", delete_after=10)
    try:
        await ctx.message.delete()
    except Exception:
        pass


# ── Error handler ──────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะแอดมิน")
    elif isinstance(error, (commands.RoleNotFound, commands.ChannelNotFound)):
        await ctx.send("❌ หา role/channel ไม่เจอ ลองใช้ @mention หรือ ID")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ ขาด argument: `{error.param.name}`")
    else:
        raise error


# ════════════════════════════════════════════════════════════════════
#  on_ready
# ════════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    bot.add_view(MainPanel())
    bot.add_view(TicketControl())
    print(f"✅ {bot.user} ออนไลน์ | keys: {_count_keys()} | panels: {len(reaction_roles)}")


# ════════════════════════════════════════════════════════════════════
#  TOKEN
# ════════════════════════════════════════════════════════════════════
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    try:
        with open("token.txt", encoding="utf-8") as f:
            TOKEN = f.read().strip()
    except FileNotFoundError:
        raise SystemExit("❌ ไม่เจอ token — ใส่ใน env DISCORD_TOKEN หรือ token.txt")

bot.run(TOKEN)
