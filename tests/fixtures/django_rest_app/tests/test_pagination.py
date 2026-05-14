from api.pagination import CursorPaginator


def test_cursor_paginator_returns_rows():
    rows = CursorPaginator(cursor="abc").page()
    assert rows[0]["cursor"] == "abc"
