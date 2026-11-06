from types import SimpleNamespace

import pytest

from rhythm_helper.engine import Engine
from rhythm_helper.vision import Head, Observation


def obs(*heads, tail=False):
    return Observation(list(heads), [tail] * 6)


def approach(engine, kind="tap", lanes=(0,), start=0.0):
    actions = []
    for offset, y in [(0, 760), (0.05, 810), (0.10, 860), (0.15, 910)]:
        actions.extend(engine.step(obs(*(Head(i, kind, y) for i in lanes)), start + offset))
    return actions


def test_only_downward_motion_reaching_line_can_press():
    engine = Engine(920, lead_ms=0)
    assert not approach(engine)
    actions = engine.step(obs(Head(0, "tap", 925)), 0.165)
    assert [(a.key, a.down) for a in actions] == [("a", True)]
    assert [(a.key, a.down) for a in engine.step(obs(), 0.20)] == [("a", False)]
    assert engine.step(obs(Head(0, "tap", 930)), 0.21) == []


def test_multiple_lanes_fire_together_and_release_independently():
    engine = Engine(920, lead_ms=0)
    approach(engine, lanes=(0, 2, 4))
    events = engine.step(obs(*(Head(i, "tap", 925) for i in (0, 2, 4))), 0.165)
    assert {a.key for a in events if a.down} == {"a", "d", "k"}
    assert {a.key for a in engine.stop() if not a.down} == {"a", "d", "k"}
    assert engine.stop() == []


def test_stationary_decoration_and_untracked_hit_flash_never_fire():
    engine = Engine(920)
    for n in range(60):
        assert engine.step(obs(Head(0, "tap", 750), Head(1, "tap", 922)), n / 120) == []


def test_hold_survives_brief_missing_tail_then_releases():
    engine = Engine(920, lead_ms=0, release_grace_ms=65, allow_color_release=True)
    approach(engine, kind="hold")
    assert engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)[0].down
    assert engine.step(obs(tail=True), 0.4) == []
    assert engine.step(obs(), 0.45) == []
    assert engine.step(obs(tail=True), 0.49) == []
    assert engine.step(obs(), 0.6) == []
    actions = engine.step(obs(), 0.67)
    assert [(a.key, a.down) for a in actions] == [("a", False)]
    assert engine.step(obs(tail=True), 0.8) == []


def test_orphan_tail_cannot_start_a_hold():
    engine = Engine(920)
    assert engine.step(obs(tail=True), 0) == []
    assert engine.step(obs(tail=True), 0.5) == []


def test_lost_head_is_predicted_briefly_but_not_indefinitely():
    engine = Engine(920, lead_ms=0)
    approach(engine)
    assert engine.step(obs(), 0.165)[0].down
    engine.stop()
    engine.step(obs(Head(0, "tap", 600)), 1)
    engine.step(obs(Head(0, "tap", 650)), 1.05)
    assert engine.step(obs(), 2) == []


def test_hold_has_a_maximum_duration():
    engine = Engine(920, lead_ms=0, max_hold_seconds=1)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    actions = engine.step(obs(tail=True), 1.2)
    assert [(a.key, a.down) for a in actions] == [("a", False)]
    assert actions[0].reason == "hold timeout"


def test_two_close_notes_on_same_lane_are_separate():
    engine = Engine(920, lead_ms=0)
    pressed = []
    for n in range(70):
        now = n / 120
        heads = [Head(0, "tap", 700 + now * 1000), Head(0, "tap", 570 + now * 1000)]
        pressed.extend(a for a in engine.step(obs(*heads), now) if a.down)
    assert len(pressed) == 2


def test_pause_clears_tracks_and_hold_ownership():
    engine = Engine(920)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 930), tail=True), 0.17)
    assert len(engine.stop()) == 1
    assert engine.step(obs(tail=True), 0.3) == []


def test_negative_lead_delays_the_press():
    engine = Engine(920, lead_ms=-40)
    actions = []
    for n in range(31):
        now = n / 100
        for event in engine.step(obs(Head(0, "tap", 700 + now * 1000)), now):
            if event.down:
                actions.append(now)
    assert len(actions) == 1
    assert 0.25 <= actions[0] <= 0.27


def test_bright_end_cap_releases_hold_without_repressing():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for offset, y in [(0, 760), (0.05, 810), (0.10, 860), (0.15, 910)]:
        assert engine.step(obs(Head(0, "end", y), tail=True), 0.4 + offset) == []
    actions = engine.step(obs(Head(0, "end", 925), tail=True), 0.565)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]
    assert engine.step(obs(Head(0, "end", 930), tail=True), 0.57) == []


