class CursorPaginator:
    def __init__(self, cursor: str | None = None):
        self.cursor = cursor

    def page(self) -> list[dict]:
        return [{"id": 1, "name": "Ada", "cursor": self.cursor}]
