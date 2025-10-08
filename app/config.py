import os

class Config:
    # Secret key for session security
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev_secret")

    # PostgreSQL connection
    # Note: '@' in passwords must be encoded as '%40'
    POSTGRES_USER = os.environ.get("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "Nicefa%4004")  # '@' replaced with %40
    POSTGRES_DB = os.environ.get("POSTGRES_DB", "surveyzim_db")
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
