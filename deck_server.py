import asyncio
import base64
import ctypes
from ctypes import wintypes
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
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

pyautogui.FAILSAFE = False
CONNECTED_CLIENTS = set()
HELPER_PATH = os.path.join(BASE_DIR, "media_helper.py")

KICK_CHANNEL = "tugruleyolll"
CHAT_HISTORY = []
SEEN_MSG_IDS = set()
SHUTDOWN_TARGET_TIME = 0


# --- 1. SES, PARLAKLIK VE SİSTEM MONİTÖRÜ ---
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
    print(f"[SES AYAR HATA]: {e}")


def toggle_system_mute():
  try:
    vol = get_volume_interface()
    current_mute = vol.GetMute()
    vol.SetMute(0 if current_mute else 1, None)
  except Exception as e:
    print(f"[MUTE HATA]: {e}")


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
    print(f"[PARLAKLIK HATA]: {e}")


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


# --- 2. İZOLE MEDYA OKUMA & KONTROL ---
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
                "artist": "YouTube Music • Opera",
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
      "artist": "Opera • YouTube Music",
      "playing": False,
  }


def send_hardware_media_key(cmd):
  vk_map = {
      "nexttrack": 0xB0,
      "prevtrack": 0xB1,
      "playpause": 0xB3,
  }
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


# --- 3. CANLI OBS DURUM OKUMA VE KONTROL ---
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
    cl = obs.ReqClient(host="127.0.0.1", port=4455, password="", timeout=1)
    scene_resp = cl.get_current_program_scene()
    stream_resp = cl.get_stream_status()
    record_resp = cl.get_record_status()

    current_scene = getattr(scene_resp, "current_program_scene_name", "")
    streaming = bool(getattr(stream_resp, "output_active", False))
    recording = bool(getattr(record_resp, "output_active", False))

    return {
        "type": "obs_update",
        "connected": True,
        "scene": current_scene,
        "streaming": streaming,
        "recording": recording,
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
    cl = obs.ReqClient(host="127.0.0.1", port=4455, password="", timeout=2)
    if command_type == "scene":
      cl.set_current_program_scene(value)
    elif command_type == "stream":
      cl.toggle_stream()
    elif command_type == "record":
      cl.toggle_record()
  except Exception as e:
    print(f"OBS Komut Hatası: {e}")


# --- 4. LIVE PEEK (UZAKTAN EKRAN ÖNİZLEME) ---
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
    print(f"[EKRAN HATA]: {e}")
    return None


# --- 5. ZAMANLAYICI & UYKU MODU ---
def handle_power_command(cmd, minutes=0):
  global SHUTDOWN_TARGET_TIME
  if cmd == "schedule_shutdown":
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


# --- 6. CANLI KICK CHAT ---
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
      ws_url = payload.get("url") or "wss://realtime.kick.com/connection/websocket"
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
      "user": sender.get("username", "İzleyici"),
      "color": identity.get("color") or "#53fc18",
      "badges": badges,
      "text": msg_data.get("content", ""),
      "time": time.strftime("%H:%M"),
  }


async def process_incoming_kick_msg(msg_data):
  global CHAT_HISTORY, SEEN_MSG_IDS
  msg_id = msg_data.get("id")
  if msg_id and msg_id in SEEN_MSG_IDS:
    return
  if msg_id:
    SEEN_MSG_IDS.add(msg_id)
    if len(SEEN_MSG_IDS) > 300:
      SEEN_MSG_IDS = set(list(SEEN_MSG_IDS)[-150:])

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
                json.dumps(
                    {"subscribe": {"channel": f"chatrooms.{chatroom_id}.v2"}, "id": 2}
                )
            )
            print(f"Kick Chat (Centrifugo) bağlandı: {KICK_CHANNEL} (Oda: {chatroom_id})")
            await broadcast(
                {"type": "chat_status", "connected": True, "channel": KICK_CHANNEL}
            )

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

    print(f"Kick Chat (Yedek Mod) aktif: {KICK_CHANNEL}")
    await broadcast(
        {"type": "chat_status", "connected": True, "channel": KICK_CHANNEL}
    )
    initial_msgs = await asyncio.to_thread(fetch_kick_messages_rest, channel_id)
    for m in reversed(initial_msgs):
      if m.get("id"):
        SEEN_MSG_IDS.add(m["id"])

    for _ in range(30):
      msgs = await asyncio.to_thread(fetch_kick_messages_rest, channel_id)
      for m in reversed(msgs):
        await process_incoming_kick_msg(m)
      await asyncio.sleep(2.5)


