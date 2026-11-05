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

@app.route(
    route="erp-customer-sample",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_customer_sample(req: func.HttpRequest) -> func.HttpResponse:

    server = "sytelinedb-man-intance.054b4836a25e.database.windows.net"
    database = "HARLAN_APP_0709"

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
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TOP (5)
                CustNum,
                CustSeq,
                Name,
                City,
                State,
                Territory,
                CustomerType,
                CustomerTypeDescription,
                CustomerAccountStatusID,
                CustomerAccountStatusDescription
            FROM dbo.ESBCustomerView
            ORDER BY Name, CustNum
        """)

        rows = cursor.fetchall()

        customers = [
            {
                "customer_number": row[0],
                "customer_sequence": row[1],
                "name": row[2],
                "city": row[3],
                "state": row[4],
                "territory": row[5],
                "customer_type": row[6],
                "customer_type_description": row[7],
                "account_status_id": row[8],
                "account_status": row[9]
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "view": "dbo.ESBCustomerView",
            "returned_rows": len(customers),
            "customers": customers
        }

        return func.HttpResponse(
            json.dumps(result, default=str, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "connection": "Failed",
                "error": str(e)
            }),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
