import asyncio
import base64
from collections import deque
import ctypes
from ctypes import wintypes
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
import urllib.request
import comtypes
from comtypes import CLSCTX_ALL
import obsws_python as obs
from PIL import ImageGrab
import psutil
import pyautogui
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import screen_brightness_control as sbc
import websockets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.stdout is None:
  sys.stdout = open(
      os.path.join(BASE_DIR, "deck.log"), "w", encoding="utf-8", buffering=1
  )
if sys.stderr is None:
  sys.stderr = sys.stdout

# Keep PyAutoGUI failsafe enabled (move mouse to top-left corner to abort)
pyautogui.FAILSAFE = True

# --- SECURITY CONFIGURATION & ALLOWLISTS ---
TOKEN_FILE = os.path.join(BASE_DIR, "deck_token.txt")


def load_or_create_token():
  env_token = os.environ.get("TUGRUL_DECK_TOKEN", "").strip()
  if env_token:
    return env_token
  if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
      saved = f.read().strip()
      if len(saved) >= 16:
        return saved
  new_token = secrets.token_urlsafe(24)
  with open(TOKEN_FILE, "w", encoding="utf-8") as f:
    f.write(new_token)
  return new_token


ACCESS_TOKEN = load_or_create_token()
OBS_PASSWORD = os.environ.get("OBS_WS_PASSWORD", "")
KICK_CHANNEL = os.environ.get("KICK_CHANNEL", "tugruleyolll")

MAX_CONNECTIONS = 5
MAX_MSG_BYTES = 8192
RATE_LIMIT_MAX_EVENTS = 35
RATE_LIMIT_WINDOW_SEC = 1.0

ALLOWED_HTTP_FILES = {"/index.html", "/manifest.json", "/sw.js"}

ALLOWED_APPS = {
    "discord": "discord://",
    "vscode": "code",
    "snip": "ms-screenclip:",
    "genshin": (
        "com.epicgames.launcher://apps/879b0d8776ab46a59a129983ba78f0ce%3A7d690c122fde4c60bed85405f343ad10%3A41869934302e4b8cafac2d3c0e7c293d?action=launch&silent=true"
    ),
    "kick_channel": f"https://kick.com/{KICK_CHANNEL}",
    "kick_dashboard": "https://dashboard.kick.com",
    "kick_popout": f"https://kick.com/popout/{KICK_CHANNEL}/chat",
    "yt_channel": "https://youtube.com/@Tugruleyolll",
    "yt_studio": "https://studio.youtube.com",
    "yt_music": "https://music.youtube.com",
    "github": "https://github.com/Tugruleyolll",
}

ALLOWED_HOTKEYS = {
    "desktop": ("win", "d"),
    "taskmgr": ("ctrl", "shift", "esc"),
    "explorer": ("win", "e"),
    "lock": ("win", "l"),
}

ALLOWED_PRESS_KEYS = {"f14", "playpause", "nexttrack", "prevtrack"}
ALLOWED_OBS_SCENES = {
    "Starting Soon",
    "Gameplay",
    "BRB",
    "Just Chatting",
    "Yayın Başlıyor",
    "Sahne",
    "Mola",
    "Sohbet",
}

AUTHENTICATED_CLIENTS = set()
HELPER_PATH = os.path.join(BASE_DIR, "media_helper.py")

CHAT_HISTORY = []
SEEN_MSG_IDS = deque(maxlen=300)
SHUTDOWN_TARGET_TIME = 0


def get_local_ips():
  ips = {"127.0.0.1", "localhost", "::1"}
  try:
    hostname = socket.gethostname()
    for info in socket.getaddrinfo(hostname, None):
      ips.add(info[4][0])
  except Exception:
    pass
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
      s.connect(("8.8.8.8", 80))
      ips.add(s.getsockname()[0])
  except Exception:
    pass
  return ips


ALLOWED_HOSTS = get_local_ips()


# --- 1. AUDIO, BRIGHTNESS & SYSTEM MONITOR ---
def get_volume_interface():
  comtypes.CoInitialize()
  devices = AudioUtilities.GetSpeakers()
  if hasattr(devices, "EndpointVolume"):
    return devices.EndpointVolume
  interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
  return ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))


