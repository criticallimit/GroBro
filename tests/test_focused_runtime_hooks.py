from grobro.grobro import raw_dump


def test_raw_dump_hook_is_compatibility_noop():
    assert raw_dump.install_raw_dump_hook() is None
