"""ID3 tag reading/writing via mutagen; shared by scanner, suggester, safety."""
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

TAG_KEYS = ('artist', 'albumartist', 'album', 'title', 'tracknumber')


def read_tags(path):
    """Return {key: str|None} for TAG_KEYS, or None if unreadable."""
    try:
        audio = MP3(path, ID3=EasyID3)
    except Exception:
        return None
    return {key: audio.get(key, [None])[0] for key in TAG_KEYS}


def read_audio_info(path):
    """Return (duration_seconds | None, bitrate | None)."""
    try:
        audio = MP3(path, ID3=EasyID3)
        return getattr(audio.info, 'length', None), getattr(audio.info, 'bitrate', None)
    except Exception:
        return None, None


def write_tags(path, fields):
    """Write the given subset of TAG_KEYS. Returns True on success."""
    try:
        audio = MP3(path, ID3=EasyID3)
        for key, value in fields.items():
            if key in TAG_KEYS and value is not None:
                audio[key] = str(value)
        audio.save()
        return True
    except Exception:
        return False
