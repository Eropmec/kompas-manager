"""Положения компонентов: матрицы 4×4 из IPlacement3D.GetMatrix3D (16 чисел подряд).

Раскладка матрицы в справке КОМПАСа не описана, поэтому она определяется по самим данным:
- «row»: перенос в элементах 12, 13, 14 (вектор-строка, p' = p·M);
- «col»: перенос в элементах 3, 7, 11 (вектор-столбец, p' = M·p).
Положение компонента подсборки в сборке верхнего уровня: сначала своё положение в подсборке,
затем положение подсборки в сборке.
"""

IDENTITY = (1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0)

EPS = 1e-9


def as_matrix(values):
    m = tuple(float(v) for v in values)
    if len(m) != 16:
        raise ValueError(f"ожидалось 16 чисел, получено {len(m)}")
    return m


def is_identity(m, eps=1e-7):
    return all(abs(a - b) < eps for a, b in zip(m, IDENTITY))


def detect_layout(matrices, default="row"):
    """Раскладка по матрицам с ненулевым переносом; если переноса нет ни в одной — default."""
    for m in matrices:
        row_t = any(abs(m[i]) > EPS for i in (12, 13, 14))
        col_t = any(abs(m[i]) > EPS for i in (3, 7, 11))
        if row_t and not col_t:
            return "row"
        if col_t and not row_t:
            return "col"
    return default


def multiply(a, b):
    """Произведение матриц 4×4, записанных по строкам."""
    return tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4))


def compose(outer, inner, layout="row"):
    """Положение компонента (inner — в подсборке) в сборке, куда вставлена подсборка (outer)."""
    if is_identity(outer):
        return tuple(inner)
    if is_identity(inner):
        return tuple(outer)
    return multiply(inner, outer) if layout == "row" else multiply(outer, inner)


def transform_point(m, p, layout="row"):
    x, y, z = p
    if layout == "row":
        return tuple(x * m[c] + y * m[4 + c] + z * m[8 + c] + m[12 + c] for c in range(3))
    return tuple(m[r * 4] * x + m[r * 4 + 1] * y + m[r * 4 + 2] * z + m[r * 4 + 3] for r in range(3))
