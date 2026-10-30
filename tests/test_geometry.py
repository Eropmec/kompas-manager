import math

from kompas_manager.core.geometry import IDENTITY, compose, detect_layout, transform_point


def rot_z_row(a, t=(0, 0, 0)):
    c, s = math.cos(a), math.sin(a)
    return (c, s, 0, 0,
            -s, c, 0, 0,
            0, 0, 1, 0,
            t[0], t[1], t[2], 1)


def transpose(m):
    return tuple(m[c * 4 + r] for r in range(4) for c in range(4))


def close(a, b):
    return all(abs(x - y) < 1e-9 for x, y in zip(a, b))


def test_compose_matches_two_step_transform():
    sub = rot_z_row(math.pi / 2, (100, 0, 0))  # подсборка повернута на 90° и сдвинута
    comp = rot_z_row(0, (10, 0, 0))  # компонент в подсборке сдвинут на 10 по X
    p = (1, 2, 3)
    for layout, s, c in (("row", sub, comp), ("col", transpose(sub), transpose(comp))):
        world = compose(s, c, layout)
        expect = transform_point(s, transform_point(c, p, layout), layout)
        assert close(transform_point(world, p, layout), expect)
    # точка (0,0,0) компонента -> (10,0,0) в подсборке -> поворот (0,10,0) -> сдвиг (100,10,0)
    assert close(transform_point(compose(sub, comp, "row"), (0, 0, 0), "row"), (100, 10, 0))


def test_identity_shortcuts_and_layout():
    comp = rot_z_row(0.3, (5, 6, 7))
    assert compose(IDENTITY, comp) == comp
    assert compose(comp, IDENTITY) == comp
    assert detect_layout([IDENTITY, comp]) == "row"
    assert detect_layout([transpose(comp)]) == "col"
    assert detect_layout([IDENTITY], default="col") == "col"
