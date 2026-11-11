import azure.functions as func
import base64
import csv
import io
import json
import mssql_python
import os
import uuid

from datetime import datetime, timedelta, timezone
from functools import wraps

from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    ContentSettings,
    generate_blob_sas
)


# =========================================================
# HISTORICAL ERP API AUTHORIZATION
# Azure App Service Authentication (Easy Auth) must be
# configured to require authentication before requests reach
# this Function App. Easy Auth validates the incoming token and
# supplies X-MS-CLIENT-PRINCIPAL to this code.
# =========================================================

REQUIRED_API_SCOPE = "historicalerp.read"
REQUIRED_API_ROLE = "HistoricalERP.Access"


def authorize_erp_request(req: func.HttpRequest):
    encoded_principal = req.headers.get("X-MS-CLIENT-PRINCIPAL")

    if not encoded_principal:
        return func.HttpResponse(
            json.dumps({"error": "Authentication required."}),
            mimetype="application/json",
            status_code=401
        )

    try:
        padding = "=" * (-len(encoded_principal) % 4)
        principal_json = base64.b64decode(
            encoded_principal + padding,
            validate=True
        ).decode("utf-8")
        principal = json.loads(principal_json)

        # This API is intended to accept Microsoft Entra identities only.
        if str(principal.get("auth_typ", "")).lower() != "aad":
            return func.HttpResponse(
                json.dumps({"error": "A Microsoft Entra identity is required."}),
                mimetype="application/json",
                status_code=401
            )

        claims = principal.get("claims", [])
        if not isinstance(claims, list):
            raise ValueError("Invalid claims collection")

        role_claim_type = str(principal.get("role_typ", "roles")).lower()
        scopes = set()
        roles = set()

        for claim in claims:
            if not isinstance(claim, dict):
                continue

            claim_type = str(claim.get("typ", "")).lower()
            claim_value = str(claim.get("val", "")).strip()

            if not claim_value:
                continue

            # Easy Auth may map the delegated scope claim to either
            # 'scp'/'scope' or the Microsoft claims URI ending in '/scope'.
            if (
                claim_type in ("scp", "scope")
                or claim_type.endswith("/scope")
            ):
                scopes.update(claim_value.split())

            # Use Easy Auth's role_typ when present, and support the
            # standard role/roles claim names and Microsoft role URI.
            if (
                claim_type == role_claim_type
                or claim_type in ("role", "roles")
                or claim_type.endswith("/role")
            ):
                roles.add(claim_value)

    except Exception:
        return func.HttpResponse(
            json.dumps({"error": "Unable to read the authenticated identity claims."}),
            mimetype="application/json",
            status_code=401
        )

    if REQUIRED_API_SCOPE not in scopes:
        return func.HttpResponse(
            json.dumps({
                "error": "You do not have the required API permission.",
                "required_scope": REQUIRED_API_SCOPE
            }),
            mimetype="application/json",
            status_code=403
        )

    if REQUIRED_API_ROLE not in roles:
        return func.HttpResponse(
            json.dumps({
                "error": "You are not authorized to access Harlan historical ERP data.",
                "required_role": REQUIRED_API_ROLE
            }),
            mimetype="application/json",
            status_code=403
        )

    return None


def require_erp_access(handler):
    @wraps(handler)
    def wrapped(req: func.HttpRequest) -> func.HttpResponse:
        auth_response = authorize_erp_request(req)
        if auth_response is not None:
            return auth_response
        return handler(req)

    return wrapped


app = func.FunctionApp()


# =========================================================
# 1. SQL CONNECTION TEST
# =========================================================

