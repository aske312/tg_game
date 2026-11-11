import hashlib
import secrets
import shutil


MAX_GAME_MEDIA_BYTES = 10 * 1024 ** 3
MAX_MEDIA_BYTES = MAX_GAME_MEDIA_BYTES
MEDIA_CHUNK_BYTES = 1024 * 1024
MEDIA_EXTENSIONS = {
    'image': ('.png', '.jpg', '.jpeg', '.jfif', '.gif', '.webp', '.avif', '.bmp'),
    'audio': ('.mp3', '.wav', '.ogg', '.oga', '.opus', '.m4a', '.aac', '.flac'),
    'video': ('.mp4', '.webm', '.mov', '.m4v'),
}


def detect_media(data, kind):
    if kind == 'image':
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'image/png', '.png'
        if data.startswith(b'\xff\xd8\xff'):
            return 'image/jpeg', '.jpg'
        if data.startswith((b'GIF87a', b'GIF89a')):
            return 'image/gif', '.gif'
        if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            return 'image/webp', '.webp'
        if data.startswith(b'BM'):
            return 'image/bmp', '.bmp'
        if data[4:8] == b'ftyp' and (data[8:12] in (b'avif', b'avis') or b'avif' in data[16:]):
            return 'image/avif', '.avif'
    if kind == 'audio':
        if data.startswith(b'RIFF') and data[8:12] == b'WAVE':
            return 'audio/wav', '.wav'
        if data.startswith(b'fLaC'):
            return 'audio/flac', '.flac'
        if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xF6 == 0xF0:
            return 'audio/aac', '.aac'
        if data.startswith(b'ID3') or (len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224):
            return 'audio/mpeg', '.mp3'
        if data.startswith(b'OggS'):
            return 'audio/ogg', '.ogg'
        if data[4:8] == b'ftyp':
            return 'audio/mp4', '.m4a'
    if kind == 'video':
        if data[4:8] == b'ftyp':
            if data[8:12] == b'qt  ':
                return 'video/quicktime', '.mov'
            return 'video/mp4', '.mp4'
        if data.startswith(b'\x1a\x45\xdf\xa3'):
            return 'video/webm', '.webm'
    raise ValueError('Формат не поддерживается. Изображения: PNG/JPG/JFIF/GIF/WebP/AVIF/BMP; аудио: MP3/WAV/OGG/Opus/M4A/AAC/FLAC; видео: MP4/WebM/MOV/M4V')


def inspect_media(path, kind):
    """Validate and hash large files with bounded memory."""
    if path.stat().st_size > MAX_MEDIA_BYTES:
        raise ValueError('Максимальный размер файла — 10 ГБ')
    digest = hashlib.sha256()
    total = 0
    with path.open('rb') as stream:
        mime, extension = detect_media(stream.read(128), kind)
        stream.seek(0)
        while chunk := stream.read(MEDIA_CHUNK_BYTES):
            total += len(chunk)
            if total > MAX_MEDIA_BYTES:
                raise ValueError('Максимальный размер файла — 10 ГБ')
            digest.update(chunk)
    return mime, extension, digest.hexdigest(), total


def copy_media_file(source, target):
    """Copy atomically on disk without loading the asset into RAM."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + target.name + '.' + secrets.token_hex(8) + '.part')
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
