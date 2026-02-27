# Salesforce Implementation Tracker

This project enables natural language interaction with the `Implementation__c` custom object in Salesforce via the REST API.

## Authentication

**Method:** OAuth 2.0 Client Credentials flow
**Instance:** `https://your-org.my.salesforce.com`
**API Version:** v62.0

Credentials are stored in `.env` (never commit this file). To authenticate:

```bash
source .env

SF_TOKEN=$(curl -s -X POST "${SF_INSTANCE_URL}/services/oauth2/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${SF_CLIENT_ID}" \
  -d "client_secret=${SF_CLIENT_SECRET}" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

Always obtain a fresh token at the start of a session. Tokens expire after ~2 hours.

## Base URL Pattern

All API calls follow:
```
${SF_INSTANCE_URL}/services/data/v62.0/sobjects/Implementation__c/
```

Use `Authorization: Bearer ${SF_TOKEN}` header on every request.

---

## Operations

### 1. Create Implementation from Opportunity ID

Given an Opportunity ID, query the Opp for Account and details, then create the Implementation record.

**Naming convention:** `{Account Name} - {Type} - {YYYY-MM-DD}`
- Example: `Acme Corp - Join - 2026-02-27`
- The Account Name comes from the Opp's Account (`Account__r.Name`)
- The Type comes from the user's `Type__c` selection
- The date is the creation date
- Set this as the `Name` field at creation time

**Required fields for creation:**
- `Name` — follows naming convention above
- `Opportunity__c` — the Opp ID (pulled from user input)
- `Account__c` — the Account ID (queried from the Opp)
- `Type__c` — must be one of: `Join`, `Pure Migration`, `Join - Lite`, `Join - Quickstart`, `Other`
- `Contract_Type__c` — must be one of: `Annual`, `Free Trial`, `Pay as you go`
- `Implementation_Stage__c` — defaults to `00 - Kick Off Call`
- `Program_Health__c` — defaults to `Healthy`

**Auto-populated by Salesforce (do not set manually):**
- `Implementation_Create_Date__c` — set automatically to creation date
- `Program_Start_Date__c` — set automatically
- `Account_Owner__c` — pulled from Account
- `SA__c` — pulled from related records
- `Potential_ARR__c`, `Projected_Amount__c` — calculated from Opp
- `Join_Days__c`, `Contracted_Days_Remaining__c` — calculated
- `Calculated_Graduation_Date__c` — formula field
- `Billing_Category__c` — auto-set
- All `*_Start_of_Program__c` metrics — default to 0

**Step 1 — Query the Opportunity and Account Name:**
```bash
curl -s -H "Authorization: Bearer ${SF_TOKEN}" \
  "${SF_INSTANCE_URL}/services/data/v62.0/query/?q=SELECT+Id,Name,AccountId,Account.Name,Amount,OwnerId+FROM+Opportunity+WHERE+Id='006XXXXXXXXXXXX'"
```

**Step 2 — Prompt user for required fields:**

Before creating, ask the user:
1. "What type of implementation?" → map to `Type__c` value
2. "What contract type?" → map to `Contract_Type__c` value
3. Optionally: CDE, contracted hours, features, migration type

**Step 3 — Create the Implementation:**
```bash
curl -s -X POST -H "Authorization: Bearer ${SF_TOKEN}" \
  -H "Content-Type: application/json" \
  "${SF_INSTANCE_URL}/services/data/v62.0/sobjects/Implementation__c/" \
  -d '{
    "Name": "<Account Name> - <Type> - <YYYY-MM-DD>",
    "Opportunity__c": "006XXXXXXXXXXXX",
    "Account__c": "<AccountId from Opp query>",
    "Type__c": "<user selection>",
    "Contract_Type__c": "<user selection>",
    "Implementation_Stage__c": "00 - Kick Off Call",
    "Program_Health__c": "Healthy",
    "In_Production__c": false
  }'
