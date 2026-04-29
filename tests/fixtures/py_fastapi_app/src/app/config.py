import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "changeme")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
