from dmi_ohs.database import get_connection


def test_database_connection():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

        assert result[0] == 1

    finally:
        connection.close()