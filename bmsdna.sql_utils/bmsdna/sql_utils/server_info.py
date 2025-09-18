from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from .query import sql_quote_name

if TYPE_CHECKING:
    from bmsdna.sql_utils.dbapi import Connection


SQL_Server_Editions = Literal[
    "Enterprise Edition",
    "Enterprise Edition: Core-based Licensing",
    "Enterprise Evaluation Edition",
    "Business Intelligence Edition",
    "Developer Edition",
    "Express Edition",
    "Express Edition with Advanced Services",
    "Standard Edition",
    "Web Edition",
    "SQL Azure",
]

Azure_SKUs = Literal[
    "Basic", "S0", "S1", "S2", "S3", "S4", "S6", "S7", "S9", "S12", "P1", "P2", "P4", "P6", "P11", "P15"
]
Azure_Edition = Literal["Basic", "Standard", "Premium", "GeneralPurpose", "BusinessCritical", "Hyperscale"]
# select cast(SERVERPROPERTY('Edition') as nvarchar(100))


def get_azure_edition(target: Azure_SKUs) -> Azure_Edition:
    #
    if target.startswith("BC_"):
        return "BusinessCritical"
    elif target.startswith("GP_"):
        return "GeneralPurpose"
    elif target.startswith("HS_"):
        return "Hyperscale"
    if target[0] == "B":
        return "Basic"
    elif target[0] == "S":
        return "Standard"
    elif target[0] == "P":
        return "Premium"
    raise ValueError(f"Invalid target: {target}")


def _wait_for_sku_sql(azure_sku: str):
    return f"""
    declare @count int = 0
    while @count < 1000
    begin
    if(select service_objective from sys.database_service_objectives)='{azure_sku}'
    begin
        print 'scale finished'
        break
    end
    else
    begin
        waitfor delay '00:00:03'
        print 'wait'
    end
        set @count+=1
    end"""


@dataclass
class DBInfo:
    edition_id: int
    edition: SQL_Server_Editions
    db_name: str
    azure_edition: Azure_Edition | None
    azure_sku: Azure_SKUs | None

    def supports_column_store_index(self) -> bool:
        if self.edition == "SQL Azure":
            if self.azure_edition == "Basic":
                return False
            if self.azure_edition == "Standard":
                return self.azure_sku not in ["S0", "S1", "S2"]
        return True

    def azure_scale_to(self, conn: "Connection", azure_sku: Azure_SKUs) -> bool:
        with conn.cursor() as cur:
            if azure_sku == self.azure_sku:
                return False
        with conn.cursor() as cur:
            db_quoted = sql_quote_name(self.db_name)
            cur.execute(
                f"ALTER DATABASE {db_quoted} MODIFY (EDITION = '{get_azure_edition(azure_sku)}, SERVICE_OBJECTIVE='{azure_sku}' )"
            )
        try:
            with conn.cursor() as cur:
                cur.execute(_wait_for_sku_sql(azure_sku))
                cur.fetchall()
        except Exception as e:
            import time

            time.sleep(3)
            with conn.cursor() as cur:  # we just retry since it's quite likely that the scaling itself caused failure
                cur.execute(_wait_for_sku_sql(azure_sku))
                cur.fetchall()
        return True


def get_db_info(conn: "Connection") -> DBInfo:
    with conn.cursor() as cursor:
        cursor.execute(
            "select cast(SERVERPROPERTY('EditionID') as nvarchar(100)), cast(SERVERPROPERTY('Edition') as nvarchar(100)), dB_NAME(), DB_ID()"
        )
        res = cursor.fetchone()
        assert res is not None
        edition_id, edition, db_name, db_id = res
    if edition == "SQL Azure":
        with conn.cursor() as cursor:
            cursor.execute(
                "select edition, service_objective from sys.database_service_objectives where database_id=DB_ID()"
            )
            res = cursor.fetchone()
            assert res is not None
            azure_edition, azure_sku = res
    else:
        azure_edition = None
        azure_sku = None
    return DBInfo(edition_id, edition, db_name, azure_edition, azure_sku)
