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
    route="erp-customer-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_customer_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters for customer search."
            }),
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

@app.route(
    route="erp-sales-order-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_sales_order_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters."
            }),
            mimetype="application/json",
            status_code=400
        )

    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({
                "error": "Search term cannot exceed 100 characters."
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

        cursor.execute("""
            SELECT TOP (25)
                CoNum,
                OrderDate,
                DerStat,
                DerStatDescription,
                CustomerID,
                CustomerName,
                CustPo,
                DerExtAmt,
                Whse
            FROM dbo.ESBSalesOrderView
            WHERE
                LTRIM(RTRIM(CoNum)) LIKE %(search)s
                OR LTRIM(RTRIM(CustomerID)) LIKE %(search)s
                OR CustomerName LIKE %(search)s
                OR CustPo LIKE %(search)s
            ORDER BY OrderDate DESC
        """, {"search": f"%{search}%"})

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

        result = {
            "connection": "Success",
            "view": "dbo.ESBSalesOrderView",
            "search_term": search,
            "returned_rows": len(orders),
            "sales_orders": orders
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

@app.route(
    route="erp-inventory-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_inventory_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters for inventory search."
            }),
            mimetype="application/json",
            status_code=400
        )

    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({
                "error": "Search term cannot exceed 100 characters."
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

        cursor.execute("""
            SELECT TOP (25)
                item,
                description,
                u_m,
                lead_time,
                qty_on_hand,
                Dealer,
                Distributor,
                Competitive,
                CLK_List,
                CLK_Net,
                OEM
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

@app.route(
    route="erp-production-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_production_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters for production search."
            }),
            mimetype="application/json",
            status_code=400
        )

    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({
                "error": "Search term cannot exceed 100 characters."
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

        cursor.execute("""
            SELECT TOP (25)
                Job,
                Suffix,
                Item,
                ItemDescription,
                Description,
                Status,
                StatusDesc,
                OrderQty,
                DueQty,
                ProducedQty,
                ItemUM,
                StartDate,
                EndDate,
                DueDate,
                EstMatlCost,
                EstLaborCost,
                EstFixOvhdCost,
                EstVarOvhdCost,
                EstOutsideCost,
                EstBurdenCost,
                EstTotalCost,
                ActMatlCost,
                ActLaborCost,
                ActFixOvhdCost,
                ActVarOvhdCost,
                ActOutsideCost,
                ActBurdenCost,
                ActTotalCost,
                WhseID
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
                DueDate,
                Job,
                Suffix
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

@app.route(
    route="erp-invoice-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_invoice_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters for invoice search."
            }),
            mimetype="application/json",
            status_code=400
        )

    if len(search) > 100:
        return func.HttpResponse(
            json.dumps({
                "error": "Search term cannot exceed 100 characters."
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

        cursor.execute("""
            SELECT TOP (25)
                InvNum,
                InvDate,
                ArtDescription,
                CustNum,
                Name,
                CoNum,
                CustPo,
                ArtDueDate,
                TotalAmount,
                ExtendedAmount,
                TaxAmount,
                DerStatus,
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

@app.route(
    route="erp-ar-aging-summary",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
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
                COUNT(DISTINCT cust_num) AS CustomerCount,
                COUNT(*) AS TransactionRows,

                COALESCE(SUM(AgeBal1), 0) AS AgeBal1,
                COALESCE(SUM(AgeBal2), 0) AS AgeBal2,
                COALESCE(SUM(AgeBal3), 0) AS AgeBal3,
                COALESCE(SUM(AgeBal4), 0) AS AgeBal4,
                COALESCE(SUM(AgeBal5), 0) AS AgeBal5,

                COALESCE(SUM(AgeBal6), 0) AS TotalARBalance,

                COALESCE(
                    SUM(
                        CASE
                            WHEN AgingDays IS NULL
                                THEN AgeBal6
                            ELSE 0
                        END
                    ), 0
                ) AS UnbucketedBalance,

                COALESCE(
                    SUM(
                        CASE
                            WHEN AgingDays IS NULL
                                THEN 1
                            ELSE 0
                        END
                    ), 0
                ) AS RowsWithNoAgeDate

            FROM dbo.AI_HistoricalARAgingView
        """)

        row = cursor.fetchone()

        if not row:
            raise Exception("The AR aging summary query returned no results.")

        result = {
            "connection": "Success",
            "report": "Historical Accounts Receivable Aging",
            "as_of_date": "2025-12-31",
            "data_status": "Historical static snapshot",
            "view": "dbo.AI_HistoricalARAgingView",

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
            "unbucketed_balance": row[8],
            "rows_with_no_age_date": row[9]
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