@app.route(
    route="sql-connection-test",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
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

        cursor.execute("""
            SELECT DB_NAME(), USER_NAME(), ORIGINAL_LOGIN()
        """)
        identity = cursor.fetchone()

        if identity:
            result["database_name"] = identity[0]
            result["database_user"] = identity[1]
            result["original_login"] = identity[2]

        cursor.execute("""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.VIEWS
        """)
        count_row = cursor.fetchone()
        result["accessible_view_count"] = count_row[0]

        cursor.execute("""
            SELECT TOP (25) TABLE_SCHEMA, TABLE_NAME
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


# =========================================================
# 2. CUSTOMER SEARCH
# =========================================================

@app.route(
    route="erp-customer-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_customer_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for customer search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            SELECT TOP (25)
                CustNum, CustSeq, Name, City, State, Territory,
                CustomerType, CustomerTypeDescription,
                CustomerAccountStatusID, CustomerAccountStatusDescription
            FROM dbo.ESBCustomerView
            WHERE Name IS NOT NULL
              AND LTRIM(RTRIM(Name)) <> ''
              AND (
                  LTRIM(RTRIM(CustNum)) LIKE %(search)s
                  OR Name LIKE %(search)s
              )
            ORDER BY Name, CustNum, CustSeq
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        customers = [
            {
                "customer_number": str(row[0]).strip() if row[0] else None,
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
            "search_term": search,
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
            json.dumps({"connection": "Failed", "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



# =========================================================
# 3. SALES ORDER SEARCH WITH PAGINATION
# =========================================================

@app.route(
    route="erp-sales-order-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_sales_order_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters."}),
            mimetype="application/json",
            status_code=400
        )

    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

    # Pagination parameters
    try:
        page_size = int(req.params.get("page_size", "100"))
        offset = int(req.params.get("offset", "0"))
    except (ValueError, TypeError):
        return func.HttpResponse(
            json.dumps({
                "error": "page_size and offset must be valid integers."
            }),
            mimetype="application/json",
            status_code=400
        )

    if page_size < 1 or page_size > 100:
        return func.HttpResponse(
            json.dumps({
                "error": "page_size must be between 1 and 100."
            }),
            mimetype="application/json",
            status_code=400
        )

    if offset < 0:
        return func.HttpResponse(
            json.dumps({
                "error": "offset cannot be negative."
            }),
            mimetype="application/json",
            status_code=400
        )

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

        search_params = {"search": f"%{search}%"}

        # Count all matching records
        cursor.execute("""
            SELECT COUNT_BIG(*)
            FROM dbo.ESBSalesOrderView
            WHERE
                LTRIM(RTRIM(CoNum)) LIKE %(search)s
                OR LTRIM(RTRIM(CustomerID)) LIKE %(search)s
                OR CustomerName LIKE %(search)s
                OR CustPo LIKE %(search)s
        """, search_params)

        total_matching_rows = int(cursor.fetchone()[0])

        # Retrieve the requested page
        cursor.execute("""
            SELECT
                CoNum, OrderDate, DerStat, DerStatDescription,
                CustomerID, CustomerName, CustPo, DerExtAmt, Whse
            FROM dbo.ESBSalesOrderView
            WHERE
                LTRIM(RTRIM(CoNum)) LIKE %(search)s
                OR LTRIM(RTRIM(CustomerID)) LIKE %(search)s
                OR CustomerName LIKE %(search)s
                OR CustPo LIKE %(search)s
            ORDER BY OrderDate DESC, CoNum DESC
            OFFSET %(offset)s ROWS
            FETCH NEXT %(page_size)s ROWS ONLY
        """, {
            "search": f"%{search}%",
            "offset": offset,
            "page_size": page_size
        })

        rows = cursor.fetchall()

        orders = [
            {
                "sales_order": str(row[0]).strip() if row[0] else None,
                "order_date": row[1],
                "status": row[2],
                "status_description": row[3],
                "customer_number": str(row[4]).strip() if row[4] else None,
                "customer_name": row[5],
                "customer_po": row[6],
                "order_amount": row[7],
                "warehouse": row[8]
            }
            for row in rows
        ]

        next_offset = offset + len(orders)
        has_more = next_offset < total_matching_rows

        result = {
            "connection": "Success",
            "view": "dbo.ESBSalesOrderView",
            "search_term": search,
            "total_matching_rows": total_matching_rows,
            "returned_rows": len(orders),
            "page_size": page_size,
            "offset": offset,
            "next_offset": next_offset if has_more else None,
            "has_more": has_more,
            "sales_orders": orders
        }

        return func.HttpResponse(
            json.dumps(result, default=str, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"connection": "Failed", "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =========================================================
# 4. SALES ORDER CSV EXPORT
# Exact customer number match; exports all matching rows.
# =========================================================

@app.route(
    route="erp-sales-order-export",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_sales_order_export(req: func.HttpRequest) -> func.HttpResponse:

    customer_number = (req.params.get("customer_number") or "").strip()

    if not customer_number:
        return func.HttpResponse(
            json.dumps({"error": "Please provide a customer number."}),
            mimetype="application/json",
            status_code=400
        )

    if len(customer_number) > 50:
        return func.HttpResponse(
            json.dumps({"error": "Customer number is too long."}),
            mimetype="application/json",
            status_code=400
        )

    storage_account = os.environ.get("ERP_EXPORT_STORAGE_ACCOUNT")
    container_name = os.environ.get("ERP_EXPORT_CONTAINER")

    if not storage_account or not container_name:
        return func.HttpResponse(
            json.dumps({"error": "Export storage configuration is missing."}),
            mimetype="application/json",
            status_code=500
        )

    conn = None
    cursor = None

    try:
        # Connect to historical SyteLine SQL database.
        server = "sytelinedb-man-intance.054b4836a25e.database.windows.net"
        database = "HARLAN_APP_0709"

        connection_string = (
            f"Server={server},1433;"
            f"Database={database};"
            "Authentication=ActiveDirectoryMSI;"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )

        conn = mssql_python.connect(connection_string)
        cursor = conn.cursor()

        # Exact customer-number match.
        cursor.execute("""
            SELECT
                CoNum, OrderDate, DerStat, DerStatDescription,
                CustomerID, CustomerName, CustPo, DerExtAmt, Whse
            FROM dbo.ESBSalesOrderView
            WHERE LTRIM(RTRIM(CustomerID)) = %(customer_number)s
            ORDER BY OrderDate DESC, CoNum DESC
        """, {"customer_number": customer_number})

        rows = cursor.fetchall()

        # Generate CSV in memory.
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Sales Order",
            "Order Date",
            "Status",
            "Status Description",
            "Customer Number",
            "Customer Name",
            "Customer PO",
            "Order Amount",
            "Warehouse"
        ])

        for row in rows:
            writer.writerow([
                str(row[0]).strip() if row[0] else "",
                row[1],
                row[2],
                row[3],
                str(row[4]).strip() if row[4] else "",
                row[5],
                row[6],
                row[7],
                row[8]
            ])

        csv_content = output.getvalue().encode("utf-8-sig")
        output.close()

        # Use the Function App's managed identity.
        credential = DefaultAzureCredential()

        account_url = f"https://{storage_account}.blob.core.windows.net"

        blob_service = BlobServiceClient(
            account_url=account_url,
            credential=credential
        )

        blob_name = (
            f"sales-orders/customer-{customer_number}/"
            f"sales-orders-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-"
            f"{uuid.uuid4().hex[:8]}.csv"
        )

        blob_client = blob_service.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        blob_client.upload_blob(
            csv_content,
            overwrite=False,
            content_settings=ContentSettings(
                content_type="text/csv; charset=utf-8"
            )
        )

        # Generate a short-lived user-delegation SAS URL.
        now = datetime.now(timezone.utc)
        starts_on = now - timedelta(minutes=5)
        expires_on = now + timedelta(minutes=15)

        delegation_key = blob_service.get_user_delegation_key(
            key_start_time=starts_on,
            key_expiry_time=expires_on
        )

        sas_token = generate_blob_sas(
            account_name=storage_account,
            container_name=container_name,
            blob_name=blob_name,
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(read=True),
            start=starts_on,
            expiry=expires_on
        )

        download_url = f"{blob_client.url}?{sas_token}"

        return func.HttpResponse(
            json.dumps({
                "connection": "Success",
                "customer_number": customer_number,
                "exported_rows": len(rows),
                "file_name": blob_name.split("/")[-1],
                "container": container_name,
                "download_url": download_url,
                "link_expires_utc": expires_on.isoformat(),
                "message": "CSV export created successfully."
            }, default=str, indent=2),
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


# =========================================================
# 5. PRODUCTION ORDER CSV EXPORT
# Exports all historical production orders.
# =========================================================

@app.route(
    route="erp-production-export",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_production_export(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

    storage_account = os.environ.get("ERP_EXPORT_STORAGE_ACCOUNT")
    container_name = os.environ.get("ERP_EXPORT_CONTAINER")

    if not storage_account or not container_name:
        return func.HttpResponse(
            json.dumps({"error": "Export storage configuration is missing."}),
            mimetype="application/json",
            status_code=500
        )

    conn = None
    cursor = None

    try:
        server = "sytelinedb-man-intance.054b4836a25e.database.windows.net"
        database = "HARLAN_APP_0709"

        connection_string = (
            f"Server={server},1433;"
            f"Database={database};"
            "Authentication=ActiveDirectoryMSI;"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
        )

        conn = mssql_python.connect(connection_string)
        cursor = conn.cursor()

        sql = """
            SELECT
                Job, Suffix, Item, ItemDescription, Description,
                Status, StatusDesc, OrderQty, DueQty, ProducedQty,
                ItemUM, StartDate, EndDate, DueDate,
                EstMatlCost, EstLaborCost, EstFixOvhdCost,
                EstVarOvhdCost, EstOutsideCost, EstBurdenCost,
                EstTotalCost, ActMatlCost, ActLaborCost,
                ActFixOvhdCost, ActVarOvhdCost, ActOutsideCost,
                ActBurdenCost, ActTotalCost, WhseID
            FROM dbo.ESBProductionOrderView
        """

        params = {}

        if search:
            sql += """
                WHERE
                    LTRIM(RTRIM(Job)) LIKE %(search)s
                    OR LTRIM(RTRIM(Item)) LIKE %(search)s
                    OR ItemDescription LIKE %(search)s
                    OR Description LIKE %(search)s
                    OR Status LIKE %(search)s
                    OR StatusDesc LIKE %(search)s
            """
            params["search"] = f"%{search}%"

        sql += """
            ORDER BY
                CASE WHEN DueDate IS NULL THEN 1 ELSE 0 END,
                DueDate, Job, Suffix
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Job Number",
            "Job Suffix",
            "Item",
            "Item Description",
            "Production Description",
            "Status",
            "Status Description",
            "Order Quantity",
            "Due Quantity",
            "Produced Quantity",
            "Unit of Measure",
            "Start Date",
            "End Date",
            "Due Date",
            "Estimated Material Cost",
            "Estimated Labor Cost",
            "Estimated Fixed Overhead",
            "Estimated Variable Overhead",
            "Estimated Outside Cost",
            "Estimated Burden Cost",
            "Estimated Total Cost",
            "Actual Material Cost",
            "Actual Labor Cost",
            "Actual Fixed Overhead",
            "Actual Variable Overhead",
            "Actual Outside Cost",
            "Actual Burden Cost",
            "Actual Total Cost",
            "Warehouse"
        ])

        for row in rows:
            writer.writerow([
                str(value).strip() if isinstance(value, str) else value
                for value in row
            ])

        csv_content = output.getvalue().encode("utf-8-sig")
        output.close()

        credential = DefaultAzureCredential()
        account_url = f"https://{storage_account}.blob.core.windows.net"

        blob_service = BlobServiceClient(
            account_url=account_url,
            credential=credential
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        unique_id = uuid.uuid4().hex[:8]

        blob_name = (
            f"production-orders/"
            f"production-orders-{timestamp}-{unique_id}.csv"
        )

        blob_client = blob_service.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        blob_client.upload_blob(
            csv_content,
            overwrite=False,
            content_settings=ContentSettings(
                content_type="text/csv; charset=utf-8"
            )
        )

        now = datetime.now(timezone.utc)
        starts_on = now - timedelta(minutes=5)
        expires_on = now + timedelta(minutes=15)

        delegation_key = blob_service.get_user_delegation_key(
            key_start_time=starts_on,
            key_expiry_time=expires_on
        )

        sas_token = generate_blob_sas(
            account_name=storage_account,
            container_name=container_name,
            blob_name=blob_name,
            user_delegation_key=delegation_key,
            permission=BlobSasPermissions(read=True),
            start=starts_on,
            expiry=expires_on
        )

        download_url = f"{blob_client.url}?{sas_token}"

        return func.HttpResponse(
            json.dumps({
                "connection": "Success",
                "view": "dbo.ESBProductionOrderView",
                "search_term": search or "ALL",
                "exported_rows": len(rows),
                "file_name": blob_name.split("/")[-1],
                "container": container_name,
                "download_url": download_url,
                "link_expires_utc": expires_on.isoformat(),
                "message": "Production order CSV export created successfully."
            }, default=str, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception:
        # Avoid returning internal database or storage details.
        return func.HttpResponse(
            json.dumps({
                "connection": "Failed",
                "error": "Production order export failed. Check Function App logs."
            }),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =========================================================
# 4. INVENTORY SEARCH (INCLUDES PRICING)
# =========================================================

@app.route(
    route="erp-inventory-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_inventory_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for inventory search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            SELECT TOP (25)
                item, description, u_m, lead_time, qty_on_hand,
                Dealer, Distributor, Competitive, CLK_List, CLK_Net, OEM
            FROM dbo.AA_HGitems
            WHERE
                item IS NOT NULL
                AND (
                    LTRIM(RTRIM(item)) LIKE %(search)s
                    OR description LIKE %(search)s
                )
            ORDER BY item
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        inventory = [
            {
                "item": str(row[0]).strip() if row[0] else None,
                "description": row[1],
                "unit_of_measure": row[2],
                "lead_time": row[3],
                "quantity_on_hand": row[4],
                "dealer_price": row[5],
                "distributor_price": row[6],
                "competitive_price": row[7],
                "list_price": row[8],
                "net_price": row[9],
                "oem_price": row[10]
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "view": "dbo.AA_HGitems",
            "search_term": search,
            "returned_rows": len(inventory),
            "inventory": inventory
        }
        return func.HttpResponse(
            json.dumps(result, default=str, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"connection": "Failed", "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =========================================================
# 5. PRODUCTION ORDER SEARCH
# =========================================================

@app.route(
    route="erp-production-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_production_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for production search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            SELECT TOP (25)
                Job, Suffix, Item, ItemDescription, Description,
                Status, StatusDesc, OrderQty, DueQty, ProducedQty,
                ItemUM, StartDate, EndDate, DueDate,
                EstMatlCost, EstLaborCost, EstFixOvhdCost,
                EstVarOvhdCost, EstOutsideCost, EstBurdenCost,
                EstTotalCost, ActMatlCost, ActLaborCost,
                ActFixOvhdCost, ActVarOvhdCost, ActOutsideCost,
                ActBurdenCost, ActTotalCost, WhseID
            FROM dbo.ESBProductionOrderView
            WHERE
                LTRIM(RTRIM(Job)) LIKE %(search)s
                OR LTRIM(RTRIM(Item)) LIKE %(search)s
                OR ItemDescription LIKE %(search)s
                OR Description LIKE %(search)s
                OR Status LIKE %(search)s
                OR StatusDesc LIKE %(search)s
            ORDER BY
                CASE WHEN DueDate IS NULL THEN 1 ELSE 0 END,
                DueDate, Job, Suffix
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        production_orders = [
            {
                "job_number": str(row[0]).strip() if row[0] else None,
                "job_suffix": row[1],
                "item": str(row[2]).strip() if row[2] else None,
                "item_description": row[3],
                "production_description": row[4],
                "status": row[5],
                "status_description": row[6],
                "order_quantity": row[7],
                "due_quantity": row[8],
                "produced_quantity": row[9],
                "unit_of_measure": row[10],
                "start_date": row[11],
                "end_date": row[12],
                "due_date": row[13],
                "estimated_material_cost": row[14],
                "estimated_labor_cost": row[15],
                "estimated_fixed_overhead": row[16],
                "estimated_variable_overhead": row[17],
                "estimated_outside_cost": row[18],
                "estimated_burden_cost": row[19],
                "estimated_total_cost": row[20],
                "actual_material_cost": row[21],
                "actual_labor_cost": row[22],
                "actual_fixed_overhead": row[23],
                "actual_variable_overhead": row[24],
                "actual_outside_cost": row[25],
                "actual_burden_cost": row[26],
                "actual_total_cost": row[27],
                "warehouse": row[28]
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "view": "dbo.ESBProductionOrderView",
            "search_term": search,
            "returned_rows": len(production_orders),
            "production_orders": production_orders
        }
        return func.HttpResponse(
            json.dumps(result, default=str, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"connection": "Failed", "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =========================================================
# 6. INVOICE SEARCH
# =========================================================

@app.route(
    route="erp-invoice-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_invoice_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for invoice search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            SELECT TOP (25)
                InvNum, InvDate, ArtDescription, CustNum, Name,
                CoNum, CustPo, ArtDueDate, TotalAmount,
                ExtendedAmount, TaxAmount, DerStatus,
                BillingISOCurrCode
            FROM dbo.ESBInvoiceHeaderView
            WHERE
                LTRIM(RTRIM(InvNum)) LIKE %(search)s
                OR LTRIM(RTRIM(CustNum)) LIKE %(search)s
                OR Name LIKE %(search)s
                OR LTRIM(RTRIM(CoNum)) LIKE %(search)s
                OR CustPo LIKE %(search)s
            ORDER BY InvDate DESC, InvNum
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        invoices = [
            {
                "invoice_number": str(row[0]).strip() if row[0] else None,
                "invoice_date": row[1],
                "invoice_description": row[2],
                "customer_number": str(row[3]).strip() if row[3] else None,
                "customer_name": row[4],
                "sales_order": str(row[5]).strip() if row[5] else None,
                "customer_po": row[6],
                "due_date": row[7],
                "total_amount": row[8],
                "extended_amount": row[9],
                "tax_amount": row[10],
                "status": row[11],
                "currency": row[12]
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "view": "dbo.ESBInvoiceHeaderView",
            "search_term": search,
            "returned_rows": len(invoices),
            "invoices": invoices
        }
        return func.HttpResponse(
            json.dumps(result, default=str, indent=2),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"connection": "Failed", "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# =========================================================
# 7. TOP 10 HISTORICAL AR CUSTOMERS
# =========================================================

@app.route(
    route="erp-ar-top-customers",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_ar_top_customers(req: func.HttpRequest) -> func.HttpResponse:
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
            SELECT TOP (10)
                a.site_ref,
                a.customer_number,
                n.CustomerName,
                a.transaction_rows,
                a.current_balance,
                a.balance_1_to_30,
                a.balance_31_to_60,
                a.balance_61_to_90,
                a.balance_over_90,
                a.total_ar_balance
            FROM dbo.AI_HistoricalARCustomerSummary a
            OUTER APPLY
            (
                SELECT TOP (1)
                    LTRIM(RTRIM(c.Name)) AS CustomerName
                FROM dbo.ESBCustomerView c
                WHERE LTRIM(RTRIM(c.CustNum)) = a.customer_number
                  AND c.Name IS NOT NULL
                  AND LTRIM(RTRIM(c.Name)) <> ''
                ORDER BY
                    CASE WHEN c.CustSeq = 0 THEN 0 ELSE 1 END,
                    c.CustSeq
            ) n
            WHERE a.total_ar_balance > 0
            ORDER BY a.total_ar_balance DESC, a.customer_number
        """)

        rows = cursor.fetchall()
        customers = [
            {
                "rank": index + 1,
                "site": row[0],
                "customer_number": str(row[1]).strip() if row[1] else None,
                "customer_name": row[2],
                "transaction_rows": row[3],
                "aging_buckets": {
                    "current": row[4],
                    "1_to_30_days": row[5],
                    "31_to_60_days": row[6],
                    "61_to_90_days": row[7],
                    "over_90_days": row[8]
                },
                "total_ar_balance": row[9]
            }
            for index, row in enumerate(rows)
        ]

        result = {
            "connection": "Success",
            "report": "Top 10 Historical Accounts Receivable Customers",
            "as_of_date": "2025-12-31",
            "data_status": "Historical static snapshot",
            "summary_table": "dbo.AI_HistoricalARCustomerSummary",
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
                "report": "Top 10 Historical Accounts Receivable Customers",
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


# =========================================================
# 8. HISTORICAL AR CUSTOMER AGING SEARCH
# =========================================================

@app.route(
    route="erp-ar-customer-aging",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_ar_customer_aging(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for customer search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            WITH MatchingCustomers AS
            (
                SELECT
                    LTRIM(RTRIM(c.CustNum)) AS CustomerNumber,
                    LTRIM(RTRIM(c.Name)) AS CustomerName,
                    ROW_NUMBER() OVER
                    (
                        PARTITION BY LTRIM(RTRIM(c.CustNum))
                        ORDER BY
                            CASE WHEN c.CustSeq = 0 THEN 0 ELSE 1 END,
                            c.CustSeq
                    ) AS RowNum
                FROM dbo.ESBCustomerView c
                WHERE
                    c.Name IS NOT NULL
                    AND LTRIM(RTRIM(c.Name)) <> ''
                    AND
                    (
                        c.Name LIKE %(search)s
                        OR LTRIM(RTRIM(c.CustNum)) LIKE %(search)s
                    )
            ),
            SelectedCustomers AS
            (
                SELECT CustomerNumber, CustomerName
                FROM MatchingCustomers
                WHERE RowNum = 1
            )
            SELECT TOP (25)
                a.site_ref,
                a.customer_number,
                c.CustomerName,
                a.transaction_rows,
                a.current_balance,
                a.balance_1_to_30,
                a.balance_31_to_60,
                a.balance_61_to_90,
                a.balance_over_90,
                a.total_ar_balance
            FROM dbo.AI_HistoricalARCustomerSummary a
            INNER JOIN SelectedCustomers c
                ON a.customer_number = c.CustomerNumber
            ORDER BY a.total_ar_balance DESC, a.customer_number
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        customers = [
            {
                "site": row[0],
                "customer_number": str(row[1]).strip() if row[1] else None,
                "customer_name": row[2],
                "transaction_rows": row[3],
                "aging_buckets": {
                    "current": row[4],
                    "1_to_30_days": row[5],
                    "31_to_60_days": row[6],
                    "61_to_90_days": row[7],
                    "over_90_days": row[8]
                },
                "total_ar_balance": row[9]
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "report": "Historical Customer Accounts Receivable Aging",
            "as_of_date": "2025-12-31",
            "data_status": "Historical static snapshot",
            "summary_table": "dbo.AI_HistoricalARCustomerSummary",
            "search_term": search,
            "returned_rows": len(customers),
            "maximum_rows": 25,
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
                "report": "Historical Customer Accounts Receivable Aging",
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


# =========================================================
# 9. HISTORICAL AR AGING SUMMARY
# =========================================================

@app.route(
    route="erp-ar-aging-summary",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_ar_aging_summary(req: func.HttpRequest) -> func.HttpResponse:
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
            SELECT
                COUNT(*) AS CustomerCount,
                COALESCE(SUM(transaction_rows), 0) AS TransactionRows,
                COALESCE(SUM(current_balance), 0) AS AgeBal1,
                COALESCE(SUM(balance_1_to_30), 0) AS AgeBal2,
                COALESCE(SUM(balance_31_to_60), 0) AS AgeBal3,
                COALESCE(SUM(balance_61_to_90), 0) AS AgeBal4,
                COALESCE(SUM(balance_over_90), 0) AS AgeBal5,
                COALESCE(SUM(total_ar_balance), 0) AS TotalARBalance
            FROM dbo.AI_HistoricalARCustomerSummary
        """)

        row = cursor.fetchone()
        if not row:
            raise Exception("The AR summary query returned no results.")

        result = {
            "connection": "Success",
            "report": "Historical Accounts Receivable Aging",
            "as_of_date": "2025-12-31",
            "data_status": "Historical static snapshot",
            "summary_table": "dbo.AI_HistoricalARCustomerSummary",
            "customer_count": row[0],
            "transaction_rows": row[1],
            "aging_buckets": {
                "current": row[2],
                "1_to_30_days": row[3],
                "31_to_60_days": row[4],
                "61_to_90_days": row[5],
                "over_90_days": row[6]
            },
            "total_ar_balance": row[7],
            "unbucketed_balance": 0,
            "rows_with_no_age_date": 0
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
                "report": "Historical Accounts Receivable Aging",
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


# =========================================================
# 10. PURCHASE ORDER SEARCH
# =========================================================

@app.route(
    route="erp-purchase-order-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_purchase_order_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for purchase order search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            SELECT TOP (50)
                PurchaseOrderType,
                PoNum,
                PoLine,
                DerStat,
                DerItem,
                DerItemDescription,
                DerQuantity,
                QtyReceivedConv,
                DerOpenQuantity,
                CASE
                    WHEN PurchaseOrderType = 'R'
                     AND QtyReceivedConv IS NOT NULL
                    THEN DerQuantity - QtyReceivedConv
                    ELSE NULL
                END AS CalculatedRemainingQuantity,
                DerQuantityUnitCode,
                DerUnitCostConv,
                DerExtendedAmountConv,
                DerTotalAmountConv,
                CurrISOCurrCode,
                ItemRequiredDeliveryDateTime,
                ReqNum,
                ReqLine,
                DerShipToLocation,
                DerShipToName,
                DerShipToAddr1,
                DerShipToAddr2,
                DerShipToAddr3,
                DerShipToAddr4,
                DerShipToCity,
                DerShipToState,
                DerShipToISOCountryCode,
                DerShipToZip,
                DerShipToContactName,
                DerShipToPhone,
                Incoterm,
                ProductionOrderRefID,
                ProductionOrderRevID,
                ProductionOrderDesc,
                ProductionOrderStat
            FROM dbo.AI_PurchaseOrderLineSearchView
            WHERE
                LTRIM(RTRIM(PoNum)) LIKE %(search)s
                OR LTRIM(RTRIM(DerItem)) LIKE %(search)s
                OR DerItemDescription LIKE %(search)s
            ORDER BY
                CASE WHEN ItemRequiredDeliveryDateTime IS NULL THEN 1 ELSE 0 END,
                ItemRequiredDeliveryDateTime,
                PoNum,
                PoLine
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        purchase_orders = [
            {
                "purchase_order_type": row[0],
                "purchase_order_number": str(row[1]).strip() if row[1] else None,
                "po_line": row[2],
                "status": row[3],
                "item_number": str(row[4]).strip() if row[4] else None,
                "item_description": row[5],
                "quantity_ordered": row[6],
                "quantity_received": row[7],
                "syteLine_open_quantity": row[8],
                "calculated_remaining_quantity": row[9],
                "unit_of_measure": row[10],
                "unit_cost": row[11],
                "extended_amount": row[12],
                "total_amount": row[13],
                "currency": row[14],
                "required_delivery_date": row[15],
                "requisition_number": row[16],
                "requisition_line": row[17],
                "ship_to": {
                    "location_type": row[18],
                    "name": row[19],
                    "address_1": row[20],
                    "address_2": row[21],
                    "address_3": row[22],
                    "address_4": row[23],
                    "city": row[24],
                    "state": row[25],
                    "country": row[26],
                    "postal_code": row[27],
                    "contact": row[28],
                    "phone": row[29]
                },
                "incoterm": row[30],
                "production_order": {
                    "reference": row[31],
                    "revision": row[32],
                    "description": row[33],
                    "status": row[34]
                }
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "report": "Historical Purchase Order Line Search",
            "data_status": "Historical static snapshot",
            "source_view": "dbo.AI_PurchaseOrderLineSearchView",
            "search_term": search,
            "returned_rows": len(purchase_orders),
            "maximum_rows": 50,
            "purchase_orders": purchase_orders
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
                "report": "Historical Purchase Order Line Search",
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


# =========================================================
# 11. SHIPPING AND TRACKING SEARCH
# =========================================================

@app.route(
    route="erp-shipping-search",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
@require_erp_access
def erp_shipping_search(req: func.HttpRequest) -> func.HttpResponse:
    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({"error": "Please provide at least two characters for shipping search."}),
            mimetype="application/json",
            status_code=400
        )
    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({"error": "Search term cannot exceed 100 characters."}),
            mimetype="application/json",
            status_code=400
        )

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
            SELECT TOP (50)
                CoNum_and_CoLine,
                co_Num,
                Co_Line,
                cust_po,
                UfcoOrderTrack,
                name,
                add1,
                add2,
                add3,
                add4,
                city,
                state,
                zip,
                county,
                country,
                phone2,
                ship_to_email,
                Uf_coDeliveryService,
                Uf_coDeliveryTerm
            FROM dbo.AA_ShippingView
            WHERE
                LTRIM(RTRIM(co_Num)) LIKE %(search)s
                OR LTRIM(RTRIM(CoNum_and_CoLine)) LIKE %(search)s
                OR LTRIM(RTRIM(cust_po)) LIKE %(search)s
                OR UfcoOrderTrack LIKE %(search)s
            ORDER BY co_Num DESC, Co_Line
        """, {"search": f"%{search}%"})

        rows = cursor.fetchall()
        shipments = [
            {
                "sales_order_line_key": row[0],
                "sales_order": str(row[1]).strip() if row[1] else None,
                "sales_order_line": str(row[2]).strip() if row[2] else None,
                "customer_po": str(row[3]).strip() if row[3] else None,
                "tracking_information": row[4],
                "ship_to": {
                    "name": row[5],
                    "address_1": row[6],
                    "address_2": row[7],
                    "address_3": row[8],
                    "address_4": row[9],
                    "city": row[10],
                    "state": row[11],
                    "postal_code": row[12],
                    "county": row[13],
                    "country": row[14],
                    "phone": row[15],
                    "email": row[16]
                },
                "delivery_service": row[17],
                "delivery_terms": row[18]
            }
            for row in rows
        ]

        result = {
            "connection": "Success",
            "report": "Historical Shipping and Tracking Search",
            "data_status": "Historical static snapshot",
            "as_of_date": "2025-12-31",
            "source_view": "dbo.AA_ShippingView",
            "search_term": search,
            "returned_rows": len(shipments),
            "maximum_rows": 50,
            "records_are_sales_order_lines": True,
            "shipments": shipments
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
                "report": "Historical Shipping and Tracking Search",
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