def get_audio_state():
  try:
    vol = get_volume_interface()
    level = round(vol.GetMasterVolumeLevelScalar() * 100)
    muted = bool(vol.GetMute())
    return {"type": "volume_update", "level": level, "muted": muted}
  except Exception:
    return {"type": "volume_update", "level": 50, "muted": False}


def set_system_volume(level):
  try:
    vol = get_volume_interface()
    vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, level / 100.0)), None)
    if level > 0:
      vol.SetMute(0, None)
  except Exception as e:
    print(f"[AUDIO ERROR]: {e}")


def toggle_system_mute():
  try:
    vol = get_volume_interface()
    current_mute = vol.GetMute()
    vol.SetMute(0 if current_mute else 1, None)
  except Exception as e:
    print(f"[MUTE ERROR]: {e}")


def get_brightness_state():
  try:
    b = sbc.get_brightness()
    val = b[0] if isinstance(b, list) and b else int(b)
    return {"type": "brightness_update", "level": val, "supported": True}
  except Exception:
    return {"type": "brightness_update", "level": 80, "supported": False}


def set_system_brightness(level):
  try:
    sbc.set_brightness(max(0, min(100, int(level))))
  except Exception as e:
    print(f"[BRIGHTNESS ERROR]: {e}")


def get_system_stats():
  try:
    cpu = round(psutil.cpu_percent(interval=None))
    vm = psutil.virtual_memory()
    ram_pct = round(vm.percent)
    ram_used = round(vm.used / (1024**3), 1)
    ram_total = round(vm.total / (1024**3), 1)
    return {
        "type": "stats_update",
        "cpu": cpu,
        "ram_pct": ram_pct,
        "ram_used": ram_used,
        "ram_total": ram_total,
    }
  except Exception:
    return {
        "type": "stats_update",
        "cpu": 0,
        "ram_pct": 0,
        "ram_used": 0,
        "ram_total": 0,
    }


# --- 2. ISOLATED MEDIA READER & HARDWARE KEYS ---
def get_window_title_fallback():
  titles = []

  def enum_windows_proc(hwnd, lParam):
    if ctypes.windll.user32.IsWindowVisible(hwnd):
      length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
      if length > 0:
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        titles.append(buff.value)
    return True

  WNDENUMPROC = ctypes.WINFUNCTYPE(
      wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
  )
  ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)

  for t in titles:
    if "YouTube Music" in t:
      for sep in [" | YouTube Music", " - YouTube Music"]:
        if sep in t:
          song = t.split(sep)[0].strip()
          if song and song != "YouTube Music":
            return {
                "type": "media_update",
                "title": song,
                "artist": "YouTube Music • Browser",
                "playing": True,
            }
  return None


def call_media_helper(cmd=None):
  try:
    args = [sys.executable, HELPER_PATH]
    if cmd:
      args.append(cmd)
    out = subprocess.check_output(
        args,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=2.5,
    )
    data = json.loads(out.decode("utf-8").strip())
    if data and data.get("title"):
      return data
  except Exception:
    pass

  win_data = get_window_title_fallback()
  if win_data:
    return win_data

  return {
      "type": "media_update",
      "title": "Şu an bir şey çalmıyor",
      "artist": "Browser • Media Session",
      "playing": False,
  }


def send_hardware_media_key(cmd):
  vk_map = {"nexttrack": 0xB0, "prevtrack": 0xB1, "playpause": 0xB3}
  vk = vk_map.get(cmd)
  if not vk:
    return

  class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

  class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT)]

  inp_down = INPUT(1, KEYBDINPUT(vk, 0, 0x0001, 0, None))
  ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
  time.sleep(0.05)
  inp_up = INPUT(1, KEYBDINPUT(vk, 0, 0x0003, 0, None))
  ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


def press_f14():
  ctypes.windll.user32.keybd_event(0x7D, 0x65, 0, 0)
  time.sleep(0.05)
  ctypes.windll.user32.keybd_event(0x7D, 0x65, 2, 0)


