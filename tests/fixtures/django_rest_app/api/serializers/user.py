class UserSerializer:
    def __init__(self, user: dict):
        self.user = user

    @property
    def data(self) -> dict:
        if "id" not in self.user:
            raise ValueError("user id is required")
        return {"id": self.user["id"], "name": self.user.get("name", "")}
