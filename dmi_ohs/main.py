from dmi_ohs.database import get_connection
from dmi_ohs.migrations import run_migrations


def main():
    print("Hello from Python!")

    run_migrations()
    try:
        connection = get_connection()
        print("Connected to PostgreSQL!")
    finally:
        connection.close()


if __name__ == "__main__":
    main()