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
        "connection": "Not tested"
    }

    try:
        connection_string = (
            f"Server={server},1433;"
            f"Database={database};"
            "Authentication=ActiveDirectoryMSI;"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )

        conn = mssql_python.connect(connection_string)
        cursor = conn.cursor()

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

        row = cursor.fetchone()

        result["connection"] = "Success"
        result["database_user"] = row[1]
        result["database_name"] = row[0]
        result["original_login"] = row[2]

        cursor.close()
        conn.close()

    except Exception as e:
        result["connection"] = "Failed"
        result["error"] = str(e)

    return func.HttpResponse(
        json.dumps(result, indent=2),
        mimetype="application/json",
        status_code=200
    )
