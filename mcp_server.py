#!/usr/bin/env python3
"""Salesforce Implementation Tracker — MCP Server.

Exposes scoped Salesforce operations as MCP tools for Claude Desktop.
Runs over stdio transport. No delete operations exposed.
"""

import os
import logging
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sfdc-mcp")

# ---------------------------------------------------------------------------
# Picklist valid values
# ---------------------------------------------------------------------------

VALID_IMPLEMENTATION_STAGES = [
    "00 - Kick Off Call",
    "01 - Explore",
    "02 - Planning",
    "03 - In Progress",
    "04 - Final Review",
    "05 - Complete",
    "06 - Passive",
    "07 - Paused",
    "08 - Unsuccessful",
]

VALID_PROGRAM_HEALTH = [
    "Healthy", "Passive", "Paused", "Unresponsive", "Risk", "Churn", "High Risk",
]

VALID_CONTRACT_TYPES = ["Annual", "Free Trial", "Pay as you go"]

VALID_TYPES = ["Join", "Pure Migration", "Join - Lite", "Join - Quickstart", "Other"]

VALID_MIGRATION_TYPES = [
    "Customer Tooling", "Dual-write and backfill", "Parallel Copy",
    "pg_dump and pg_restore", "NA", "TS Tooling", "Live Migration",
]

VALID_FEATURES = [
    "Read Replicas", "HA Replicas", "Data Tiering", "Caggs",
    "Compression", "Migration", "Vector", "Hypertables",
]

VALID_PROJECT_TASKS = [
    "CAGG", "Case work", "Compression", "Connection Pooling", "HA Replica",
    "Hypershift", "Ingest", "Internal Meetings - Non Customer", "Internal Testing",
    "Migration", "POC", "Project Plan", "Query Optimization", "Read Replica",
    "Replica", "Retention", "CNS", "Sales", "Sales Call", "Schema Design",
    "Security", "Sizing", "Troubleshooting", "VPC",
]

VALID_PROJECT_TYPES = [
    "Churn", "Implementation", "Internal Meetings", "Join", "Join - Lite",
    "Join - QS", "Pre-Sales", "Pre-Sales (Discover Call)", "Projects",
    "Support", "Training",
]

VALID_RECORD_STAGES = ["Trial", "Pre-Production", "Production"]

# Fields that can be updated on Implementation__c via the update tool
UPDATABLE_FIELDS = {
    "Implementation_Stage__c", "Program_Health__c", "Type__c", "Contract_Type__c",
    "Migration_Type__c", "Features__c", "Contracted_Hours__c", "Percent_Complete__c",
    "In_Production__c", "Risks__c", "Comments__c", "Post_Mortem__c",
    "Technical_Win__c", "Migration_Source__c", "Support_Tier__c",
    "Grafana__c", "Project_Doc__c", "CDE__c", "CSM__c",
    "Customer_Start_Date__c", "Kick_Off_Call__c", "Estimated_Graduation_Date__c",
    "Production_Date__c", "Final_Review_Call__c", "Next_Step_Date__c",
    "X3_Month_Check_In__c", "Adjustment_Days__c",
    "ARR_Start_of_Program__c", "ARR_End_of_Program__c",
    "Hypertables_Start_of_Program__c", "Hypertables_End_of_Program__c",
    "Caggs_Start_of_Program__c", "Caggs_End_of_Program__c",
    "Compression_Ratio_Start_of_Program__c", "Compression_Ratio_End_of_Program__c",
    "DUM_Start_of_Program__c", "DUM_End_of_Program__c",
    "Number_of_Services_Start_of_Program__c", "Number_of_Services_End_of_Program__c",
    "Tiered_Data_Start_of_Program__c", "Tiered_Data_End_of_Program__c",
    "Contract__c", "Billing_Category__c",
}