# --- 3. OBS STUDIO WEBSOCKET CONTROL ---
def is_obs_port_open():
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(0.05)
    return s.connect_ex(("127.0.0.1", 4455)) == 0


def get_obs_state():
  if not is_obs_port_open():
    return {
        "type": "obs_update",
        "connected": False,
        "scene": "",
        "streaming": False,
        "recording": False,
    }
  try:
    cl = obs.ReqClient(
        host="127.0.0.1", port=4455, password=OBS_PASSWORD, timeout=1
    )
    scene_resp = cl.get_current_program_scene()
    stream_resp = cl.get_stream_status()
    record_resp = cl.get_record_status()

    return {
        "type": "obs_update",
        "connected": True,
        "scene": getattr(scene_resp, "current_program_scene_name", ""),
        "streaming": bool(getattr(stream_resp, "output_active", False)),
        "recording": bool(getattr(record_resp, "output_active", False)),
    }
  except Exception:
    return {
        "type": "obs_update",
        "connected": False,
        "scene": "",
        "streaming": False,
        "recording": False,
    }


def handle_obs(command_type, value):
  if not is_obs_port_open():
    return
  try:
    cl = obs.ReqClient(
        host="127.0.0.1", port=4455, password=OBS_PASSWORD, timeout=2
    )
    if command_type == "scene" and value in ALLOWED_OBS_SCENES:
      cl.set_current_program_scene(value)
    elif command_type == "stream":
      cl.toggle_stream()
    elif command_type == "record":
      cl.toggle_record()
  except Exception as e:
    print(f"[OBS ERROR]: {e}")


# --- 4. LIVE PEEK (SCREEN CAPTURE) ---
def capture_screen_base64():
  try:
    img = ImageGrab.grab()
    w, h = img.size
    new_w = 960
    new_h = int(h * (new_w / w))
    img = img.resize((new_w, new_h))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=60)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "screen_frame", "image": f"data:image/jpeg;base64,{b64}"}
  except Exception as e:
    print(f"[SCREEN ERROR]: {e}")
    return None


