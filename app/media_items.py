"""Iterate legacy primary media and additional question/answer attachments."""
def media_items(question):
    primary = question.get('media')
    if primary is not None:
        yield primary
    attachments = question.get('attachments', [])
    if isinstance(attachments, list):
        yield from attachments
