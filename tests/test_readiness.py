from rhythm_helper.readiness import WindowReadiness


def test_restoring_fullscreen_waits_through_minimize_and_resize():
    gate = WindowReadiness()
    full = (0, 0, 1920, 1080)
    assert not gate.observe(1, None, 0)
    assert not gate.observe(1, full, 0.1)
    assert not gate.observe(1, (0, 0, 1280, 720), 0.3)
    assert not gate.observe(1, full, 0.4)
    assert not gate.observe(1, full, 0.6)
    assert gate.observe(1, full, 0.71)


def test_focus_loss_or_zero_area_restarts_stability_window():
    gate = WindowReadiness()
    full = (0, 0, 1920, 1080)
    gate.observe(1, full, 0)
    gate.reset()
    assert not gate.observe(1, full, 0.4)
    assert not gate.observe(1, (0, 0, 0, 0), 0.7)
    assert not gate.observe(1, full, 1)
    assert gate.observe(1, full, 1.31)


def test_a_different_window_cannot_reuse_the_previous_timer():
    gate = WindowReadiness()
    full = (0, 0, 1920, 1080)
    gate.observe(1, full, 0)
    assert not gate.observe(2, full, 0.4)
    assert gate.observe(2, full, 0.71)
