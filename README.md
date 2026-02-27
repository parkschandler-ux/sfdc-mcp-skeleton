# Salesforce Implementation Tracker — MCP Server

An MCP server that gives Claude Desktop natural-language access to a Salesforce `Implementation__c` custom object. Create implementations, log hours, update records, and run queries — all through conversation.

## Tools

| Tool | Description |
|------|-------------|
| `create_implementation` | Create a new Implementation from an Opportunity ID |
| `update_implementation` | Update fields on an existing record (access-controlled) |
| `log_hours` | Log hours against an Implementation |
| `query_implementations` | Run preset or custom SOQL queries |
| `get_implementation` | Get full details of a single record |

## Setup

1. Clone the repo and run the setup script:

```bash
git clone <this-repo>
cd sfdc-mcp-skeleton
./setup.sh
```

2. Copy `.env.example` to `.env` and fill in your Salesforce Connected App credentials.

3. Add the MCP server to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "salesforce-impl": {
      "command": "/path/to/.venv/bin/python3",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "SF_CLIENT_ID": "your-connected-app-client-id",
        "SF_CLIENT_SECRET": "your-connected-app-client-secret",
        "SF_INSTANCE_URL": "https://your-org.my.salesforce.com",
        "SF_USER_EMAIL": "you@your-org.com"
      }
    }
  }
}
```

4. Restart Claude Desktop.

## Access Control

- **Admins** (System Administrator profile) can update any record
- **Everyone else** can only update records where they are the assigned CDE
- **No delete operations** are exposed
- Record creates are rate-limited to 5 per rolling 60-second window

## Prerequisites

- Python 3.10+ (setup script installs 3.12 via `uv`)
- A Salesforce org with the `Implementation__c` and `Implementation_Hours__c` custom objects
- A Connected App configured for OAuth Client Credentials flow

## Customization

- **Picklist values**: Edit the `VALID_*` lists in `mcp_server.py` to match your org
- **Rate limits**: Adjust `MAX_CREATES_PER_SESSION` in `mcp_server.py`
- **Schema**: See `CLAUDE.md` for the full field reference