```

The response returns the new record `Id`. Additional fields can be set at creation or updated after.

### 2. Log Hours

Hours are logged by creating records on the **`Implementation_Hours__c`** child object. The `Actual_Hours_Spent__c` field on Implementation__c is a roll-up summary — do NOT update it directly.

**Required fields for `Implementation_Hours__c`:**
- `Implementation__c` — the parent Implementation record ID
- `Hours_Worked__c` — number of hours (double)
- `Project_Task__c` — multipicklist, **required**

**Optional fields:**
- `Task_Date__c` — date (YYYY-MM-DD), defaults to today
- `Notes__c` — textarea for description of work
- `Project_Type__c` — picklist
- `Record_Stage__c` — picklist
- `Contact__c` — reference to Contact
- `Linked_Case__c` — reference to Case

**`Project_Task__c` valid values** (multipicklist, semicolon-separated):
`CAGG`, `Case work`, `Compression`, `Connection Pooling`, `HA Replica`, `Hypershift`, `Ingest`, `Internal Meetings - Non Customer`, `Internal Testing`, `Migration`, `POC`, `Project Plan`, `Query Optimization`, `Read Replica`, `Replica`, `Retention`, `CNS`, `Sales`, `Sales Call`, `Schema Design`, `Security`, `Sizing`, `Troubleshooting`, `VPC`

**`Project_Type__c` valid values:**
`Churn`, `Implementation`, `Internal Meetings`, `Join`, `Join - Lite`, `Join - QS`, `Pre-Sales`, `Pre-Sales (Discover Call)`, `Projects`, `Support`, `Training`

**`Record_Stage__c` valid values:**
`Trial`, `Pre-Production`, `Production`

```bash
# Log hours on an implementation
curl -s -X POST -H "Authorization: Bearer ${SF_TOKEN}" \
  -H "Content-Type: application/json" \
  "${SF_INSTANCE_URL}/services/data/v62.0/sobjects/Implementation_Hours__c/" \
  -d '{
    "Implementation__c": "a0BXXXXXXXXXXXX",
    "Hours_Worked__c": 3,
    "Task_Date__c": "2026-02-27",
    "Project_Task__c": "Schema Design",
    "Notes__c": "Worked on schema design and optimization"
  }'
```

When a user says "log hours", ask them:
1. How many hours?
2. What task? → present `Project_Task__c` options
3. Any notes? (optional)

### 3. Update Fields

Use PATCH to update any writeable field. Multiple fields can be updated in one call:

```bash
curl -s -X PATCH -H "Authorization: Bearer ${SF_TOKEN}" \
  -H "Content-Type: application/json" \
  "${SF_INSTANCE_URL}/services/data/v62.0/sobjects/Implementation__c/a0BXXXXXXXXXXXX" \
  -d '{
    "Implementation_Stage__c": "03 - In Progress",
    "Program_Health__c": "Healthy",
    "Percent_Complete__c": 50
  }'
```

A successful PATCH returns HTTP 204 with no body.

### 4. Query / Reports

Use SOQL via the query endpoint:

```bash
curl -s -H "Authorization: Bearer ${SF_TOKEN}" \
  "${SF_INSTANCE_URL}/services/data/v62.0/query/?q=<URL-encoded SOQL>"
