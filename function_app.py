import azure.functions as func
import socket
import json

app = func.FunctionApp()

@app.route(
    route="sql-network-test",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def sql_network_test(req: func.HttpRequest) -> func.HttpResponse:

    hostname = "sytelinedb-man-intance.054b4836a25e.database.windows.net"
    port = 1433

    result = {
        "hostname": hostname,
        "port": port,
        "dns": "Not tested",
        "tcp": "Not tested"
    }

    try:
        addresses = socket.getaddrinfo(hostname, port)
        result["dns"] = "Success"
        result["resolved_addresses"] = list(
            set(item[4][0] for item in addresses)
        )

        try:
            connection = socket.create_connection(
                (hostname, port), timeout=8
            )
            connection.close()
            result["tcp"] = "Success"
        except Exception as e:
            result["tcp"] = f"Failed: {str(e)}"

    except Exception as e:
        result["dns"] = f"Failed: {str(e)}"

    return func.HttpResponse(
        json.dumps(result, indent=2),
        mimetype="application/json",
        status_code=200
    )