class NoCacheHTTPRequestHandler(SimpleHTTPRequestHandler):

  def end_headers(self):
    self.send_header(
        "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"
    )
    self.send_header("Pragma", "no-cache")
    self.send_header("Expires", "0")
    super().end_headers()


def start_http_server():
  handler = partial(NoCacheHTTPRequestHandler, directory=BASE_DIR)
  httpd = ThreadingHTTPServer(("0.0.0.0", 8000), handler)
  print("HTTP Arayüz Sunucusu 8000 portunda çalışıyor (No-Cache aktif)...")
  httpd.serve_forever()


async def broadcast(payload):
  msg = json.dumps(payload)
  for client in list(CONNECTED_CLIENTS):
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
    if CONNECTED_CLIENTS:
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


async def handle_command(websocket):
  print("Telefon bağlandı!")
  CONNECTED_CLIENTS.add(websocket)

  try:
    await websocket.send(json.dumps(get_audio_state()))
    await websocket.send(json.dumps(await asyncio.to_thread(get_brightness_state)))
    await websocket.send(json.dumps(get_system_stats()))
    await websocket.send(
        json.dumps(await asyncio.to_thread(call_media_helper, None))
    )
    await websocket.send(json.dumps(await asyncio.to_thread(get_obs_state)))
    await websocket.send(json.dumps(get_power_state()))
    await websocket.send(
        json.dumps({"type": "chat_history", "messages": CHAT_HISTORY})
    )

    async for message in websocket:
      data = json.loads(message)
      action = data.get("action")
      value = data.get("value")

      if action == "set_volume":
        set_system_volume(int(value))
        await broadcast(get_audio_state())
      elif action == "toggle_mute":
        toggle_system_mute()
        await broadcast(get_audio_state())
      elif action == "set_brightness":
        await asyncio.to_thread(set_system_brightness, int(value))
      elif action == "obs_scene":
        await asyncio.to_thread(handle_obs, "scene", value)
        await asyncio.sleep(0.15)
        await broadcast(await asyncio.to_thread(get_obs_state))
      elif action == "obs_toggle":
        await asyncio.to_thread(handle_obs, value, None)
        await asyncio.sleep(0.25)
        await broadcast(await asyncio.to_thread(get_obs_state))
      elif action == "get_screen":
        frame = await asyncio.to_thread(capture_screen_base64)
        if frame:
          await websocket.send(json.dumps(frame))
      elif action == "power":
        cmd_type = value.get("cmd")
        mins = value.get("minutes", 0)
        await asyncio.to_thread(handle_power_command, cmd_type, mins)
        await broadcast(get_power_state())
      elif action == "clear_chat":
        CHAT_HISTORY.clear()
        await broadcast({"type": "chat_history", "messages": []})
      elif action == "hotkey":
        pyautogui.hotkey(*value)
      elif action == "press":
        if value == "f14":
          press_f14()
        elif value in ["playpause", "nexttrack", "prevtrack"]:
          send_hardware_media_key(value)
          updated_media = await asyncio.to_thread(call_media_helper, value)
          await broadcast(updated_media)
        else:
          pyautogui.press(value)
      elif action == "app":
        if value == "genshin":
          os.startfile(
              "com.epicgames.launcher://apps/879b0d8776ab46a59a129983ba78f0ce%3A7d690c122fde4c60bed85405f343ad10%3A41869934302e4b8cafac2d3c0e7c293d?action=launch&silent=true"
          )
        else:
          os.startfile(value)

  except websockets.exceptions.ConnectionClosed:
    print("Bağlantı kesildi.")
  finally:
    CONNECTED_CLIENTS.discard(websocket)


async def main():
  threading.Thread(target=start_http_server, daemon=True).start()
  asyncio.create_task(monitor_system_loop())
  asyncio.create_task(kick_chat_listener())

  async with websockets.serve(handle_command, "0.0.0.0", 8765):
    print("Stream Deck Sunucusu 8765 portunda çalışıyor...")
    await asyncio.Future()


if __name__ == "__main__":
  asyncio.run(main())