def test_end_cap_without_start_never_presses():
    engine = Engine(920, lead_ms=0)
    assert approach(engine, kind="end") == []
    assert engine.step(obs(Head(0, "end", 925), tail=True), 0.165) == []


@pytest.mark.parametrize(("game_fps", "speed"), [(20, 1000), (30, 1500)])
def test_repeated_low_fps_frames_do_not_duplicate_a_tap(game_fps, speed):
    engine = Engine(920, lead_ms=0)
    events = []
    for tick in range(100):
        now = tick / 120
        game_time = (tick * game_fps // 120) / game_fps
        y = 600 + speed * game_time
        events.extend(engine.step(obs(*([Head(0, "tap", y)] if y <= 962 else [])), now))
    assert [(a.down, a.reason) for a in events] == [(True, "tap"), (False, "tap complete")]


def test_missing_end_cannot_bind_endpoint_after_next_hold_start():
    engine = Engine(920, lead_ms=0)
    events = []
    for tick in range(100):
        now = tick / 120
        heads = [
            Head(0, kind, y + 1000 * now)
            for kind, y in (("hold", 760), ("hold", 500), ("end", 300))
            if y + 1000 * now <= 962
        ]
        tail = 0.16 <= now < 0.27 or 0.42 <= now < 0.62
        events.extend(engine.step(obs(*heads, tail=tail), now))
    assert [(a.down, a.reason) for a in events] == [
        (True, "hold"),
        (False, "next note (unseen end)"),
        (True, "hold"),
        (False, "end cap"),
    ]


def test_color_loss_after_press_never_repeats_reported_133ms_release():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now in (0.18, 0.30, 0.6, 1.0):
        assert engine.step(obs(), now) == []
        assert 0 in engine.pressed
    for now, y in ((1.1, 700), (1.15, 750), (1.2, 800), (1.25, 850)):
        assert engine.step(obs(Head(0, "end", y)), now) == []
    assert [(a.down, a.reason) for a in engine.step(obs(), 1.325)] == [(False, "end cap")]


def test_detection_latency_is_included_in_press_decision():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    events = engine.step(obs(Head(0, "hold", 900)), 0.14, action_at=0.165)
    assert [(a.down, a.reason) for a in events] == [(True, "hold")]


@pytest.mark.parametrize("phase", range(4))
def test_irregular_capture_and_centroid_noise_keep_start_timing_stable(phase):
    engine = Engine(920, lead_ms=0)
    now = 0.0
    downs = []
    for tick in range(70):
        now += (0.013, 0.022, 0.016, 0.017)[(tick + phase) % 4]
        visible_time = int(now * 60) / 60
        y = 500 + 600 * visible_time + (-3, 2, -2, 3)[tick % 4]
        heads = [Head(0, "hold", y)] if y <= 962 else []
        downs.extend(now for a in engine.step(obs(*heads), now) if a.down)
    assert downs == [pytest.approx(0.7, abs=0.035)]


def supported(*heads, tail=False, support=0):
    # Keep the engine contract independent of the optional vision field's default.
    return SimpleNamespace(heads=list(heads), tail_present=[tail] * 6, hold_support=[support] * 6)


def test_unseen_ribbon_does_not_end_a_confirmed_hold_after_120ms():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    assert engine.step(obs(Head(0, "hold", 925)), 0.165)[0].down
    for now in (0.18, 0.3, 0.5):
        assert engine.step(obs(), now) == []
    for now, y in ((0.6, 760), (0.65, 810), (0.7, 860), (0.75, 910)):
        assert engine.step(obs(Head(0, "end", y)), now) == []
    actions = engine.step(obs(Head(0, "end", 925)), 0.765)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]


def test_same_purple_circle_cannot_split_and_release_its_own_start():
    engine = Engine(920, lead_ms=0)
    actions = []
    for now, y, kind in (
        (0, 760, "hold"),
        (0.016, 776, "hold"),
        (0.033, 793, "end"),
        (0.05, 810, "end"),
        (0.066, 826, "hold"),
        (0.083, 843, "hold"),
        (0.1, 860, "hold"),
        (0.116, 876, "hold"),
        (0.133, 893, "hold"),
        (0.15, 910, "hold"),
        (0.166, 926, "hold"),
        (0.175, 935, "end"),
        (0.185, 945, "end"),
        (0.195, 955, "end"),
    ):
        actions.extend(engine.step(obs(Head(0, kind, y), tail=True), now))
    assert [(a.key, a.down) for a in actions] == [("a", True)]
    assert engine.pressed[0].kind == "hold"


