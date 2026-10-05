from dmi_ohs.database import get_connection


def main():
    print("Hello from Python!")


    try:
        connection = get_connection()
        print("Connected to PostgreSQL!")
    finally:
        connection.close()


if __name__ == "__main__":
    main()