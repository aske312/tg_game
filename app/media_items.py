"""Iterate legacy primary media and additional question/answer attachments."""
def media_items(question):
    primary = question.get('media')
    if primary is not None:
        yield primary
    attachments = question.get('attachments', [])
    if isinstance(attachments, list):
        yield from attachments


def scene_media(question, scene):
    """Keep question files separate from explicitly authored answer files."""
    answer = scene == 'answer'
    if scene not in ('question', 'answer'):
        return []
    return [m for m in media_items(question) if
            (bool(m.get('answer')) or (m is question.get('media') and m.get('show_in_question', not m.get('audio_only', False)) is False and m.get('kind') == 'image')) == answer]


def playback_media(question, scene):
    return next((m for m in scene_media(question, scene) if m.get('kind') in ('audio', 'video')), None)