# --- 5. POWER & SHUTDOWN TIMER ---
def handle_power_command(cmd, minutes=0):
  global SHUTDOWN_TARGET_TIME
  if cmd == "schedule_shutdown":
    if minutes not in (30, 60, 120):
      return
    subprocess.run(
        ["shutdown", "/a"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    seconds = int(minutes) * 60
    subprocess.run(
        ["shutdown", "/s", "/t", str(seconds)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    SHUTDOWN_TARGET_TIME = time.time() + seconds
  elif cmd == "cancel_shutdown":
    subprocess.run(
        ["shutdown", "/a"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    SHUTDOWN_TARGET_TIME = 0
  elif cmd == "sleep_now":
    SHUTDOWN_TARGET_TIME = 0
    ctypes.windll.powrprof.SetSuspendState(0, 1, 0)


def get_power_state():
  global SHUTDOWN_TARGET_TIME
  if SHUTDOWN_TARGET_TIME > 0:
    remaining = max(0, int(SHUTDOWN_TARGET_TIME - time.time()))
    if remaining == 0:
      SHUTDOWN_TARGET_TIME = 0
    return {"type": "power_update", "active": True, "remaining": remaining}
  return {"type": "power_update", "active": False, "remaining": 0}


# --- 6. LIVE KICK CHAT LISTENER ---
KICK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://kick.com",
    "Referer": f"https://kick.com/{KICK_CHANNEL}",
}


def fetch_kick_ids(channel_slug):
  urls = [
      f"https://kick.com/api/v2/channels/{channel_slug}",
      f"https://kick.com/api/v2/channels/{channel_slug}/chatroom",
  ]
  for url in urls:
    try:
      req = urllib.request.Request(url, headers=KICK_HEADERS)
      with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if "chatroom" in data and isinstance(data["chatroom"], dict):
          return data.get("id"), data["chatroom"].get("id")
        if "id" in data:
          return None, data["id"]
    except Exception:
      continue
  return None, None


def get_centrifugo_auth():
  try:
    req = urllib.request.Request(
        "https://web.kick.com/api/v1/realtime/auth/connection",
        data=b"{}",
        headers={**KICK_HEADERS, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
      raw = json.loads(resp.read().decode("utf-8"))
      payload = raw.get("data", raw)
      token = payload.get("token")
      ws_url = (
          payload.get("url") or "wss://realtime.kick.com/connection/websocket"
      )
      return ws_url, token
  except Exception:
    return None, None


def fetch_kick_messages_rest(channel_id):
  if not channel_id:
    return []
  try:
    url = f"https://kick.com/api/v2/channels/{channel_id}/messages"
    req = urllib.request.Request(url, headers=KICK_HEADERS)
    with urllib.request.urlopen(req, timeout=6) as resp:
      raw = json.loads(resp.read().decode("utf-8"))
      return raw.get("data", {}).get("messages", [])
  except Exception:
    return []


def format_kick_message(msg_data):
  sender = msg_data.get("sender", {})
  identity = sender.get("identity", {})
  badges = [b.get("type") for b in identity.get("badges", [])]
  return {
      "type": "chat_message",
      "user": sender.get("username", "Viewer"),
      "color": identity.get("color") or "#53fc18",
      "badges": badges,
      "text": msg_data.get("content", ""),
      "time": time.strftime("%H:%M"),
  }


async def process_incoming_kick_msg(msg_data):
  global CHAT_HISTORY
  msg_id = msg_data.get("id")
  if msg_id and msg_id in SEEN_MSG_IDS:
    return
  if msg_id:
    SEEN_MSG_IDS.append(msg_id)

  chat_item = format_kick_message(msg_data)
  if not chat_item["text"]:
    return
  CHAT_HISTORY.append(chat_item)
  if len(CHAT_HISTORY) > 60:
    CHAT_HISTORY = CHAT_HISTORY[-60:]
  await broadcast(chat_item)


async def kick_chat_listener():
  while True:
    channel_id, chatroom_id = await asyncio.to_thread(
        fetch_kick_ids, KICK_CHANNEL
    )
    if not chatroom_id:
      await broadcast(
          {"type": "chat_status", "connected": False, "channel": KICK_CHANNEL}
      )
      await asyncio.sleep(10)
      continue

    ws_url, token = await asyncio.to_thread(get_centrifugo_auth)
    if ws_url and token:
      try:
        async with websockets.connect(
            ws_url, additional_headers={"Origin": "https://kick.com"}
        ) as kws:
          await kws.send(json.dumps({"connect": {"token": token}, "id": 1}))
          conn_reply = json.loads(await asyncio.wait_for(kws.recv(), timeout=5))
          if "connect" in conn_reply:
            await kws.send(
                json.dumps({
                    "subscribe": {"channel": f"chatrooms.{chatroom_id}.v2"},
                    "id": 2,
                })
            )
            await broadcast({
                "type": "chat_status",
                "connected": True,
                "channel": KICK_CHANNEL,
            })

            async for raw_frame in kws:
              for line in str(raw_frame).splitlines():
                if not line.strip():
                  continue
                frame = json.loads(line)
                if frame == {}:
                  await kws.send("{}")
                  continue
                pub = frame.get("push", {}).get("pub", {}).get("data", {})
                if pub and ("content" in pub or "sender" in pub):
                  await process_incoming_kick_msg(pub)
                elif isinstance(pub.get("data"), str):
                  inner = json.loads(pub["data"])
                  if "content" in inner:
                    await process_incoming_kick_msg(inner)
      except Exception:
        pass

    await broadcast(
        {"type": "chat_status", "connected": True, "channel": KICK_CHANNEL}
    )
    initial_msgs = await asyncio.to_thread(fetch_kick_messages_rest, channel_id)
    for m in reversed(initial_msgs):
      if m.get("id"):
        SEEN_MSG_IDS.append(m["id"])

    for _ in range(30):
      msgs = await asyncio.to_thread(fetch_kick_messages_rest, channel_id)
      for m in reversed(msgs):
        await process_incoming_kick_msg(m)
      await asyncio.sleep(2.5)


# --- 7. HARDENED STATIC HTTP SERVER (ALLOWLIST + SECURITY HEADERS) ---
class HardenedHTTPRequestHandler(SimpleHTTPRequestHandler):

  def do_GET(self):
    clean_path = urlparse(self.path).path
    if clean_path == "/":
      self.path = "/index.html"
      clean_path = "/index.html"

    if clean_path not in ALLOWED_HTTP_FILES:
      self.send_response(403)
      self.send_header("Content-Type", "text/plain; charset=utf-8")
      self.end_headers()
      self.wfile.write(b"403 Forbidden")
      return

    super().do_GET()

  def list_directory(self, path):
    self.send_error(403, "Directory listing forbidden")
    return None

  def end_headers(self):
    self.send_header(
        "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"
    )
    self.send_header("Pragma", "no-cache")
    self.send_header("Expires", "0")
    self.send_header("X-Frame-Options", "DENY")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("Referrer-Policy", "no-referrer")
    self.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src"
        " 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
        " ws: wss:; frame-ancestors 'none'; base-uri 'none'",
    )
    super().end_headers()

  def log_message(self, format, *args):
    pass


def start_http_server():
  handler = partial(HardenedHTTPRequestHandler, directory=BASE_DIR)
  httpd = ThreadingHTTPServer(("0.0.0.0", 8000), handler)
  print("Hardened HTTP UI Server listening on port 8000...")
  httpd.serve_forever()


async def broadcast(payload):
  if not AUTHENTICATED_CLIENTS:
    return
  msg = json.dumps(payload)
  for client in list(AUTHENTICATED_CLIENTS):
    try:
      await client.send(msg)
    except Exception:
      pass


async def monitor_system_loop():
  psutil.cpu_percent(interval=None)
  last_audio = None
  last_brightness = None
  last_media = None
  last_obs = None
  last_power = None
  while True:
    if AUTHENTICATED_CLIENTS:
      current_audio = get_audio_state()
      if current_audio != last_audio:
        last_audio = current_audio
        await broadcast(current_audio)

      current_brightness = await asyncio.to_thread(get_brightness_state)
      if current_brightness != last_brightness:
        last_brightness = current_brightness
        await broadcast(current_brightness)

      await broadcast(get_system_stats())

      current_media = await asyncio.to_thread(call_media_helper, None)
      if current_media != last_media:
        last_media = current_media
        await broadcast(current_media)

      current_obs = await asyncio.to_thread(get_obs_state)
      if current_obs != last_obs:
        last_obs = current_obs
        await broadcast(current_obs)

      current_power = get_power_state()
      if current_power != last_power:
        last_power = current_power
        await broadcast(current_power)
    await asyncio.sleep(1.0)


def is_valid_origin_and_host(websocket):
  headers = websocket.request.headers
  host_header = headers.get("Host", "").split(":")[0].strip()
  if host_header and host_header not in ALLOWED_HOSTS:
    return False

  origin = headers.get("Origin", "").strip()
  if origin:
    parsed = urlparse(origin)
    if parsed.hostname not in ALLOWED_HOSTS:
      return False
  return True


async def handle_command(websocket):
  if len(AUTHENTICATED_CLIENTS) >= MAX_CONNECTIONS:
    await websocket.close(1013, "Max connections reached")
    return

  if not is_valid_origin_and_host(websocket):
    await websocket.close(1008, "Invalid Origin or Host")
    return

  authenticated = False
  msg_timestamps = deque()

  try:
    await websocket.send(json.dumps({"type": "auth_required"}))

    async for message in websocket:
      if isinstance(message, bytes) or len(message) > MAX_MSG_BYTES:
        await websocket.close(1009, "Message too large")
        return

      now = time.monotonic()
      while (
          msg_timestamps and (now - msg_timestamps[0]) > RATE_LIMIT_WINDOW_SEC
      ):
        msg_timestamps.popleft()
      if len(msg_timestamps) >= RATE_LIMIT_MAX_EVENTS:
        continue
      msg_timestamps.append(now)

      try:
        data = json.loads(message)
      except json.JSONDecodeError:
        continue

      if not isinstance(data, dict):
        continue

      action = data.get("action")
      value = data.get("value")

      # Step 1: Mandatory Token Authentication
      if not authenticated:
        if action == "auth" and isinstance(value, str):
          if secrets.compare_digest(value.strip(), ACCESS_TOKEN):
            authenticated = True
            AUTHENTICATED_CLIENTS.add(websocket)
            await websocket.send(json.dumps({"type": "auth_ok"}))
            await websocket.send(json.dumps(get_audio_state()))
            await websocket.send(
                json.dumps(await asyncio.to_thread(get_brightness_state))
            )
            await websocket.send(json.dumps(get_system_stats()))
            await websocket.send(
                json.dumps(await asyncio.to_thread(call_media_helper, None))
            )
            await websocket.send(
                json.dumps(await asyncio.to_thread(get_obs_state))
            )
            await websocket.send(json.dumps(get_power_state()))
            await websocket.send(
                json.dumps({"type": "chat_history", "messages": CHAT_HISTORY})
            )
            continue
        await websocket.send(json.dumps({"type": "auth_failed"}))
        await websocket.close(1008, "Authentication failed")
        return

      # Step 2: Strict Allowlisted Command Execution
      if action == "set_volume" and isinstance(value, (int, float)):
        vol_val = max(0, min(100, int(value)))
        set_system_volume(vol_val)
        await broadcast(get_audio_state())

      elif action == "toggle_mute":
        toggle_system_mute()
        await broadcast(get_audio_state())

      elif action == "set_brightness" and isinstance(value, (int, float)):
        bright_val = max(0, min(100, int(value)))
        await asyncio.to_thread(set_system_brightness, bright_val)

      elif (
          action == "obs_scene"
          and isinstance(value, str)
          and value in ALLOWED_OBS_SCENES
      ):
        await asyncio.to_thread(handle_obs, "scene", value)
        await asyncio.sleep(0.15)
        await broadcast(await asyncio.to_thread(get_obs_state))

      elif action == "obs_toggle" and value in ("stream", "record"):
        await asyncio.to_thread(handle_obs, value, None)
        await asyncio.sleep(0.25)
        await broadcast(await asyncio.to_thread(get_obs_state))

      elif action == "get_screen":
        frame = await asyncio.to_thread(capture_screen_base64)
        if frame:
          await websocket.send(json.dumps(frame))

      elif action == "power" and isinstance(value, dict):
        cmd_type = value.get("cmd")
        mins = value.get("minutes", 0)
        if cmd_type in ("schedule_shutdown", "cancel_shutdown", "sleep_now"):
          await asyncio.to_thread(handle_power_command, cmd_type, mins)
          await broadcast(get_power_state())

      elif action == "clear_chat":
        CHAT_HISTORY.clear()
        await broadcast({"type": "chat_history", "messages": []})

      elif (
          action == "hotkey"
          and isinstance(value, str)
          and value in ALLOWED_HOTKEYS
      ):
        pyautogui.hotkey(*ALLOWED_HOTKEYS[value])

      elif (
          action == "press"
          and isinstance(value, str)
          and value in ALLOWED_PRESS_KEYS
      ):
        if value == "f14":
          press_f14()
        else:
          send_hardware_media_key(value)
          updated_media = await asyncio.to_thread(call_media_helper, value)
          await broadcast(updated_media)

      elif action == "app" and isinstance(value, str) and value in ALLOWED_APPS:
        os.startfile(ALLOWED_APPS[value])

  except websockets.exceptions.ConnectionClosed:
    pass
  finally:
    AUTHENTICATED_CLIENTS.discard(websocket)


async def main():
  print(f"Tuğrul Deck Access Token (deck_token.txt): {ACCESS_TOKEN}")
  threading.Thread(target=start_http_server, daemon=True).start()
  asyncio.create_task(monitor_system_loop())
  asyncio.create_task(kick_chat_listener())

  async with websockets.serve(
      handle_command, "0.0.0.0", 8765, max_size=MAX_MSG_BYTES
  ):
    print("Hardened WebSocket Server listening on port 8765...")
    await asyncio.Future()


if __name__ == "__main__":
  asyncio.run(main())