import pytest
from scripts.release import metadata, require_green, require_newer


def test_release_version_must_increase_numerically():
    require_newer('0.0.6', [])
    require_newer('0.0.10', ['v0.0.9', 'other'])
    for version in ('0.0.8', '0.0.9'):
        with pytest.raises(ValueError):
            require_newer(version, ['v0.0.9'])


def test_release_requires_matching_tag_and_notes(tmp_path):
    (tmp_path/'VERSION').write_text('0.0.6\n')
    (tmp_path/'CHANGELOG.md').write_text('# Releases\n\n## 0.0.6\n\n- Fix media.\n\n## 0.0.5\nOld\n')
    assert metadata(tmp_path, 'v0.0.6') == ('0.0.6', '- Fix media.\n')
    with pytest.raises(ValueError):
        metadata(tmp_path, 'v0.0.5')
    (tmp_path/'CHANGELOG.md').write_text('## 0.0.6\n\n## 0.0.5\nOld\n')
    with pytest.raises(ValueError):
        metadata(tmp_path)


@pytest.mark.parametrize('status,conclusion', [('in_progress',None), ('completed','failure'), ('completed','cancelled')])
def test_failed_or_pending_checks_cannot_be_released(status, conclusion):
    with pytest.raises(ValueError):
        require_green([dict(head_sha='abc',head_branch='main',event='push',status=status,conclusion=conclusion)], 'abc')


def test_checks_must_belong_to_exact_main_commit():
    run = dict(head_sha='abc',head_branch='main',event='push',status='completed',conclusion='success')
    require_green([run], 'abc')
    for changed in (dict(head_sha='old'),dict(event='pull_request'),dict(head_branch='other')):
        with pytest.raises(ValueError):
            require_green([dict(run, **changed)], 'abc')
    with pytest.raises(ValueError):
        require_green([], 'abc')