def test_endpoint_seen_before_start_survives_long_occlusion():
    engine = Engine(920, lead_ms=0)
    actions = []
    for now in (0, 0.05, 0.1, 0.15, 0.165):
        heads = [Head(0, "hold", 760 + now * 1000)]
        if now <= 0.1:
            heads.append(Head(0, "end", 500 + now * 1000))
        actions.extend(engine.step(obs(*heads), now))
    assert [(a.key, a.down) for a in actions] == [("a", True)]
    for now in (0.20, 0.3, 0.41):
        assert engine.step(obs(), now) == []
    actions = engine.step(obs(), 0.425)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]


def test_trusted_endpoint_deadline_overrides_local_ribbon_loss():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now, y in ((0.2, 400), (0.25, 450), (0.3, 500)):
        assert engine.step(obs(Head(0, "end", y), tail=True), now) == []
    for now in (0.35, 0.45, 0.6, 0.71):
        assert engine.step(obs(), now) == []
    actions = engine.step(obs(), 0.725)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]


def test_confirmed_end_stays_an_end_when_near_line_color_role_flips():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now, y, kind in (
        (0.4, 700, "end"),
        (0.45, 750, "end"),
        (0.5, 800, "end"),
        (0.55, 850, "hold"),
        (0.6, 900, "hold"),
    ):
        assert engine.step(obs(Head(0, kind, y), tail=True), now) == []
    actions = engine.step(obs(Head(0, "hold", 925), tail=True), 0.625)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]


def test_capture_boundary_hold_guess_can_become_a_confirmed_orphan_end():
    engine = Engine(920, lead_ms=0)
    actions = []
    for now, y, kind in (
        (0, 550, "hold"),
        (0.05, 600, "hold"),
        (0.10, 650, "end"),
        (0.15, 700, "end"),
        (0.20, 750, "end"),
        (0.25, 800, "hold"),
        (0.30, 850, "hold"),
        (0.35, 900, "hold"),
        (0.375, 925, "hold"),
    ):
        actions.extend(engine.step(obs(Head(0, kind, y), tail=True), now))
    assert actions == []


def test_endpoint_estimate_is_updated_when_its_observed_motion_changes():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now, y in ((0.4, 600), (0.45, 650), (0.5, 700), (0.6, 760), (0.65, 790)):
        assert engine.step(obs(Head(0, "end", y), tail=True), now) == []
    # Earlier observations projected arrival at .72; the later slowdown must update it.
    assert engine.step(obs(), 0.73) == []
    end_at = engine.pressed[0].end_at
    assert end_at is not None and end_at > 0.78
    assert [(a.key, a.down) for a in engine.step(obs(), end_at + 0.001)] == [("a", False)]


def test_upstream_support_protects_a_hold_during_local_dropout():
    engine = Engine(920, lead_ms=0, allow_color_release=True)
    approach(engine, kind="hold")
    engine.step(supported(Head(0, "hold", 925), support=300), 0.165)
    for now in (0.18, 0.3, 0.35):
        assert engine.step(supported(), now) == []
    actions = engine.step(supported(), 0.5)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "tail ended")]


def test_real_endpoint_overrides_lingering_purple_support_and_glow():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now, y in ((0.2, 700), (0.25, 750), (0.3, 800)):
        assert engine.step(supported(Head(0, "end", y), tail=True, support=300), now) == []
    actions = engine.step(supported(tail=True, support=300), 0.425)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]


@pytest.mark.parametrize("fps", [20, 30, 120])
def test_short_hold_and_its_separate_endpoint_do_not_merge_at_low_fps(fps):
    engine = Engine(920, lead_ms=0)
    events = []
    for n in range(round(fps * 0.5) + 1):
        now = n / fps
        heads = [
            Head(0, kind, start_y + now * 1000)
            for kind, start_y in (("hold", 760), ("end", 660))
            if start_y + now * 1000 <= 962
        ]
        events.extend((now, a.down, a.reason) for a in engine.step(obs(*heads, tail=True), now))
    assert [down for _, down, _ in events] == [True, False]
    assert events[0][0] == pytest.approx(0.16, abs=1 / fps)
    assert events[1][0] == pytest.approx(0.26, abs=1 / fps)
    assert events[1][2] == "end cap"


def test_tap_after_hold_end_on_same_frame_is_not_swallowed():
    engine = Engine(920, lead_ms=0)
    events = []
    for n in range(40):
        now = n / 60
        heads = [
            Head(0, kind, start_y + now * 1000)
            for kind, start_y in (("hold", 760), ("end", 500), ("tap", 495))
            if start_y + now * 1000 <= 962
        ]
        events.extend(engine.step(obs(*heads, tail=True), now))
    assert [(a.down, a.reason) for a in events] == [
        (True, "hold"),
        (False, "end cap"),
        (True, "tap"),
        (False, "tap complete"),
    ]