```

Common queries:

| Request | SOQL |
|---------|------|
| All at-risk implementations | `SELECT Name, Account__c, Program_Health__c, Risks__c FROM Implementation__c WHERE Program_Health__c IN ('Risk', 'High Risk', 'Churn')` |
| My active implementations | `SELECT Name, Implementation_Stage__c, Percent_Complete__c FROM Implementation__c WHERE Implementation_Stage__c NOT IN ('05 - Complete', '06 - Passive', '08 - Unsuccessful')` |
| Bandwidth (hours remaining) | `SELECT Name, Contracted_Hours__c, Actual_Hours_Spent__c, Contracted_Hours_Remaining__c FROM Implementation__c WHERE Implementation_Stage__c IN ('01 - Explore', '02 - Planning', '03 - In Progress')` |
| Stale implementations | `SELECT Name, Stale_Days__c, Next_Step_Date__c, Implementation_Stage__c FROM Implementation__c WHERE Stale_Days__c > 14 ORDER BY Stale_Days__c DESC` |
| Implementations by stage | `SELECT Implementation_Stage__c, COUNT(Id) FROM Implementation__c GROUP BY Implementation_Stage__c` |

SOQL in URLs must be URL-encoded. Spaces become `+`, single quotes become `%27`.

---

## Implementation__c Schema

### Lookup Fields (References)

| API Name | Type | Points To |
|----------|------|-----------|
| `Account__c` | reference | Account |
| `Opportunity__c` | reference | Opportunity |
| `Account_Owner__c` | reference | User |
| `CDE__c` | reference | User |
| `CSM__c` | reference | User |
| `SA__c` | reference | User |

### Picklist Fields — Valid Values

**`Implementation_Stage__c`** (Implementation Stage):
- `00 - Kick Off Call`
- `01 - Explore`
- `02 - Planning`
- `03 - In Progress`
- `04 - Final Review`
- `05 - Complete`
- `06 - Passive`
- `07 - Paused`
- `08 - Unsuccessful`

**`Program_Health__c`** (Program Health):
- `Healthy`
- `Passive`
- `Paused`
- `Unresponsive`
- `Risk`
- `Churn`
- `High Risk`

**`Contract_Type__c`** (Contract Type):
- `Annual`
- `Free Trial`
- `Pay as you go`

**`Type__c`** (Type):
- `Join`
- `Pure Migration`
- `Join - Lite`
- `Join - Quickstart`
- `Other`

**`Migration_Type__c`** (Migration Type):
- `Customer Tooling`
- `Dual-write and backfill`
- `Parallel Copy`
- `pg_dump and pg_restore`
- `NA`
- `TS Tooling`
- `Live Migration`

**`Features__c`** (Features — multipicklist, semicolon-separated):
- `Read Replicas`
- `HA Replicas`
- `Data Tiering`
- `Caggs`
- `Compression`
- `Migration`
- `Vector`
- `Hypertables`

When setting multipicklist values via API, separate with semicolons: `"Read Replicas;Compression;Hypertables"`

### Date Fields

| API Name | Label |
|----------|-------|
| `Customer_Start_Date__c` | Customer Start Date |
| `Implementation_Create_Date__c` | Implementation Create Date |
| `Kick_Off_Call__c` | Kick Off Call |
| `Program_Start_Date__c` | Program Start Date |
| `Estimated_Graduation_Date__c` | Graduation Date |
| `Calculated_Graduation_Date__c` | Calculated Graduation Date |
| `Production_Date__c` | Production Date |
| `Final_Review_Call__c` | Final Review Call |
| `Next_Step_Date__c` | Next Step Date |
| `X3_Month_Check_In__c` | 3 Month Check In |

Date format for API: `YYYY-MM-DD`

### Numeric Fields

| API Name | Type | Label |
|----------|------|-------|
| `Actual_Hours_Spent__c` | double | Actual Hours Spent |
| `Contracted_Hours__c` | double | Contracted Hours |
| `Contracted_Hours_Remaining__c` | double | Contract Hours Remaining |
| `Contracted_Days_Remaining__c` | double | Contracted Days Remaining |
| `Join_Days__c` | double | Contracted Days |
| `Adjustment_Days__c` | double | Adjustment Days |
| `Days_In_Program__c` | double | Days In Program |
| `Days_to_Graduate_P2P__c` | double | Days to Graduate |
| `Stale_Days__c` | double | Stale Days |
| `Percent_Complete__c` | percent | % Complete |
| `P2P_Cost__c` | double | CDE Cost |
| `ARR_Start_of_Program__c` | double | ARR Start of Program |
| `ARR_End_of_Program__c` | double | ARR End of Program |
| `ARR_Vs_Potential__c` | double | ARR Vs Potential |
| `Contract__c` | currency | Contract $ |
| `Potential_ARR__c` | currency | Potential ARR |
| `Projected_Amount__c` | currency | Projected Amount |
| `Hypertables_Start_of_Program__c` | double | Hypertables Start of Program |
| `Hypertables_End_of_Program__c` | double | Hypertables End of Program |
| `Caggs_Start_of_Program__c` | double | Caggs Start of Program |
| `Caggs_End_of_Program__c` | double | Caggs End of Program |
| `Compression_Ratio_Start_of_Program__c` | double | Compression Ratio Start of Program |
| `Compression_Ratio_End_of_Program__c` | double | Compression Ratio End of Program |
| `DUM_Start_of_Program__c` | double | DUM Start of Program |
| `DUM_End_of_Program__c` | double | DUM End of Program |
| `Number_of_Services_Start_of_Program__c` | double | Number of Services Start of Program |
| `Number_of_Services_End_of_Program__c` | double | Number of Services End of Program |
| `Tiered_Data_Start_of_Program__c` | double | Tiered Data Start of Program |
| `Tiered_Data_End_of_Program__c` | double | Tiered Data End of Program |

### Text / URL Fields

| API Name | Type | Label |
|----------|------|-------|
| `Comments__c` | textarea | Comments |
| `Risks__c` | textarea | Risks |
| `Post_Mortem__c` | textarea | Post Mortem |
| `Technical_Win__c` | textarea | Technical Win |
| `Billing_Category__c` | string | Billing Category |
| `Migration_Source__c` | string | Migration Source |
| `Support_Tier__c` | string | Support Tier |
| `Grafana__c` | url | Grafana |
| `Project_Doc__c` | url | Exec Summary |

### Boolean Fields

| API Name | Default | Label |
|----------|---------|-------|
| `In_Production__c` | false | In Production |

---

## Example Natural Language Prompts

These are examples of what team members can ask and how Claude should handle them:

| Prompt | Action |
|--------|--------|
| "Create an implementation for Opp 006Nv000009abc" | Query Opp → Ask user for Type and Contract Type → Create Implementation__c with linked Account, required fields, stage 00, health Healthy |
| "Log 3 hours on IMPL-0042" | Ask for Project Task → Create `Implementation_Hours__c` record with Hours_Worked__c=3 linked to the Implementation |
| "Move IMPL-0042 to In Progress" | PATCH `Implementation_Stage__c` = `03 - In Progress` |
| "Mark IMPL-0042 as at risk with note: customer unresponsive" | PATCH `Program_Health__c` = `Risk`, `Risks__c` = "customer unresponsive" |
| "Set features to Compression and Hypertables on IMPL-0042" | PATCH `Features__c` = `Compression;Hypertables` |
| "Show all at-risk implementations" | SOQL query filtering Program_Health__c IN ('Risk', 'High Risk', 'Churn') |
| "What's our team bandwidth?" | SOQL query summing Contracted_Hours_Remaining__c for active implementations |
| "Show stale implementations over 14 days" | SOQL query WHERE Stale_Days__c > 14 |
| "Set graduation date to March 15 for IMPL-0042" | PATCH `Estimated_Graduation_Date__c` = `2026-03-15` |
| "Update migration type to Live Migration" | PATCH `Migration_Type__c` = `Live Migration` |

When a user references an implementation by name (e.g., "IMPL-0042"), query by Name field first to get the record Id, then perform the operation.

### Interactive Creation Flow

When a user says "Create an implementation for Opp [ID]", follow this flow:

1. **Authenticate** — get a fresh token
2. **Query the Opportunity** — pull Name, AccountId, Amount
3. **Ask the user** for the required fields:
   - "What type of implementation?" → present options: Join, Pure Migration, Join - Lite, Join - Quickstart, Other
   - "What contract type?" → present options: Annual, Free Trial, Pay as you go
4. **Optionally ask** for commonly-set fields:
   - Contracted Hours (`Contracted_Hours__c`)
   - CDE assignment (`CDE__c` — needs a User ID)
   - Features (`Features__c`)
   - Migration Type (`Migration_Type__c`) — if type involves migration
5. **Create the record** with the collected values
6. **Confirm** by returning the new record ID and a summary of what was set

---

## Schema Refresh

When fields or picklist values change in Salesforce, run:
```bash
./scripts/refresh-schema.sh
```
This pulls the latest describe from the API and saves it to `schema/`. Then update the relevant sections of this CLAUDE.md to match.

---

## Important Notes

- **Picklist values are case-sensitive.** Always use the exact values listed above.
- **Multipicklist values are semicolon-separated** with no spaces around the semicolon.
- **Date format is `YYYY-MM-DD`** for all date fields.
- **Currency and percent fields** accept plain numbers (e.g., `50` for 50%).
- **PATCH returns 204 No Content** on success — no response body.
- **POST returns 201 Created** with the new record Id.
- **Record IDs** are 15 or 18 character Salesforce IDs (use 18-char version for API calls).
- **SOQL strings in URLs** must be URL-encoded.

---

## MCP Server (Claude Desktop)

The project includes an MCP server (`mcp_server.py`) that exposes Salesforce operations as tools for Claude Desktop. This gives team members a natural-language interface without needing the CLI.

### Setup

1. **Install dependencies:** Run `./setup.sh` (requires Python 3.10+ and `pip` or `uv`)
2. **Add to Claude Desktop config** (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "salesforce-impl": {
      "command": "python3",
      "args": ["/absolute/path/to/sfdc-implementation/mcp_server.py"],
      "env": {
        "SF_CLIENT_ID": "<your-client-id>",
        "SF_CLIENT_SECRET": "<your-client-secret>",
        "SF_INSTANCE_URL": "https://your-org.my.salesforce.com",
        "SF_USER_EMAIL": "<your-email>"
      }
    }
  }
}
```

3. **Restart Claude Desktop** to pick up the new server.

### Tools Exposed

| Tool | Description | Access |
|------|-------------|--------|
| `create_implementation` | Create from Opp ID (type, contract type, etc.) | All users |
| `update_implementation` | Update fields on an existing record | CDE only (admin bypass) |
| `log_hours` | Create an Implementation_Hours__c record | All users |
| `query_implementations` | Run preset or custom SOQL queries | All users |
| `get_implementation` | Get full details of a single record | All users |

### Access Control

- `SF_USER_EMAIL` is resolved to a Salesforce User on startup
- **Admins** (System Administrator profile) can update any record
- **Everyone else** can only update records where they are the assigned CDE
- **No delete operations** are exposed
- Creates, queries, and logging hours are unrestricted
