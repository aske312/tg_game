from pathlib import Path
import re
import pytest

from app.media import detect_media


@pytest.mark.parametrize('kind,data,expected', [
    ('image', b'\xff\xd8\xff\xe0\x00\x10JFIF\x00', ('image/jpeg', '.jpg')),
    ('image', b'BM' + b'\x00'*30, ('image/bmp', '.bmp')),
    ('image', b'\x00\x00\x00\x20ftypavif\x00\x00\x00\x00avif', ('image/avif', '.avif')),
    ('audio', b'fLaC' + b'\x00'*30, ('audio/flac', '.flac')),
    ('audio', b'\xff\xf1\x50\x80', ('audio/aac', '.aac')),
    ('audio', b'\xff\xfb\x90\x00', ('audio/mpeg', '.mp3')),
    ('audio', b'OggS' + b'\x00'*24 + b'OpusHead', ('audio/ogg', '.ogg')),
    ('video', b'\x00\x00\x00\x20ftypqt  ' + b'\x00'*16, ('video/quicktime', '.mov')),
    ('video', b'\x00\x00\x00\x20ftypM4V ' + b'\x00'*16, ('video/mp4', '.mp4')),
])
def test_common_media_signatures(kind, data, expected):
    assert detect_media(data, kind) == expected


def test_ui_sources_are_utf8_without_replacement_characters():
    root = Path(__file__).resolve().parents[1]
    for folder in ('static', 'builder/static'):
        for path in (root/folder).rglob('*'):
            if path.suffix in ('.js', '.css', '.html', '.svg'):
                text = path.read_text(encoding='utf-8')
                assert '\ufffd' not in text, str(path)
                assert not re.search(r'\?{3,}', text), str(path)
    assert '🪤' not in (root/'static/app.js').read_text(encoding='utf-8')
    assert '🪤' not in (root/'static/index.html').read_text(encoding='utf-8')
