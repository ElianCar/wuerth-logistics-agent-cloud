import psycopg

from app.config import get_config


def get_connection() -> psycopg.Connection:
    config = get_config()
    connection_args = {
        "host": config.postgres_host,
        "port": config.postgres_port,
        "dbname": config.postgres_db,
        "user": config.postgres_user,
    }

    if config.postgres_password:
        connection_args["password"] = config.postgres_password

    try:
        return psycopg.connect(**connection_args)
    except psycopg.Error as error:
        raise RuntimeError(
            "Could not connect to PostgreSQL. "
            "Check that PostgreSQL is running and that your .env settings are correct. "
            f"Original error: {error}"
        ) from error