def test_stop_discards_saved_endpoint_deadlines_for_every_lane():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold", lanes=(0, 4))
    engine.step(obs(Head(0, "hold", 925), Head(4, "hold", 925), tail=True), 0.165)
    for now, y in ((0.2, 500), (0.25, 550), (0.3, 600)):
        engine.step(obs(Head(0, "end", y), Head(4, "end", y), tail=True), now)
    assert {a.key for a in engine.stop()} == {"a", "k"}
    assert engine.step(obs(), 0.7) == []


def test_next_hold_ribbon_cannot_extend_the_previous_hold_color_fallback():
    engine = Engine(920, lead_ms=0, allow_color_release=True)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    # The old ribbon has cleared. These upper pixels belong to a separate
    # upcoming start between the support sample and the judgement line.
    assert engine.step(supported(Head(0, "hold", 720), support=248), 0.2) == []
    assert engine.step(supported(Head(0, "hold", 770), support=248), 0.25) == []
    actions = engine.step(supported(Head(0, "hold", 820), support=248), 0.3)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "tail ended")]


def test_partial_end_centroid_cannot_turn_judgement_glow_into_a_slowdown():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now, y in ((0.4, 700), (0.45, 750), (0.5, 800)):
        assert engine.step(obs(Head(0, "end", y), tail=True), now) == []
    # The circle actually reaches 850/900, but its lower half is hidden.
    # Vision cannot establish end direction and reports a biased hold centre.
    assert engine.step(obs(Head(0, "hold", 825)), 0.55) == []
    assert engine.step(obs(Head(0, "hold", 840)), 0.6) == []
    actions = engine.step(obs(), 0.625)
    assert [(a.key, a.down, a.reason) for a in actions] == [("a", False, "end cap")]


def test_repeated_capture_of_one_end_label_is_not_three_end_observations():
    engine = Engine(920, lead_ms=0)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925), tail=True), 0.165)
    for now, y, kind in (
        (0.2, 600, "hold"),
        (0.25, 650, "hold"),
        (0.3, 700, "end"),
        (0.305, 700, "end"),
        (0.31, 700, "end"),
        (0.315, 700, "end"),
        (0.35, 750, "hold"),
        (0.4, 800, "hold"),
        (0.45, 850, "hold"),
        (0.5, 900, "hold"),
    ):
        assert engine.step(obs(Head(0, kind, y), tail=True), now) == []
    assert engine.step(obs(tail=True), 0.6) == []
    assert 0 in engine.pressed


def test_hold_with_no_color_or_endpoint_still_has_timeout():
    engine = Engine(920, lead_ms=0, max_hold_seconds=1)
    approach(engine, kind="hold")
    engine.step(obs(Head(0, "hold", 925)), 0.165)
    assert engine.step(obs(), 1) == []
    assert [(a.down, a.reason) for a in engine.step(obs(), 1.2)] == [(False, "hold timeout")]


def test_independent_endpoint_deadlines_release_each_lane_at_its_own_time():
    engine = Engine(920, lead_ms=0)
    events = []
    for tick in range(50):
        now = tick / 60
        heads = [
            Head(lane, kind, y + now * 1000)
            for lane, kind, y in (
                (0, "hold", 760),
                (0, "end", 500),
                (4, "hold", 760),
                (4, "end", 300),
            )
            if y + now * 1000 <= 962
        ]
        events.extend((now, a.key, a.down) for a in engine.step(obs(*heads, tail=True), now))
    releases = {key: now for now, key, down in events if not down}
    assert releases == {"a": pytest.approx(0.42, abs=1 / 60), "k": pytest.approx(0.62, abs=1 / 60)}
    assert len(events) == 4


@pytest.mark.parametrize("fps", [20, 120])
def test_consecutive_holds_keep_four_distinct_circle_identities(fps):
    engine = Engine(920, lead_ms=0)
    events = []
    for tick in range(round(fps * 0.9) + 1):
        now = tick / fps
        heads = [
            Head(0, kind, y + now * 1000)
            for kind, y in (("hold", 760), ("end", 520), ("hold", 440), ("end", 120))
            if y + now * 1000 <= 962
        ]
        events.extend((now, a.down) for a in engine.step(obs(*heads, tail=True), now))
    assert [down for _, down in events] == [True, False, True, False]
    for (actual, _), expected in zip(events, (0.16, 0.4, 0.48, 0.8), strict=True):
        assert actual == pytest.approx(expected, abs=1 / fps)
