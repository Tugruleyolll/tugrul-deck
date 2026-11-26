import asyncio
import json
import sys
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)


async def run(cmd=None):
  sessions = await MediaManager.request_async()
  target = sessions.get_current_session()

  # Opera veya tarayıcı oturumunu önceliklendir
  for s in sessions.get_sessions():
    app_id = (s.source_app_user_model_id or "").lower()
    if any(
        x in app_id for x in ["opera", "chrome", "msedge", "brave", "youtube"]
    ):
      target = s
      break

  if not target:
    return None

  if cmd == "playpause":
    await target.try_toggle_play_pause_async()
    await asyncio.sleep(0.15)
  elif cmd == "nexttrack":
    await target.try_skip_next_async()
    await asyncio.sleep(0.25)
  elif cmd == "prevtrack":
    await target.try_skip_previous_async()
    await asyncio.sleep(0.25)

  info = await target.try_get_media_properties_async()
  pb = target.get_playback_info()
  is_playing = pb.playback_status == PlaybackStatus.PLAYING

  if info.title:
    return {
        "type": "media_update",
        "title": info.title,
        "artist": info.artist if info.artist else "YouTube Music • Opera",
        "playing": is_playing,
    }
  return None


if __name__ == "__main__":
  command = sys.argv[1] if len(sys.argv) > 1 else None
  try:
    res = asyncio.run(asyncio.wait_for(run(command), timeout=2.0))
    print(json.dumps(res if res else {}))
  except Exception:
    print("{}")