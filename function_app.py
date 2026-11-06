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
    route="erp-ar-top-customers",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
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

                WHERE LTRIM(RTRIM(c.CustNum)) =
                      a.customer_number

                  AND c.Name IS NOT NULL
                  AND LTRIM(RTRIM(c.Name)) <> ''

                ORDER BY
                    CASE
                        WHEN c.CustSeq = 0 THEN 0
                        ELSE 1
                    END,
                    c.CustSeq

            ) n

            WHERE a.total_ar_balance > 0

            ORDER BY
                a.total_ar_balance DESC,
                a.customer_number
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

@app.route(
    route="erp-ar-customer-aging",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_ar_customer_aging(req: func.HttpRequest) -> func.HttpResponse:

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
                SELECT
                    CustomerNumber,
                    CustomerName
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

            ORDER BY
                a.total_ar_balance DESC,
                a.customer_number

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
                COUNT(*) AS CustomerCount,

                COALESCE(SUM(transaction_rows), 0)
                    AS TransactionRows,

                COALESCE(SUM(current_balance), 0)
                    AS AgeBal1,

                COALESCE(SUM(balance_1_to_30), 0)
                    AS AgeBal2,

                COALESCE(SUM(balance_31_to_60), 0)
                    AS AgeBal3,

                COALESCE(SUM(balance_61_to_90), 0)
                    AS AgeBal4,

                COALESCE(SUM(balance_over_90), 0)
                    AS AgeBal5,

                COALESCE(SUM(total_ar_balance), 0)
                    AS TotalARBalance

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

            # These were validated as zero when the summary
            # table was created from the historical aging view.
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


@app.route(
    route="erp-purchase-order-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_purchase_order_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters for purchase order search."
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
                CASE
                    WHEN ItemRequiredDeliveryDateTime IS NULL
                    THEN 1 ELSE 0
                END,
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


@app.route(
    route="erp-shipping-search",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def erp_shipping_search(req: func.HttpRequest) -> func.HttpResponse:

    search = (req.params.get("search") or "").strip()

    if len(search) < 2:
        return func.HttpResponse(
            json.dumps({
                "error": "Please provide at least two characters for shipping search."
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

                OR LTRIM(RTRIM(CoNum_and_CoLine))
                    LIKE %(search)s

                OR LTRIM(RTRIM(cust_po)) LIKE %(search)s

                OR UfcoOrderTrack LIKE %(search)s

            ORDER BY
                co_Num DESC,
                Co_Line

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