# Picklist validation map: field name -> valid values list
PICKLIST_VALIDATORS = {
    "Implementation_Stage__c": VALID_IMPLEMENTATION_STAGES,
    "Program_Health__c": VALID_PROGRAM_HEALTH,
    "Contract_Type__c": VALID_CONTRACT_TYPES,
    "Type__c": VALID_TYPES,
    "Migration_Type__c": VALID_MIGRATION_TYPES,
}

# Multipicklist validation map
MULTIPICKLIST_VALIDATORS = {
    "Features__c": VALID_FEATURES,
}

API_VERSION = "v62.0"
MANAGER_EMAIL = os.environ.get("SF_MANAGER_EMAIL", "")  # optional: email of user who can update any record
MAX_CREATES_PER_WINDOW = 5
CREATE_WINDOW_SECONDS = 60  # rolling 1-minute window


# ---------------------------------------------------------------------------
# Salesforce REST Client
# ---------------------------------------------------------------------------

class SalesforceClient:
    def __init__(self, client_id: str, client_secret: str, instance_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.instance_url = instance_url.rstrip("/")
        self.token: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=30.0)

    @property
    def base_url(self) -> str:
        return f"{self.instance_url}/services/data/{API_VERSION}"

    async def authenticate(self) -> None:
        resp = await self._http.post(
            f"{self.instance_url}/services/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        resp.raise_for_status()
        self.token = resp.json()["access_token"]
        logger.info("Authenticated with Salesforce")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make an authenticated request, retrying once on 401."""
        # Merge auth headers with any extra headers provided
        extra_headers = kwargs.pop("headers", {})
        merged = {**self._headers(), **extra_headers}
        resp = await self._http.request(method, url, headers=merged, **kwargs)
        if resp.status_code == 401:
            await self.authenticate()
            merged = {**self._headers(), **extra_headers}
            resp = await self._http.request(method, url, headers=merged, **kwargs)
        return resp

    async def query(self, soql: str) -> dict:
        resp = await self._request("GET", f"{self.base_url}/query/", params={"q": soql})
        resp.raise_for_status()
        return resp.json()

    async def get_record(self, sobject: str, record_id: str, fields: Optional[list[str]] = None) -> dict:
        url = f"{self.base_url}/sobjects/{sobject}/{record_id}"
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        resp = await self._request("GET", url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def create_record(self, sobject: str, data: dict) -> dict:
        resp = await self._request(
            "POST",
            f"{self.base_url}/sobjects/{sobject}/",
            json=data,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()

    async def update_record(self, sobject: str, record_id: str, data: dict) -> bool:
        resp = await self._request(
            "PATCH",
            f"{self.base_url}/sobjects/{sobject}/{record_id}",
            json=data,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.status_code == 204


# ---------------------------------------------------------------------------
# Access Control
# ---------------------------------------------------------------------------

class AccessControl:
    def __init__(self, sf: SalesforceClient, user_email: str):
        self.sf = sf
        self.user_email = user_email.lower().strip()
        self.user_id: Optional[str] = None
        self.profile_name: Optional[str] = None
        self.is_admin = False
        self.is_manager = self.user_email == MANAGER_EMAIL

    async def resolve_user(self) -> None:
        result = await self.sf.query(
            f"SELECT Id, Profile.Name FROM User WHERE Email = '{self.user_email}' AND IsActive = true LIMIT 1"
        )
        if not result.get("records"):
            raise RuntimeError(f"No active Salesforce user found for email: {self.user_email}")
        user = result["records"][0]
        self.user_id = user["Id"]
        self.profile_name = user.get("Profile", {}).get("Name", "")
        self.is_admin = self.profile_name == "System Administrator"
        logger.info(
            "Resolved user %s → %s (profile=%s, admin=%s, manager=%s)",
            self.user_email, self.user_id, self.profile_name, self.is_admin, self.is_manager,
        )

    async def can_update(self, implementation_id: str) -> tuple[bool, str]:
        if self.is_admin or self.is_manager:
            return True, ""
        record = await self.sf.get_record("Implementation__c", implementation_id, ["CDE__c"])
        cde_id = record.get("CDE__c")
        if cde_id == self.user_id:
            return True, ""
        return False, "Access denied: you are not the assigned CDE on this record. Only the CDE, admins, or the manager can update it."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def resolve_implementation_id(sf: SalesforceClient, name_or_id: str) -> str:
    """Resolve an implementation Name (e.g. IMPL-0042) or ID to a record ID."""
    name_or_id = name_or_id.strip()
    # Salesforce IDs are 15 or 18 alphanumeric chars starting with 'a0'
    if len(name_or_id) in (15, 18) and name_or_id[:2].lower() == "a0":
        return name_or_id
    # Otherwise treat as a Name lookup
    result = await sf.query(
        f"SELECT Id FROM Implementation__c WHERE Name = '{name_or_id}' LIMIT 1"
    )
    if not result.get("records"):
        raise ValueError(f"No Implementation record found with Name: {name_or_id}")
    return result["records"][0]["Id"]


def validate_picklist(field: str, value: str) -> Optional[str]:
    """Return an error message if the value is invalid for a picklist field, else None."""
    if field in PICKLIST_VALIDATORS:
        valid = PICKLIST_VALIDATORS[field]
        if value not in valid:
            return f"Invalid value '{value}' for {field}. Valid values: {', '.join(valid)}"
    if field in MULTIPICKLIST_VALIDATORS:
        valid = MULTIPICKLIST_VALIDATORS[field]
        parts = [v.strip() for v in value.split(";")]
        invalid = [p for p in parts if p not in valid]
        if invalid:
            return f"Invalid value(s) {invalid} for {field}. Valid values: {', '.join(valid)}"
    return None


def format_implementation(record: dict) -> str:
    """Format an Implementation__c record into a readable summary."""
    lines = []
    name = record.get("Name", "Unknown")
    lines.append(f"**{name}** (ID: {record.get('Id', 'N/A')})")

    field_labels = [
        ("Implementation_Stage__c", "Stage"),
        ("Program_Health__c", "Health"),
        ("Type__c", "Type"),
        ("Contract_Type__c", "Contract"),
        ("Percent_Complete__c", "% Complete"),
        ("In_Production__c", "In Production"),
        ("Contracted_Hours__c", "Contracted Hours"),
        ("Actual_Hours_Spent__c", "Hours Spent"),
        ("Contracted_Hours_Remaining__c", "Hours Remaining"),
        ("Days_In_Program__c", "Days In Program"),
        ("Stale_Days__c", "Stale Days"),
        ("Features__c", "Features"),
        ("Migration_Type__c", "Migration Type"),
        ("Risks__c", "Risks"),
        ("Comments__c", "Comments"),
        ("Next_Step_Date__c", "Next Step Date"),
        ("Estimated_Graduation_Date__c", "Graduation Date"),
        ("Production_Date__c", "Production Date"),
        ("Potential_ARR__c", "Potential ARR"),
        ("Projected_Amount__c", "Projected Amount"),
        ("Grafana__c", "Grafana"),
        ("Project_Doc__c", "Exec Summary"),
    ]
    for api_name, label in field_labels:
        val = record.get(api_name)
        if val is not None and val != "":
            lines.append(f"  {label}: {val}")

    # Account and Opportunity names via relationship fields
    account = record.get("Account__r")
    if account and isinstance(account, dict):
        lines.append(f"  Account: {account.get('Name', 'N/A')}")
    opp = record.get("Opportunity__r")
    if opp and isinstance(opp, dict):
        lines.append(f"  Opportunity: {opp.get('Name', 'N/A')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

# These will be initialized on startup via lifespan
sf_client: Optional[SalesforceClient] = None
access_ctl: Optional[AccessControl] = None
create_timestamps: list[float] = []


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize Salesforce client and access control on startup."""
    global sf_client, access_ctl

    client_id = os.environ.get("SF_CLIENT_ID")
    client_secret = os.environ.get("SF_CLIENT_SECRET")
    instance_url = os.environ.get("SF_INSTANCE_URL")
    user_email = os.environ.get("SF_USER_EMAIL")

    if not all([client_id, client_secret, instance_url, user_email]):
        raise RuntimeError(
            "Missing required environment variables. "
            "Set SF_CLIENT_ID, SF_CLIENT_SECRET, SF_INSTANCE_URL, and SF_USER_EMAIL."
        )

    sf_client = SalesforceClient(client_id, client_secret, instance_url)
    await sf_client.authenticate()

    access_ctl = AccessControl(sf_client, user_email)
    await access_ctl.resolve_user()
    logger.info("MCP server initialized — user: %s", user_email)

    yield {}

    # Cleanup: close the HTTP client
    await sf_client._http.aclose()


mcp = FastMCP("salesforce-impl", lifespan=lifespan)


@mcp.tool()
async def create_implementation(
    opportunity_id: str,
    type: str,
    contract_type: str,
    contracted_hours: Optional[float] = None,
    features: Optional[str] = None,
    migration_type: Optional[str] = None,
) -> str:
    """Create a new Implementation__c record from an Opportunity ID.

    Args:
        opportunity_id: The 15 or 18-char Salesforce Opportunity ID (starts with 006).
        type: Implementation type. Must be one of: Join, Pure Migration, Join - Lite, Join - Quickstart, Other.
        contract_type: Contract type. Must be one of: Annual, Free Trial, Pay as you go.
        contracted_hours: Optional number of contracted hours.
        features: Optional semicolon-separated features (e.g. "Compression;Hypertables"). Valid values: Read Replicas, HA Replicas, Data Tiering, Caggs, Compression, Migration, Vector, Hypertables.
        migration_type: Optional migration type. Valid values: Customer Tooling, Dual-write and backfill, Parallel Copy, pg_dump and pg_restore, NA, TS Tooling, Live Migration.
    """
    now = time.time()
    recent = [t for t in create_timestamps if now - t < CREATE_WINDOW_SECONDS]
    if len(recent) >= MAX_CREATES_PER_WINDOW:
        return f"Rate limit reached: {MAX_CREATES_PER_WINDOW} records created in the last {CREATE_WINDOW_SECONDS} seconds. Wait a moment before creating more."

    # Validate picklists
    err = validate_picklist("Type__c", type)
    if err:
        return err
    err = validate_picklist("Contract_Type__c", contract_type)
    if err:
        return err
    if migration_type:
        err = validate_picklist("Migration_Type__c", migration_type)
        if err:
            return err
    if features:
        err = validate_picklist("Features__c", features)
        if err:
            return err

    # Query the Opportunity
    result = await sf_client.query(
        f"SELECT Id, Name, AccountId, Account.Name, Amount, OwnerId "
        f"FROM Opportunity WHERE Id = '{opportunity_id}'"
    )
    if not result.get("records"):
        return f"No Opportunity found with ID: {opportunity_id}"

    opp = result["records"][0]
    account_id = opp["AccountId"]
    account_name = opp.get("Account", {}).get("Name", "Unknown")

    # Build the name: {Account Name} - {Type} - {YYYY-MM-DD}
    today = date.today().isoformat()
    impl_name = f"{account_name} - {type} - {today}"

    data = {
        "Name": impl_name,
        "Opportunity__c": opportunity_id,
        "Account__c": account_id,
        "Type__c": type,
        "Contract_Type__c": contract_type,
        "Implementation_Stage__c": "00 - Kick Off Call",
        "Program_Health__c": "Healthy",
        "In_Production__c": False,
    }
    if contracted_hours is not None:
        data["Contracted_Hours__c"] = contracted_hours
    if features:
        data["Features__c"] = features
    if migration_type:
        data["Migration_Type__c"] = migration_type

    resp = await sf_client.create_record("Implementation__c", data)
    record_id = resp.get("id", "unknown")
    create_timestamps.append(time.time())

    return (
        f"Implementation created successfully.\n"
        f"  Record ID: {record_id}\n"
        f"  Name: {impl_name}\n"
        f"  Account: {account_name}\n"
        f"  Type: {type}\n"
        f"  Contract: {contract_type}\n"
        f"  Stage: 00 - Kick Off Call\n"
        f"  Health: Healthy"
    )


@mcp.tool()
async def update_implementation(
    record_name_or_id: str,
    updates: dict,
) -> str:
    """Update fields on an existing Implementation__c record.

    Access control: only the assigned CDE, admins, or the manager can update a record.

    Args:
        record_name_or_id: Implementation record Name (e.g. "IMPL-0042") or Salesforce ID.
        updates: Dictionary of field API names to new values. Updatable fields include:
            Implementation_Stage__c, Program_Health__c, Type__c, Contract_Type__c,
            Migration_Type__c, Features__c, Contracted_Hours__c, Percent_Complete__c,
            In_Production__c, Risks__c, Comments__c, Post_Mortem__c, Technical_Win__c,
            CDE__c, CSM__c, Next_Step_Date__c, Estimated_Graduation_Date__c,
            Production_Date__c, and more. Dates must be YYYY-MM-DD format.
    """
    try:
        record_id = await resolve_implementation_id(sf_client, record_name_or_id)
    except ValueError as e:
        return str(e)

    # Access check
    allowed, reason = await access_ctl.can_update(record_id)
    if not allowed:
        return reason

    # Validate field names
    invalid_fields = [f for f in updates if f not in UPDATABLE_FIELDS]
    if invalid_fields:
        return f"Cannot update field(s): {', '.join(invalid_fields)}. Not in the allowed update list."

    # Validate picklist/multipicklist values
    for field, value in updates.items():
        if isinstance(value, str):
            err = validate_picklist(field, value)
            if err:
                return err

    await sf_client.update_record("Implementation__c", record_id, updates)
    field_summary = ", ".join(f"{k} = {v}" for k, v in updates.items())
    return f"Updated {record_name_or_id} (ID: {record_id}): {field_summary}"


@mcp.tool()
async def log_hours(
    record_name_or_id: str,
    hours: float,
    project_task: Optional[str] = None,
    notes: Optional[str] = None,
    task_date: Optional[str] = None,
    project_type: Optional[str] = None,
    record_stage: Optional[str] = None,
) -> str:
    """Log hours on an Implementation by creating an Implementation_Hours__c record.

    IMPORTANT: Do NOT call this tool until you have asked the user to select a project_task
    from the valid values below. Always present the list and let the user choose, even if
    they mentioned a task in their request.

    Args:
        record_name_or_id: Implementation record Name (e.g. "IMPL-0042") or Salesforce ID.
        hours: Number of hours worked.
        project_task: The task category — MUST be confirmed by the user before calling. Valid values: CAGG, Case work, Compression, Connection Pooling, HA Replica, Hypershift, Ingest, Internal Meetings - Non Customer, Internal Testing, Migration, POC, Project Plan, Query Optimization, Read Replica, Replica, Retention, CNS, Sales, Sales Call, Schema Design, Security, Sizing, Troubleshooting, VPC. Multiple values can be semicolon-separated.
        notes: Optional description of work done.
        task_date: Optional date in YYYY-MM-DD format. Defaults to today.
        project_type: Optional project type. Valid values: Churn, Implementation, Internal Meetings, Join, Join - Lite, Join - QS, Pre-Sales, Pre-Sales (Discover Call), Projects, Support, Training.
        record_stage: Optional record stage. Valid values: Trial, Pre-Production, Production.
    """
    now = time.time()
    recent = [t for t in create_timestamps if now - t < CREATE_WINDOW_SECONDS]
    if len(recent) >= MAX_CREATES_PER_WINDOW:
        return f"Rate limit reached: {MAX_CREATES_PER_WINDOW} records created in the last {CREATE_WINDOW_SECONDS} seconds. Wait a moment before creating more."

    if not project_task:
        return (
            "A project task is required. Please ask the user to select from:\n"
            + "\n".join(f"  - {t}" for t in VALID_PROJECT_TASKS)
        )

    try:
        record_id = await resolve_implementation_id(sf_client, record_name_or_id)
    except ValueError as e:
        return str(e)

    # Validate project_task
    parts = [v.strip() for v in project_task.split(";")]
    invalid = [p for p in parts if p not in VALID_PROJECT_TASKS]
    if invalid:
        return f"Invalid Project Task value(s): {invalid}. Valid values: {', '.join(VALID_PROJECT_TASKS)}"

    if project_type and project_type not in VALID_PROJECT_TYPES:
        return f"Invalid Project Type '{project_type}'. Valid values: {', '.join(VALID_PROJECT_TYPES)}"

    if record_stage and record_stage not in VALID_RECORD_STAGES:
        return f"Invalid Record Stage '{record_stage}'. Valid values: {', '.join(VALID_RECORD_STAGES)}"

    data = {
        "Implementation__c": record_id,
        "Hours_Worked__c": hours,
        "Project_Task__c": project_task,
    }
    if notes:
        data["Notes__c"] = notes
    if task_date:
        data["Task_Date__c"] = task_date
    else:
        data["Task_Date__c"] = date.today().isoformat()
    if project_type:
        data["Project_Type__c"] = project_type
    if record_stage:
        data["Record_Stage__c"] = record_stage

    resp = await sf_client.create_record("Implementation_Hours__c", data)
    hours_id = resp.get("id", "unknown")
    create_timestamps.append(time.time())

    return (
        f"Hours logged successfully.\n"
        f"  Hours Record ID: {hours_id}\n"
        f"  Implementation: {record_name_or_id} (ID: {record_id})\n"
        f"  Hours: {hours}\n"
        f"  Task: {project_task}\n"
        f"  Date: {data['Task_Date__c']}"
        + (f"\n  Notes: {notes}" if notes else "")
    )


@mcp.tool()
async def query_implementations(
    query_type: str,
    custom_soql: Optional[str] = None,
) -> str:
    """Query Implementation__c records.

    Args:
        query_type: One of: at_risk, active, bandwidth, stale, by_stage, custom.
            - at_risk: implementations with health Risk, High Risk, or Churn
            - active: implementations not in Complete, Passive, or Unsuccessful stages
            - bandwidth: hours remaining on active implementations
            - stale: implementations with Stale_Days > 14
            - by_stage: count of implementations grouped by stage
            - custom: run a custom SOQL query (provide custom_soql)
        custom_soql: Required when query_type is "custom". A SOQL SELECT query against Implementation__c.
    """
    queries = {
        "at_risk": (
            "SELECT Name, Id, Account__r.Name, Program_Health__c, Risks__c, Implementation_Stage__c "
            "FROM Implementation__c "
            "WHERE Program_Health__c IN ('Risk', 'High Risk', 'Churn') "
            "ORDER BY Program_Health__c"
        ),
        "active": (
            "SELECT Name, Id, Account__r.Name, Implementation_Stage__c, Percent_Complete__c, "
            "Program_Health__c, Stale_Days__c "
            "FROM Implementation__c "
            "WHERE Implementation_Stage__c NOT IN ('05 - Complete', '06 - Passive', '08 - Unsuccessful') "
            "ORDER BY Implementation_Stage__c"
        ),
        "bandwidth": (
            "SELECT Name, Id, Contracted_Hours__c, Actual_Hours_Spent__c, Contracted_Hours_Remaining__c "
            "FROM Implementation__c "
            "WHERE Implementation_Stage__c IN ('01 - Explore', '02 - Planning', '03 - In Progress') "
            "ORDER BY Contracted_Hours_Remaining__c ASC"
        ),
        "stale": (
            "SELECT Name, Id, Stale_Days__c, Next_Step_Date__c, Implementation_Stage__c, Account__r.Name "
            "FROM Implementation__c "
            "WHERE Stale_Days__c > 14 "
            "ORDER BY Stale_Days__c DESC"
        ),
        "by_stage": (
            "SELECT Implementation_Stage__c, COUNT(Id) total "
            "FROM Implementation__c "
            "GROUP BY Implementation_Stage__c "
            "ORDER BY Implementation_Stage__c"
        ),
    }

    if query_type == "custom":
        if not custom_soql:
            return "custom_soql is required when query_type is 'custom'."
        # Safety: only allow SELECT
        if not custom_soql.strip().upper().startswith("SELECT"):
            return "Only SELECT queries are allowed."
        soql = custom_soql
    elif query_type in queries:
        soql = queries[query_type]
    else:
        return f"Invalid query_type '{query_type}'. Must be one of: {', '.join(list(queries.keys()) + ['custom'])}"

    result = await sf_client.query(soql)
    records = result.get("records", [])
    total = result.get("totalSize", 0)

    if total == 0:
        return f"No results found for query type '{query_type}'."

    # Format results
    if query_type == "by_stage":
        lines = [f"Implementations by stage ({total} groups):"]
        for r in records:
            stage = r.get("Implementation_Stage__c", "Unknown")
            count = r.get("total", 0)
            lines.append(f"  {stage}: {count}")
        return "\n".join(lines)

    lines = [f"Found {total} record(s):"]
    for r in records:
        # Clean up Salesforce metadata
        r.pop("attributes", None)
        lines.append("")
        lines.append(format_implementation(r))

    return "\n".join(lines)


@mcp.tool()
async def get_implementation(
    record_name_or_id: str,
) -> str:
    """Get full details of a single Implementation__c record.

    Args:
        record_name_or_id: Implementation record Name (e.g. "IMPL-0042") or Salesforce ID.
    """
    try:
        record_id = await resolve_implementation_id(sf_client, record_name_or_id)
    except ValueError as e:
        return str(e)

    fields = [
        "Id", "Name", "Implementation_Stage__c", "Program_Health__c",
        "Type__c", "Contract_Type__c", "Percent_Complete__c", "In_Production__c",
        "Account__c", "Opportunity__c", "CDE__c", "CSM__c", "SA__c",
        "Contracted_Hours__c", "Actual_Hours_Spent__c", "Contracted_Hours_Remaining__c",
        "Days_In_Program__c", "Join_Days__c", "Contracted_Days_Remaining__c",
        "Stale_Days__c", "Features__c", "Migration_Type__c",
        "Risks__c", "Comments__c", "Post_Mortem__c", "Technical_Win__c",
        "Customer_Start_Date__c", "Implementation_Create_Date__c",
        "Kick_Off_Call__c", "Program_Start_Date__c",
        "Estimated_Graduation_Date__c", "Calculated_Graduation_Date__c",
        "Production_Date__c", "Final_Review_Call__c", "Next_Step_Date__c",
        "Potential_ARR__c", "Projected_Amount__c", "Contract__c",
        "ARR_Start_of_Program__c", "ARR_End_of_Program__c",
        "Grafana__c", "Project_Doc__c", "Migration_Source__c", "Support_Tier__c",
    ]

    record = await sf_client.get_record("Implementation__c", record_id, fields)
    record.pop("attributes", None)
    return format_implementation(record)


if __name__ == "__main__":
    mcp.run(transport="stdio")
