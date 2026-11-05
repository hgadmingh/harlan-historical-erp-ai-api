import azure.functions as func
import socket
import json
import os
import mssql_python

app = func.FunctionApp()

@app.route(
    route="sql-connection-test",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def sql_connection_test(req: func.HttpRequest) -> func.HttpResponse:

    server = "sytelinedb-man-intance.054b4836a25e.database.windows.net"
    database = "HARLAN_APP_0709"

    result = {
        "server": server,
        "database": database,
        "authentication": "Managed Identity",
        "connection": "Not tested",
        "view_query": "Not tested"
    }

    conn = None
    cursor = None

    try:
        connection_string = (
            f"Server={server},1433;"
            f"Database={database};"
            "Authentication=ActiveDirectoryMSI;"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )

        conn = mssql_python.connect(connection_string)
        result["connection"] = "Success"

        cursor = conn.cursor()

        # Verify the authenticated database identity
        cursor.execute("""
            SELECT
                DB_NAME(),
                USER_NAME(),
                ORIGINAL_LOGIN()
        """)

        identity = cursor.fetchone()

        if identity:
            result["database_name"] = identity[0]
            result["database_user"] = identity[1]
            result["original_login"] = identity[2]

        # Count views visible to this identity
        cursor.execute("""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.VIEWS
        """)

        count_row = cursor.fetchone()
        result["accessible_view_count"] = count_row[0]

        # Return the first 25 accessible views
        cursor.execute("""
            SELECT TOP (25)
                TABLE_SCHEMA,
                TABLE_NAME
            FROM INFORMATION_SCHEMA.VIEWS
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """)

        rows = cursor.fetchall()

        result["accessible_views"] = [
            {"schema": row[0], "view": row[1]}
            for row in rows
        ]

        result["view_query"] = "Success"

    except Exception as e:
        if result["connection"] == "Success":
            result["view_query"] = "Failed"
        else:
            result["connection"] = "Failed"

        result["error"] = str(e)

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return func.HttpResponse(
        json.dumps(result, indent=2),
        mimetype="application/json",
        status_code=200
    )
